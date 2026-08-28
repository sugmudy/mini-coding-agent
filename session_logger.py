from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~-]{8,}"),
    re.compile(
        r"(?i)[\"']?(?:api[_-]?key|token|secret|password)[\"']?\s*[:=]\s*[\"']?[^\"'\s,;}]+[\"']?"
    ),
]


class SessionLogger:
    """Append-only JSONL trace with bounded fields and conservative secret redaction."""

    MAX_FIELD_CHARS = 50_000

    def __init__(self, log_dir: str | Path = "logs", *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.path: Path | None = None
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_id = f"{stamp}-{uuid.uuid4().hex[:6]}"
        if enabled:
            directory = Path(log_dir).expanduser().resolve()
            directory.mkdir(parents=True, exist_ok=True)
            self.path = directory / f"session_{self.session_id}.jsonl"

    @classmethod
    def _redact_text(cls, text: str) -> str:
        value = text
        for pattern in _SECRET_PATTERNS:
            value = pattern.sub("[REDACTED]", value)
        if len(value) > cls.MAX_FIELD_CHARS:
            half = cls.MAX_FIELD_CHARS // 2
            value = value[:half] + "\n... log field truncated ...\n" + value[-half:]
        return value

    @classmethod
    def _sanitize(cls, value: Any) -> Any:
        if isinstance(value, str):
            return cls._redact_text(value)
        if isinstance(value, dict):
            sanitized = {}
            for key, item in value.items():
                key_text = str(key)
                normalized = key_text.lower().replace("-", "_")
                if any(marker in normalized for marker in ("api_key", "apikey", "token", "secret", "password")):
                    sanitized[key_text] = "[REDACTED]"
                else:
                    sanitized[key_text] = cls._sanitize(item)
            return sanitized
        if isinstance(value, list):
            return [cls._sanitize(v) for v in value]
        if isinstance(value, tuple):
            return [cls._sanitize(v) for v in value]
        return value

    def log(self, event: str, **data: Any) -> None:
        if not self.enabled or self.path is None:
            return
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "event": event,
            **self._sanitize(data),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
