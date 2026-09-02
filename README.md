# Mini Coding Agent

A compact coding agent implemented from scratch for the NJU Software Engineering recommendation assessment.

The remote OpenAI-compatible gateway is used only for model inference and native tool calling. The local harness owns conversation/context management, tool schemas and dispatch, workspace file access, command execution, retry policy, loop control, safety policy, session tracing, termination, runtime statistics, and error recovery.

Current version: **v0.5.1**.

## V5: Bounded Multi-Agent Collaboration

V5 adds an explicit local `Planner -> Implementer -> Reviewer` workflow above the proven single-Agent runtime. Every role owns an independent model client, history and state; the Coordinator passes only a validated plan and bounded blackboard artifacts between them.

- Planner has read-only tools and must return a locally validated acyclic JSON plan.
- Implementer is the only role with file mutation tools and receives structured review feedback as bounded follow-up turns.
- Reviewer can inspect and run validation but cannot edit files.
- Role permissions are enforced locally by ToolRegistry allow-lists.
- Global model-call/token budgets and review-round limits prevent unbounded collaboration loops.
- Overall success requires Reviewer approval and successful runtime records for every planned acceptance command.

Run it explicitly with:

```bash
python main.py --multi-agent --workspace path/to/project --model MODEL_ID \
  --review-rounds 2 --multi-agent-max-llm-calls 40 \
  "Implement the requested change and validate it"
```

See [Multi-Agent Collaboration](docs/MULTI_AGENT.md) for protocols, permissions, budgets, histories, and limitations.

## V4.1: Engineering hardening

V4.1 keeps the V4 user experience and strengthens the local runtime using explicit software-engineering invariants:

- one `Agent` instance is a single-flight state machine and rejects overlapping turns;
- file changes use atomic replacement and optional SHA-256 compare-and-swap revisions;
- session traces use thread-safe JSONL appends with schema and monotonic event sequence numbers;
- failed turns add a sanitized failure marker to later model context;
- command policy parses Git global options, fails closed for unknown Git subcommands, and covers dependency-command aliases;
- repository text line endings are declared in `.gitattributes`, and duplicated tests were removed.

The detailed rationale, history-storage model, concurrency boundary, consistency guarantees, and trade-offs are documented in [Software Engineering Design](docs/ENGINEERING.md).

## V4: Stateful Multi-turn Coding Agent

V4 keeps the reliable V1–V3 harness and adds a real persistent conversation lifecycle. Running without a positional task now opens a REPL: enter a request, let the agent inspect/edit/validate, then ask a follow-up that can use the earlier conversation and tool observations. The same workspace, audit history, safety policy, session log, and cumulative metrics remain active until `/exit`.

### Multi-turn conversation

- Explicit `start_session() -> run_turn() -> finish_session()` lifecycle, with `run(task)` retained for one-shot callers.
- Full in-memory conversation history across user turns; runtime-only turn metadata is stripped before API requests.
- Separate per-turn and session-wide facts, token usage, latency, tool counts, changed files, validation, and reports.
- Conversation-aware context compaction drops old complete turns first and preserves assistant/tool protocol pairs.
- Validation nudges and loop detection are scoped to the current turn, so an earlier command or repeated read cannot distort a follow-up.
- Built-in `/help`, `/status`, `/history`, and `/exit` commands are handled locally and never sent to the model.
- A failed turn is logged and reported without discarding the preceding successful conversation.

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
- A turn-local validation guard nudges the model when the current request changed files but ran no test/build/run command.

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
User input(s)
   |
   v
 Interactive REPL / one-shot CLI / Approval ----------------+
   |                                                        |
   v                                                        |
 Agent session ------------ AgentState / TurnState / Logger |
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
AGENT_LLM_STREAM=true
AGENT_LLM_PARALLEL_TOOL_CALLS=false
AGENT_REASONING_EFFORT=low
```

List models:

```bash
python main.py --list-models
```

Run against the default `workspace/`:

```bash
python main.py "Inspect the project, fix the failing tests, and validate the result"
```

Start a persistent conversation by omitting the task:

```bash
python main.py --workspace path/to/project --model MODEL_ID

# For a reasoning model behind a latency-sensitive gateway:
python main.py --workspace path/to/project --model MODEL_ID --reasoning-effort low
```

Then enter normal follow-ups such as:

```text
You> Inspect the project and explain the failing tests first. Do not edit yet.
You> Fix the two issues you found and run the focused tests.
You> Now run the complete suite and summarize every changed file.
You> /status
You> /exit
```

`--max-steps` is a per-turn limit in this mode, not a lifetime limit for the whole conversation. See the [Conversation Guide](docs/CONVERSATION.md) for lifecycle, commands, failure behavior, and API usage.

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
--quiet       hide traces and print each final answer only
--no-color    structured UI without colors
--no-log      disable JSONL trace for this run
--version     print the current version
```

## Tests

```bash
python -m pytest -q
```

The deterministic test suite does not require a live API credential. It covers tool behavior and boundaries, exact editing, search, multi-turn lifecycle and context retention, context compaction/protocol integrity, turn-local validation and loop detection, interactive commands, retry classification, logging/redaction, safety classification, dangerous Git blocking, large rewrite approval, runtime metrics, Rich UI rendering, and complete fake-LLM agent loops.

## Documentation

- [Usage Guide](docs/USAGE.md)
- [Multi-turn Conversation Guide](docs/CONVERSATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Reliability Design](docs/RELIABILITY.md)
- [Software Engineering Design](docs/ENGINEERING.md)
- [Multi-Agent Collaboration](docs/MULTI_AGENT.md)
- [Safety Model](docs/SAFETY.md)
- [Demo Guide](docs/DEMO.md)

## Scope and limitations

The project is intentionally a small, explicit coding-agent harness rather than a framework-heavy platform. Conversation memory lasts only for the current process; it does not provide persistent cross-session memory. V5 multi-Agent mode is a bounded sequential role workflow, not unrestricted autonomous swarms or parallel writers. The project also does not provide a hardened OS/container sandbox, browser access, RAG/vector databases, MCP, or automatic Git commit/push. The final safety boundary is therefore appropriate for disposable/local development workspaces, not for running untrusted code with host-level privileges.
