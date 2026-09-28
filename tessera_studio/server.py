"""Loopback-only, read-only HTTP server for Tessera Studio."""
from __future__ import annotations

import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .store import NotFound, Store

STATIC = Path(__file__).parent / "static"
# Content types are fixed here: ``mimetypes`` reads the Windows registry, which
# can map .js to text/plain and break module scripts under nosniff.
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml; charset=utf-8"),
}
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
ALLOWED_METHODS = "GET, HEAD"


def make_handler(store: Store, allowed_hosts: set[str]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TesseraStudio"
        sys_version = ""

        def log_message(self, fmt, *args):  # keep the terminal quiet; errors still surface
            pass

        def _send(self, status: int, body: bytes, content_type: str, headers: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in {**SECURITY_HEADERS, **(headers or {})}.items():
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, payload, headers: dict | None = None):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8", headers)

        def send_error(self, code, message=None, explain=None):
            # Protocol errors raised by BaseHTTPRequestHandler (bad request line,
            # unknown method, ...) get the same JSON body and security headers.
            if code == HTTPStatus.NOT_IMPLEMENTED:
                code = HTTPStatus.METHOD_NOT_ALLOWED
            self.close_connection = True
            try:
                self._json(code, {"error": HTTPStatus(code).phrase.lower()}, {"Allow": ALLOWED_METHODS})
            except OSError:
                pass

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            # Reject foreign or missing Host headers so a DNS-rebinding page cannot read the API.
            if self.headers.get("Host", "").lower() not in allowed_hosts:
                return self._json(HTTPStatus.MISDIRECTED_REQUEST, {"error": "host not allowed"})
            path = urlsplit(self.path).path
            try:
                return self._route(path)
            except NotFound:
                return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
            except Exception as error:  # noqa: BLE001 - never leak a traceback to the client
                print(f"tessera-studio: {self.command} {path} failed: {type(error).__name__}", file=sys.stderr)
                self.close_connection = True
                try:
                    self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal error"})
                except OSError:
                    pass

        def _route(self, path: str):
            if path in STATIC_FILES:
                name, content_type = STATIC_FILES[path]
                return self._send(HTTPStatus.OK, (STATIC / name).read_bytes(), content_type)
            parts = [unquote(p) for p in path.strip("/").split("/")]
            if parts == ["api", "projects"]:
                return self._json(HTTPStatus.OK, {"roots": [str(r) for r in store.roots], "projects": store.projects()})
            if len(parts) == 3 and parts[:2] == ["api", "projects"]:
                return self._json(HTTPStatus.OK, store.project(parts[2]))
            if len(parts) == 5 and parts[:2] == ["api", "projects"] and parts[3] == "decisions":
                return self._json(HTTPStatus.OK, store.decision(parts[2], parts[4]))
            return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def _refuse(self):
            self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "read-only"}, {"Allow": ALLOWED_METHODS})

        do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_TRACE = do_CONNECT = _refuse

    return Handler


def create_server(store: Store, port: int = 8765) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store, set()))
    actual = server.server_address[1]
    server.RequestHandlerClass = make_handler(store, {f"127.0.0.1:{actual}", f"localhost:{actual}"})
    return server
