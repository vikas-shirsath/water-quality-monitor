from fastapi.testclient import TestClient
from app.main import app

def test_health_and_reading_lifecycle():
    with TestClient(app) as client:
        assert client.get('/api/health').status_code == 200
        assert client.get('/api/dashboard').status_code == 200
        payload={'device_id':'TEST-WQM','ph':7.1,'tds':240,'turbidity':2.2,'temperature':25.8}
        response=client.post('/api/readings',json=payload)
        assert response.status_code == 201
        assert response.json()['device_id']=='TEST-WQM'
        assert client.get('/api/readings?device_id=TEST-WQM').json()['total']>=1

def test_validation_and_threshold_alert_actions():
    with TestClient(app) as client:
        invalid=client.post('/api/readings',json={'device_id':'TEST-BAD','ph':19,'tds':1,'turbidity':1,'temperature':20})
        assert invalid.status_code == 422
        event=client.post('/api/readings',json={'device_id':'TEST-ALERT','ph':7,'tds':200,'turbidity':9,'temperature':25})
        assert event.status_code == 201
        alerts=client.get('/api/alerts').json()
        alert=next(a for a in alerts if a['device_id']=='TEST-ALERT')
        assert alert['severity']=='CRITICAL'
        assert client.post(f"/api/alerts/{alert['id']}/acknowledge").json()['acknowledged'] is True
        assert client.post(f"/api/alerts/{alert['id']}/resolve").json()['resolved_at'] is not None
