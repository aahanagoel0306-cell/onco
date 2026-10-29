"""Database layer: PostgreSQL when DATABASE_URL is set (production), SQLite otherwise (local dev/tests)."""
import os, sqlite3, json
URL = os.environ.get("DATABASE_URL"); PG = bool(URL)
if PG:
    import psycopg
    from psycopg.rows import dict_row
    INTEGRITY = (psycopg.errors.UniqueViolation,)
else:
    INTEGRITY = (sqlite3.IntegrityError,)
J = lambda v: json.loads(v) if isinstance(v, str) else v          # jsonb comes back parsed, sqlite as text
DAY = "substr(ts::text,1,10)" if PG else "substr(ts,1,10)"

class Conn:
    def __init__(s):
        if PG: s.c = psycopg.connect(URL, row_factory=dict_row)
        else: s.c = sqlite3.connect(os.environ.get("DB", "onco.db")); s.c.row_factory = sqlite3.Row
    def execute(s, q, a=()):
        if PG: cur = s.c.cursor(); cur.execute(q.replace("?", "%s"), a); return cur
        return s.c.execute(q, a)
    def insert(s, q, a=()):  # returns the new row id
        if PG: return s.execute(q + " returning id", a).fetchone()["id"]
        return s.execute(q, a).lastrowid
    def commit(s): s.c.commit()
    def close(s): s.c.close()

def connect(): return Conn()

SQLITE_SCHEMA = """
create table if not exists users(id integer primary key, email text unique, pw text, role text, name text, consent text, clinician_id int);
create table if not exists checkins(id integer primary key, user_id int, ts text, data text, level text, score real, reasons text);
create table if not exists alerts(id integer primary key, user_id int, checkin_id int, level text, reasons text, ts text, status text default 'open', notes text default '[]');
create table if not exists audit(id integer primary key, ts text, actor int, action text, target text);"""

def init():  # PostgreSQL schema is managed by migrations (Supabase), SQLite is created here
    if not PG:
        c = connect(); c.c.executescript(SQLITE_SCHEMA); c.commit(); c.close()
