from __future__ import annotations
import csv, io, json, logging, os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

class Settings(BaseSettings):
    database_url: str = 'sqlite:///./wqm.db'
    cors_origins: str = 'http://localhost:5173'
    app_env: str = 'development'
    log_level: str = 'INFO'
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
settings=Settings()
logging.basicConfig(level=getattr(logging,settings.log_level.upper(),logging.INFO),format='%(asctime)s %(levelname)s %(name)s %(message)s')
log=logging.getLogger('wqm')
connect_args={'check_same_thread':False} if settings.database_url.startswith('sqlite') else {}
engine=create_engine(settings.database_url,pool_pre_ping=True,connect_args=connect_args)
Session=sessionmaker(engine,expire_on_commit=False)
class Base(DeclarativeBase): pass
class DeviceRow(Base):
    __tablename__='devices'
    device_id:Mapped[str]=mapped_column(String(80),primary_key=True);name:Mapped[str]=mapped_column(String(120),default='Water sensor node');status:Mapped[str]=mapped_column(String(16),default='OFFLINE');ip_address:Mapped[str|None]=mapped_column(String(64),nullable=True);last_seen:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc));firmware_version:Mapped[str]=mapped_column(String(40),default='1.0.0');sampling_interval:Mapped[int]=mapped_column(Integer,default=30);created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
class ReadingRow(Base):
    __tablename__='readings'
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True);device_id:Mapped[str]=mapped_column(ForeignKey('devices.device_id'),index=True);ph:Mapped[float]=mapped_column(Float);tds:Mapped[float]=mapped_column(Float);turbidity:Mapped[float]=mapped_column(Float);temperature:Mapped[float]=mapped_column(Float);created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc),index=True)
class AlertRow(Base):
    __tablename__='alerts'
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True);device_id:Mapped[str]=mapped_column(String(80),index=True);parameter:Mapped[str]=mapped_column(String(30));value:Mapped[float]=mapped_column(Float);threshold:Mapped[float]=mapped_column(Float);severity:Mapped[str]=mapped_column(String(16));message:Mapped[str]=mapped_column(String(255));created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc),index=True);acknowledged:Mapped[bool]=mapped_column(Boolean,default=False);resolved_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
class ThresholdRow(Base):
    __tablename__='thresholds'
    id:Mapped[int]=mapped_column(Integer,primary_key=True,default=1);ph_min:Mapped[float]=mapped_column(Float,default=6.5);ph_max:Mapped[float]=mapped_column(Float,default=8.5);tds_max:Mapped[float]=mapped_column(Float,default=500);turbidity_max:Mapped[float]=mapped_column(Float,default=5);temperature_min:Mapped[float]=mapped_column(Float,default=10);temperature_max:Mapped[float]=mapped_column(Float,default=35)
class ReadingIn(BaseModel):
    device_id:str=Field(min_length=1,max_length=80);ph:float=Field(ge=0,le=14);tds:float=Field(ge=0,le=100000);turbidity:float=Field(ge=0,le=10000);temperature:float=Field(ge=-50,le=150);created_at:datetime|None=None
class ThresholdIn(BaseModel):
    ph_min:float=Field(ge=0,le=14);ph_max:float=Field(ge=0,le=14);tds_max:float=Field(gt=0);turbidity_max:float=Field(gt=0);temperature_min:float=Field(ge=-50,le=150);temperature_max:float=Field(ge=-50,le=150)
    def valid_range(self):
        if self.ph_min>=self.ph_max or self.temperature_min>=self.temperature_max: raise ValueError('Minimum thresholds must be lower than maximum thresholds')
class DeviceIn(BaseModel): device_id:str;name:str='Water sensor node';firmware_version:str='1.0.0';sampling_interval:int=30;ip_address:str|None=None
class ConnectionManager:
    def __init__(self):self.clients:set[WebSocket]=set()
    async def connect(self,ws:WebSocket):await ws.accept();self.clients.add(ws);log.info('WebSocket connected clients=%s',len(self.clients))
    def disconnect(self,ws:WebSocket):self.clients.discard(ws);log.info('WebSocket disconnected clients=%s',len(self.clients))
    async def publish(self,message:dict[str,Any]):
        for client in list(self.clients):
            try:await client.send_json(message)
            except Exception:self.clients.discard(client)
manager=ConnectionManager()
def serialize(obj):
    out={c.name:getattr(obj,c.name) for c in obj.__table__.columns}
    for k,v in out.items():
        if isinstance(v,datetime):out[k]=(v.replace(tzinfo=timezone.utc) if v.tzinfo is None else v).isoformat()
    return out
