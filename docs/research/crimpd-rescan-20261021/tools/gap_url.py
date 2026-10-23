"""Launch URL / initData for the isolated local stand (synthetic ids only).
usage: gap_url.py TELEGRAM_ID [--init]
Uses a SHORT placeholder `signature` (the app never verifies it; the HMAC covers it) so the URL can be copied by hand."""
import sys, os, time, json
from urllib.parse import quote, urlencode
sys.path.insert(0, os.getcwd())
from scripts.qa.mint_init_data import sign_fields
tid = int(sys.argv[1]); tok = os.environ.get("BOT_TOKEN", "gap-local-token")
user = json.dumps({"id": tid, "first_name": "G%d" % tid}, separators=(",", ":"), ensure_ascii=False)
f = {"user": user, "auth_date": str(int(time.time())), "query_id": "AAEAAAAAAAAA", "signature": "SIG"}
f["hash"] = sign_fields(f, tok)
init = urlencode(f, quote_via=quote)
if "--init" in sys.argv:
    print(init)
else:
    print("http://127.0.0.1:8021/#tgWebAppData=%s&tgWebAppVersion=8.0&tgWebAppPlatform=ios&tgWebAppThemeParams=%%7B%%7D" % quote(init, safe=""))
