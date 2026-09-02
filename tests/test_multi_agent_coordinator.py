from __future__ import annotations

import json

import pytest

from multi_agent.coordinator import MultiAgentBudgetExceeded, MultiAgentCoordinator
from session_logger import SessionLogger


PLAN = json.dumps(
    {
        "objective": "Make the requested change",
        "steps": [
            {"id": "S1", "description": "Implement and test", "files": ["a.py"], "depends_on": []}
        ],
        "acceptance_commands": ["python -m pytest -q"],
        "risks": ["regression"],
    }
)
APPROVED = json.dumps(
    {"approved": True, "summary": "Tests and implementation verified.", "issues": [], "required_actions": []}
)
REJECTED = json.dumps(
    {
        "approved": False,
        "summary": "A regression remains.",
        "issues": ["edge case fails"],
        "required_actions": ["fix the edge case and rerun tests"],
    }
)


class FakeState:
    def __init__(self, *, validation=False, tokens_per_call=10):
        self.validation_command = (
            "python -m pytest -q" if validation is True else validation if isinstance(validation, str) else None
        )
        self.tokens_per_call = tokens_per_call
        self.calls = 0

    def summary(self):
        return {
            "llm_calls": self.calls,
            "api_retries": 0,
            "prompt_tokens": self.calls * (self.tokens_per_call - 2),
            "completion_tokens": self.calls * 2,
            "total_tokens": self.calls * self.tokens_per_call,
            "tool_calls": 1 if self.validation_command and self.calls else 0,
            "changed_files": ["a.py"] if self.validation_command and self.calls else [],
            "commands_run": [self.validation_command] if self.validation_command and self.calls else [],
        }


class FakeRoleAgent:
    def __init__(self, outcomes, *, validation=False, tokens_per_call=10):
        self.outcomes = list(outcomes)
        self.prompts = []
        self.state = FakeState(validation=validation, tokens_per_call=tokens_per_call)
        self.max_steps = 30
        self.started = 0
        self.finished = 0

    def start_session(self):
        self.started += 1

    def run_turn(self, prompt, *, render_report=True):
        self.prompts.append(prompt)
        self.state.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def finish_session(self, *, render_report=True, final_text=None):
        self.finished += 1


def coordinator(planner, implementer, reviewer, **kwargs):
    return MultiAgentCoordinator(
        planner=planner,
        implementer=implementer,
        reviewer=reviewer,
        logger=SessionLogger(enabled=False),
        **kwargs,
    )


def test_first_review_approval_finishes_without_rework():
    planner = FakeRoleAgent([PLAN])
    implementer = FakeRoleAgent(["implemented"], validation=True)
    reviewer = FakeRoleAgent([APPROVED])
    result = coordinator(planner, implementer, reviewer).run("change it")

    assert result.success is True
    assert result.rounds == 1
    assert len(implementer.prompts) == 1
    assert len(reviewer.prompts) == 1
    assert result.state["last_validation"] == "python -m pytest -q"
    assert all(agent.finished == 1 for agent in (planner, implementer, reviewer))


def test_review_feedback_is_passed_to_bounded_revision_round():
    planner = FakeRoleAgent([PLAN])
    implementer = FakeRoleAgent(["initial", "revised"], validation=True)
    reviewer = FakeRoleAgent([REJECTED, APPROVED])
    result = coordinator(
        planner,
        implementer,
        reviewer,
        max_review_rounds=2,
    ).run("change it")

    assert result.success is True
    assert result.rounds == 2
    assert len(implementer.prompts) == 2
    assert "edge case fails" in implementer.prompts[1]
    assert len(reviewer.prompts) == 2


def test_review_loop_never_exceeds_configured_rounds():
    planner = FakeRoleAgent([PLAN])
    implementer = FakeRoleAgent(["initial", "revised"], validation=True)
    reviewer = FakeRoleAgent([REJECTED, REJECTED])
    result = coordinator(
        planner,
        implementer,
        reviewer,
        max_review_rounds=2,
    ).run("change it")

    assert result.success is False
    assert result.rounds == 2
    assert len(reviewer.prompts) == 2
    assert len(implementer.prompts) == 2
    assert "configured review limit" in result.final_text


def test_textual_approval_without_runtime_validation_is_not_success():
    planner = FakeRoleAgent([PLAN])
    implementer = FakeRoleAgent(["claimed success"], validation=False)
    reviewer = FakeRoleAgent([APPROVED])
    result = coordinator(
        planner,
        implementer,
        reviewer,
        max_review_rounds=1,
    ).run("change it")

    assert result.success is False
    assert result.reviews[0].approved is False
    assert "no successful record" in result.reviews[0].summary


def test_unrelated_successful_command_does_not_satisfy_plan_acceptance():
    planner = FakeRoleAgent([PLAN])
    implementer = FakeRoleAgent(["claimed success"], validation="git status")
    reviewer = FakeRoleAgent([APPROVED])
    result = coordinator(
        planner,
        implementer,
        reviewer,
        max_review_rounds=1,
    ).run("change it")

    assert result.success is False
    assert any("python -m pytest -q" in action for action in result.reviews[0].required_actions)


def test_global_call_budget_stops_before_scheduling_next_role():
    planner = FakeRoleAgent([PLAN])
    implementer = FakeRoleAgent(["implemented"], validation=True)
    reviewer = FakeRoleAgent([APPROVED])

    with pytest.raises(MultiAgentBudgetExceeded, match="before review"):
        coordinator(
            planner,
            implementer,
            reviewer,
            max_total_llm_calls=2,
        ).run("change it")

    assert len(planner.prompts) == 1
    assert len(implementer.prompts) == 1
    assert len(reviewer.prompts) == 0


def test_token_budget_accumulates_across_roles_and_stops_after_completed_call():
    planner = FakeRoleAgent([PLAN], tokens_per_call=10)
    implementer = FakeRoleAgent(["implemented"], validation=True, tokens_per_call=10)
    reviewer = FakeRoleAgent([APPROVED], tokens_per_call=10)

    with pytest.raises(MultiAgentBudgetExceeded, match="initial implementation"):
        coordinator(
            planner,
            implementer,
            reviewer,
            max_total_tokens=15,
        ).run("change it")

    assert len(reviewer.prompts) == 0


def test_role_protocol_error_still_finishes_every_started_agent():
    planner = FakeRoleAgent(["not-json"])
    implementer = FakeRoleAgent(["unused"], validation=True)
    reviewer = FakeRoleAgent([APPROVED])

    with pytest.raises(ValueError):
        coordinator(planner, implementer, reviewer).run("change it")

    assert all(agent.finished == 1 for agent in (planner, implementer, reviewer))
