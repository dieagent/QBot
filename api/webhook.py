"""Vercel serverless function — Telegram webhook endpoint.

Served at https://<deployment>/api/webhook

- GET  -> initializes the runtime (registers the webhook) and reports status
- POST -> validates the Telegram secret header and processes the update
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# Vercel runs functions from their own directory; make the project root
# importable so `marco_bot` resolves.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from marco_bot import serverless  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class handler(BaseHTTPRequestHandler):
    server_version = "marco-p2p-webhook/1.0"

    def _respond(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        try:
            result = _run(serverless.status())
        except Exception as exc:  # surface config problems plainly
            _log_error(exc)
            self._respond(500, {"ok": False, "error": str(exc)})
            return
        self._respond(200, result)

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            update_data = json.loads(raw.decode() or "{}")
        except (ValueError, json.JSONDecodeError):
            self._respond(400, {"ok": False, "error": "invalid JSON body"})
            return

        secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token")
        try:
            ok = _run(serverless.handle_update(update_data, secret))
        except Exception as exc:
            _log_error(exc)
            # 500 makes Telegram retry the delivery (correct while cold-start
            # races settle); config errors will keep failing visibly in logs.
            self._respond(500, {"ok": False, "error": str(exc)})
            return
        if not ok:
            self._respond(401, {"ok": False, "error": "bad secret token"})
            return
        self._respond(200, {"ok": True})

    def log_message(self, format: str, *args) -> None:  # keep function logs clean
        sys.stderr.write("webhook: " + (format % args) + "\n")


def _log_error(exc: Exception) -> None:
    sys.stderr.write(f"webhook error: {exc!r}\n")
