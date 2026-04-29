from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SERVICE_NAME = "flood-risk-api"
SERVICE_VERSION = os.getenv("API_VERSION", "0.1.0-draft")


class PlaceholderHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(
                {
                    "status": "ok",
                    "service": SERVICE_NAME,
                    "version": SERVICE_VERSION,
                    "checked_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                }
            )
            return
        self._send_json({"error": {"code": "not_found", "message": "Route not found"}}, status=404)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, payload: dict[str, object], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    port = int(os.getenv("API_PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), PlaceholderHandler)
    print(json.dumps({"event": "api.placeholder_started", "port": port}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

