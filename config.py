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

    @classmethod
    def from_env(
        cls,
        *,
        workspace: str | Path | None = None,
        model: str | None = None,
        max_steps: int | None = None,
    ) -> "Settings":
        selected_model = model or os.getenv("AGENT_MODEL") or None
        selected_workspace = Path(workspace or os.getenv("AGENT_WORKSPACE", "workspace"))

        return cls(
            model=selected_model,
            workspace=selected_workspace,
            max_steps=max_steps or int(os.getenv("AGENT_MAX_STEPS", "20")),
            command_timeout=int(os.getenv("AGENT_COMMAND_TIMEOUT", "30")),
            llm_timeout=float(os.getenv("AGENT_LLM_TIMEOUT", "60")),
        )
