"""Authorised API driver for the edited-copy rehearsal (isolated API + DB only, bot token = rehearsal token).

    edited_copy_api.py <base> <token> edit <db_dsn>        # старый API: правка E1/E2, удаление копии E4 (оба пользователя)
    edited_copy_api.py <base> <token> summary <out.json>   # итоги Журнала/Профиля/Аналитики/списка сессий
    edited_copy_api.py diff <a.json> <b.json>
"""
import hashlib, hmac, json, subprocess, sys, time, urllib.error, urllib.request
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote, urlencode

USERS = (770001, 770002)


def init(token, tid):
    f = {"user": json.dumps({"id": tid, "first_name": "T"}, separators=(",", ":"), ensure_ascii=False),
         "auth_date": str(int(time.time())), "query_id": "AAEAAAAAAAAA"}
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(f.items()))
    f["hash"] = hmac.new(hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest(), dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(f, quote_via=quote)


def call(base, token, tid, method, path, body=None):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Telegram-Init-Data": init(token, tid), "Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=60)
        raw = r.read()
        return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300].decode("utf8", "replace")


def psql(dsn, sql):
    return subprocess.run(["psql", dsn, "-Atc", sql], capture_output=True, text=True, check=True).stdout.strip().splitlines()


def edit(base, token, dsn):
    for tid in USERS:
        rows = psql(dsn, f"select ts.id from training_sessions ts join users u on u.id=ts.user_id where u.telegram_id={tid} "
                         f"and ts.source='elective' order by ts.performed_at")
        e1, e2, e3, e4 = (int(x) for x in rows)
        c, b = call(base, token, tid, "PATCH", f"/api/v2/sessions/{e1}", {"sets": [{"block_index": 0, "set_number": 1, "value": 20, "note": None}]})
        print(tid, "E1 edit value 15->20:", c, "" if c == 200 else b)
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
        c, b = call(base, token, tid, "PATCH", f"/api/v2/sessions/{e2}", {"performed_on": yesterday})
        print(tid, "E2 move date -> yesterday:", c, "" if c == 200 else b)
        c, b = call(base, token, tid, "DELETE", f"/api/v2/sessions/{e4}")
        print(tid, "E4 delete copy:", c, "" if c in (200, 204) else b)


def summary(base, token, out):
    now = datetime.now(timezone.utc)
    months = {now.strftime("%Y-%m"), (now - timedelta(days=31)).strftime("%Y-%m")}
    res = {}
    for tid in USERS:
        r = {}
        for m in sorted(months):
            r[f"journal_days_{m}"] = call(base, token, tid, "GET", f"/api/v2/journal/days?month={m}")
        r["sessions_completed"] = call(base, token, tid, "GET", "/api/v2/sessions?status=completed&limit=200")
        r["analytics"] = call(base, token, tid, "GET", f"/api/v2/analytics/training?from={(date.today() - timedelta(days=60)).isoformat()}&to={date.today().isoformat()}")
        r["profile"] = call(base, token, tid, "GET", "/api/profile")
        r["history"] = call(base, token, tid, "GET", "/api/history")
        res[str(tid)] = r
    json.dump(res, open(out, "w"), indent=1, sort_keys=True, default=str)
    for tid, r in res.items():
        print(tid, {k: v[0] for k, v in r.items()})


def digest(obj):
    """сессии: (минута, источник, сумма value) — без id; остальное — как есть"""
    return obj


def diff(a, b):
    A, B = json.load(open(a)), json.load(open(b))
    for tid in A:
        for k in A[tid]:
            (ca, va), (cb, vb) = A[tid][k], B[tid][k]
            if k == "sessions_completed" and isinstance(va, dict) and isinstance(vb, dict):
                def sig(v):
                    return sorted((s.get("performed_at", "")[:16], s.get("source"), json.dumps(s.get("blocks"), sort_keys=True, default=str)[:0]) for s in v.get("sessions", []))
                same = sig(va) == sig(vb)
                print(f"{tid} {k}: sessions {len(va.get('sessions', []))} -> {len(vb.get('sessions', []))} | same_(minute,source)_multiset={same}")
                continue
            same = (ca, va) == (cb, vb)
            print(f"{tid} {k}: status {ca}->{cb} {'IDENTICAL' if same else 'DIFFERS'}")
            if not same and isinstance(va, dict) and isinstance(vb, dict):
                for kk in sorted(set(va) | set(vb)):
                    if va.get(kk) != vb.get(kk):
                        print(f"     {kk}: {json.dumps(va.get(kk), default=str)[:160]}  ->  {json.dumps(vb.get(kk), default=str)[:160]}")


if __name__ == "__main__":
    if sys.argv[1] == "diff":
        diff(sys.argv[2], sys.argv[3])
    elif sys.argv[3] == "edit":
        edit(sys.argv[1], sys.argv[2], sys.argv[4])
    else:
        summary(sys.argv[1], sys.argv[2], sys.argv[4])
