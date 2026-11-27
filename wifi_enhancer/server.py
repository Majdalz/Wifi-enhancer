"""Local web server: serves the dashboard and a small JSON API."""

from __future__ import annotations

import argparse
import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__
from .analysis import analyze
from .latency import TARGETS, ping
from .scanner import scan

STATIC_DIR = Path(__file__).parent / "static"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}


class Handler(BaseHTTPRequestHandler):
    server_version = f"WifiEnhancer/{__version__}"
    force_demo = False

    def log_message(self, fmt, *args):  # quieter logs
        if not self.path.startswith("/api/"):
            return
        super().log_message(fmt, *args)

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200):
        self._send(code, json.dumps(data).encode(), "application/json")

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        qs = parse_qs(url.query)

        if url.path in STATIC_FILES:
            name, ctype = STATIC_FILES[url.path]
            return self._send(200, (STATIC_DIR / name).read_bytes(), ctype)

        if url.path == "/api/scan":
            demo = self.force_demo or qs.get("demo", ["0"])[0] == "1"
            result = scan(force_demo=demo)
            nets = result["networks"]
            return self._json({
                "timestamp": time.time(),
                "source": result["source"],
                "demo": result["demo"],
                "error": result["error"],
                "networks": [n.to_dict() for n in sorted(nets, key=lambda n: -n.signal)],
                "analysis": analyze(nets),
            })

        if url.path == "/api/ping":
            target = qs.get("target", ["cloudflare"])[0]
            if target not in TARGETS:
                return self._json({"error": "unknown target"}, 400)
            return self._json(ping(target))

        if url.path == "/api/info":
            return self._json({"version": __version__, "targets": list(TARGETS),
                               "force_demo": self.force_demo})

        self._json({"error": "not found"}, 404)


def main(argv=None):
    p = argparse.ArgumentParser(prog="wifi-enhancer", description="Wi-Fi Enhancer web dashboard")
    p.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=8765, help="port (default 8765)")
    p.add_argument("--demo", action="store_true", help="always use simulated networks")
    p.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    args = p.parse_args(argv)

    Handler.force_demo = args.demo
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}/"
    print(f"Wi-Fi Enhancer dashboard running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
