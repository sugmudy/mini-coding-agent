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

## 2. Configure OpenLux

The project keeps credentials out of source code and relies on the standard environment configuration supported by the OpenAI Python SDK. The SDK supports `OPENAI_BASE_URL` for OpenAI-compatible gateways.

For OpenLux, configure these values locally. Replace the placeholders with your own token and a model ID available to that token.

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

Do not place the real token in this repository, README files, screenshots, or recorded demos.

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
