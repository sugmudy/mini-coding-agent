# Mini Coding Agent

A compact coding agent implemented from scratch for the NJU Software Engineering recommendation assessment.

The remote model gateway is used only for inference and native tool calling. The agent harness itself runs locally and owns conversation/context management, tool schemas and dispatch, workspace file access, command execution, retry policy, loop control, logging, termination, and error recovery.

## V2: Reliable Coding Agent

V2 keeps the small V1 harness but strengthens the parts that matter on real codebases:

- **Precise editing** — `edit_file` performs one exact, unique replacement and refuses ambiguous edits; successful edits return a unified diff.
- **Code search** — `search_files` performs cross-platform literal/regex search with path scopes, file globs, result limits, binary/large-file skipping, and line metadata.
- **Focused reads** — `read_file` supports inclusive line ranges, line numbers, size limits, and metadata instead of repeatedly injecting entire large files.
- **Context control** — full history is retained for audit, while the model receives a bounded view. Compaction preserves complete assistant/tool interaction blocks so tool-call protocol pairs are never split.
- **Loop detection** — exact repetition and short periodic tool cycles are detected. A successful code edit advances a workspace generation so legitimate re-reading after changes is not incorrectly blocked.
- **Transient API recovery** — model requests use an explicit, testable retry policy for rate limits, 5xx responses, timeouts, and connection failures with exponential backoff; non-transient request/auth failures fail fast.
- **Session tracing** — append-only JSONL logs capture model/tool timing and agent events with conservative secret redaction. Runtime logs are ignored by Git.
- **Validation guard** — if code was changed but no command was run, the runtime nudges the model once to validate before claiming completion when reasonable.
- **Runtime state** — changed files, command history, tool counts, and current step are tracked independently from model memory.

The V1 guarantees remain: workspace-constrained file access, structured tool errors, guarded command execution with `shell=False`, timeouts/output limits, maximum-step termination, and credentials outside source code.

## Architecture

```text
User Task
   |
   v
 main.py
   |
   +--> Settings / SessionLogger
   |
   v
 Agent ----------------------------------------------------+
   |                                                       |
   | full audit history                                    |
   +--> ContextManager --> bounded model view              |
   |                          |                            |
   |                          v                            |
   |                     LLMClient --> Gateway --> LLM     |
   |                          ^                   |         |
   |                          |                   v         |
   |                    retry policy          tool_calls    |
   |                                              |         |
   +--> LoopDetector -----------------------------+         |
   |                                              |         |
   v                                              v         |
 ToolRegistry --> list_files / read_file / search_files    |
              --> write_file / edit_file / run_command     |
   |                                                        |
   +--> structured result --> ContextManager --> history ---+
```

The project intentionally does **not** use LangChain, LlamaIndex, OpenAI Agents SDK, AutoGen, CrewAI, or any other agent framework.

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

List models exposed by the configured gateway:

```bash
python main.py --list-models
```

Run against the default `workspace/`:

```bash
python main.py "Inspect the project, fix the failing tests, and validate the fix"
```

Or point at another local project:

```bash
python main.py --workspace path/to/project "Fix the failing tests"
```

A local JSONL trace is written to `logs/` by default. Disable it for a run with:

```bash
python main.py --no-log "Fix the bug"
```

## Tests

```bash
pytest -q
```

The automated suite does not require a live API credential. It covers precise edits, ranged reads, workspace containment, code search, context compaction/protocol integrity, loop detection, retry behavior, structured logging/redaction, command policy, registry behavior, and complete multi-step agent execution.

## Documentation

- [Usage Guide](docs/USAGE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Reliability Design](docs/RELIABILITY.md)

## Security Boundary

Credentials are never embedded in source code. File operations resolve paths against the configured workspace and reject path escapes. `run_command` tokenizes commands, uses `shell=False`, runs with the workspace as `cwd`, applies an executable allow-list, captures bounded output, and enforces a timeout.

This is a pragmatic development-command boundary, **not** a full OS/container sandbox. Stronger isolation and interactive approval are candidates for a later polished version.

## Scope

V2 focuses on making the harness reliable rather than adding framework-heavy features. GUI, browser tools, multi-agent orchestration, RAG/vector databases, long-term memory, Docker sandboxing, MCP, and streaming are intentionally outside the current scope.
