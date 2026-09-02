from __future__ import annotations

import json

import pytest

from multi_agent.models import MultiAgentProtocolError, ReviewVerdict, TaskPlan


def plan_text(*, steps=None, acceptance=None, **extra):
    payload = {
        "objective": "Implement the requested behavior",
        "steps": steps
        or [
            {"id": "S1", "description": "Inspect", "files": [], "depends_on": []},
            {"id": "S2", "description": "Implement", "files": ["a.py"], "depends_on": ["S1"]},
        ],
        "acceptance_commands": acceptance or ["python -m pytest -q"],
        "risks": ["regression"],
        **extra,
    }
    return json.dumps(payload)


def test_valid_plan_builds_dependency_graph_and_accepts_one_code_fence():
    plan = TaskPlan.from_text("```json\n" + plan_text() + "\n```")
    assert [step.id for step in plan.steps] == ["S1", "S2"]
    assert plan.steps[1].depends_on == ("S1",)
    assert plan.acceptance_commands == ("python -m pytest -q",)


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        plan_text() + " trailing prose",
        '{"objective":"x"}{"objective":"y"}',
        plan_text(extra_field=True),
    ],
)
def test_plan_protocol_fails_closed_on_ambiguous_or_unknown_output(text):
    with pytest.raises(MultiAgentProtocolError):
        TaskPlan.from_text(text)


@pytest.mark.parametrize(
    "steps",
    [
        [
            {"id": "S1", "description": "one", "files": [], "depends_on": []},
            {"id": "S1", "description": "duplicate", "files": [], "depends_on": []},
        ],
        [{"id": "S1", "description": "unknown", "files": [], "depends_on": ["S9"]}],
        [{"id": "S1", "description": "self", "files": [], "depends_on": ["S1"]}],
        [
            {"id": "S1", "description": "cycle one", "files": [], "depends_on": ["S2"]},
            {"id": "S2", "description": "cycle two", "files": [], "depends_on": ["S1"]},
        ],
    ],
)
def test_plan_rejects_invalid_dependency_graph(steps):
    with pytest.raises(MultiAgentProtocolError):
        TaskPlan.from_text(plan_text(steps=steps))


def test_plan_requires_executable_acceptance_evidence():
    payload = json.loads(plan_text())
    payload["acceptance_commands"] = []
    with pytest.raises(MultiAgentProtocolError, match="acceptance command"):
        TaskPlan.from_text(json.dumps(payload))


@pytest.mark.parametrize(
    "payload",
    [
        {"approved": "yes", "summary": "bad", "issues": [], "required_actions": []},
        {"approved": True, "summary": "bad", "issues": ["still broken"], "required_actions": []},
        {"approved": False, "summary": "bad", "issues": [], "required_actions": []},
        {"approved": True, "summary": "ok", "issues": [], "required_actions": [], "extra": 1},
    ],
)
def test_review_protocol_is_strict(payload):
    with pytest.raises(MultiAgentProtocolError):
        ReviewVerdict.from_text(json.dumps(payload))


def test_review_protocol_accepts_consistent_approval_and_rejection():
    approved = ReviewVerdict.from_text(
        json.dumps({"approved": True, "summary": "verified", "issues": [], "required_actions": []})
    )
    rejected = ReviewVerdict.from_text(
        json.dumps(
            {
                "approved": False,
                "summary": "test failed",
                "issues": ["one failure"],
                "required_actions": ["fix it"],
            }
        )
    )
    assert approved.approved is True
    assert rejected.approved is False
