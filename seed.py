"""Creates SIMULATED demo users + 5-day histories. Run: python seed.py  (local only; never seed real/production data)"""
import json
import db as D
from main import hpw, now
from risk import assess
D.init(); c = D.connect()
PROFILES = {"Sarah (demo)": 1.0, "Demo Patient B": .5, "Demo Patient C": .05}

def user(email, role, name, clinician_id=None):
    r = c.execute("select id from users where email=?", (email,)).fetchone()
    if r: return r["id"]
    return c.insert("insert into users(email,pw,role,name,consent,clinician_id) values(?,?,?,?,?,?)",
                    (email, hpw("demo1234"), role, name, now() if role == "patient" else None, clinician_id))

doc = user("doc@demo.test", "clinician", "Dr. Demo")
for i, (name, k) in enumerate(PROFILES.items()):
    uid = user(f"p{i}@demo.test", "patient", name, doc if i < 2 else None)  # patient C stays unassigned (demo of the claim flow)
    if c.execute("select 1 from checkins where user_id=?", (uid,)).fetchone(): continue
    hist = []
    for d in range(5):
        f = d / 4; q = f * f
        cur = dict(temp=round(36.7 + k * 1.7 * q, 1), weight=round(62 - k * 2.5 * f, 1), fever=round(k * 6 * q), nausea=round(k * 5 * q),
                   vomiting=round(k * 7 * q), diarrhea=round(k * 4 * q), pain=round(1 + k * 5 * q), fatigue=round(1 + k * 7 * f),
                   appetite_loss=round(k * 5 * q), medication_taken=True, notes="")
        a = assess(cur, hist); hist.append(cur)
        cid = c.insert("insert into checkins(user_id,ts,data,level,score,reasons) values(?,?,?,?,?,?)", (uid, now(), json.dumps(cur), a["level"], a["score"], json.dumps(a["reasons"])))
        if a["level"] != "GREEN":
            op = c.execute("select id from alerts where user_id=? and status='open'", (uid,)).fetchone()
            if op: c.execute("update alerts set level=?,checkin_id=?,reasons=?,ts=? where id=?", (a["level"], cid, json.dumps(a["reasons"]), now(), op["id"]))
            else: c.execute("insert into alerts(user_id,checkin_id,level,reasons,ts) values(?,?,?,?,?)", (uid, cid, a["level"], json.dumps(a["reasons"]), now()))
c.commit(); c.close(); print("Seeded. Clinician: doc@demo.test / demo1234 · Patients: p0..p2@demo.test / demo1234")
