"""Vercel serverless function — daily ops summary, triggered by Vercel Cron.

Served at https://<deployment>/api/cron

Vercel Cron sends `Authorization: Bearer <CRON_SECRET>` when the CRON_SECRET
env var is set; the handler refuses every caller without it. Hobby plan runs
at most once per day (configured in vercel.json).
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


class handler(BaseHTTPRequestHandler):
    server_version = "marco-p2p-cron/1.0"

    def _respond(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        authorization = self.headers.get("Authorization")
        try:
            result = asyncio.run(serverless.daily_summary(authorization))
        except Exception as exc:  # surface config problems plainly
            sys.stderr.write(f"cron error: {exc!r}\n")
            self._respond(500, {"ok": False, "error": str(exc)})
            return
        if not result.get("ok"):
            self._respond(401, result)
            return
        self._respond(200, result)

    def log_message(self, format: str, *args) -> None:  # keep function logs clean
        sys.stderr.write("cron: " + (format % args) + "\n")
