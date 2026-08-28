# Architecture

## Goal

The project implements the agent harness itself while using an OpenAI-compatible model gateway only for model inference and native tool-calling.

```text
User Task
   |
   v
 main.py
   |
   v
 Agent ----------------------+
   |                          |
   | messages + tool schemas |
   v                          |
 LLMClient -> Gateway -> LLM |
   |                          |
   | assistant tool_calls    |
   v                          |
 ToolRegistry                 |
   |                          |
   +--> list_files            |
   +--> read_file             |
   +--> write_file            |
   +--> run_command           |
   |                          |
   +---- tool result ---------+
```

## Module responsibilities

- `main.py`: CLI, configuration wiring, user-facing error handling.
- `config.py`: non-secret runtime configuration.
- `llm_client.py`: thin OpenAI-compatible API adapter. Credential and gateway configuration are delegated to the SDK environment.
- `agent.py`: conversation history, tool-call parsing, agent loop, termination by final response or `max_steps`.
- `tools/registry.py`: tool schemas plus local dispatch.
- `tools/file_tools.py`: workspace-constrained file listing, reading, and writing.
- `tools/shell_tool.py`: guarded local development-command execution with timeout and output capture.
- `prompts.py`: system-level operating rules for the model.

## Agent loop

1. Initialize `messages` with a system prompt and user task.
2. Send `messages` and tool schemas to the LLM.
3. Append the assistant message to history.
4. If the assistant requests tools, parse each function name and JSON argument string.
5. Dispatch the tool locally and append a `role=tool` result with the matching `tool_call_id`.
6. Repeat from step 2.
7. Stop when the assistant returns no tool calls, or raise an error when `max_steps` is reached.

## Error handling

Tool failures are converted into structured tool results instead of crashing the process. This allows the model to observe errors such as missing files, invalid arguments, command-policy rejections, command failures, and timeouts and then decide what to do next.

API/configuration failures are surfaced to the CLI and terminate the current run cleanly.

## Command boundary

V1 deliberately avoids arbitrary shell evaluation. `run_command` tokenizes the requested command, executes it with `shell=False`, and accepts a bounded set of common development executables. Commands run with the workspace as their current working directory and are subject to a timeout.

This is a pragmatic safety boundary, not a full sandbox. A later version can replace the allow-list with an explicit approval policy or a stronger isolated runtime.

## V1 design boundaries

V1 intentionally uses full-file `write_file` instead of patch editing and keeps the full conversation history. Later versions can add precise edits, search, context compression, retries, loop detection, richer logging, and streaming without changing the core harness architecture.
