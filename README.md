# Mini Coding Agent

A lightweight coding agent implemented from scratch for the NJU Software Engineering recommendation assessment.

The project uses an OpenAI-compatible model gateway for inference and native tool-calling, while the agent harness itself is implemented locally: conversation history, tool definitions and dispatch, file operations, command execution, loop control, termination, and error handling.

## V1 Features

- OpenAI-compatible Chat Completions client (OpenLux can be used as the gateway)
- Native function/tool calling
- Multi-turn conversation history
- Local tool registry and dispatcher
- Recursive workspace file listing
- Workspace-constrained file reading and writing
- Guarded local development-command execution with timeout
- Tool-error feedback to the model instead of process crashes
- Maximum-step termination guard
- CLI task input and model listing
- Credentials kept outside source code through SDK environment configuration
- Unit tests for tools, dispatcher behavior, command execution, and the complete agent loop

## Architecture

```text
User -> Agent -> LLMClient -> Gateway -> LLM
          ^                       |
          |                       v
          +--- Tool Results <- Tool Calls
                 |
                 +-- list_files
                 +-- read_file
                 +-- write_file
                 +-- run_command
```

The remote API is used only for model inference. File and command tools execute locally in this project.

## Quick Start

Create and activate a virtual environment, then install dependencies:

```bash
pip install -r requirements.txt
```

Configure the standard OpenAI Python SDK environment for your OpenAI-compatible gateway. For OpenLux the base URL is:

```text
https://api.openlux.ai/v1
```

Keep the real credential only in your local shell environment. Set `AGENT_MODEL` to a model ID available through your token, or pass `--model` on the command line.

List available models:

```bash
python main.py --list-models
```

Put a project in `workspace/`, then run:

```bash
python main.py "Inspect the project, fix the bug, and run the tests"
```

Or point the agent at another directory:

```bash
python main.py --workspace path/to/project "Fix the failing tests"
```

## Tests

```bash
pytest -q
```

The automated tests do not require a live API credential.

## Documentation

- [Usage Guide](docs/USAGE.md)
- [Architecture](docs/ARCHITECTURE.md)

## Security

Never commit real API credentials. File tools reject paths that escape the configured workspace. The command tool uses `shell=False`, a development-command allow-list, a workspace working directory, output limits, and a timeout. This is a pragmatic safety boundary, not a full operating-system sandbox.

## Current Scope

V1 intentionally favors a small, explicit, explainable harness over framework-heavy features. Planned improvements include precise patch editing, code search, context compression, retry/loop controls, richer logging, and a polished terminal experience.
