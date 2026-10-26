from __future__ import annotations
import base64, csv, hashlib, hmac, io, json, logging, os, smtplib, ssl, time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
import joblib

class Settings(BaseSettings):
    database_url: str
    cors_origins: str = 'http://localhost:5173'
    app_env: str = 'development'
    log_level: str = 'INFO'
    auth_username: str = 'admin'
    auth_password: str = 'water123'
    auth_token_secret: str = 'local-demo-secret-change-me'
    alert_email_to: str = 'vikasshirsath04@gmail.com'
    smtp_host: str = ''
    smtp_port: int = 587
    smtp_username: str = ''
    smtp_password: str = ''
    smtp_from_email: str = ''
    default_turbidity_ntu: float = Field(default=2.8, ge=0, le=10000)
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
settings=Settings()
if settings.app_env.lower()=='production' and (settings.auth_password=='water123' or settings.auth_token_secret=='local-demo-secret-change-me'):
    raise RuntimeError('Set AUTH_PASSWORD and AUTH_TOKEN_SECRET to non-demo values in production.')
logging.basicConfig(level=getattr(logging,settings.log_level.upper(),logging.INFO),format='%(asctime)s %(levelname)s %(name)s %(message)s')
log=logging.getLogger('wqm')
database_url=settings.database_url.strip()
if database_url.startswith('postgres://'):
    database_url='postgresql+psycopg://' + database_url.removeprefix('postgres://')
elif database_url.startswith('postgresql://'):
    database_url='postgresql+psycopg://' + database_url.removeprefix('postgresql://')
if not database_url.startswith('postgresql+psycopg://'):
    raise ValueError('DATABASE_URL must be a PostgreSQL URL using the psycopg driver.')
parsed_url=make_url(database_url)
if 'sslmode' not in parsed_url.query:
    parsed_url=parsed_url.set(query={**dict(parsed_url.query),'sslmode':'require'})
engine=create_engine(parsed_url,pool_pre_ping=True)
Session=sessionmaker(engine,expire_on_commit=False)
MODEL_PATH=Path(__file__).with_name('water_quality_model.joblib')
_model_bundle=None
def model_assessment(reading):
    """Return the supplied dataset's top-category score, never a safety certification."""
    global _model_bundle
    if reading is None or not MODEL_PATH.exists():return None
    if _model_bundle is None:_model_bundle=joblib.load(MODEL_PATH)
    model=_model_bundle['model'];features=_model_bundle['features']
    values={'pH':reading.ph,'TDS_ppm':reading.tds,'Turbidity_NTU':reading.turbidity,'Temperature_C':reading.temperature}
    probabilities=model.predict_proba([[values[name] for name in features]])[0]
    predicted_index=int(probabilities.argmax())
    score=round(float(probabilities[predicted_index])*100,1)
    return {'score':score,'prediction':str(model.classes_[predicted_index]),'basis':'Supplied Water_Quality labels','is_certified':False}

def _b64(data:bytes)->str:return base64.urlsafe_b64encode(data).decode().rstrip('=')
def issue_token(username:str)->str:
    payload=_b64(json.dumps({'sub':username,'exp':int(time.time())+86400},separators=(',',':')).encode())
    signature=_b64(hmac.new(settings.auth_token_secret.encode(),payload.encode(),hashlib.sha256).digest())
    return f'{payload}.{signature}'
def token_username(token:str|None)->str|None:
    try:
        payload,signature=token.split('.',1)
        expected=_b64(hmac.new(settings.auth_token_secret.encode(),payload.encode(),hashlib.sha256).digest())
        if not hmac.compare_digest(signature,expected):return None
        data=json.loads(base64.urlsafe_b64decode(payload+'='*(-len(payload)%4)))
        if int(data['exp'])<=int(time.time()) or data['sub']!=settings.auth_username:return None
        return str(data['sub'])
    except (ValueError,KeyError,TypeError,json.JSONDecodeError):return None

class LoginIn(BaseModel): username:str=Field(min_length=1,max_length=100);password:str=Field(min_length=1,max_length=200)
class Base(DeclarativeBase): pass
class DeviceRow(Base):
    __tablename__='devices'
    device_id:Mapped[str]=mapped_column(String(80),primary_key=True);name:Mapped[str]=mapped_column(String(120),default='Water sensor node');status:Mapped[str]=mapped_column(String(16),default='OFFLINE');ip_address:Mapped[str|None]=mapped_column(String(64),nullable=True);last_seen:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc));firmware_version:Mapped[str]=mapped_column(String(40),default='1.0.0');sampling_interval:Mapped[int]=mapped_column(Integer,default=30);created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
