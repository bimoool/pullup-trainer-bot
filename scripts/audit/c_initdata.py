"""Test-only: print signed initData for a telegram id (BOT_TOKEN=audit-token)."""
import hashlib, hmac, json, sys, time, urllib.parse
tok = "audit-token"
user = json.dumps({"id": int(sys.argv[1]), "first_name": "Audit"}, separators=(",", ":"))
f = {"user": user, "auth_date": str(int(time.time())), "query_id": "AAEAAAAAAAAA"}
dcs = "\n".join(f"{k}={f[k]}" for k in sorted(f)).replace("/", "\\/")
sk = hmac.new(b"WebAppData", tok.encode(), hashlib.sha256).digest()
f["hash"] = hmac.new(sk, dcs.encode(), hashlib.sha256).hexdigest()
print("&".join(f"{k}={urllib.parse.quote(v, safe='')}" for k, v in f.items()))
