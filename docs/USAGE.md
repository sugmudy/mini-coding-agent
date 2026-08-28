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

Never store the real credential in the repository, README, screenshots, recordings, or session examples.

List models available through the configured gateway:

```bash
python main.py --list-models
```

A model may also be selected per run:

```bash
python main.py --model MODEL_ID "Fix the failing tests"
```

## 3. Select a workspace

Default workspace:

```text
./workspace
```

Or point to another local project:

```bash
python main.py --workspace path/to/project "Fix the failing tests"
```

All file tools resolve paths against this directory. Path traversal outside it is rejected.

## 4. Run tasks

Interactive:

```bash
python main.py
```

One-shot:

```bash
python main.py "Find the cause of the failing tests, fix it, and validate the result"
```

Useful CLI flags:

```text
--workspace PATH    project directory
--model MODEL_ID    override AGENT_MODEL
--max-steps N       maximum model turns (default 30)
--quiet             hide intermediate trace output
--log-dir PATH      JSONL session log directory
--no-log            disable session logging for this run
--list-models       list gateway models and exit
```

## 5. V2 tool behavior

### Search first

The model can call `search_files` with literal/regex queries, path scopes and file globs. Search output is bounded and includes line numbers.

### Focused reads

`read_file` accepts optional `start_line` and `end_line`. Large files should be navigated with focused ranges rather than repeatedly loaded in full.

### Precise edits

`edit_file` accepts an exact `old_text` and `new_text`. The old snippet must be unique. Ambiguous or missing snippets produce structured errors so the model can re-read and refine the edit. Successful edits return a unified diff.

### Whole-file writes

`write_file` remains available for new files and intentional complete replacements.

### Validation commands

`run_command` uses `shell=False`, an executable allow-list, workspace `cwd`, timeout, and bounded output. Supported executables include common Python, Git, Node, Java, C/C++, CMake/Make, Cargo, and Go development commands.

If files were changed and the model attempts to finish without running any command, V2 issues one runtime validation nudge.

## 6. Session logs

By default a JSONL trace is written under `logs/`:

```text
logs/session_YYYYMMDD_HHMMSS_xxxxxx.jsonl
```

It contains events such as:

```text
session_start
llm_request
llm_response
tool_result
tool_blocked
validation_nudge
session_complete
```

Logs are local runtime artifacts and are excluded from Git. Secret-like values are redacted conservatively. Use `--no-log` when no trace is desired.

## 7. Runtime configuration

The following optional environment variables tune V2 without code changes:

```text
AGENT_MODEL
AGENT_WORKSPACE
AGENT_MAX_STEPS              default 30
AGENT_COMMAND_TIMEOUT        default 30 seconds
AGENT_LLM_TIMEOUT            default 60 seconds
AGENT_LLM_MAX_RETRIES        default 3
AGENT_RETRY_BACKOFF          default 1.0 seconds
AGENT_MAX_HISTORY_CHARS      default 160000
AGENT_MAX_TOOL_RESULT_CHARS  default 30000
AGENT_LOOP_REPEAT_LIMIT      default 3
AGENT_LOG_DIR                default logs
```

## 8. Tests

Run the full deterministic suite:

```bash
pytest -q
```

The suite does not need a live API key. For real end-to-end verification, configure the gateway and point the agent at a disposable test project, then ask it to fix failing tests.

## 9. Safety note

The workspace and command policies reduce accidental reach but do not provide a hardened sandbox. Run the agent on code/workspaces you are comfortable allowing local development commands to modify.
