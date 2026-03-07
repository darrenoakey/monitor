"""Simple HTTP server with content-hash cache-busting for static assets."""

import hashlib
import json
import re
import sys
import uuid
from http.cookies import SimpleCookie
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

UI_DIR = Path(__file__).parent
STATIC_DIR = UI_DIR / "static"
PREFS_DIR = UI_DIR / "data"
TOKEN_FILE = Path.home() / "src" / "pubsub" / "data" / "token"
COOKIE_MAX_AGE = 10 * 365 * 24 * 3600  # 10 years

CONTENT_TYPES = {
    ".css": "text/css",
    ".js": "application/javascript",
    ".html": "text/html",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".json": "application/json",
}

_static_hashes: dict[str, str] = {}


def _build_static_hashes() -> None:
    if _static_hashes:
        return
    if not STATIC_DIR.is_dir():
        return
    for f in STATIC_DIR.iterdir():
        if f.is_file():
            digest = hashlib.sha256(f.read_bytes()).hexdigest()[:12]
            _static_hashes[f.name] = digest


def resolve_static_tags(html: str) -> str:
    _build_static_hashes()

    def _replace(m: re.Match) -> str:
        name = m.group(1).strip()
        h = _static_hashes.get(name, "0")
        return f"/static/{name}?v={h}"

    return re.sub(r"\{\{\s*static:([^}]+)\}\}", _replace, html)


def _prefs_path(client_id: str) -> Path | None:
    """Return prefs file path if client_id is a valid UUID, else None."""
    try:
        uuid.UUID(client_id)
    except ValueError:
        return None
    return PREFS_DIR / f"{client_id}.json"


def _read_prefs(client_id: str) -> dict:
    p = _prefs_path(client_id)
    if p and p.is_file():
        return json.loads(p.read_text())
    return {}


def _write_prefs(client_id: str, prefs: dict) -> bool:
    p = _prefs_path(client_id)
    if not p:
        return False
    PREFS_DIR.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(prefs))
    return True


class Handler(SimpleHTTPRequestHandler):
    def _get_client_id(self) -> str:
        """Read client_id from cookie, or generate a new one."""
        cookie_header = self.headers.get("Cookie", "")
        cookie = SimpleCookie(cookie_header)
        if "client_id" in cookie:
            cid = cookie["client_id"].value
            try:
                uuid.UUID(cid)
                return cid
            except ValueError:
                pass
        return str(uuid.uuid4())

    def _set_client_cookie(self, client_id: str) -> None:
        self.send_header(
            "Set-Cookie",
            f"client_id={client_id}; Path=/; Max-Age={COOKIE_MAX_AGE}; SameSite=Lax",
        )

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]

        if path == "/" or path == "/index.html":
            client_id = self._get_client_id()
            html = (UI_DIR / "index.html").read_text()
            token = TOKEN_FILE.read_text().strip() if TOKEN_FILE.is_file() else ""
            html = html.replace("{{ token }}", token)
            body = resolve_static_tags(html).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self._set_client_cookie(client_id)
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/prefs":
            client_id = self._get_client_id()
            prefs = _read_prefs(client_id)
            self._send_json(prefs)
            return

        if path.startswith("/static/"):
            name = path[len("/static/"):]
            if "/" in name or name.startswith("."):
                self.send_error(403)
                return
            fpath = STATIC_DIR / name
            if not fpath.is_file():
                self.send_error(404)
                return
            body = fpath.read_bytes()
            ext = fpath.suffix
            ct = CONTENT_TYPES.get(ext, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_error(404)

    def do_PUT(self) -> None:
        path = self.path.split("?")[0]

        if path == "/prefs":
            client_id = self._get_client_id()
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                prefs = json.loads(body)
            except (json.JSONDecodeError, ValueError):
                self.send_error(400)
                return
            if not isinstance(prefs, dict):
                self.send_error(400)
                return
            _write_prefs(client_id, prefs)
            self._send_json({"ok": True})
            return

        self.send_error(404)

    def log_message(self, format, *args) -> None:  # noqa: A002
        pass


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    server = HTTPServer(("", port), Handler)
    print(f"Serving on http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