class ReadingRow(Base):
    __tablename__='readings'
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True);device_id:Mapped[str]=mapped_column(ForeignKey('devices.device_id'),index=True);ph:Mapped[float]=mapped_column(Float);tds:Mapped[float]=mapped_column(Float);turbidity:Mapped[float]=mapped_column(Float);temperature:Mapped[float]=mapped_column(Float);created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc),index=True)
class AlertRow(Base):
    __tablename__='alerts'
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True);device_id:Mapped[str]=mapped_column(String(80),index=True);parameter:Mapped[str]=mapped_column(String(30));value:Mapped[float]=mapped_column(Float);threshold:Mapped[float]=mapped_column(Float);severity:Mapped[str]=mapped_column(String(16));message:Mapped[str]=mapped_column(String(255));created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc),index=True);acknowledged:Mapped[bool]=mapped_column(Boolean,default=False);resolved_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True);email_last_attempt_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True);email_sent_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True);email_last_error:Mapped[str|None]=mapped_column(String(255),nullable=True)
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
    assessment=model_assessment(r);email_alert=None
    if assessment and assessment['prediction']=='Poor':
        recent_model=db.scalars(select(AlertRow).where(AlertRow.device_id==r.device_id,AlertRow.parameter=='model',AlertRow.resolved_at.is_(None)).order_by(AlertRow.created_at.desc()).limit(1)).first()
        if not recent_model:
            recent_model=AlertRow(device_id=r.device_id,parameter='model',value=assessment['score'],threshold=50,severity='CRITICAL',message='Model predicts Poor water quality: treat as not drinkable pending laboratory confirmation.',created_at=ts);db.add(recent_model);created.append(recent_model)
        else:recent_model.value=assessment['score']
        smtp_configured=all((settings.smtp_host,settings.smtp_username,settings.smtp_password,settings.smtp_from_email))
        last_attempt=recent_model.email_last_attempt_at
        retry_due=last_attempt is None or (ts-(last_attempt.replace(tzinfo=timezone.utc) if last_attempt.tzinfo is None else last_attempt))>=timedelta(seconds=30)
        if smtp_configured and recent_model.email_sent_at is None and retry_due:
            recent_model.email_last_attempt_at=ts;recent_model.email_last_error=None;email_alert=recent_model
    db.commit()
    for a in created:db.refresh(a);log.warning('Alert generated id=%s device=%s parameter=%s',a.id,a.device_id,a.parameter)
    if email_alert:db.refresh(email_alert)
    return created,serialize(email_alert) if email_alert else None
def send_model_alert_email(alert:dict[str,Any]):
    if not all((settings.smtp_host,settings.smtp_username,settings.smtp_password,settings.smtp_from_email)):
        log.warning('Poor-quality alert email not sent: SMTP settings are incomplete')
        return
    msg=EmailMessage();msg['Subject']=f"Water quality alert: {alert['device_id']} predicted Poor";msg['From']=settings.smtp_from_email;msg['To']=settings.alert_email_to
    msg.set_content(f"The water quality model predicted Poor for device {alert['device_id']}.\n\nModel score: {alert['value']:.1f}%\nReceived: {alert['created_at']}\n\nTreat this reading as a warning and avoid drinking the water until it has been tested appropriately. This experimental model is not a drinking-water safety certification.")
    try:
        with smtplib.SMTP(settings.smtp_host,settings.smtp_port,timeout=15) as server:
            server.starttls(context=ssl.create_default_context());server.login(settings.smtp_username,settings.smtp_password);server.send_message(msg)
        with Session() as db:
            row=db.get(AlertRow,int(alert['id']))
            if row:row.email_sent_at=datetime.now(timezone.utc);row.email_last_error=None;db.commit()
        log.info('Poor-quality alert email sent recipient=%s alert_id=%s',settings.alert_email_to,alert['id'])
    except Exception as error:
        if isinstance(error,smtplib.SMTPAuthenticationError):hint='SMTP authentication failed. Check SMTP_USERNAME and use a fresh Gmail App Password.'
        elif isinstance(error,smtplib.SMTPRecipientsRefused):hint='SMTP rejected ALERT_EMAIL_TO. Check the recipient address.'
        elif isinstance(error,smtplib.SMTPSenderRefused):hint='SMTP rejected SMTP_FROM_EMAIL. Check that it matches the authenticated sender.'
        elif isinstance(error,(smtplib.SMTPConnectError,smtplib.SMTPServerDisconnected,TimeoutError,ConnectionError,ssl.SSLError)):hint='Could not establish SMTP/TLS connection. Check SMTP_HOST, SMTP_PORT, and TLS access.'
        elif isinstance(error,smtplib.SMTPException):hint=f'SMTP delivery failed ({type(error).__name__}). Check the SMTP settings and Render logs.'
        else:hint=f'Email delivery failed ({type(error).__name__}). Check Render logs.'
        with Session() as db:
            row=db.get(AlertRow,int(alert['id']))
            if row:row.email_last_error=hint;db.commit()
        log.error('Unable to send poor-quality alert email alert_id=%s error_type=%s hint=%s',alert.get('id'),type(error).__name__,hint)
@asynccontextmanager
async def lifespan(app:FastAPI):
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE alerts ADD COLUMN IF NOT EXISTS email_last_attempt_at TIMESTAMPTZ'))
        connection.execute(text('ALTER TABLE alerts ADD COLUMN IF NOT EXISTS email_sent_at TIMESTAMPTZ'))
        connection.execute(text('ALTER TABLE alerts ADD COLUMN IF NOT EXISTS email_last_error VARCHAR(255)'))
    with Session() as db:
        thresholds(db)
        if not db.get(DeviceRow,'WQM-001'):
            db.add(DeviceRow(device_id='WQM-001',name='North basin sensor',firmware_version='1.2.4',sampling_interval=30));db.commit()
    log.info('WQM API started env=%s database=%s',settings.app_env,'configured')
    yield
