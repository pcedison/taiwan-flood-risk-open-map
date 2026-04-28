from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class PlaceholderHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json({"status": "ok", "service": "api", "runtime": "placeholder"})
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

