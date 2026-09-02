# Multi-turn Conversation Guide

## Start a conversation

Omit the positional task to enter persistent conversation mode:

```bash
python main.py --workspace path/to/project --model MODEL_ID
```

The process creates one agent session. Every normal line is a new user turn inside that session:

```text
You> Inspect the failing tests and explain the root causes. Do not edit yet.
You> Fix only the parser issue you identified and run its focused tests.
You> Now fix the remaining failure and run the complete suite.
You> Summarize the final diff and any remaining risks.
```

The later requests can refer to earlier prompts, answers, tool results, and files changed in the same workspace. Nothing is persisted as model memory after the process exits; the source files and optional JSONL log remain on disk.

## Local commands

Conversation commands are parsed by the local CLI and are never sent to the model:

| Command | Behavior |
|---|---|
| `/help` | Show the command reference. |
| `/status` | Show cumulative turns, calls, tokens, changed files, and log path. |
| `/history` | List user requests and their completion status for this session. |
| `/exit` or `/quit` | Finish the session and show its cumulative report. |

Plain `exit` and `quit` are also accepted. An empty line does nothing. An unknown slash command is rejected locally so a typo cannot become an unintended coding request.

## Step budgets and reports

`--max-steps` applies independently to each user turn. For example, `--max-steps 15` permits up to 15 model responses in the first request and another 15 in the next request. It does not mean the whole conversation is limited to 15 total steps.

After each successful turn, the UI shows a turn report containing facts collected during that turn: changed files, most recent validation command, model/tool calls, tokens, and duration. At `/exit` or EOF, it shows a cumulative session report. These values come from local execution state rather than the model's final prose.

## Validation and loop behavior

Validation is intentionally scoped per turn. If turn 1 runs tests and turn 2 changes another file, the old test command does not satisfy turn 2's validation guard. The model receives one reminder to validate the new change or explicitly explain why no executable validation applies.

Repeated-tool detection is also turn-aware. Repeating the same unchanged read several times within one turn can be blocked, but a later user request may legitimately inspect that file again. Successful edits still advance the detector's workspace generation so a post-edit read is allowed.

## Context growth

The full conversation remains in local memory and in the optional trace. The model-facing copy is bounded by `AGENT_MAX_HISTORY_CHARS`:

1. Tool results are truncated with their beginning and end preserved.
2. Older complete user turns are omitted before recent turns.
3. If the newest turn alone is too large, its user request and newest complete assistant/tool blocks are retained.
4. A deterministic summary records omitted turn/block counts, tool counts, and paths seen.
5. Internal `_turn_id` metadata is removed before the provider request.

This controls token growth without sending an unmatched `tool` result or mutating the full audit history.

## Failure behavior

A provider error, exhausted step budget, or other recoverable runtime error closes the current turn as `error` and returns to the prompt. Earlier successful turns and workspace changes remain available. If the underlying problem is persistent—for example, an invalid API credential—exit, correct the configuration, and start a new process.

The full partial trace of the failed turn remains available for audit. A sanitized system marker is also appended to the conversation before the next request, telling the model that the prior turn did not complete and that partial tool side effects may exist. Raw provider error text is not copied into future prompts.

`Ctrl+C` interrupts the active operation and closes the session. EOF (for example, `Ctrl+Z` then Enter on Windows or `Ctrl+D` on macOS/Linux) exits normally when the agent is waiting for input.

## Quiet and approval modes

Interactive `--quiet` keeps the `You>` input prompt and prints each final answer, while hiding tool traces and reports. Review-level actions are still denied by default in a non-rendering UI; combine `--quiet --yes` only when you intentionally want automatic approval. Operations classified as blocked remain blocked in every mode.

## Programmatic lifecycle

The same behavior is available without the terminal loop:

```python
agent.start_session()
try:
    diagnosis = agent.run_turn("Diagnose the failing tests", render_report=False)
    result = agent.run_turn("Fix the issues you found and validate", render_report=False)
finally:
    agent.finish_session(render_report=False)
```

For existing one-shot integrations, `agent.run("task")` remains supported and internally performs one complete start/turn/finish lifecycle.

Do not invoke `run_turn()` concurrently on the same Agent instance. It deliberately fails fast because its conversation is an ordered state machine. A future coordinator may run separate Agent instances in parallel, but each worker must own its model client and runtime state.
