from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    model: str | None
    workspace: Path
    max_steps: int
    command_timeout: int
    llm_timeout: float
    llm_max_retries: int
    retry_backoff: float
    max_history_chars: int
    max_tool_result_chars: int
    loop_repeat_limit: int
    log_dir: Path
    safety_mode: str
    input_price_per_million: float | None
    output_price_per_million: float | None

    @classmethod
    def from_env(
        cls,
        *,
        workspace: str | Path | None = None,
        model: str | None = None,
        max_steps: int | None = None,
        log_dir: str | Path | None = None,
        safety_mode: str | None = None,
    ) -> "Settings":
        selected_model = model or os.getenv("AGENT_MODEL") or None
        selected_workspace = Path(workspace or os.getenv("AGENT_WORKSPACE", "workspace"))
        selected_log_dir = Path(log_dir or os.getenv("AGENT_LOG_DIR", "logs"))

        values = cls(
            model=selected_model,
            workspace=selected_workspace,
            max_steps=max_steps or int(os.getenv("AGENT_MAX_STEPS", "30")),
            command_timeout=int(os.getenv("AGENT_COMMAND_TIMEOUT", "30")),
            llm_timeout=float(os.getenv("AGENT_LLM_TIMEOUT", "60")),
            llm_max_retries=int(os.getenv("AGENT_LLM_MAX_RETRIES", "3")),
            retry_backoff=float(os.getenv("AGENT_RETRY_BACKOFF", "1.0")),
            max_history_chars=int(os.getenv("AGENT_MAX_HISTORY_CHARS", "160000")),
            max_tool_result_chars=int(os.getenv("AGENT_MAX_TOOL_RESULT_CHARS", "30000")),
            loop_repeat_limit=int(os.getenv("AGENT_LOOP_REPEAT_LIMIT", "3")),
            log_dir=selected_log_dir,
            safety_mode=(safety_mode or os.getenv("AGENT_SAFETY_MODE", "balanced")).strip().lower(),
            input_price_per_million=(
                float(os.getenv("AGENT_INPUT_PRICE_PER_MILLION"))
                if os.getenv("AGENT_INPUT_PRICE_PER_MILLION")
                else None
            ),
            output_price_per_million=(
                float(os.getenv("AGENT_OUTPUT_PRICE_PER_MILLION"))
                if os.getenv("AGENT_OUTPUT_PRICE_PER_MILLION")
                else None
            ),
        )
        if values.max_steps <= 0:
            raise ValueError("AGENT_MAX_STEPS must be positive.")
        if values.command_timeout <= 0 or values.llm_timeout <= 0:
            raise ValueError("Timeouts must be positive.")
        if values.llm_max_retries < 0:
            raise ValueError("AGENT_LLM_MAX_RETRIES must be >= 0.")
        if values.retry_backoff < 0:
            raise ValueError("AGENT_RETRY_BACKOFF must be >= 0.")
        if values.safety_mode not in {"strict", "balanced", "permissive"}:
            raise ValueError("AGENT_SAFETY_MODE must be strict, balanced, or permissive.")
        for price in (values.input_price_per_million, values.output_price_per_million):
            if price is not None and price < 0:
                raise ValueError("Token prices must be non-negative.")
        return values
