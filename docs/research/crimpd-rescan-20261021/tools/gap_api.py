"""Tiny API client for the isolated local stand. Run from the app checkout:  python gap_api.py TID METHOD PATH [json]"""
import sys, os, json, time, urllib.request
from urllib.parse import quote, urlencode
sys.path.insert(0, os.getcwd())
from scripts.qa.mint_init_data import sign_fields
BASE = "http://127.0.0.1:8021"; TOK = os.environ.get("BOT_TOKEN", "gap-local-token")
def init(tid):
    user = json.dumps({"id": tid, "first_name": "G%d" % tid}, separators=(",", ":"), ensure_ascii=False)
    f = {"user": user, "auth_date": str(int(time.time())), "query_id": "AAEAAAAAAAAA", "signature": "SIG"}
    f["hash"] = sign_fields(f, TOK); return urlencode(f, quote_via=quote)
def call(tid, method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=(json.dumps(body).encode() if body is not None else None),
        headers={"X-Telegram-Init-Data": init(tid), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r: raw = r.read().decode(); code = r.status
    except urllib.error.HTTPError as e: raw = e.read().decode(); code = e.code
    try: data = json.loads(raw) if raw else None
    except Exception: data = raw
    return code, data
if __name__ == "__main__":
    tid, method, path = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    body = json.loads(sys.argv[4]) if len(sys.argv) > 4 else None
    code, data = call(tid, method, path, body)
    print(code, json.dumps(data, ensure_ascii=False, indent=1)[:int(os.environ.get("MAXC", "3000"))])
