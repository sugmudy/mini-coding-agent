# Usage Guide

## 1. Environment setup

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Check the installed version:

```bash
python main.py --version
```

## 2. Configure an OpenAI-compatible gateway

Credentials remain outside source code. The project uses the standard environment configuration supported by the OpenAI Python SDK.

For OpenLux:

### Windows PowerShell

```powershell
$env:OPENAI_BASE_URL="https://api.openlux.ai/v1"
$env:OPENAI_API_KEY="<your OpenLux token>"
$env:AGENT_MODEL="<model id>"
```

### macOS / Linux

```bash
export OPENAI_BASE_URL="https://api.openlux.ai/v1"
export OPENAI_API_KEY="<your OpenLux token>"
export AGENT_MODEL="<model id>"
```

Never put a real credential in the repository, README, screenshots, recordings, demo fixtures, or session examples.

List available models:

```bash
python main.py --list-models
```

A model can also be selected per run:

```bash
python main.py --model MODEL_ID "Fix the failing tests"
```

## 3. Select a workspace

Default workspace:

```text
./workspace
```

Or use another project:

```bash
python main.py --workspace path/to/project "Fix the failing tests"
```

All file tools resolve paths against this directory. `../` path traversal or absolute paths that resolve outside the workspace are rejected.

## 4. Run tasks

Interactive:

```bash
python main.py --workspace path/to/project --model MODEL_ID
```

This starts a persistent multi-turn conversation. Each normal line is a new user turn; prior user messages, assistant answers, and tool observations remain available to the next turn. Use `/help`, `/status`, `/history`, and `/exit` for local conversation control. These slash commands are not sent to the model.

One-shot:

```bash
python main.py "Inspect the project, diagnose all failing tests, make the minimum necessary fixes, and validate the final result"
```

V4 CLI options:

```text
--workspace PATH        project directory
--model MODEL_ID        override AGENT_MODEL
--max-steps N           maximum model steps per user turn (default 30)
--safety MODE           strict | balanced | permissive
--yes                   auto-approve review actions (never blocked actions)
--quiet                 hide traces and print each final answer only
--no-color              structured terminal output without colors
--log-dir PATH          JSONL session log directory
--no-log                disable session logging
--list-models           list gateway models and exit
--version               print Mini Coding Agent version
```

V5 multi-Agent options:

```text
--multi-agent                   run Planner -> Implementer -> Reviewer; requires a task
--review-rounds N               maximum Reviewer calls, including the first review
--multi-agent-max-llm-calls N   hard aggregate model-call budget across all roles
--multi-agent-token-budget N    optional observed-token budget checked between role turns
```

Example:

```bash
python main.py --multi-agent --workspace path/to/project --model MODEL_ID \
  --review-rounds 2 --multi-agent-max-llm-calls 40 \
  "Implement the requested feature and run the complete test suite"
```

Multi-Agent mode is currently one-shot. See [Multi-Agent Collaboration](MULTI_AGENT.md) for its role protocol and termination rules.

On Windows, prefer `conda activate AIenv` followed by `python main.py ...`. Some `conda run` versions incorrectly re-encode captured Unicode model output through the GBK console and can report a printing error after the underlying workflow has already completed.

## 5. Tool behavior

### Locate code first

`search_files` supports literal/regex queries, path scopes and file globs. Results contain file paths and line numbers. Generated/dependency directories, large files and binary files are skipped.

### Read only the relevant range

`read_file` accepts `start_line` / `end_line` and returns line-numbered content, total-line metadata, and a SHA-256 revision. Large reads are bounded.

### Prefer precise edits

`edit_file(path, old_text, new_text, expected_sha256?)` requires exactly one occurrence of `old_text`. Zero or multiple matches are explicit errors; the model must re-read and refine the snippet. Passing the revision from `read_file` turns the edit into an optimistic compare-and-swap operation, so stale concurrent work is refused. Successful edits use atomic replacement and return a unified diff rendered in the terminal.

### Whole-file replacement is guarded

`write_file` is appropriate for new files and intentional complete rewrites. It accepts the same optional revision; use `expected_sha256="missing"` when a new file must not already exist. If an existing non-trivial file would shrink to less than roughly 35% of its prior size, V3 classifies the action as review-level and asks for approval in balanced mode.

