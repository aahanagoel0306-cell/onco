import os, hmac, hashlib, json, time, base64, secrets
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, APIRouter, HTTPException, Depends, Header
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from risk import assess, SYM
import db as D
from db import J, DAY

KEY = os.environ.get("SECRET", "dev-change-me").encode()
if os.environ.get("PROD") and KEY == b"dev-change-me": raise SystemExit("Set SECRET before running with PROD=1")
CLINIC_CODE = os.environ.get("CLINIC_CODE", "onco-demo")
now = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")

def dbc():  # one connection per request, always closed
    c = D.connect()
    try: yield c
    finally: c.close()

def audit(c, actor, action, target=""):
    c.execute("insert into audit(ts,actor,action,target) values(?,?,?,?)", (now(), actor, action, target))

def hpw(p, salt=None):
    salt = salt or secrets.token_hex(8)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", p.encode(), salt.encode(), 120_000).hex()

def sign(p): return hmac.new(KEY, p.encode(), hashlib.sha256).hexdigest()

def token(u):
    p = base64.urlsafe_b64encode(json.dumps(dict(uid=u["id"], role=u["role"], exp=time.time() + 86400)).encode()).decode()
    return p + "." + sign(p)

def me(authorization: str = Header("")):
    try:
        p, sig = authorization.removeprefix("Bearer ").rsplit(".", 1)
        if not hmac.compare_digest(sig, sign(p)): raise ValueError
        d = json.loads(base64.urlsafe_b64decode(p))
        if d["exp"] < time.time(): raise ValueError
        return d
    except Exception:
        raise HTTPException(401, "Please sign in again")

FAILS = {}
def throttle(k):
    t = time.time(); FAILS[k] = [x for x in FAILS.get(k, []) if t - x < 300]
    if len(FAILS[k]) >= 5: raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
def failed(k): FAILS.setdefault(k, []).append(time.time())

def clin(u=Depends(me)):
    if u["role"] != "clinician": raise HTTPException(403, "Clinician access only")
    return u

class Reg(BaseModel):
    email: str; password: str = Field(min_length=8); name: str = Field(max_length=80); role: str = "patient"; code: str = ""; consent: bool = False
class Login(BaseModel):
    email: str; password: str
class CheckIn(BaseModel):
    temp: float = Field(ge=34, le=42); weight: Optional[float] = Field(None, ge=20, le=250)
    fever: int = Field(0, ge=0, le=10); nausea: int = Field(0, ge=0, le=10); vomiting: int = Field(0, ge=0, le=10)
    diarrhea: int = Field(0, ge=0, le=10); pain: int = Field(0, ge=0, le=10); fatigue: int = Field(0, ge=0, le=10)
    appetite_loss: int = Field(0, ge=0, le=10); medication_taken: bool = True; notes: str = Field("", max_length=500)
class Note(BaseModel):
    text: str = Field(min_length=1, max_length=500)

api = APIRouter(prefix="/api")
ck_out = lambda r: dict(ts=r["ts"], level=r["level"], score=float(r["score"]), reasons=J(r["reasons"]), data=J(r["data"]))

def visible(c, u, pid):
    """Clinicians see their own patients plus the unassigned pool."""
    r = c.execute("select id,name,clinician_id from users where id=? and role='patient'", (pid,)).fetchone()
    if not r: raise HTTPException(404, "Not found")
    if r["clinician_id"] not in (None, u["uid"]): raise HTTPException(403, "Patient is assigned to another clinician")
    return r

@api.get("/health")
def health(): return {"ok": True, "db": "postgres" if D.PG else "sqlite"}

@api.post("/auth/register")
def register(r: Reg, c=Depends(dbc)):
    if r.role not in ("patient", "clinician"): raise HTTPException(400, "Bad role")
    if r.role == "clinician" and r.code != CLINIC_CODE: raise HTTPException(403, "Invalid clinician invite code")
    if r.role == "patient" and not r.consent: raise HTTPException(400, "Consent is required to use ONCO-CARE")
    try:
        c.execute("insert into users(email,pw,role,name,consent) values(?,?,?,?,?)", (r.email.lower(), hpw(r.password), r.role, r.name, now() if r.consent else None)); c.commit()
    except D.INTEGRITY:
        raise HTTPException(409, "Email already registered")
    return {"ok": True}

@api.post("/auth/login")
def login(l: Login, c=Depends(dbc)):
    throttle(l.email.lower()); u = c.execute("select * from users where email=?", (l.email.lower(),)).fetchone()
    if not u or not hmac.compare_digest(u["pw"], hpw(l.password, u["pw"].split("$")[0])):
        failed(l.email.lower()); raise HTTPException(401, "Wrong email or password")
    audit(c, u["id"], "login"); c.commit()
    return {"token": token(u), "role": u["role"], "name": u["name"]}

