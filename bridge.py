"""
FastDM bridge - سيرفر محلي صغير بيستقبل الروابط من إضافة المتصفح.
بيشتغل على 127.0.0.1 فقط (مش ظاهر على الشبكة)، وبيقبل الطلبات من إضافات المتصفح بس،
علشان أي موقع عادي ما يقدرش يبعت تحميلات للبرنامج من وراك.
"""
import json
import queue
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 6801
ALLOWED_ORIGINS = ("chrome-extension://", "moz-extension://", "extension://")


def already_running():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/ping", timeout=1) as r:
            return json.load(r).get("app") == "FastDM"
    except Exception:  # noqa
        return False


class Bridge:
    def __init__(self):
        self.inbox = queue.Queue()      # الواجهة بتسحب منها
        self.server = None

    def start(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _origin_ok(self):
                o = self.headers.get("Origin", "")
                return o.startswith(ALLOWED_ORIGINS)

            def _send(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                o = self.headers.get("Origin", "")
                if o.startswith(ALLOWED_ORIGINS):
                    self.send_header("Access-Control-Allow-Origin", o)
                    self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self):
                self._send(204 if self._origin_ok() else 403, {})

            def do_GET(self):
                if self.path == "/ping":
                    self._send(200, {"app": "FastDM", "version": 2})
                else:
                    self._send(404, {})

            def do_POST(self):
                if self.path != "/add" or not self._origin_ok():
                    return self._send(403, {"ok": False})
                try:
                    n = min(int(self.headers.get("Content-Length", 0)), 1 << 20)
                    data = json.loads(self.rfile.read(n) or b"{}")
                    items = data.get("items") or [data]
                    good = []
                    for it in items:
                        url = str(it.get("url", ""))
                        if url.startswith(("http://", "https://")):
                            good.append({
                                "url": url,
                                "filename": str(it.get("filename") or "")[:200],
                                "kind": "page" if it.get("kind") == "page" else "direct",
                                "headers": {k: str(it.get(k) or "") for k in ("referer", "cookie", "userAgent")},
                            })
                    for g in good:
                        g["headers"] = {"Referer": g["headers"]["referer"],
                                        "Cookie": g["headers"]["cookie"],
                                        "User-Agent": g["headers"]["userAgent"]}
                        bridge.inbox.put(g)
                    self._send(200, {"ok": bool(good), "count": len(good)})
                except Exception as e:  # noqa
                    self._send(400, {"ok": False, "error": str(e)})

        try:
            self.server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
        except OSError:
            return False
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return True

    def stop(self):
        if self.server:
            self.server.shutdown()
