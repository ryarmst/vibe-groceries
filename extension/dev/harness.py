"""Dev harness: serve the extension pages (with shim.js) and proxy /api to the server, same origin.

    python extension/dev/harness.py --port 8765 --api http://127.0.0.1:8100
Then pair at http://localhost:8765/ui/app.html#/settings using server URL http://localhost:8765.
"""

import argparse
import http.server
import pathlib
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent


class Handler(http.server.SimpleHTTPRequestHandler):
    api = "http://127.0.0.1:8100"

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def end_headers(self):
        self.send_header("cache-control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self.proxy()
        if self.path.split("?")[0].endswith(".html"):
            body = (ROOT / self.path.split("?")[0].lstrip("/")).read_text()
            body = body.replace("<head>", '<head>\n  <script src="/dev/shim.js"></script>', 1).encode()
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def do_POST(self): self.proxy()
    def do_PUT(self): self.proxy()
    def do_DELETE(self): self.proxy()

    def proxy(self):
        length = int(self.headers.get("content-length") or 0)
        data = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() in ("authorization", "content-type")}
        req = urllib.request.Request(self.api + self.path, data=data, method=self.command, headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=300)
        except urllib.error.HTTPError as e:
            resp = e
        self.send_response(resp.status)
        for k, v in resp.headers.items():
            if k.lower() in ("content-type", "cache-control"):
                self.send_header(k, v)
        self.end_headers()
        while True:
            chunk = resp.read1(4096) if hasattr(resp, "read1") else resp.read(4096)
            if not chunk:
                break
            self.wfile.write(chunk)
            self.wfile.flush()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--api", default="http://127.0.0.1:8100")
    args = p.parse_args()
    Handler.api = args.api
    http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
