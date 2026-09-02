from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

from multi_agent.models import Blackboard, ReviewVerdict, TaskPlan
from session_logger import SessionLogger
from ui import BaseUI, NullUI


class RoleAgent(Protocol):
    state: Any

    def start_session(self) -> None: ...

    def run_turn(self, user_input: str, *, render_report: bool = True) -> str: ...

    def finish_session(self, *, render_report: bool = True, final_text: str | None = None) -> None: ...


@dataclass(frozen=True)
class MultiAgentResult:
    success: bool
    final_text: str
    plan: TaskPlan
    reviews: tuple[ReviewVerdict, ...]
    rounds: int
    state: dict[str, Any]


class MultiAgentBudgetExceeded(RuntimeError):
    """Raised when global LLM-call or token budget is exhausted."""


class MultiAgentCoordinator:
    """Deterministic Planner -> Implementer -> Reviewer orchestration."""

    def __init__(
        self,
        *,
        planner: RoleAgent,
        implementer: RoleAgent,
        reviewer: RoleAgent,
        max_review_rounds: int = 2,
        max_total_llm_calls: int = 60,
        max_total_tokens: int | None = None,
        logger: SessionLogger | None = None,
        ui: BaseUI | None = None,
    ) -> None:
        if max_review_rounds <= 0:
            raise ValueError("max_review_rounds must be positive.")
        if max_total_llm_calls <= 0:
            raise ValueError("max_total_llm_calls must be positive.")
        if max_total_tokens is not None and max_total_tokens <= 0:
            raise ValueError("max_total_tokens must be positive when provided.")
        self.planner = planner
        self.implementer = implementer
        self.reviewer = reviewer
        self.max_review_rounds = max_review_rounds
        self.max_total_llm_calls = max_total_llm_calls
        self.max_total_tokens = max_total_tokens
        self.logger = logger or SessionLogger(enabled=False)
        self.ui = ui or NullUI()
        self._agents = (planner, implementer, reviewer)
        self._started_at: float | None = None

    @staticmethod
    def _agent_summary(agent: RoleAgent) -> dict[str, Any]:
        state = getattr(agent, "state", None)
        if state is None or not hasattr(state, "summary"):
            return {}
        summary = state.summary()
        return summary if isinstance(summary, dict) else {}

    def _aggregate_state(self) -> dict[str, Any]:
        role_names = ("planner", "implementer", "reviewer")
        roles = {
            role: self._agent_summary(agent)
            for role, agent in zip(role_names, self._agents)
        }
        numeric_fields = (
            "llm_calls",
            "api_retries",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "tool_calls",
            "context_compactions",
            "safety_blocks",
            "safety_approvals",
        )
        aggregate: dict[str, Any] = {field: 0 for field in numeric_fields}
        changed_files: set[str] = set()
        commands: list[str] = []
        for summary in roles.values():
            for field in numeric_fields:
                aggregate[field] += int(summary.get(field, 0) or 0)
            changed_files.update(summary.get("changed_files", []) or [])
            commands.extend(summary.get("commands_run", []) or [])
        aggregate.update(
            {
                "changed_files": sorted(changed_files),
                "commands_run": commands[-40:],
                "last_validation": commands[-1] if commands else None,
                "roles": roles,
                "duration_ms": round(
                    (time.perf_counter() - self._started_at) * 1000,
                    2,
                ) if self._started_at is not None else 0.0,
            }
        )
        return aggregate

    def _run_agent_turn(self, agent: RoleAgent, prompt: str, *, stage: str) -> str:
        """Run one role turn without allowing the global call budget to overshoot."""
        current_calls = int(self._aggregate_state().get("llm_calls", 0) or 0)
        remaining = self.max_total_llm_calls - current_calls
        if remaining <= 0:
            raise MultiAgentBudgetExceeded(
                f"Global LLM-call budget exhausted before {stage}: {current_calls} call(s)."
            )

        original_max_steps = getattr(agent, "max_steps", None)
        if isinstance(original_max_steps, int):
            agent.max_steps = min(original_max_steps, remaining)
        try:
            return agent.run_turn(prompt, render_report=False)
        finally:
            if isinstance(original_max_steps, int):
                agent.max_steps = original_max_steps

    def _check_budget(self, stage: str) -> None:
        state = self._aggregate_state()
        if state["llm_calls"] > self.max_total_llm_calls:
            raise MultiAgentBudgetExceeded(
                f"Global LLM-call budget exceeded after {stage}: "
                f"{state['llm_calls']} > {self.max_total_llm_calls}."
            )
        if self.max_total_tokens is not None and state["total_tokens"] > self.max_total_tokens:
            raise MultiAgentBudgetExceeded(
                f"Global token budget exceeded after {stage}: "
                f"{state['total_tokens']} > {self.max_total_tokens}."
            )

    @staticmethod
    def _planner_request(request: str) -> str:
        return (
            "Inspect the repository and create the structured implementation plan for this request:\n\n"
            + request
        )

    @staticmethod
    def _implementation_request(request: str, plan: TaskPlan) -> str:
        return (
            "Original user request:\n"
            + request
            + "\n\nCoordinator-approved plan:\n"
            + json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)
            + "\n\nImplement the plan in the actual workspace and validate the result."
        )

    @staticmethod
    def _review_request(blackboard: Blackboard, round_number: int) -> str:
        return (
            f"Review round {round_number}. Inspect the actual workspace before deciding.\n\n"
            "Shared blackboard snapshot:\n"
            + json.dumps(blackboard.snapshot(), ensure_ascii=False, indent=2)
        )

    @staticmethod
    def _revision_request(verdict: ReviewVerdict) -> str:
        return (
            "The independent Reviewer rejected the implementation. Address every item, re-inspect current files, "
            "and re-run validation. Reviewer verdict:\n"
            + json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2)
        )

    def run(self, request: str) -> MultiAgentResult:
        text = request.strip()
        if not text:
            raise ValueError("Multi-agent request cannot be empty.")

        blackboard = Blackboard(request=text)
        started: list[RoleAgent] = []
        self._started_at = time.perf_counter()
        self.logger.log(
            "multi_agent_start",
            request=text,
            max_review_rounds=self.max_review_rounds,
            max_total_llm_calls=self.max_total_llm_calls,
            max_total_tokens=self.max_total_tokens,
        )
        try:
            for agent in self._agents:
                agent.start_session()
                started.append(agent)

            self.ui.info("[Planner] inspecting workspace and producing a dependency-aware plan...")
            raw_plan = self._run_agent_turn(
                self.planner,
                self._planner_request(text),
                stage="planning",
            )
            plan = TaskPlan.from_text(raw_plan)
            blackboard.plan = plan
            self.logger.log("multi_agent_plan", plan=plan.to_dict())
            self._check_budget("planning")

            self.ui.info("[Implementer] applying the plan and validating changes...")
            implementation = self._run_agent_turn(
                self.implementer,
                self._implementation_request(text, plan),
                stage="initial implementation",
            )
            blackboard.add_implementation(implementation)
            self.logger.log("multi_agent_implementation", round=1, summary=implementation)
            self._check_budget("initial implementation")

            verdict: ReviewVerdict | None = None
            for round_number in range(1, self.max_review_rounds + 1):
                self.ui.info(f"[Reviewer] independent review round {round_number}/{self.max_review_rounds}...")
                raw_review = self._run_agent_turn(
                    self.reviewer,
                    self._review_request(blackboard, round_number),
                    stage=f"review round {round_number}",
                )
                verdict = ReviewVerdict.from_text(raw_review)
                commands_run = set(self._aggregate_state().get("commands_run") or [])
                missing_acceptance = [
                    command
                    for command in plan.acceptance_commands
                    if command not in commands_run
                ]
                if verdict.approved and missing_acceptance:
                    verdict = ReviewVerdict(
                        approved=False,
                        summary=(
                            "The textual review approved the change, but runtime state has no successful record "
                            "for every plan acceptance command."
                        ),
                        issues=tuple(
                            f"Missing successful acceptance command: {command}"
                            for command in missing_acceptance
                        ),
                        required_actions=tuple(
                            f"Run successfully: {command}"
                            for command in missing_acceptance
                        ),
                    )
                blackboard.reviews.append(verdict)
                self.logger.log(
                    "multi_agent_review",
                    round=round_number,
                    verdict=verdict.to_dict(),
                )
                self._check_budget(f"review round {round_number}")

                if verdict.approved:
                    final = (
                        "Multi-agent workflow approved.\n\n"
                        "Implementation report:\n"
                        + blackboard.implementation_summaries[-1]
                        + "\n\nIndependent review:\n"
                        + verdict.summary
                    )
                    state = self._aggregate_state()
                    self.logger.log(
                        "multi_agent_complete",
                        success=True,
                        rounds=round_number,
                        state=state,
                    )
                    return MultiAgentResult(
                        success=True,
                        final_text=final,
                        plan=plan,
                        reviews=tuple(blackboard.reviews),
                        rounds=round_number,
                        state=state,
                    )

                if round_number < self.max_review_rounds:
                    self.ui.warning(
                        f"Reviewer requested revision: {verdict.summary}"
                    )
                    self.ui.info("[Implementer] addressing bounded review feedback...")
                    implementation = self._run_agent_turn(
                        self.implementer,
                        self._revision_request(verdict),
                        stage=f"revision round {round_number}",
                    )
                    blackboard.add_implementation(implementation)
                    self.logger.log(
                        "multi_agent_implementation",
                        round=round_number + 1,
                        summary=implementation,
                    )
                    self._check_budget(f"revision round {round_number}")

            assert verdict is not None
            final = (
                "Multi-agent workflow stopped without approval after the configured review limit.\n\n"
                "Latest implementation report:\n"
                + blackboard.implementation_summaries[-1]
                + "\n\nUnresolved review:\n"
                + verdict.summary
                + "\nRequired actions:\n- "
                + "\n- ".join(verdict.required_actions or verdict.issues)
            )
            state = self._aggregate_state()
            self.logger.log(
                "multi_agent_complete",
                success=False,
                rounds=self.max_review_rounds,
                state=state,
            )
            return MultiAgentResult(
                success=False,
                final_text=final,
                plan=plan,
                reviews=tuple(blackboard.reviews),
                rounds=self.max_review_rounds,
                state=state,
            )
        except Exception as exc:
            self.logger.log(
                "multi_agent_error",
                error_type=type(exc).__name__,
                error=str(exc),
                state=self._aggregate_state(),
            )
            raise
        finally:
            for agent in reversed(started):
                try:
                    agent.finish_session(render_report=False)
                except Exception as exc:
                    self.logger.log(
                        "multi_agent_cleanup_error",
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
