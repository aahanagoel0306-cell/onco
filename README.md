# ONCO-CARE — 4-week prototype build
Decision-support prototype. **Simulated data only. Not a medical device.**

## Run (5 minutes)
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                      # engine + API tests
python seed.py                 # demo users + simulated histories
SECRET=$(openssl rand -hex 32) uvicorn main:app --reload
# open http://localhost:8000   doc@demo.test / demo1234  (clinician)   p0@demo.test / demo1234 (patient)
```
API docs: http://localhost:8000/docs · Clinician registration needs invite code (`CLINIC_CODE`, default `onco-demo` — change it).

## What changed in v2
- XSS-safe frontend (all dynamic text escaped), consent screen, login rate limiting, one open alert per patient, `PROD=1` refuses the default secret.
- Risk engine v2: median baseline (needs 3 check-ins), severe-symptom and missed-medication rules, every reason shows its score points.
- Clinician UI: alert tabs + level filter, analytics, per-symptom chart, explainability panel. PWA manifest + service worker, Dockerfile, CI, `.env.example`.
- **v3:** PostgreSQL (Supabase, Mumbai) via `DATABASE_URL`, SQLite kept for local dev/tests (`db.py`). Patients can be claimed by a clinician; clinicians only see their own patients plus the unassigned pool.
- Still TODO: email/WhatsApp notifications, JWT refresh, landing/story site.

## Production setup
1. Supabase project `onco-care` already has the schema. Get the connection string: Supabase dashboard > Connect > Session/Transaction pooler, and put it in `DATABASE_URL` (reset the DB password there if you don't have it).
2. Push this folder to a GitHub repo, create a Render web service from it (runtime Docker), and set env vars: `DATABASE_URL`, `SECRET` (`openssl rand -hex 32`), `CLINIC_CODE`, `PROD=1`.
3. Do NOT set `SEED=1` on a database with real data; it creates demo users with a known password.

## What exists
- `risk.py` rule-based temporal engine: personal baseline (first 3 check-ins), consecutive-day worsening, multi-symptom co-occurrence, fever/weight rules → GREEN/YELLOW/RED + plain-language reasons.
- `main.py` FastAPI + SQLite: auth (PBKDF2 + signed tokens), roles, check-ins, patients, alerts, notes, resolve, audit log.
- `frontend/` patient check-in + trend + history; clinician dashboard, search, patient detail, alert actions.
- `tests/` risk + full API flow incl. role enforcement and validation.

## 4-week plan
| Week | Goal | Done when |
|---|---|---|
| 1 | Run this baseline; agree symptom list/thresholds with a clinical advisor; DB → PostgreSQL; deploy to a free host with HTTPS | Everyone can log in on the live URL |
| 2 | Polish patient app (PWA, reminders), real charts, alert filters/tabs, patient detail per-symptom charts, notification (email/WhatsApp stub) | Full patient→alert→clinician loop demoed live |
| 3 | Explainability panel, analytics page, rate limiting, JWT refresh, consent screen, backup + logging; test on 5–10 synthetic scenarios | Test suite green; scenario table reviewed by advisor |
| 4 | Landing/story site (the multi-page site), demo script, 3-min video, bug bash, README + architecture slide | Rehearsed demo; nothing crashes |

Suggested split: backend/AI · frontend/UX · clinical research + test scenarios · demo/story/docs.

## Before any real patient (do NOT skip)
Oncologist-set thresholds; retrospective validation; track false positives/negatives; ethics/IRB approval; India DPDP Act consent + data-protection review; hosting/security audit. Until then: simulated data only, no medical claims.
