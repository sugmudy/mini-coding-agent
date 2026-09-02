from __future__ import annotations

import json
import sys
from pathlib import Path

repository = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repository))

from agent import Agent
from llm_client import LLMClient
from session_logger import SessionLogger
from tools.registry import ToolRegistry
from ui import NullUI


root = Path(__file__).resolve().parent / "v4-api-test"
logger = SessionLogger(repository / "logs" / "v4-api-smoke")
agent = Agent(
    llm=LLMClient(model="gpt-5.4-mini", timeout=60, max_retries=2, retry_backoff=0.5),
    tools=ToolRegistry(root),
    max_steps=8,
    verbose=False,
    session_logger=logger,
    ui=NullUI(assume_yes=True),
    workspace=root,
)
prompts = [
    "Read notes.txt and report the project codename and numeric value. Do not change files.",
    (
        "Without reading notes.txt again, repeat the codename and value you learned in the previous turn, "
        "and explicitly say you used conversation context."
    ),
    (
        "Create result.txt with exactly two lines: codename=ORCHID-47 and doubled_value=14. "
        "Then use a Python command to validate the exact file content."
    ),
    "Read result.txt and confirm whether it matches what the previous turn intended. Do not modify anything.",
]

agent.start_session()
try:
    for prompt in prompts:
        answer = agent.run_turn(prompt, render_report=False)
        print(json.dumps({"turn": len(agent.state.turns), "answer": answer}, ensure_ascii=False))
finally:
    agent.finish_session(render_report=False)

print(json.dumps({"state": agent.state.summary(), "log": str(logger.path)}, ensure_ascii=False))
