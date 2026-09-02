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
logger = SessionLogger(repository / "logs" / "v4-api-validation-smoke")
agent = Agent(
    llm=LLMClient(model="gpt-5.4-mini", timeout=60, max_retries=2, retry_backoff=0.5),
    tools=ToolRegistry(root),
    max_steps=4,
    verbose=False,
    session_logger=logger,
    ui=NullUI(assume_yes=True),
    workspace=root,
)
prompt = (
    "Validate result.txt with run_command. Use one cross-platform python -c command, with no pipes, "
    "redirection, command chaining, multi-line command, or heredoc. The command must assert that the exact "
    "content is 'codename=ORCHID-47\\ndoubled_value=14' and print 'validated'. Report the observed stdout."
)

answer = agent.run(prompt)
print(json.dumps({"answer": answer, "state": agent.state.summary(), "log": str(logger.path)}, ensure_ascii=False))
