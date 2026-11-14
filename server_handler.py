"""
Shared HTTP request handler for both local dev (app.py) and Vercel serverless
deployment (api/index.py). Uses HttpOnly cookies for stateless OAuth/session
storage so no database or persistent disk is needed.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import urllib.parse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, Optional

import fitbit_client
import healthspan_engine

PUBLIC_DIR = Path(__file__).parent / "public"
COOKIE_NAME = "gh_session"


def _decode_session(cookie_header: Optional[str]) -> Dict[str, Any]:
    if not cookie_header:
        return {}
    c = SimpleCookie()
    c.load(cookie_header)
    if COOKIE_NAME not in c:
        return {}
    raw_val = c[COOKIE_NAME].value
    try:
        padded = raw_val + "=" * (-len(raw_val) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return {}


def _encode_session_cookie(st: Dict[str, Any], is_https: bool) -> str:
    payload = json.dumps(st, separators=(",", ":")).encode("utf-8")
    b64 = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
    parts = [
        f"{COOKIE_NAME}={b64}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        "Max-Age=2592000",
    ]
    if is_https:
        parts.append("Secure")
    return "; ".join(parts)


class HealthspanHandler(BaseHTTPRequestHandler):
    serve_static: bool = False

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def _is_https(self) -> bool:
        proto = self.headers.get("X-Forwarded-Proto", "http")
        return proto.lower() == "https"

    def _redirect_uri(self) -> str:
        proto = "https" if self._is_https() else "http"
        host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "localhost:8765"
        return f"{proto}://{host}/callback"

    def _get_session(self) -> Dict[str, Any]:
        return _decode_session(self.headers.get("Cookie"))

    def _send_json(self, payload: Dict[str, Any], status: int = 200, new_state: Optional[Dict[str, Any]] = None) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if new_state is not None:
            self.send_header("Set-Cookie", _encode_session_cookie(new_state, self._is_https()))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, html: str, status: int = 200) -> None:
        data = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def _sample_payload(self, st: Dict[str, Any]) -> Dict[str, Any]:
        cfg = fitbit_client.get_config(st)
        chrono_age = float(cfg.get("chronological_age") or 33.0)
        lean_pct = cfg.get("manual_lean_pct")
        dash = healthspan_engine.generate_sample_dashboard(chrono_age, lean_pct)
        dash["config"] = cfg
        return dash

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        st = self._get_session()

        if path == "/api/dashboard":
            try:
                self._send_json(self._sample_payload(st))
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)
            return

        if path == "/callback":
            qs = urllib.parse.parse_qs(parsed.query)
            if "error" in qs:
                err = qs.get("error_description", qs["error"])[0]
                self._send_html(
                    f"<h2>Google Health Authorization Cancelled</h2><p>{err}</p>"
                    f"<p><a href='/'>Return to Dashboard</a></p>",
                    status=400,
                )
                return

            code = qs.get("code", [""])[0]
            state_param = qs.get("state", [""])[0]
            try:
                st = fitbit_client.exchange_code(st, code, state_param, self._redirect_uri())
                self.send_response(302)
                self.send_header("Set-Cookie", _encode_session_cookie(st, self._is_https()))
                self.send_header("Location", "/?connected=1")
                self.end_headers()
            except Exception as exc:
                self._send_html(
                    f"<h2>Google Health Connection Error</h2><p>{exc}</p>"
                    f"<p><a href='/'>Return to Dashboard</a></p>",
                    status=500,
                )
            return

        if self.serve_static:
            rel_path = "index.html" if path == "/" else path.lstrip("/")
            file_path = (PUBLIC_DIR / rel_path).resolve()
            if not str(file_path).startswith(str(PUBLIC_DIR.resolve())) or not file_path.is_file():
                self.send_error(404, "Not found")
                return
            mime_type, _ = mimetypes.guess_type(str(file_path))
            content = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime_type or "application/octet-stream")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        self.send_error(404, "Not found")

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        st = self._get_session()

        try:
            body = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON body"}, status=400)
            return

        if path == "/api/config":
            st = fitbit_client.update_config(
                st,
                client_id=body.get("client_id"),
                client_secret=body.get("client_secret"),
                chronological_age=body.get("chronological_age"),
                manual_lean_pct=body.get("manual_lean_pct"),
            )
            self._send_json(self._sample_payload(st), new_state=st)
            return

        if path == "/api/auth/start":
            client_id = (body.get("client_id") or "").strip()
            client_secret = (body.get("client_secret") or "").strip()
            try:
                auth_url, st = fitbit_client.build_auth_url(st, client_id, client_secret, self._redirect_uri())
                self._send_json({"auth_url": auth_url}, new_state=st)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)
            return

        if path == "/api/sync":
            try:
                raw, chrono_age, st = fitbit_client.sync_fitbit_data(st)
                cfg = fitbit_client.get_config(st)
                dash = healthspan_engine.compute_from_fitbit_raw(
                    raw,
                    chrono_age,
                    cfg.get("manual_lean_pct"),
                )
                dash["config"] = cfg
                self._send_json(dash, new_state=st)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)
            return

        if path == "/api/disconnect":
            st = fitbit_client.disconnect(st)
            self._send_json(self._sample_payload(st), new_state=st)
            return

        self._send_json({"error": "Unknown endpoint"}, status=404)
