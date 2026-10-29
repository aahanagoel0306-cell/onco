"""Rule-based temporal risk engine v2 (decision support only).
Thresholds are PLACEHOLDERS: must be set and validated with oncologists.
Every reason carries its score contribution, e.g. "Temperature raised (+1.5)"."""
from statistics import median
SYM = ["fever", "nausea", "vomiting", "diarrhea", "pain", "fatigue", "appetite_loss"]
W = dict(fever=.25, nausea=.1, vomiting=.35, diarrhea=.3, pain=.2, fatigue=.2, appetite_loss=.1)
LABEL = lambda k: k.replace("_", " ")
BASELINE_N = 3  # personal baseline = first 3 check-ins (median); not used until 3 exist

def assess(cur: dict, hist: list) -> dict:
    """cur: today's check-in; hist: previous check-ins, oldest -> newest."""
    s, R = 0.0, []
    def add(pts, why):
        nonlocal s; s += pts
        if why: R.append(f"{why} (+{pts:g})")
    t = cur["temp"]
    if t >= 38.0: add(3.5, "Temperature at or above 38.0 C")
    elif t >= 37.5: add(1.5, "Temperature raised")
    s += sum(cur[k] * W[k] for k in SYM)  # base symptom load (not itemised)
    if max(cur[k] for k in SYM) >= 8: add(1, "Severe symptom (8+/10)")
    if len(hist) >= BASELINE_N:
        base = hist[:BASELINE_N]
        for k in SYM:
            if cur[k] - median(h[k] for h in base) >= 3: add(.5, f"{LABEL(k).title()} above personal baseline")
        w0 = [h["weight"] for h in base if h.get("weight")]
        if w0 and cur.get("weight") and median(w0) - cur["weight"] >= 2: add(1.5, "Weight down 2 kg or more from baseline")
    if len(hist) >= 2:  # consecutive-day worsening
        up = [k for k in SYM if cur[k] > hist[-1][k] >= hist[-2][k] and cur[k] - hist[-2][k] >= 2]
        if up: add(1 + .5 * len(up), "Worsening across consecutive days: " + ", ".join(LABEL(k) for k in up))
    if sum(cur[k] >= 5 for k in SYM) >= 2: add(1, "Multiple symptoms elevated together")
    if not cur.get("medication_taken", True): add(.5, "Medication not taken")
    lvl = "RED" if s >= 6 else "YELLOW" if s >= 3 else "GREEN"
    return dict(level=lvl, score=round(s, 1), reasons=R)
