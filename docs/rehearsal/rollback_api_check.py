"""Rollback evidence: OLD code (develop/current) against (A) the old schema and (B) the upgraded+converged schema.

    rollback_api_check.py <baseA> <baseB> <token>

Reads: critical authorised GETs WITH valid parameters, content summary compared A vs B (status + top-level shape + sizes).
Writes (each side, own DB copy): 1) record an old journal entry (POST /api/v2/sessions backdated),
2) start a FREE live session from the user's own workout (POST /sessions/live {workout_id}), log sets (sets:batch),
   complete (POST /complete) -> then it must appear in GET /sessions and in journal/days.
"""
import hashlib, hmac, json, sys, time, urllib.error, urllib.request, uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote, urlencode

A, B, TOKEN = sys.argv[1], sys.argv[2], sys.argv[3]
USERS = (880002, 880004, 880006, 880007, 880010, 880011, 880003)
today = date.today()
MONTH = today.strftime("%Y-%m")


def init(tid):
    f = {"user": json.dumps({"id": tid, "first_name": "T"}, separators=(",", ":"), ensure_ascii=False),
         "auth_date": str(int(time.time())), "query_id": "AAEAAAAAAAAA"}
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(f.items()))
    f["hash"] = hmac.new(hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest(), dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(f, quote_via=quote)


def call(base, tid, method, path, body=None):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Telegram-Init-Data": init(tid), "Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=60)
        raw = r.read()
        return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200].decode("utf8", "replace")


READS = [
    "/api/profile", "/api/profile/prefs", "/api/subscription", "/api/dashboard", "/api/history", "/api/progress",
    "/api/analytics", "/api/leaderboard?metric=max_reps", "/api/profile/body-metrics?metric=weight_kg",
    f"/api/v2/journal/days?month={MONTH}", "/api/v2/sessions?status=completed&limit=50",
    f"/api/v2/analytics/training?from={(today - timedelta(days=60)).isoformat()}&to={today.isoformat()}",
    "/api/v2/plan", "/api/v2/plan-items", "/api/v2/programs", "/api/v2/workouts", "/api/v2/workouts/catalog",
    "/api/v2/sessions/live/active", "/api/workout/plan", "/api/gto",
]


def shape(v):
    if isinstance(v, dict):
        return {k: (len(x) if isinstance(x, list) else type(x).__name__) for k, x in sorted(v.items())}
    return type(v).__name__


print("== READS (valid params): old code on old schema (A) vs upgraded+converged schema (B)")
bad = 0
for path in READS:
    sa, sb = [], []
    differ = []
    for tid in USERS:
        (ca, va), (cb, vb) = call(A, tid, "GET", path), call(B, tid, "GET", path)
        sa.append(ca); sb.append(cb)
        if ca == 200 and cb == 200 and shape(va) != shape(vb):
            differ.append((tid, {k: (shape(va).get(k), shape(vb).get(k)) for k in set(shape(va)) | set(shape(vb)) if shape(va).get(k) != shape(vb).get(k)}))
    ok = all(c == 200 for c in sa + sb)
    bad += 0 if ok else 1
    print(f"  {'OK ' if ok else 'BAD'} {path.split('?')[0]:34s} A={sorted(set(sa))} B={sorted(set(sb))}" + (f"  shape/size differs for {len(differ)} users" if differ else ""))
    for tid, d in differ[:3]:
        print(f"       user {tid}: {d}")
print(f"  endpoints with non-200: {bad}")

print("\n== WRITES by OLD code (user 880011, own workout; A and B each on its own DB copy)")
for name, base in (("A old schema", A), ("B upgraded", B)):
    tid = 880011
    r = {}
    before = call(base, tid, "GET", "/api/v2/sessions?status=completed&limit=200")[1]["sessions"]
    now = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    wk = call(base, tid, "GET", "/api/v2/workouts")[1]
    workouts = wk.get("workouts", wk) if isinstance(wk, dict) else wk
    own = [w for w in workouts if (w.get("title") or w.get("name")) == "Золотая тренировка"]
    wid = own[0]["id"] if own else workouts[0]["id"]
    ex = call(base, tid, "GET", "/api/v2/workouts")  # noqa: F841
    c, b = call(base, tid, "POST", "/api/v2/sessions/live", {"client_session_id": str(uuid.uuid4()), "workout_id": wid})
    r["live start"] = c
    if c == 200:
        sid, blocks = b["id"], b.get("blocks", [])
        exercise_id = None
        for blk in blocks:
            exercise_id = blk.get("exercise_id") or exercise_id
        c2, b2 = call(base, tid, "POST", f"/api/v2/sessions/live/{sid}/sets:batch",
                      {"sets": [{"set_index": 0, "exercise_id": exercise_id, "value": "8"}, {"set_index": 1, "exercise_id": exercise_id, "value": "8"}]})
        r["sets:batch"] = c2 if c2 == 200 else (c2, b2)
        c3, b3 = call(base, tid, "POST", f"/api/v2/sessions/live/{sid}/complete", {"abandoned": False, "effort": 3})
        r["complete"] = c3 if c3 == 200 else (c3, b3)
        r["completed status"] = (b3 or {}).get("status") if isinstance(b3, dict) else None
    c4, b4 = call(base, tid, "POST", "/api/v2/sessions", {"source": "backdated", "performed_at": now, "effort": 3, "blocks": [
        {"exercise_id": exercise_id, "sets": [{"set_number": 1, "metric_type": "reps", "value": "9", "unit": "reps"}]}] if exercise_id else []})
    r["journal entry (backdated)"] = c4 if c4 == 200 else (c4, str(b4)[:120])
    after = call(base, tid, "GET", "/api/v2/sessions?status=completed&limit=200")[1]["sessions"]
    days = call(base, tid, "GET", f"/api/v2/journal/days?month={MONTH}")[1]
    r["completed sessions before->after"] = (len(before), len(after))
    r["journal day total"] = sum(d["count"] for d in days["days"])
    print(f"  {name}: {r}")
