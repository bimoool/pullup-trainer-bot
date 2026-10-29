"""Управляемый прокси перед ИЗОЛИРОВАННЫМ стендом (127.0.0.1:8021) для офлайн-сценариев.
Режимы (POST /__mode/<name>, GET /__log): pass | drop (закрыть соединение, на бэкенд не пересылать) |
drop_response (переслать на бэкенд, ответ клиенту не отдавать — запрос ПРИМЕНЁН, клиент ответа не увидит) |
delay:<sec> (задержка перед пересылкой). Применяется только к /api/*; статика всегда проходит.
Логирует каждый запрос: режим, метод, путь, статус бэкенда."""
import http.client, json, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
BACK = ("127.0.0.1", 8021); MODE = ["pass"]; LOG = []; LOCK = threading.Lock()

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def _ctl(self):
        if self.path.startswith("/__mode/"):
            MODE[0] = self.path[8:]; LOG.append({"t": time.time(), "mode_set": MODE[0]}); return self._send(200, b"ok")
        if self.path == "/__log": return self._send(200, json.dumps(LOG).encode())
        if self.path == "/__clear": LOG.clear(); return self._send(200, b"ok")
        return False
    def _send(self, code, body, headers=()):
        self.send_response(code)
        for k, v in headers: self.send_header(k, v)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def handle_any(self):
        if self.path.startswith("/__") and self._ctl() is not False: return
        n = int(self.headers.get("Content-Length") or 0); body = self.rfile.read(n) if n else None
        mode = MODE[0] if self.path.startswith("/api/") else "pass"
        rec = {"t": time.time(), "mode": mode, "m": self.command, "p": self.path[:90]}
        with LOCK: LOG.append(rec)
        if mode == "drop": rec["res"] = "closed"; self.close_connection = True; return
        if mode.startswith("delay:"): time.sleep(float(mode.split(":")[1]))
        c = http.client.HTTPConnection(*BACK, timeout=60)
        h = {k: v for k, v in self.headers.items() if k.lower() not in ("host", "connection")}
        c.request(self.command, self.path, body, h); r = c.getresponse(); data = r.read(); rec["status"] = r.status
        if mode == "drop_response": rec["res"] = "applied_but_response_dropped"; self.close_connection = True; return
        self.send_response(r.status)
        for k, v in r.getheaders():
            if k.lower() not in ("transfer-encoding", "connection", "content-length"): self.send_header(k, v)
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = handle_any
ThreadingHTTPServer(("127.0.0.1", 8022), H).serve_forever()
