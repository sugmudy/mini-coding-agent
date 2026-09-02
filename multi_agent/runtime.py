from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent import Agent
from config import Settings
from context import ContextManager
from llm_client import LLMClient
from loop_detector import LoopDetector
from multi_agent.prompts import (
    IMPLEMENTER_SYSTEM_PROMPT,
    PLANNER_SYSTEM_PROMPT,
    REVIEWER_SYSTEM_PROMPT,
)
from safety import SafetyPolicy
from session_logger import SessionLogger
from tools.registry import ToolRegistry
from ui import BaseUI, NullUI


READ_ONLY_TOOLS = frozenset({"list_files", "read_file", "search_files"})
REVIEW_TOOLS = frozenset({"list_files", "read_file", "search_files", "run_command"})
IMPLEMENTER_TOOLS = frozenset(
    {"list_files", "read_file", "search_files", "write_file", "edit_file", "run_command"}
)


class RoleLogger:
    """Attach a stable role dimension to events in one shared trace."""

    def __init__(self, logger: SessionLogger, role: str) -> None:
        self._logger = logger
        self.role = role
        self.session_id = logger.session_id
        self.path = logger.path

    def log(self, event: str, **data) -> None:
        self._logger.log(event, agent_role=self.role, **data)


@dataclass
class RoleAgentFactory:
    settings: Settings
    safety_policy: SafetyPolicy
    approval_ui: BaseUI
    logger: SessionLogger

    def create(self, role: str) -> Agent:
        definitions = {
            "planner": (PLANNER_SYSTEM_PROMPT, READ_ONLY_TOOLS),
            "implementer": (IMPLEMENTER_SYSTEM_PROMPT, IMPLEMENTER_TOOLS),
            "reviewer": (REVIEWER_SYSTEM_PROMPT, REVIEW_TOOLS),
        }
        if role not in definitions:
            raise ValueError(f"Unknown multi-agent role: {role}")
        system_prompt, tools = definitions[role]
        llm = LLMClient(
            model=self.settings.model,
            timeout=self.settings.llm_timeout,
            stream=self.settings.llm_stream,
            parallel_tool_calls=self.settings.llm_parallel_tool_calls,
            reasoning_effort=self.settings.reasoning_effort,
            max_retries=self.settings.llm_max_retries,
            retry_backoff=self.settings.retry_backoff,
        )
        registry = ToolRegistry(
            self.settings.workspace,
            command_timeout=self.settings.command_timeout,
            safety_policy=self.safety_policy,
            approval_callback=self.approval_ui.confirm,
            allowed_tools=tools,
        )
        return Agent(
            llm=llm,
            tools=registry,
            max_steps=self.settings.max_steps,
            verbose=False,
            context_manager=ContextManager(
                max_history_chars=self.settings.max_history_chars,
                max_tool_result_chars=self.settings.max_tool_result_chars,
            ),
            loop_detector=LoopDetector(repeat_limit=self.settings.loop_repeat_limit),
            session_logger=RoleLogger(self.logger, role),
            ui=NullUI(),
            workspace=Path(self.settings.workspace),
            input_price_per_million=self.settings.input_price_per_million,
            output_price_per_million=self.settings.output_price_per_million,
            system_prompt=system_prompt,
        )