### Validate with local commands

`run_command` uses `shell=False`, an executable allow-list, workspace `cwd`, timeout, output bounds, and a V3 safety classification. It accepts one direct executable invocation at a time; pipes, redirection, command chaining, multi-line commands, and heredocs are rejected rather than being silently misinterpreted as arguments. Use a cross-platform form such as `python -c "..."` for short validation scripts. Test/build/run commands normally execute automatically. Package installation and mutating Git actions can require approval; destructive Git history operations are blocked.

## 6. Safety modes

### Balanced (default)

```bash
python main.py --safety balanced "Fix the project"
```

Safe commands run automatically. Review-level actions ask the user. Blocked actions never run.

### Strict

```bash
python main.py --safety strict "Fix the project"
```

Both review and blocked actions are rejected. Use this when the workspace should be modified only through the explicit file tools and ordinary validation commands.

### Permissive

```bash
python main.py --safety permissive "Fix the project"
```

Review-level actions run without asking, but blocked destructive/history-changing operations remain blocked.

### Auto-approval

```bash
python main.py --yes "Fix the project"
```

`--yes` answers yes to review prompts. It does not disable the blocked-action policy.

## 7. Terminal UI

The default V4 interface uses Rich to show:

```text
session metadata
user task
model steps
structured tool calls
search/read summaries
file diffs
command exit/output
warnings and safety approvals
per-turn answer/report
final cumulative session report
```

Use `--no-color` when recording in a terminal that does not render color reliably. Use `--quiet` when only answers are desired; input prompts remain available in interactive mode and `--yes` still controls review-level approvals.

## 8. Session traces and observability

A JSONL file is written to `logs/` by default:

```text
logs/session_YYYYMMDD_HHMMSS-xxxxxx.jsonl
```

Every event carries the same session ID. Typical events include:

```text
session_start
turn_start
llm_request
llm_response
context_compaction
tool_result
tool_blocked
validation_nudge
turn_complete / turn_error
session_complete
```

The runtime records both per-turn and cumulative LLM/tool latency, retry count, token usage when the gateway returns `usage`, tool counts, changed files, validation commands and context compactions. Every turn carries a stable integer `turn_id`; the entire JSONL file carries one session ID. Logs are excluded from Git and apply conservative credential redaction without hiding numeric token metrics.

Disable logging:

```bash
python main.py --no-log "Fix the project"
```

## 9. Optional cost estimate

Token counts come from the OpenAI-compatible response when available. Because gateway/model prices vary, prices are never hard-coded. To display a local estimate in the final report, set per-million-token rates:

```text
AGENT_INPUT_PRICE_PER_MILLION
AGENT_OUTPUT_PRICE_PER_MILLION
```

If either value is absent, the report shows token counts but not a cost estimate.

## 10. Runtime configuration

```text
AGENT_MODEL
AGENT_WORKSPACE
AGENT_MAX_STEPS                  default 30
AGENT_COMMAND_TIMEOUT            default 30 seconds
AGENT_LLM_TIMEOUT                default 60 seconds
AGENT_LLM_STREAM                 default true; set false for non-streaming gateways
AGENT_LLM_PARALLEL_TOOL_CALLS    default false; bounds each model response to one tool call
AGENT_REASONING_EFFORT           optional: none/minimal/low/medium/high/xhigh
AGENT_LLM_MAX_RETRIES            default 3
AGENT_RETRY_BACKOFF              default 1.0 seconds
AGENT_MAX_HISTORY_CHARS          default 160000
AGENT_MAX_TOOL_RESULT_CHARS      default 30000
AGENT_LOOP_REPEAT_LIMIT          default 3
AGENT_LOG_DIR                    default logs
AGENT_SAFETY_MODE                default balanced
AGENT_INPUT_PRICE_PER_MILLION    optional
AGENT_OUTPUT_PRICE_PER_MILLION   optional
```

## 11. Tests

Run the deterministic suite:

```bash
python -m pytest -q
```

The tests require no live API credential. For final integration validation, point the configured agent at a disposable multi-file project with failing tests and verify the real trajectory includes search, focused reads, precise edits, error-driven iteration and a passing validation command.
