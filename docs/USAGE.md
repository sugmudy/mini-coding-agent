# Usage Guide

## 1. Create a virtual environment

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

## 2. Configure the OpenAI-compatible gateway

The project deliberately keeps credentials out of source code. It uses the standard environment configuration understood by the OpenAI Python SDK.

For OpenLux, set the SDK base URL to:

```text
https://api.openlux.ai/v1
```

Then configure the SDK credential environment variable with your own OpenLux token. Do not place the token in this repository, README files, screenshots, or recorded demos.

Set the model separately through:

```text
AGENT_MODEL=<model id>
```

To inspect model IDs available through the configured gateway:

```bash
python main.py --list-models
```

You may also select a model per run with `--model`.

## 3. Prepare a workspace

By default the agent works in `./workspace`, which is created automatically.

Example:

```text
workspace/
├── calculator.py
└── test_calculator.py
```

You can point at another project directory:

```bash
python main.py --workspace path/to/project "Fix the failing tests"
```

## 4. Run a task

Interactive mode:

```bash
python main.py
```

Then enter a task at `Task>`.

One-shot mode:

```bash
python main.py "Fix the bug and run the tests"
```

With explicit options:

```bash
python main.py --model MODEL_ID --workspace ./workspace --max-steps 20 "Fix the failing tests"
```

Use `--quiet` to hide intermediate tool traces.

## 5. Run tests

The repository tests do not require a live API credential and use a fake LLM for the agent-loop test.

```bash
pytest -q
```

## Command policy

The V1 `run_command` tool does not evaluate an arbitrary shell string. It tokenizes commands, uses `shell=False`, applies a timeout, and limits the executable to common development tools such as Python, pytest, pip, git, Node.js tooling, Java, C/C++ compilers, CMake, Make, Cargo, and Go.

This is a safety boundary rather than a full OS sandbox.