def thresholds(db):
    row=db.get(ThresholdRow,1)
    if not row:row=ThresholdRow(id=1);db.add(row);db.commit();db.refresh(row)
    return row
def eval_alerts(db,r,ts):
    t=thresholds(db);checks=[('ph',r.ph,t.ph_min,'below minimum','WARNING') if r.ph<t.ph_min else ('ph',r.ph,t.ph_max,'above maximum','WARNING') if r.ph>t.ph_max else None,('tds',r.tds,t.tds_max,'above maximum','WARNING') if r.tds>t.tds_max else None,('turbidity',r.turbidity,t.turbidity_max,'above maximum','CRITICAL') if r.turbidity>t.turbidity_max else None,('temperature',r.temperature,t.temperature_min,'below minimum','WARNING') if r.temperature<t.temperature_min else ('temperature',r.temperature,t.temperature_max,'above maximum','WARNING') if r.temperature>t.temperature_max else None]
    created=[]
    for item in checks:
        if not item:continue
        parameter,value,limit,direction,severity=item
        recent=db.scalars(select(AlertRow).where(AlertRow.device_id==r.device_id,AlertRow.parameter==parameter,AlertRow.resolved_at.is_(None)).order_by(AlertRow.created_at.desc()).limit(1)).first()
        if recent:continue
        a=AlertRow(device_id=r.device_id,parameter=parameter,value=value,threshold=limit,severity=severity,message=f'{parameter.upper()} {direction}',created_at=ts);db.add(a);created.append(a)
    db.commit()
    for a in created:db.refresh(a);log.warning('Alert generated id=%s device=%s parameter=%s',a.id,a.device_id,a.parameter)
    return created
@asynccontextmanager
async def lifespan(app:FastAPI):
    Base.metadata.create_all(engine)
    with Session() as db:
        thresholds(db)
        if not db.get(DeviceRow,'WQM-001'):
            db.add(DeviceRow(device_id='WQM-001',name='North basin sensor',firmware_version='1.2.4',sampling_interval=30));db.commit()
    log.info('WQM API started env=%s database=%s',settings.app_env,'configured')
    yield
app=FastAPI(title='Smart Water Quality Monitor API',version='1.0.0',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=[x.strip() for x in settings.cors_origins.split(',') if x.strip()],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])
@app.get('/api/health')
def health():return {'status':'ok','service':'wqm-api','time':datetime.now(timezone.utc).isoformat()}
@app.get('/api/dashboard')
def dashboard():
    with Session() as db:
        r=db.scalars(select(ReadingRow).order_by(ReadingRow.created_at.desc()).limit(1)).first();device=db.get(DeviceRow,r.device_id if r else 'WQM-001');cutoff=datetime.now(timezone.utc)-timedelta(seconds=(device.sampling_interval*3 if device else 90))
        if device and device.last_seen.replace(tzinfo=timezone.utc)<cutoff:device.status='OFFLINE';db.commit()
        t=thresholds(db);alerts=db.scalars(select(AlertRow).order_by(AlertRow.created_at.desc()).limit(5)).all()
        return {'reading':serialize(r) if r else None,'device':serialize(device) if device else None,'alerts':[serialize(a) for a in alerts],'thresholds':serialize(t),'system_status':device.status if device else 'OFFLINE'}
@app.get('/api/readings')
def list_readings(limit:int=Query(100,ge=1,le=1000),offset:int=Query(0,ge=0),device_id:str|None=None):
    with Session() as db:
        q=select(ReadingRow);countq=select(ReadingRow.id)
        if device_id:q=q.where(ReadingRow.device_id==device_id);countq=countq.where(ReadingRow.device_id==device_id)
        items=db.scalars(q.order_by(ReadingRow.created_at.desc()).offset(offset).limit(limit)).all();total=len(db.scalars(countq).all())
        return {'items':[serialize(r) for r in reversed(items)],'total':total,'limit':limit,'offset':offset}
