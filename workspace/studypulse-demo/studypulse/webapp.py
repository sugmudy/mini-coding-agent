from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .storage import JsonRecordStore

ROOT_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT_DIR / "web"
DEFAULT_DATA_FILE = ROOT_DIR / "data" / "records.json"


class StudyPulseHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, store: JsonRecordStore | None = None, **kwargs):
        self.store = store or JsonRecordStore(DEFAULT_DATA_FILE)
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/records":
            self._send_json([record.to_dict() for record in self.store.list_records()])
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/records":
            self._handle_create_record()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/records/"):
            record_id = parsed.path.rsplit("/", 1)[-1]
            self._handle_toggle_record(record_id)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/records/"):
            record_id = parsed.path.rsplit("/", 1)[-1]
            self._handle_delete_record(record_id)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_create_record(self) -> None:
        try:
            payload = self._read_json()
            record = self.store.create_record(
                subject=payload.get("subject", ""),
                minutes=payload.get("minutes", 0),
                completed=payload.get("completed", False),
            )
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, explain=str(exc))
            return
        self._send_json(record.to_dict(), status=HTTPStatus.CREATED)

    def _handle_toggle_record(self, record_id: str) -> None:
        try:
            payload = self._read_json()
            record = self.store.set_completed(record_id, payload.get("completed"))
        except KeyError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, explain=str(exc))
            return
        self._send_json(record.to_dict())

    def _handle_delete_record(self, record_id: str) -> None:
        try:
            record = self.store.delete_record(record_id)
        except KeyError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._send_json(record.to_dict())

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send_json(self, payload, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def create_server(host: str, port: int, store_path: str | Path = DEFAULT_DATA_FILE) -> ThreadingHTTPServer:
    store = JsonRecordStore(store_path)

    def handler(*args, **kwargs):
        StudyPulseHandler(*args, store=store, **kwargs)

    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run StudyPulse web app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    server = create_server(args.host, args.port)
    print(f"StudyPulse running at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
