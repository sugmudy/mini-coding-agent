from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


class MultiAgentProtocolError(ValueError):
    """Raised when a role does not satisfy the coordinator's structured protocol."""


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse exactly one JSON object from plain or single-fenced output."""
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            stripped = "\n".join(lines[1:-1]).strip()

    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise MultiAgentProtocolError(
            "Role output must be exactly one JSON object without leading or trailing prose."
        ) from exc
    if not isinstance(value, dict):
        raise MultiAgentProtocolError("Role output JSON must be an object.")
    return value


def _reject_unknown_fields(value: dict[str, Any], allowed: set[str], *, location: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise MultiAgentProtocolError(
            f"Unknown field(s) in {location}: {', '.join(sorted(unknown))}."
        )


def _string_list(value: Any, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise MultiAgentProtocolError(f"'{field_name}' must be a list of strings.")
    return tuple(item.strip() for item in value if item.strip())


@dataclass(frozen=True)
class PlanStep:
    id: str
    description: str
    files: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: Any) -> "PlanStep":
        if not isinstance(value, dict):
            raise MultiAgentProtocolError("Every plan step must be an object.")
        _reject_unknown_fields(
            value,
            {"id", "description", "files", "depends_on"},
            location="plan step",
        )
        step_id = value.get("id")
        description = value.get("description")
        if not isinstance(step_id, str) or not step_id.strip():
            raise MultiAgentProtocolError("Every plan step needs a non-empty string 'id'.")
        if not isinstance(description, str) or not description.strip():
            raise MultiAgentProtocolError(f"Plan step '{step_id}' needs a non-empty description.")
        return cls(
            id=step_id.strip(),
            description=description.strip(),
            files=_string_list(value.get("files"), field_name=f"steps[{step_id}].files"),
            depends_on=_string_list(value.get("depends_on"), field_name=f"steps[{step_id}].depends_on"),
        )


@dataclass(frozen=True)
class TaskPlan:
    objective: str
    steps: tuple[PlanStep, ...]
    acceptance_commands: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()

    @classmethod
    def from_text(cls, text: str) -> "TaskPlan":
        value = extract_json_object(text)
        _reject_unknown_fields(
            value,
            {"objective", "steps", "acceptance_commands", "risks"},
            location="plan",
        )
        objective = value.get("objective")
        raw_steps = value.get("steps")
        if not isinstance(objective, str) or not objective.strip():
            raise MultiAgentProtocolError("Plan requires a non-empty string 'objective'.")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise MultiAgentProtocolError("Plan requires a non-empty 'steps' list.")
        if len(raw_steps) > 20:
            raise MultiAgentProtocolError("Plan cannot contain more than 20 steps.")
        plan = cls(
            objective=objective.strip(),
            steps=tuple(PlanStep.from_dict(step) for step in raw_steps),
            acceptance_commands=_string_list(
                value.get("acceptance_commands"), field_name="acceptance_commands"
            ),
            risks=_string_list(value.get("risks"), field_name="risks"),
        )
        if not plan.acceptance_commands:
            raise MultiAgentProtocolError(
                "Plan requires at least one direct acceptance command so completion can be verified locally."
            )
        plan._validate_graph()
        return plan

    def _validate_graph(self) -> None:
        identifiers = [step.id for step in self.steps]
        if len(identifiers) != len(set(identifiers)):
            raise MultiAgentProtocolError("Plan step IDs must be unique.")
        known = set(identifiers)
        for step in self.steps:
            unknown = set(step.depends_on) - known
            if unknown:
                raise MultiAgentProtocolError(
                    f"Plan step '{step.id}' has unknown dependencies: {', '.join(sorted(unknown))}."
                )
            if step.id in step.depends_on:
                raise MultiAgentProtocolError(f"Plan step '{step.id}' cannot depend on itself.")

        dependencies = {step.id: set(step.depends_on) for step in self.steps}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise MultiAgentProtocolError("Plan dependency graph contains a cycle.")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in dependencies[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for identifier in identifiers:
            visit(identifier)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewVerdict:
    approved: bool
    summary: str
    issues: tuple[str, ...] = ()
    required_actions: tuple[str, ...] = ()

    @classmethod
    def from_text(cls, text: str) -> "ReviewVerdict":
        value = extract_json_object(text)
        _reject_unknown_fields(
            value,
            {"approved", "summary", "issues", "required_actions"},
            location="review",
        )
        approved = value.get("approved")
        summary = value.get("summary")
        if not isinstance(approved, bool):
            raise MultiAgentProtocolError("Review requires a boolean 'approved'.")
        if not isinstance(summary, str) or not summary.strip():
            raise MultiAgentProtocolError("Review requires a non-empty string 'summary'.")
        verdict = cls(
            approved=approved,
            summary=summary.strip(),
            issues=_string_list(value.get("issues"), field_name="issues"),
            required_actions=_string_list(value.get("required_actions"), field_name="required_actions"),
        )
        if approved and (verdict.issues or verdict.required_actions):
            raise MultiAgentProtocolError(
                "An approved review cannot contain unresolved issues or required actions."
            )
        if not approved and not (verdict.issues or verdict.required_actions):
            raise MultiAgentProtocolError(
                "A rejected review must contain at least one issue or required action."
            )
        return verdict

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Blackboard:
    request: str
    plan: TaskPlan | None = None
    implementation_summaries: list[str] = field(default_factory=list)
    reviews: list[ReviewVerdict] = field(default_factory=list)

    MAX_ARTIFACT_CHARS = 20_000

    @classmethod
    def _bounded(cls, text: str) -> str:
        if len(text) <= cls.MAX_ARTIFACT_CHARS:
            return text
        half = cls.MAX_ARTIFACT_CHARS // 2
        return text[:half] + "\n... blackboard artifact truncated ...\n" + text[-half:]

    def add_implementation(self, summary: str) -> None:
        self.implementation_summaries.append(self._bounded(summary))

    def snapshot(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "plan": self.plan.to_dict() if self.plan else None,
            "implementation_summaries": list(self.implementation_summaries),
            "reviews": [review.to_dict() for review in self.reviews],
        }
