# Architecture

## Design goal

Mini Coding Agent deliberately separates the model from the agent harness. The OpenAI-compatible gateway performs inference and native tool selection; all important agent/runtime behavior is local code written in this repository.

```text
User / one-shot CLI or REPL
   |
   +--> RichUI / approval callback
   |
   v
 Agent ---------------------------------------------------------------+
   |                                                                  |
   +--> AgentState --> TurnState                                       |
   +--> SessionLogger                                                  |
   +--> LoopDetector                                                   |
   |                                                                  |
   +--> full audit messages                                            |
   |       |                                                          |
   |       v                                                          |
   |    ContextManager --> bounded protocol-valid model view          |
   |                              |                                   |
   |                              v                                   |
   |                         LLMClient                                 |
   |                    retry / usage metrics                          |
   |                              |                                   |
   |                              v                                   |
   |                      OpenAI-compatible gateway                    |
   |                              |                                   |
   |                           tool_calls                              |
   |                              v                                   |
   +------------------------ ToolRegistry                              |
                                  |                                   |
                             SafetyPolicy                              |
                                  |                                   |
                     +------------+-------------+                     |
                     |            |             |                     |
                  FileTools    SearchTool    ShellTool                 |
                     |            |             |                     |
                     +------ structured result -----------------------+
```

## Module responsibilities

- `main.py` — CLI, persistent REPL commands, settings wiring, UI selection, safety mode, top-level error handling.
- `version.py` — explicit project version.
- `config.py` — non-secret runtime configuration and environment validation.
- `llm_client.py` — thin Chat Completions adapter, explicit transient retry policy, response usage extraction.
- `agent.py` — session/turn lifecycle, model/tool loop, history, validation guard, state updates, and report handoff.
- `context.py` — turn-aware bounded model view while preserving full local history and assistant/tool protocol.
- `loop_detector.py` — repeated/cyclic behavior detection with workspace generations.
- `state.py` — `TurnState` facts plus cumulative `AgentState` metrics.
- `session_logger.py` — append-only redacted JSONL trace and stable session ID.
- `safety.py` — command/rewrite risk classification and authorization policy.
- `ui.py` — Rich, plain and null frontends plus safety confirmation and final-report rendering.
- `tools/registry.py` — model-visible schemas and local function dispatch.
- `tools/file_tools.py` — workspace-constrained list/read/write/edit operations and unified diffs.
- `tools/search_tool.py` — cross-platform bounded source search.
- `tools/shell_tool.py` — guarded local process execution.
- `prompts.py` — model operating rules; it does not implement agent control flow.

## Session and turn lifecycle

1. `start_session()` installs one system prompt, resets aggregate state, and emits exactly one `session_start` event.
2. Each `run_turn(user_input)` creates a `TurnState`, attaches an internal turn ID to audit messages, clears turn-local loop history, and emits `turn_start`.
3. `ContextManager` strips internal metadata and builds a bounded, protocol-valid model view. It removes old complete turns first; if the newest turn alone is oversized, it preserves its user anchor and newest complete assistant/tool blocks.
4. The loop calls `LLMClient`, records usage/retries/latency in both turn and session state, dispatches tool calls through the registry and safety policy, then appends matching tool results.
5. A model answer ends only the current turn. The validation guard considers changes and commands from that turn, not stale session-wide activity.
6. `turn_complete` or `turn_error` closes the turn. A later user input reuses the same full history and workspace.
7. `/exit`, EOF, or one-shot completion calls `finish_session()`, emits one `session_complete`, and renders cumulative metrics.

`Agent.run(task)` is a compatibility wrapper around this lifecycle. Programmatic integrations can use the three explicit methods directly.

## Concurrency and consistency boundary

An `Agent` instance is a single-flight state machine. `run_turn()` rejects an overlapping call instead of interleaving mutable message history, turn metrics, loop-detector state, context diagnostics, and model-client observations. Parallel work must therefore use separate Agent/LLM/Context instances coordinated above this layer.

File mutations use two complementary mechanisms. A per-`FileTools` re-entrant lock serializes each in-process check/write critical section, while `expected_sha256` provides optimistic concurrency control across independent registries or workers. Content is staged in the destination directory, flushed, and installed with `os.replace`, so readers observe either the old complete file or the new complete file rather than a partial write.

The JSONL logger serializes events per logger instance and assigns a monotonically increasing `event_seq`. The sequence defines local trace order even when wall-clock timestamps have insufficient resolution. See [Software Engineering Design](ENGINEERING.md) for the invariants, storage model, limitations, and future multi-agent boundary.

## Separation of facts and model narration

V4 distinguishes model-generated explanations from runtime facts at two levels. Changed files, commands, token counts, retries, tool counts, latency and context compactions are derived from executed operations for each turn and for the cumulative session. The model can summarize *why* it made changes, but reports do not rely on model memory to claim what actually happened.

## UI is not the runtime

`ui.py` is an adapter, not part of the decision logic. Tests and quiet runs can use `NullUI`; interactive users use `RichUI`. Safety approval is exposed as a callback so `FileTools` and `ShellTool` remain testable with deterministic callbacks rather than terminal input embedded inside low-level code.

## Safety boundary

Safety has multiple independent layers:

```text
workspace path confinement
+ exact/unique edit semantics
+ suspicious rewrite detection
+ executable allow-list
+ shell=False
+ command risk classification
+ timeout/output bounds
+ blocked destructive Git actions
```

This is intentionally stronger than V2 but remains a pragmatic local-development boundary rather than a VM/container sandbox.

## What remains intentionally outside scope

The system does not implement RAG/vector databases, browser tools, MCP, long-term memory, automatic Git commits/pushes, parallel writers, or a hardened OS sandbox. V5 multi-Agent orchestration is deliberately a bounded sequential role workflow; see [Multi-Agent Collaboration](MULTI_AGENT.md).

## V5 composition root

`main.py` remains the composition root. In explicit `--multi-agent` mode, `RoleAgentFactory` creates three independent worker runtimes with role-specific system prompts and ToolRegistry allow-lists. `MultiAgentCoordinator` owns the workflow, blackboard, aggregate budgets and result. The original Agent class remains unaware of peer agents, preserving its single-worker invariants and backward-compatible API.
