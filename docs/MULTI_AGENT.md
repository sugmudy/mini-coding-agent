# Multi-Agent Collaboration

V5 adds a local, deterministic Coordinator above the existing single-Agent runtime. The model gateway still provides inference and native tool calls; role assignment, permissions, communication, budgets, review loops, success criteria, logging, and termination are implemented locally.

## Workflow

```text
User request
    |
    v
Local Coordinator --------------------------------------------------+
    |                                                               |
    +--> Planner (read-only) --> validated TaskPlan DAG              |
    |                               |                               |
    |                               v                               |
    +--> Implementer (read/write/command) --> implementation report |
    |                               |                               |
    |                               v                               |
    +--> Reviewer (read/command) --> structured verdict             |
                                    |                               |
                     rejected ------+------ approved                |
                        |                       |                    |
                        v                       v                    |
             bounded revision             final result <-----------+
```

The initial version intentionally runs roles in sequence. This is genuine multi-Agent collaboration—each role has an independent model client, system prompt, message history, state, context manager, loop detector, and tool capability—but it does not claim that parallel writers are safe. Read-only parallel Researchers and isolated-worktree writers are later extensions.

## Local protocol

The Coordinator is ordinary Python code, not another model. It enforces these transitions:

1. Planner inspects the real workspace and returns exactly one JSON `TaskPlan`.
2. Local parsing rejects unknown fields, duplicate step IDs, missing dependencies, cycles, more than 20 steps, and missing acceptance commands.
3. Implementer receives the original request plus the validated plan. It is the only role with write tools.
4. Reviewer receives a bounded blackboard snapshot, then independently inspects the current workspace and returns a strict JSON verdict.
5. A rejection becomes a new Implementer turn containing only structured feedback. Review calls never exceed `--review-rounds`.
6. Approval is accepted only when runtime state contains successful records for every plan `acceptance_commands` entry. An unrelated successful command or model prose cannot satisfy completion.

Planner and Reviewer outputs fail closed when they contain prose outside the JSON object or fields outside the documented schema. This makes protocol drift visible instead of silently guessing the model's intent.

## Role capability isolation

| Role | Local tools |
|---|---|
| Planner | `list_files`, `read_file`, `search_files` |
| Implementer | list/read/search + `write_file`, `edit_file`, `run_command` |
| Reviewer | list/read/search + `run_command` |

Permissions are enforced by `ToolRegistry.allowed_tools`, not only by prompts. If a read-only role invents a `write_file` call, dispatch returns `Unknown tool` and no write occurs. All roles still share the same workspace confinement, safety policy, command allow-list, timeout, and secret-redacting logger.

Reviewer has command access so it can independently run acceptance tests; it has no file mutation tools. Package installation or repository mutation remains subject to SafetyPolicy approval.

## Blackboard and histories

Workers never share raw `messages` or tool-call protocol records. The Coordinator maintains a bounded `Blackboard` containing:

- original user request;
- validated structured plan;
- bounded Implementer reports;
- structured Reviewer verdicts.

Downstream roles receive a serialized blackboard snapshot and must re-read exact file content from the workspace. This avoids tool-call ID collisions, role-history contamination, and exponential context growth.

All roles write to one thread-safe JSONL trace through a role-bound logger. Each event has the shared session ID, global `event_seq`, and `agent_role`, while Coordinator events record plan, review round, termination, and aggregate state. Credentials remain in environment variables and never enter the blackboard.

## Budgets and termination

- `--max-steps` remains the maximum model steps for one role turn.
- `--multi-agent-max-llm-calls` is a hard aggregate call budget. Before a role turn, its `max_steps` is temporarily reduced to the remaining global allowance.
- `--multi-agent-token-budget` is checked after each completed role turn. One in-flight response can cross the threshold, but no later role is scheduled.
- `--review-rounds` is exactly the maximum number of Reviewer calls, including the first review.
- malformed JSON, role exceptions, budget exhaustion, or invalid graph structure terminates the workflow and closes every started role session.

If every allowed review rejects, the command exits non-zero and prints unresolved required actions. It does not present a partial implementation as approved.

## Run

```bash
python main.py --multi-agent --workspace path/to/project \
  --model MODEL_ID --review-rounds 2 \
  --multi-agent-max-llm-calls 40 \
  "Inspect the project, implement the requested change, and validate it"
```

Add `--multi-agent-token-budget 50000` to limit aggregate observed usage. `--quiet`, `--no-color`, `--no-log`, safety modes, and `--yes` behave as in single-Agent mode.

V5 multi-Agent mode currently requires a positional one-shot task. The V4 interactive REPL remains single-Agent so `/status` and `/history` keep their established semantics.

## Failure and concurrency model

The system does not attempt a distributed transaction across LLM calls, commands, and files. A failed role can leave already completed tool side effects; the log records those facts. Implementer is serialized, file writes are atomic, and `expected_sha256` can reject stale updates.

Each role owns a distinct LLMClient because retry/usage observations are instance-local mutable state. UI input also belongs only to the Coordinator, so multiple roles cannot race for terminal approval. Future parallel read-only roles may safely use `NullUI`; parallel writers require independent Git worktrees or mandatory revision preconditions and a deterministic merge policy.
