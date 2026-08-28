# Architecture

## Design goal

Mini Coding Agent deliberately separates the model from the agent harness. The OpenAI-compatible gateway performs inference and native tool selection; all important agent/runtime behavior is local code written in this repository.

```text
User / CLI
   |
   +--> RichUI / approval callback
   |
   v
 Agent ---------------------------------------------------------------+
   |                                                                  |
   +--> AgentState                                                     |
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

- `main.py` — CLI, settings wiring, UI selection, safety mode, top-level error handling.
- `version.py` — explicit project version.
- `config.py` — non-secret runtime configuration and environment validation.
- `llm_client.py` — thin Chat Completions adapter, explicit transient retry policy, response usage extraction.
- `agent.py` — full agent loop, tool-call parsing, history, validation guard, state/metric updates, final report handoff.
- `context.py` — bounded model-facing view while preserving the local full history and tool-call protocol.
- `loop_detector.py` — repeated/cyclic behavior detection with workspace generations.
- `state.py` — runtime-derived factual state and aggregate metrics.
- `session_logger.py` — append-only redacted JSONL trace and stable session ID.
- `safety.py` — command/rewrite risk classification and authorization policy.
- `ui.py` — Rich, plain and null frontends plus safety confirmation and final-report rendering.
- `tools/registry.py` — model-visible schemas and local function dispatch.
- `tools/file_tools.py` — workspace-constrained list/read/write/edit operations and unified diffs.
- `tools/search_tool.py` — cross-platform bounded source search.
- `tools/shell_tool.py` — guarded local process execution.
- `prompts.py` — model operating rules; it does not implement agent control flow.

## Agent loop

1. Preserve the system prompt and user task in full local history.
2. Build a bounded, protocol-valid model view through `ContextManager`.
3. Call the model through `LLMClient`; collect latency, retry and token metadata.
4. Append the assistant message to the full audit history.
5. If there are no tool calls, apply the one-shot validation guard when needed; otherwise finish.
6. For every tool call, first run loop detection.
7. Dispatch the tool through `ToolRegistry`; file/command operations can consult `SafetyPolicy` before mutation.
8. Convert success/failure into a structured result, update `AgentState`, log the event, render it through the UI, bound the tool observation and append `role=tool` with the matching `tool_call_id`.
9. Repeat until final answer or `max_steps` termination.

## Separation of facts and model narration

V3 intentionally distinguishes model-generated explanations from runtime facts. Changed files, commands, token counts, retries, tool counts, latency and context compactions are derived from executed operations. The model can summarize *why* it made changes, but the final report does not rely on model memory to claim what actually happened.

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

The system does not implement multi-agent orchestration, RAG/vector databases, browser tools, MCP, long-term memory, automatic Git commits/pushes, or a hardened OS sandbox. Those features would add complexity without improving the core assessment goal: an understandable coding-agent harness whose important logic is implemented locally.
