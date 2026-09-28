"""Loopback-only, read-only HTTP server for Tessera Studio."""
from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .store import NotFound, Store

STATIC = Path(__file__).parent / "static"
STATIC_FILES = {"/": "index.html", "/app.css": "app.css", "/app.js": "app.js", "/favicon.svg": "favicon.svg"}
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def make_handler(store: Store, allowed_hosts: set[str]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TesseraStudio"
        sys_version = ""

        def log_message(self, fmt, *args):  # keep the terminal quiet; errors still surface
            pass

        def _send(self, status: int, body: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in SECURITY_HEADERS.items():
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, payload):
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            # Reject foreign Host headers so a DNS-rebinding page cannot read the API.
            if self.headers.get("Host", "").lower() not in allowed_hosts:
                return self._json(HTTPStatus.MISDIRECTED_REQUEST, {"error": "host not allowed"})
            path = urlsplit(self.path).path
            try:
                if path in STATIC_FILES:
                    return self._static(STATIC_FILES[path])
                parts = [unquote(p) for p in path.strip("/").split("/")]
                if parts == ["api", "projects"]:
                    return self._json(HTTPStatus.OK, {"roots": [str(r) for r in store.roots], "projects": store.projects()})
                if len(parts) == 3 and parts[:2] == ["api", "projects"]:
                    return self._json(HTTPStatus.OK, store.project(parts[2]))
                if len(parts) == 5 and parts[:2] == ["api", "projects"] and parts[3] == "decisions":
                    return self._json(HTTPStatus.OK, store.decision(parts[2], parts[4]))
            except NotFound:
                return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def _refuse(self):
            self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "read-only"})

        do_POST = do_PUT = do_PATCH = do_DELETE = _refuse

        def _static(self, name: str):
            content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type.endswith(("javascript", "svg+xml")):
                content_type += "; charset=utf-8"
            self._send(HTTPStatus.OK, (STATIC / name).read_bytes(), content_type)

    return Handler


def create_server(store: Store, port: int = 8765) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store, set()))
    actual = server.server_address[1]
    server.RequestHandlerClass = make_handler(store, {f"127.0.0.1:{actual}", f"localhost:{actual}"})
    return server