@app.post('/api/readings',status_code=201)
async def create_reading(payload:ReadingIn):
    ts=payload.created_at or datetime.now(timezone.utc)
    try:
        with Session() as db:
            d=db.get(DeviceRow,payload.device_id)
            if not d:d=DeviceRow(device_id=payload.device_id);db.add(d);db.flush()
            d.last_seen=ts;d.status='ONLINE';r=ReadingRow(device_id=payload.device_id,ph=payload.ph,tds=payload.tds,turbidity=payload.turbidity,temperature=payload.temperature,created_at=ts);db.add(r);db.commit();db.refresh(r);created=eval_alerts(db,r,ts);out=serialize(r);dev=serialize(d)
        await manager.publish({'type':'reading.created','reading':out,'device':dev})
        for a in created:await manager.publish({'type':'alert.created','alert':serialize(a)})
        return out
    except Exception as e:log.exception('Incoming reading error');raise HTTPException(500,'Unable to store sensor reading') from e
@app.get('/api/readings/export.csv')
def export_csv():
    with Session() as db:
        rows=db.scalars(select(ReadingRow).order_by(ReadingRow.created_at.desc())).all();s=io.StringIO();w=csv.writer(s);w.writerow(['timestamp','device_id','ph','tds_ppm','turbidity_ntu','temperature_c']);[w.writerow([r.created_at.isoformat(),r.device_id,r.ph,r.tds,r.turbidity,r.temperature]) for r in rows]
        return StreamingResponse(iter([s.getvalue()]),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="wqm-readings.csv"'})
@app.get('/api/alerts')
def list_alerts():
    with Session() as db:return [serialize(a) for a in db.scalars(select(AlertRow).order_by(AlertRow.created_at.desc())).all()]
def mutate_alert(alert_id:int,action:str):
    with Session() as db:
        a=db.get(AlertRow,alert_id)
        if not a:raise HTTPException(404,'Alert not found')
        if action=='acknowledge':a.acknowledged=True
        else:a.resolved_at=datetime.now(timezone.utc);a.acknowledged=True
        db.commit();db.refresh(a);return serialize(a)
@app.post('/api/alerts/{alert_id}/acknowledge')
def acknowledge(alert_id:int):return mutate_alert(alert_id,'acknowledge')
@app.post('/api/alerts/{alert_id}/resolve')
def resolve(alert_id:int):return mutate_alert(alert_id,'resolve')
@app.get('/api/devices')
def list_devices():
    with Session() as db:return [serialize(d) for d in db.scalars(select(DeviceRow).order_by(DeviceRow.created_at)).all()]
@app.post('/api/devices',status_code=201)
def add_device(payload:DeviceIn):
    with Session() as db:
        if db.get(DeviceRow,payload.device_id):raise HTTPException(409,'Device already exists')
        d=DeviceRow(**payload.model_dump());db.add(d);db.commit();db.refresh(d);return serialize(d)
@app.get('/api/thresholds')
def get_thresholds():
    with Session() as db:return serialize(thresholds(db))
@app.put('/api/thresholds')
def put_thresholds(payload:ThresholdIn):
    try:payload.valid_range()
    except ValueError as e:raise HTTPException(422,str(e))
    with Session() as db:
        row=thresholds(db)
        for k,v in payload.model_dump().items():setattr(row,k,v)
        db.commit();db.refresh(row);return serialize(row)
@app.get('/api/analytics')
def analytics(parameter:str='ph',range:str='24H',device_id:str|None=None):
    if parameter not in {'ph','tds','turbidity','temperature'}:raise HTTPException(422,'Invalid parameter')
    hours={'1H':1,'6H':6,'24H':24,'7D':168}.get(range.upper(),24);since=datetime.now(timezone.utc)-timedelta(hours=hours)
    with Session() as db:
        q=select(ReadingRow).where(ReadingRow.created_at>=since)
        if device_id:q=q.where(ReadingRow.device_id==device_id)
        rows=list(db.scalars(q.order_by(ReadingRow.created_at)).all());values=[getattr(r,parameter) for r in rows];t=thresholds(db)
        def violated(reading):
            return (reading.ph<t.ph_min or reading.ph>t.ph_max or reading.tds>t.tds_max or reading.turbidity>t.turbidity_max or reading.temperature<t.temperature_min or reading.temperature>t.temperature_max)
        return {'average':sum(values)/len(values) if values else 0,'minimum':min(values) if values else 0,'maximum':max(values) if values else 0,'violations':sum(violated(r) for r in rows),'readings':[serialize(r) for r in rows]}
@app.websocket('/ws')
async def websocket_endpoint(ws:WebSocket):
    await manager.connect(ws)
    try:
        while True:await ws.receive_text()
    except WebSocketDisconnect:manager.disconnect(ws)
    except Exception:manager.disconnect(ws)
