# Mini Coding Agent

A compact coding agent implemented from scratch for the NJU Software Engineering recommendation assessment.

The remote OpenAI-compatible gateway is used only for model inference and native tool calling. The local harness owns conversation/context management, tool schemas and dispatch, workspace file access, command execution, retry policy, loop control, safety policy, session tracing, termination, runtime statistics, and error recovery.

Current version: **v0.3.0**.

## V3: Polished & Defensible Coding Agent

V3 keeps the V1/V2 core harness and adds product-level usability, safety, and observability without introducing an agent framework.

### Coding capabilities

- `list_files` — bounded recursive project listing with generated/dependency directories ignored.
- `search_files` — cross-platform literal/regex search with path scopes, globs, line metadata, binary/large-file skipping, and result limits.
- `read_file` — focused inclusive line-range reads with line numbers and size bounds.
- `edit_file` — exact unique replacement for precise changes; ambiguous edits are refused and successful edits return a unified diff.
- `write_file` — new-file creation or intentional whole-file replacement with large-rewrite safety detection.
- `run_command` — local development commands using `shell=False`, workspace `cwd`, an executable allow-list, timeout, bounded stdout/stderr, and V3 risk classification.

### Reliability

- Full local audit history plus a bounded model-facing context view.
- Context compaction removes only complete assistant/tool interaction blocks.
- Tool outputs are bounded with head/tail preservation.
- Exact repetition and short periodic tool loops are detected.
- Successful edits advance a workspace generation so legitimate post-edit rechecks are not misclassified as loops.
- Transient API failures use explicit exponential-backoff retry; authentication/request errors fail fast.
- A one-shot validation guard nudges the model when files changed but no test/build/run command was executed.

### Safety

- File paths are resolved against the configured workspace and path escapes are rejected.
- Commands use `shell=False` and a bounded development executable allow-list.
- V3 `SafetyPolicy` classifies actions as `safe`, `review`, or `blocked`.
- `balanced` mode (default) asks for confirmation before review-level actions such as package installation or mutating Git state.
- `strict` rejects review-level actions; `permissive` auto-allows review-level actions.
- Destructive/history-changing Git actions such as `git reset --hard`, `git clean`, `git commit`, `git push`, force push, rebase, and cherry-pick remain blocked in every mode.
- Suspicious whole-file replacements that shrink a non-trivial existing file below 35% of its previous size require explicit approval.
- Session logs redact common API-key/token/secret/password patterns and remain outside Git.

### Usability & observability

- Rich terminal UI with structured task/step/tool output.
- Unified diff rendering for file edits and replacements.
- Concise search/read/command result rendering instead of dumping every raw tool payload to the terminal.
- Per-run session ID and append-only JSONL trace.
- Runtime-derived final report: changed files, validation command, LLM/tool calls, retries, context compactions, token usage, latency, and total duration.
- Optional estimated API cost when per-million-token prices are configured locally.
- Plain/no-color/quiet execution modes remain available for terminals and automation.

## Architecture

```text
User Task
   |
   v
 Terminal UI / Approval ------------------------------------+
   |                                                        |
   v                                                        |
 Agent -------------------- AgentState / SessionLogger      |
   |                                                        |
   +--> ContextManager --> bounded model view               |
   |                         |                              |
   |                         v                              |
   |                    LLMClient --> Gateway --> LLM       |
   |                         ^                   |           |
   |                  retry + usage              | tool_calls|
   |                                             v           |
   +--> LoopDetector ----------------------> ToolRegistry    |
                                             |              |
                                      SafetyPolicy          |
                                             |              |
                           +-----------------+---------------+
                           |                 |               |
                         Files            Search          Command
                           |                 |               |
                           +------ structured results -------+
                                             |
                                     Context / UI / State
```

The project intentionally does **not** use LangChain, LlamaIndex, OpenAI Agents SDK, AutoGen, CrewAI, or another agent framework.

## Quick Start

Install dependencies:

```bash
pip install -r requirements.txt
```

Configure your OpenAI-compatible gateway in the local shell. For OpenLux:

```text
OPENAI_BASE_URL=https://api.openlux.ai/v1
OPENAI_API_KEY=<your token>
AGENT_MODEL=<model id>
```

List models:

```bash
python main.py --list-models
```

Run against the default `workspace/`:

```bash
python main.py "Inspect the project, fix the failing tests, and validate the result"
```

Or use another local project:

```bash
python main.py --workspace path/to/project "Fix all failing tests"
```

Safety modes:

```bash
python main.py --safety balanced "Fix the project"   # default: prompt for review actions
python main.py --safety strict "Fix the project"     # reject review actions
python main.py --safety permissive "Fix the project" # auto-allow review actions
```

`--yes` auto-approves review-level prompts, but **cannot override blocked destructive operations**.

Other useful flags:

```text
--quiet       final answer only
--no-color    structured UI without colors
--no-log      disable JSONL trace for this run
--version     print the current version
```

## Tests

```bash
python -m pytest -q
```

The deterministic test suite does not require a live API credential. It covers tool behavior and boundaries, exact editing, search, context compaction/protocol integrity, loop detection, retry classification, logging/redaction, safety classification, dangerous Git blocking, large rewrite approval, runtime metrics, Rich UI rendering, and complete fake-LLM agent loops.

## Documentation

- [Usage Guide](docs/USAGE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Reliability Design](docs/RELIABILITY.md)
- [Safety Model](docs/SAFETY.md)
- [Demo Guide](docs/DEMO.md)

## Scope and limitations

The project is intentionally a small, explicit coding-agent harness rather than a framework-heavy platform. It does not provide a hardened OS/container sandbox, browser access, multi-agent orchestration, RAG/vector databases, long-term memory, MCP, or automatic Git commit/push. The final safety boundary is therefore appropriate for disposable/local development workspaces, not for running untrusted code with host-level privileges.