@api.post("/checkins")
def add_checkin(ci: CheckIn, u=Depends(me), c=Depends(dbc)):
    if u["role"] != "patient": raise HTTPException(403, "Patients only")
    cur = ci.model_dump()
    hist = [J(r["data"]) for r in c.execute("select data from checkins where user_id=? order by id", (u["uid"],))]
    a = assess(cur, hist)
    cid = c.insert("insert into checkins(user_id,ts,data,level,score,reasons) values(?,?,?,?,?,?)",
                   (u["uid"], now(), json.dumps(cur), a["level"], a["score"], json.dumps(a["reasons"])))
    if a["level"] != "GREEN":  # one open alert per patient: update instead of spamming
        op = c.execute("select id,level from alerts where user_id=? and status='open' order by id desc limit 1", (u["uid"],)).fetchone()
        if op:
            lv = "RED" if "RED" in (op["level"], a["level"]) else "YELLOW"
            c.execute("update alerts set level=?,checkin_id=?,reasons=?,ts=? where id=?", (lv, cid, json.dumps(a["reasons"]), now(), op["id"]))
        else:
            c.execute("insert into alerts(user_id,checkin_id,level,reasons,ts) values(?,?,?,?,?)", (u["uid"], cid, a["level"], json.dumps(a["reasons"]), now()))
    audit(c, u["uid"], "checkin", str(cid)); c.commit()
    return a

@api.get("/checkins/me")
def my_checkins(u=Depends(me), c=Depends(dbc)):
    return [ck_out(r) for r in c.execute("select * from checkins where user_id=? order by id desc limit 30", (u["uid"],))]

@api.get("/patients")
def patients(u=Depends(clin), c=Depends(dbc)):
    out = []
    for p in c.execute("select id,name,clinician_id from users where role='patient' and (clinician_id is null or clinician_id=?)", (u["uid"],)).fetchall():
        r = c.execute("select * from checkins where user_id=? order by id desc limit 1", (p["id"],)).fetchone()
        out.append(dict(id=p["id"], name=p["name"], mine=p["clinician_id"] == u["uid"], level=r["level"] if r else None,
                        score=float(r["score"]) if r else None, reasons=J(r["reasons"]) if r else [], last=r["ts"] if r else None))
    order = {"RED": 0, "YELLOW": 1, "GREEN": 2, None: 3}
    return sorted(out, key=lambda x: order[x["level"]])

@api.get("/patients/{pid}")
def patient(pid: int, u=Depends(clin), c=Depends(dbc)):
    p = visible(c, u, pid); audit(c, u["uid"], "view_patient", str(pid)); c.commit()
    return dict(id=p["id"], name=p["name"], assigned=p["clinician_id"] == u["uid"],
                checkins=[ck_out(r) for r in c.execute("select * from checkins where user_id=? order by id", (pid,))])

@api.post("/patients/{pid}/claim")
def claim(pid: int, u=Depends(clin), c=Depends(dbc)):
    visible(c, u, pid); c.execute("update users set clinician_id=? where id=?", (u["uid"], pid)); audit(c, u["uid"], "claim", str(pid)); c.commit(); return {"ok": True}

@api.get("/alerts")
def alerts(status: str = "open", u=Depends(clin), c=Depends(dbc)):
    rows = c.execute("select a.*,u.name from alerts a join users u on u.id=a.user_id where a.status=? and (u.clinician_id is null or u.clinician_id=?) order by (a.level='RED') desc, a.id desc", (status, u["uid"]))
    return [dict(id=r["id"], patient_id=r["user_id"], name=r["name"], level=r["level"], reasons=J(r["reasons"]),
                 ts=r["ts"], status=r["status"], notes=J(r["notes"])) for r in rows]

def alert_row(c, u, aid):
    r = c.execute("select id,user_id,notes from alerts where id=?", (aid,)).fetchone()
    if not r: raise HTTPException(404, "Not found")
    visible(c, u, r["user_id"]); return r

@api.post("/alerts/{aid}/resolve")
def resolve(aid: int, u=Depends(clin), c=Depends(dbc)):
    alert_row(c, u, aid); c.execute("update alerts set status='resolved' where id=?", (aid,)); audit(c, u["uid"], "resolve", str(aid)); c.commit(); return {"ok": True}

@api.post("/alerts/{aid}/notes")
def note(aid: int, n: Note, u=Depends(clin), c=Depends(dbc)):
    r = alert_row(c, u, aid); notes = J(r["notes"]) + [dict(ts=now(), by=u["uid"], text=n.text)]
    c.execute("update alerts set notes=? where id=?", (json.dumps(notes), aid)); audit(c, u["uid"], "note", str(aid)); c.commit(); return {"ok": True}

@api.get("/analytics")
def analytics(u=Depends(clin), c=Depends(dbc)):
    lv = {r["level"]: r["n"] for r in c.execute("select level,count(*) n from checkins group by level")}
    day = [dict(day=r["d"], n=r["n"]) for r in c.execute(f"select {DAY} d,count(*) n from checkins group by d order by d desc limit 14")]
    return dict(by_level=lv, per_day=day[::-1], patients=c.execute("select count(*) n from users where role='patient'").fetchone()["n"],
                open_alerts=c.execute("select count(*) n from alerts where status='open'").fetchone()["n"])

app = FastAPI(title="ONCO-CARE API (prototype, simulated data only)")
D.init(); app.include_router(api)
app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "frontend"), html=True))