app=FastAPI(title='Smart Water Quality Monitor API',version='1.0.0',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=[x.strip().rstrip('/') for x in settings.cors_origins.split(',') if x.strip()],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])
@app.middleware('http')
async def require_login(request:Request,call_next):
    path=request.url.path;method=request.method.upper()
    open_request=(method=='OPTIONS' or path in {'/health','/api/health','/api/auth/login'} or (path=='/api/readings' and method=='POST'))
    if path.startswith('/api/') and not open_request:
        authorization=request.headers.get('authorization','')
        scheme,_,token=authorization.partition(' ')
        if scheme.lower()!='bearer' or token_username(token) is None:
            return JSONResponse({'detail':'Authentication required'},status_code=401)
    return await call_next(request)
@app.get('/health')
@app.get('/api/health')
def health():return {'status':'ok','service':'wqm-api','time':datetime.now(timezone.utc).isoformat()}
@app.post('/api/auth/login')
def login(payload:LoginIn):
    valid_user=hmac.compare_digest(payload.username,settings.auth_username)
    valid_password=hmac.compare_digest(payload.password,settings.auth_password)
    if not (valid_user and valid_password):raise HTTPException(401,'Incorrect username or password')
    return {'access_token':issue_token(payload.username),'token_type':'bearer','expires_in':86400,'username':payload.username}
@app.get('/api/auth/me')
def current_user(request:Request):
    token=request.headers.get('authorization','').partition(' ')[2]
    username=token_username(token)
    if not username:raise HTTPException(401,'Authentication required')
    return {'username':username}
@app.get('/api/dashboard')
def dashboard():
    with Session() as db:
        r=db.scalars(select(ReadingRow).order_by(ReadingRow.created_at.desc()).limit(1)).first();device=db.get(DeviceRow,r.device_id if r else 'WQM-001');cutoff=datetime.now(timezone.utc)-timedelta(seconds=(device.sampling_interval*3 if device else 90))
        if device and device.last_seen.replace(tzinfo=timezone.utc)<cutoff:device.status='OFFLINE';db.commit()
        t=thresholds(db);alerts=db.scalars(select(AlertRow).order_by(AlertRow.created_at.desc()).limit(5)).all()
        return {'reading':serialize(r) if r else None,'device':serialize(device) if device else None,'alerts':[serialize(a) for a in alerts],'thresholds':serialize(t),'system_status':device.status if device else 'OFFLINE','model_assessment':model_assessment(r)}
@app.get('/api/readings')
def list_readings(limit:int=Query(100,ge=1,le=1000),offset:int=Query(0,ge=0),device_id:str|None=None):
    with Session() as db:
        q=select(ReadingRow);countq=select(ReadingRow.id)
        if device_id:q=q.where(ReadingRow.device_id==device_id);countq=countq.where(ReadingRow.device_id==device_id)
        items=db.scalars(q.order_by(ReadingRow.created_at.desc()).offset(offset).limit(limit)).all();total=len(db.scalars(countq).all())
        return {'items':[serialize(r) for r in reversed(items)],'total':total,'limit':limit,'offset':offset}
@app.post('/api/readings',status_code=201)
async def create_reading(payload:ReadingIn,background_tasks:BackgroundTasks):
    ts=payload.created_at or datetime.now(timezone.utc)
    if ts.tzinfo is None:ts=ts.replace(tzinfo=timezone.utc)
    try:
        with Session() as db:
            d=db.get(DeviceRow,payload.device_id)
            if not d:d=DeviceRow(device_id=payload.device_id);db.add(d);db.flush()
            # Turbidity is temporarily fixed while its sensor is unavailable.
            # Keep accepting the ESP32 payload unchanged, but use the backend
            # configured default for storage, alerts, model scoring, and UI.
            d.last_seen=ts;d.status='ONLINE';r=ReadingRow(device_id=payload.device_id,ph=payload.ph,tds=payload.tds,turbidity=settings.default_turbidity_ntu,temperature=payload.temperature,created_at=ts);db.add(r);db.commit();db.refresh(r);created,email_alert=eval_alerts(db,r,ts);out=serialize(r);dev=serialize(d)
        await manager.publish({'type':'reading.created','reading':out,'device':dev,'model_assessment':model_assessment(r)})
        if email_alert:background_tasks.add_task(send_model_alert_email,email_alert)
        for a in created:
            alert=serialize(a);await manager.publish({'type':'alert.created','alert':alert})
            if a.parameter=='model':background_tasks.add_task(send_model_alert_email,alert)
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
    if token_username(ws.query_params.get('token')) is None:
        await ws.close(code=4401);return
    await manager.connect(ws)
    try:
        while True:await ws.receive_text()
    except WebSocketDisconnect:manager.disconnect(ws)
    except Exception:manager.disconnect(ws)
