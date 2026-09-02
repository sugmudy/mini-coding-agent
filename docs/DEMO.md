# Demo Guide

The assessment video is short, so the demo should show the agent *reasoning through a real codebase* rather than solving a one-line toy bug or scrolling through implementation files for most of the recording.

## Recommended demo project

Use a disposable project with roughly 5–8 source/test files and these properties:

- at least one failing automated test;
- the task description does not reveal the exact bug location;
- one failure requires locating a symbol across files;
- the agent can use `search_files` + focused `read_file` instead of reading everything;
- at least one localized change is suitable for `edit_file` so the unified diff is visible;
- after the first change, validation should either pass or reveal a second small issue that demonstrates error-driven iteration;
- total runtime is comfortably below the video limit.

## Recommended multi-turn demo

```text
You> Inspect this project and diagnose the failing tests. Do not edit yet.
You> Make the minimum necessary fixes for the issues you found and run focused tests.
You> Run the complete test suite, then summarize the changed files.
You> /status
```

This trajectory demonstrates that follow-ups reuse prior diagnosis and workspace observations rather than starting a disconnected agent run. It also shows that status is derived locally and does not spend an API request.

## Ideal visible trajectory

```text
Turn 1 diagnosis
  -> search_files for a failing symbol/error
  -> focused read around relevant lines
  -> edit_file
  -> unified diff rendered
  -> pytest -q
  -> if needed: inspect failure -> second focused edit
  -> pytest -q succeeds
  -> turn report
  -> Turn 2 refers to prior diagnosis and edits
  -> focused validation
  -> Turn 3 runs full validation
  -> /status and cumulative session report
```

The final report should visibly show changed files, validation command, tool/model counts, token/latency metrics and session trace path. This demonstrates that runtime facts come from the harness rather than being invented by the model.

## Suggested two-minute structure

### 0:00–0:15 — What it is

Briefly state that the project is a coding-agent harness implemented from scratch. The remote API is used only for inference/tool selection; file execution, context, retry, loop control, safety and termination are local code.

### 0:15–1:30 — Real task

Run the prepared task. Keep the terminal large enough to read search matches, diffs and test output. Avoid manually intervening unless a review-level safety prompt is intentionally part of the demonstration.

### 1:30–1:50 — Final report

Show passing validation plus runtime-derived changed files, calls/tokens/latency and session ID.

### 1:50–2:00 — Architecture sentence

Finish with one sentence describing the design evolution: V1 built the minimal harness, V2 improved reliability, V3 added safety and observability, V4 added explicit multi-turn session semantics, and V5 added locally orchestrated Planner/Implementer/Reviewer collaboration without an agent framework.

## Optional safety mini-demo

If time permits outside the main submission video, demonstrate that:

```text
git status
```

is safe, while:

```text
git reset --hard HEAD
```

is locally blocked even if the model requests it. This is useful for interview discussion but should not consume the main two-minute demo unless safety becomes a focus of questioning.

## Recording precautions

- Never display the real API token in the terminal, environment dump, README, log, or recording.
- Prepare the disposable demo workspace before recording.
- Use `--no-color` only if the recorder/terminal renders ANSI colors poorly.
- Do not use `--quiet`; the tool trajectory is the most important evidence.
- Keep the repository's actual commit/push workflow manual rather than asking the agent to perform it.

## Optional V5 multi-Agent segment

For a multi-Agent demo, use a tiny repository with one failing test and run:

```bash
python main.py --multi-agent --workspace demo-project --model MODEL_ID \
  --review-rounds 2 --multi-agent-max-llm-calls 30 \
  "Fix the defect with a minimal change and run the complete test suite"
```

Capture the Coordinator stage labels, resulting diff/test evidence, and final report. Explain that each role owns a separate Agent/LLM/history, while only validated JSON and bounded blackboard artifacts cross role boundaries. The command exits non-zero if review never approves or runtime state lacks a successful record for any planned acceptance command.
