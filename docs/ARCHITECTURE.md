# Architecture

## 1. Design goal

The project separates **model inference** from **agent execution**. An OpenAI-compatible gateway returns assistant messages and native tool calls; every important agent behavior is implemented locally.

The local runtime owns:

- full conversation history and model-facing context preparation;
- tool schema definitions and local dispatch;
- workspace-constrained file operations;
- guarded command execution;
- loop detection and maximum-step termination;
- transient API retry policy;
- execution state and session tracing;
- tool-error feedback and validation nudging.

## 2. Component graph

```text
                         +-----------------------+
                         | OpenAI-compatible LLM |
                         +-----------+-----------+
                                     ^
                                     | messages + tools
                                     | assistant/tool_calls
                                     v
+----------+        +----------------+----------------+
|   User   | -----> |              Agent              |
+----------+        +---+---------+-----------+--------+
                       |         |           |
                       |         |           +--> AgentState
                       |         +--------------> SessionLogger
                       v
                 ContextManager
                       |
                       v
                   LLMClient
                       |
                 retry/backoff
                       |
                  model gateway

Assistant tool_calls return to Agent:

Agent -> LoopDetector -> ToolRegistry -> local tool -> structured result -> Agent history
```

## 3. Agent loop

For each model step:

1. The runtime keeps a **full audit history** in `Agent.messages`.
2. `ContextManager.prepare()` creates a bounded model-facing copy.
3. `LLMClient.complete()` performs the Chat Completions request using native tool calling.
4. The assistant message is appended to full history.
5. If there are tool calls, each call is checked by `LoopDetector` before execution.
6. `ToolRegistry` parses the JSON arguments and dispatches the registered local Python function.
7. The result is serialized into a structured `{ok, result/error}` observation and appended with the exact `tool_call_id`.
8. `AgentState` records changed files, commands, step, and tool counts; `SessionLogger` records the trace.
9. The loop repeats until the model returns a final response or `max_steps` is reached.
10. If files were changed but no command was run, a one-shot validation guard asks the model to validate when reasonable before completion is accepted.

## 4. Tool design

### `list_files`

Lists relevant workspace paths recursively while skipping common generated/dependency directories (`.git`, `.venv`, `node_modules`, caches, build outputs). Output is bounded.

### `read_file`

Reads UTF-8 text with optional 1-based inclusive `start_line` / `end_line`. It returns line numbers and metadata so the model can navigate large files without repeatedly reading the whole file. Large results are bounded.

### `search_files`

Cross-platform Python implementation rather than an OS `grep` dependency. Supports literal or regular-expression search, case-sensitive/insensitive modes, directory scoping, filename/path globs, maximum result counts, binary/oversized-file skipping, and path/line metadata.

### `write_file`

Creates a new text file or intentionally replaces a whole existing file. Replacement of an existing file returns a unified diff.

### `edit_file`

Performs a precise exact-text replacement. `old_text` must occur **exactly once**. Zero matches produce a recoverable error telling the model to re-read; multiple matches are rejected as ambiguous. Success returns a unified diff and edit metadata.

This avoids fragile line-number patching and avoids silently modifying the wrong occurrence.

### `run_command`

Uses `shlex` + `subprocess.run(..., shell=False)` with the workspace as `cwd`. It accepts a bounded development executable set, captures `exit_code/stdout/stderr`, truncates excessive output, and enforces a timeout.

## 5. Context management

V1 appended all messages directly to every request. V2 separates:

- **audit history**: the complete in-memory sequence;
- **model view**: a bounded copy prepared for the next API request.

Tool outputs are head/tail truncated deterministically. When history exceeds the configured budget, older interactions are removed only as **complete assistant + tool-result blocks**. This matters because dropping only one side of a tool-call pair can make an OpenAI-compatible request invalid.

A deterministic compaction notice records how many interaction blocks were omitted, counts of tools used, and paths previously seen. It deliberately does not ask another LLM to summarize history, avoiding a second source of hallucination. If exact old content is needed, the model is instructed to re-read it.

## 6. Loop detection

A normalized signature is built from:

```text
(tool name, canonical JSON arguments, workspace generation)
```

The detector catches identical consecutive repetition and short two/three-action periodic cycles repeated three times.

A successful `write_file` or `edit_file` increments the workspace generation. Therefore, reading the same file again **after a change** is treated as a legitimate new observation rather than a loop.

## 7. Retry policy

The SDK's built-in retry is disabled so retry behavior belongs to this harness and can be explained/tested directly.

Retries are limited to transient classes: HTTP 429, HTTP 5xx, connection failures, and timeout/rate-limit/internal-server error classes. Backoff is exponential (`base`, `2*base`, `4*base`, ...). Authentication and ordinary 4xx request errors fail immediately.

## 8. State and logging

`AgentState` tracks runtime facts independently of model memory: current step, tool-call counts, changed files, and commands run.

`SessionLogger` writes append-only JSONL traces with event timestamps and durations. Fields are bounded and secret-like strings/keys are redacted. `logs/` is git-ignored.

## 9. Error recovery

Tool exceptions are returned as structured observations rather than crashing the process. The model can recover from missing files, ambiguous edits, invalid ranges, invalid JSON arguments, command-policy rejection, failed commands, and timeouts.

Gateway/configuration failures are surfaced cleanly to the CLI. `max_steps` remains a final termination guard even if model behavior fails to converge.

## 10. Deliberate boundaries

V2 is still a small single-agent harness. It intentionally does not add multi-agent orchestration, retrieval/vector databases, browser tools, long-term memory, GUI layers, or agent SDKs. The objective is to make the core coding loop reliable and defensible before polishing the user interface or adding stronger isolation.
