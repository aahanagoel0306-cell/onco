import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["DB"] = tempfile.mktemp(suffix=".db")
from risk import assess
from fastapi.testclient import TestClient
from main import app
z = dict(temp=36.8, weight=62, fever=0, nausea=0, vomiting=0, diarrhea=0, pain=1, fatigue=1, appetite_loss=0)

def test_stable_is_green(): assert assess(z, [])["level"] == "GREEN"
def test_worsening_is_red():
    bad = {**z, "temp": 38.5, "vomiting": 6, "fever": 6, "fatigue": 8}
    r = assess(bad, [z, z, z]); assert r["level"] == "RED" and r["reasons"]

def test_consent_required_and_dedupe_and_throttle():
    c = TestClient(app)
    assert c.post("/api/auth/register", json=dict(email="n@x.io", password="password1", name="N")).status_code == 400
    c.post("/api/auth/register", json=dict(email="m@x.io", password="password1", name="M", consent=True))
    c.post("/api/auth/register", json=dict(email="k@x.io", password="password1", name="K", role="clinician", code="onco-demo"))
    H = {"Authorization": "Bearer " + c.post("/api/auth/login", json=dict(email="m@x.io", password="password1")).json()["token"]}
    K = {"Authorization": "Bearer " + c.post("/api/auth/login", json=dict(email="k@x.io", password="password1")).json()["token"]}
    for _ in range(2): c.post("/api/checkins", json={"temp": 38.6, "vomiting": 7, "fever": 7, "fatigue": 8}, headers=H)
    assert len([a for a in c.get("/api/alerts", headers=K).json() if a["name"] == "M"]) == 1
    assert c.get("/api/analytics", headers=K).json()["open_alerts"] >= 1
    for _ in range(5): c.post("/api/auth/login", json=dict(email="zz@x.io", password="wrongwrong"))
    assert c.post("/api/auth/login", json=dict(email="zz@x.io", password="wrongwrong")).status_code == 429

def test_flow():
    c = TestClient(app)
    c.post("/api/auth/register", json=dict(email="a@x.io", password="password1", name="A", consent=True))
    c.post("/api/auth/register", json=dict(email="d@x.io", password="password1", name="D", role="clinician", code="onco-demo"))
    t = c.post("/api/auth/login", json=dict(email="a@x.io", password="password1")).json()["token"]
    d = c.post("/api/auth/login", json=dict(email="d@x.io", password="password1")).json()["token"]
    H, K = {"Authorization": "Bearer " + t}, {"Authorization": "Bearer " + d}
    assert c.post("/api/checkins", json={"temp": 38.6, "vomiting": 7, "fever": 7, "fatigue": 8}, headers=H).json()["level"] == "RED"
    assert c.get("/api/patients", headers=H).status_code == 403
    al = c.get("/api/alerts", headers=K).json(); assert al and al[0]["level"] == "RED"
    assert c.post(f"/api/alerts/{al[0]['id']}/resolve", headers=K).status_code == 200
    assert c.post("/api/checkins", json={"temp": 50}, headers=H).status_code == 422

def test_assignment_isolation():
    c = TestClient(app)
    for e, r, kw in [("pa@x.io", "patient", dict(consent=True)), ("c1@x.io", "clinician", dict(code="onco-demo")), ("c2@x.io", "clinician", dict(code="onco-demo"))]:
        c.post("/api/auth/register", json=dict(email=e, password="password1", name=e, role=r, **kw))
    tok = lambda e: {"Authorization": "Bearer " + c.post("/api/auth/login", json=dict(email=e, password="password1")).json()["token"]}
    P, A, B = tok("pa@x.io"), tok("c1@x.io"), tok("c2@x.io")
    c.post("/api/checkins", json={"temp": 38.6, "vomiting": 7, "fever": 7, "fatigue": 8}, headers=P)
    pid = [p for p in c.get("/api/patients", headers=A).json() if p["name"] == "pa@x.io"][0]["id"]
    assert c.post(f"/api/patients/{pid}/claim", headers=A).status_code == 200
    assert c.get(f"/api/patients/{pid}", headers=A).json()["assigned"] is True
    assert c.get(f"/api/patients/{pid}", headers=B).status_code == 403
    assert not [p for p in c.get("/api/patients", headers=B).json() if p["id"] == pid]
    aid = [a for a in c.get("/api/alerts", headers=A).json() if a["patient_id"] == pid][0]["id"]
    assert c.post(f"/api/alerts/{aid}/resolve", headers=B).status_code == 403
