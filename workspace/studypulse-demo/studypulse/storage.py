from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import Lock
from typing import Iterable

from .models import StudyRecord


class JsonRecordStore:
    def __init__(self, path: str | Path = Path("data/records.json")) -> None:
        self.path = Path(path)
        self._lock = Lock()

    def list_records(self) -> list[StudyRecord]:
        with self._lock:
            return list(self._load())

    def create_record(self, subject: str, minutes: int, completed: bool = False) -> StudyRecord:
        with self._lock:
            records = self._load()
            record = StudyRecord.create(subject=subject, minutes=minutes, completed=completed)
            records.append(record)
            self._save(records)
            return record

    def set_completed(self, record_id: str, completed: bool) -> StudyRecord:
        if not isinstance(completed, bool):
            raise ValueError("completed must be a boolean")
        with self._lock:
            records = self._load()
            updated: list[StudyRecord] = []
            found: StudyRecord | None = None
            for record in records:
                if record.id == record_id:
                    found = record if record.completed == completed else StudyRecord(
                        id=record.id,
                        subject=record.subject,
                        minutes=record.minutes,
                        completed=completed,
                    )
                    updated.append(found)
                else:
                    updated.append(record)
            if found is None:
                raise KeyError(record_id)
            self._save(updated)
            return found

    def delete_record(self, record_id: str) -> StudyRecord:
        with self._lock:
            records = self._load()
            remaining: list[StudyRecord] = []
            deleted: StudyRecord | None = None
            for record in records:
                if record.id == record_id:
                    deleted = record
                else:
                    remaining.append(record)
            if deleted is None:
                raise KeyError(record_id)
            self._save(remaining)
            return deleted

    def _load(self) -> list[StudyRecord]:
        if not self.path.exists():
            return []
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            return []
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("records file must contain a list")
        return [StudyRecord.from_dict(item) for item in data]

    def _save(self, records: Iterable[StudyRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [record.to_dict() for record in records]
        data = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as handle:
            handle.write(data)
            temp_path = Path(handle.name)
        os.replace(temp_path, self.path)
