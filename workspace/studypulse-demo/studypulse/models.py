from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class StudyRecord:
    id: str
    subject: str
    minutes: int
    completed: bool

    @classmethod
    def create(cls, subject: str, minutes: Any, completed: Any = False) -> "StudyRecord":
        cleaned_subject = subject.strip()
        if not cleaned_subject:
            raise ValueError("subject must not be empty")
        if not isinstance(minutes, int) or isinstance(minutes, bool) or not (1 <= minutes <= 600):
            raise ValueError("minutes must be an integer between 1 and 600")
        if not isinstance(completed, bool):
            raise ValueError("completed must be a boolean")
        return cls(id=uuid4().hex, subject=cleaned_subject, minutes=minutes, completed=completed)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StudyRecord":
        if not isinstance(data.get("id"), str) or not data["id"]:
            raise ValueError("id must be a non-empty string")
        subject = data.get("subject")
        minutes = data.get("minutes")
        completed = data.get("completed")
        if not isinstance(subject, str):
            raise ValueError("subject must be a string")
        if not isinstance(minutes, int) or isinstance(minutes, bool) or not (1 <= minutes <= 600):
            raise ValueError("minutes must be an integer between 1 and 600")
        if not isinstance(completed, bool):
            raise ValueError("completed must be a boolean")
        return cls(id=data["id"], subject=subject.strip(), minutes=minutes, completed=completed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "minutes": self.minutes,
            "completed": self.completed,
        }
