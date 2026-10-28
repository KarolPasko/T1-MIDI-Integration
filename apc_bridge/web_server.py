"""Tiny local web server for the HTML interface (Python standard library only).

It only listens on 127.0.0.1, checks the Host header, and every API call
must carry a random token that is generated at start-up and only given to
the page this server itself serves. A website open in another browser tab
therefore cannot switch output on or change settings.
"""

from __future__ import annotations

import json
import logging
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .app_core import ActionError, BridgeCore

log = logging.getLogger(__name__)


def web_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "apc_bridge" / "web"


def make_server(core: BridgeCore, port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """Create (not start) the server. Returns (server, url)."""
    token = secrets.token_urlsafe(24)
    page = (web_dir() / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", token)

    actions = {
        "refresh_ports": lambda b: core.refresh_ports(),
        "connect": lambda b: core.connect(str(b.get("input") or ""), str(b.get("output") or "")),
        "disconnect": lambda b: core.disconnect(),
        "output": lambda b: core.set_output(bool(b.get("on"))),
        "simulate_output": lambda b: core.set_simulate_output(bool(b.get("on"))),
        "settings": lambda b: core.apply_settings(b.get("config") or {}),
        "save": lambda b: core.save(b.get("name") or None),
        "open": lambda b: core.open_file(str(b.get("kind") or ""), str(b.get("name") or "")),
        "import": lambda b: core.import_config(b.get("config") or {}, str(b.get("name") or "")),
        "new": lambda b: core.new_file(),
        "learn": lambda b: core.set_learning(bool(b.get("on"))),
        "blackout": lambda b: core.set_blackout(bool(b.get("on"))),
        "test": lambda b: core.start_test(str(b.get("mode") or "")),
        "test_stop": lambda b: core.stop_test(),
    }

    class Handler(BaseHTTPRequestHandler):
        server_version = "APCBridge"

        def log_message(self, fmt, *args):  # keep the console/log quiet
            pass

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            return host in ("127.0.0.1", "localhost")

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

        def _authorised(self) -> bool:
            return self._host_ok() and secrets.compare_digest(self.headers.get("X-Bridge-Token", ""), token)

        def do_GET(self):
            url = urlparse(self.path)
            if not self._host_ok():
                return self._json(403, {"ok": False, "error": "forbidden"})
            if url.path in ("/", "/index.html"):
                return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if url.path == "/api/state":
                if not self._authorised():
                    return self._json(403, {"ok": False, "error": "forbidden"})
                since = int(parse_qs(url.query).get("since", ["0"])[0] or 0)
                return self._json(200, {"ok": True, "state": core.state(since)})
            return self._send(404, b"Not found", "text/plain")

        def do_POST(self):
            url = urlparse(self.path)
            if not self._authorised():
                return self._json(403, {"ok": False, "error": "forbidden"})
            name = url.path.removeprefix("/api/")
            if name not in actions:
                return self._json(404, {"ok": False, "error": f"unknown action {name}"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                if not isinstance(body, dict):
                    raise ValueError("body must be an object")
                actions[name](body)
            except ActionError as exc:
                return self._json(400, {"ok": False, "error": str(exc)})
            except (ValueError, json.JSONDecodeError) as exc:
                return self._json(400, {"ok": False, "error": f"bad request: {exc}"})
            except Exception as exc:
                log.exception("Action %s failed", name)
                return self._json(500, {"ok": False, "error": str(exc)})
            return self._json(200, {"ok": True})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def serve_in_background(server: ThreadingHTTPServer) -> threading.Thread:
    t = threading.Thread(target=server.serve_forever, name="web-server", daemon=True)
    t.start()
    return t
