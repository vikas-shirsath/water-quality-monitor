"""Populate a development database with three days of representative telemetry."""
import math, random
from datetime import datetime,timedelta,timezone
from app.main import Base,DeviceRow,ReadingRow,AlertRow,ThresholdRow,Session,engine
Base.metadata.create_all(engine);random.seed(14)
with Session() as db:
    d=db.get(DeviceRow,'WQM-001') or DeviceRow(device_id='WQM-001',name='North basin sensor',firmware_version='1.2.4',sampling_interval=30,status='ONLINE')
    db.add(d);db.merge(ThresholdRow(id=1))
    if not db.query(ReadingRow).first():
        now=datetime.now(timezone.utc)
        for i in range(432):
            ph=7.1+math.sin(i/17)*.2+random.uniform(-.04,.04);tds=245+math.sin(i/23)*29+random.uniform(-5,5);turb=2.4+math.sin(i/11)*.6+random.uniform(-.12,.12);temp=26.3+math.sin(i/31)*.9+random.uniform(-.15,.15)
            if i in (90,270):turb=6.4
            if i==350:ph=6.25
            db.add(ReadingRow(device_id='WQM-001',ph=round(ph,2),tds=round(tds,1),turbidity=round(turb,2),temperature=round(temp,1),created_at=now-timedelta(minutes=(431-i)*10)))
        db.add(AlertRow(device_id='WQM-001',parameter='turbidity',value=6.4,threshold=5,severity='CRITICAL',message='TURBIDITY above maximum',created_at=datetime.now(timezone.utc)-timedelta(hours=8),acknowledged=True))
        db.add(AlertRow(device_id='WQM-001',parameter='ph',value=6.25,threshold=6.5,severity='WARNING',message='PH below minimum',created_at=datetime.now(timezone.utc)-timedelta(hours=2)))
    db.commit()
print('Seeded WQM-001 and development telemetry.')
