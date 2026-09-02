# Reliability Design Notes

This document records the main V2 design decisions and the failure modes they address. It is useful both for maintenance and for explaining the implementation in an interview.

## Precise edits instead of blind whole-file rewrites

**Problem:** Re-generating an entire large file to modify a few lines wastes context and can accidentally change unrelated code.

**Decision:** `edit_file(path, old_text, new_text)` requires one exact unique occurrence. It refuses zero or multiple matches and returns a unified diff on success.

**Why not line-number editing?** Line numbers become stale after preceding edits. Exact snippets with sufficient surrounding context are more stable and force ambiguity to surface as an explicit error.

## Search before broad reads

**Problem:** On a multi-file project, repeatedly guessing filenames and reading whole files is slow and context-expensive.

**Decision:** `search_files` returns bounded matches with path + line metadata. `read_file` accepts focused line ranges. The system prompt explicitly encourages `search -> focused read -> edit -> validate`.

## Bounded context without broken tool protocol

**Problem:** Long tool outputs and repeated file reads make prompt history grow indefinitely. Naively deleting old messages can leave a `tool` message without the assistant `tool_call` it answers.

**Decision:** Full history remains available locally, while `ContextManager` builds a bounded copy. Old history is removed only as complete interaction blocks. Tool results are head/tail truncated. Omitted history is represented by deterministic metadata rather than an LLM-generated semantic summary.

## Loop detection that understands workspace changes

**Problem:** Models can repeat the same read/search pattern even after the observation has already been returned.

**Naive solution:** Block every repeated tool call.

**Why that is wrong:** A second `read_file("a.py")` after editing `a.py` may be exactly the correct verification step.

**Decision:** Tool signatures include a workspace generation. Successful file writes/edits advance the generation, resetting repetition semantics. The detector also catches short periodic cycles such as `read -> search -> read -> search`.

## Runtime validation guard

**Problem:** A model can write code and immediately claim the task is done without running an available test/build command.

**Decision:** If files changed and no command has run, the runtime issues one validation nudge before accepting completion. It only nudges once because some tasks (for example pure documentation changes) have no meaningful executable validation.

## Explicit transient retry policy

**Problem:** A single gateway timeout, rate limit, or upstream 5xx should not destroy an otherwise recoverable coding session.

**Decision:** The harness owns retry behavior instead of relying on opaque SDK defaults. Transient classes are retried with bounded exponential backoff; ordinary 4xx/authentication failures fail fast.

## Streaming model responses

**Problem:** A gateway can accept and record a long-running request but close an idle non-streaming connection before the complete response is returned. The dashboard then shows a call while the local SDK reports a connection failure.

**Decision:** Chat Completions stream by default. The adapter incrementally assembles text, provider reasoning content, multiple indexed tool calls and their fragmented JSON arguments into one protocol-valid assistant message. Usage is committed only after the complete stream succeeds, and stream creation plus consumption share the same retry boundary so a partial response never enters conversation history. Both SDK API errors and lower-level HTTP transport failures are classified by the same bounded retry policy.

Parallel tool calls default to off. A coding model otherwise may serialize several complete file bodies into one very large response, increasing gateway disconnect risk and committing multiple writes before it can observe any result. One tool call per response creates a bounded decide-act-observe cycle. `AGENT_LLM_PARALLEL_TOOL_CALLS=true` is available for reliable gateways and read-heavy workloads; `AGENT_LLM_STREAM=false` remains available for gateways that do not implement streaming.

Reasoning effort is explicit rather than guessed from a model name. Latency-sensitive gateways can use `--reasoning-effort low` (or `AGENT_REASONING_EFFORT=low`) to bound time spent before a tool decision, while direct providers and offline workflows can choose a higher supported level. Omitting the option preserves the provider default and compatibility with non-reasoning models.

## Structured execution state

**Problem:** Important facts such as which files were changed should not exist only inside model memory.

**Decision:** `AgentState` tracks changed files, commands and tool counts from executed actions. This data is usable for logs, future UI summaries, and later safety policies.

## Append-only session traces

**Problem:** Without a trace, it is difficult to explain why an agent made a bad edit or got stuck.

**Decision:** Each run can produce a local JSONL trace containing model/tool events and timing. The logger redacts secret-like keys/strings and the log directory is excluded from Git.

## Testing philosophy

V2 tests deterministic harness behavior without requiring a paid/live model request. The suite covers both happy paths and boundary conditions: ambiguous edits, path escapes, invalid line ranges, search modes, tool protocol preservation during context compaction, loop cycles, retry classification, command policy, secret redaction, validation nudging, and a full fake-LLM edit/validate loop.

## V3: reliability becomes observable and enforceable

V3 does not replace the V2 mechanisms; it exposes and strengthens them. `AgentState` now aggregates LLM/tool latency, token usage, retries and context compactions so reliability behavior can be inspected after a real run. The final report uses these runtime facts rather than model claims.

Safety also moves beyond prompt guidance. `SafetyPolicy` sits on the local execution path, and review/block decisions happen before commands or suspicious whole-file rewrites are executed. The terminal UI receives only an approval callback; low-level tools therefore remain deterministic and testable.

The V3 UI is intentionally an adapter. Rich rendering, plain output and quiet execution all share the same Agent/Tool runtime, preventing product polish from becoming a second control-flow implementation.

## V4: reliable multi-turn state

V4 introduces a session lifecycle instead of repeatedly invoking the one-shot runner. `start_session()` owns the system prompt and stable session ID, `run_turn()` owns one user's step budget and validation decision, and `finish_session()` closes cumulative logging/reporting exactly once. The old `run(task)` API delegates to this lifecycle, so one-shot behavior and integrations remain compatible.

Conversation history is retained in full locally. Each runtime message carries a private turn ID used only for grouping; `ContextManager` removes private keys before calling the provider. When history exceeds the budget, complete older turns are omitted first. If one active turn is itself too large, only complete assistant/tool blocks are removed, preventing orphan tool responses.

Reliability policies that should not leak across requests are turn-local. The validation guard only treats a command in the current turn as validation for edits in that turn. Loop-detector history is cleared at a new turn, allowing a legitimate follow-up to inspect the same unchanged file, while edit generations still protect within-turn rechecks.

`TurnState` and `AgentState` are updated from the same runtime observations. This produces a concise report after every answer and a cumulative report at exit without trusting model narration. JSONL adds `turn_start`, `turn_complete`, and `turn_error`, and every model/tool event carries its turn ID. Failed turns close cleanly so the user can continue from prior successful context.

Real gateway testing also exposed a portability trap: with `shell=False`, a Unix heredoc can be passed as inert Python arguments and return exit code 0 without running the intended assertions. The command parser therefore rejects multi-line input and shell operators, and only a zero-exit, error-free `run_command` is recorded as successful validation.

## V4.1: explicit invariants and write consistency

V4.1 treats the conversation runtime as an ordered state machine. One Agent instance accepts at most one active turn; an overlapping call is rejected immediately. This makes the ordering of messages, tool observations, metrics, loop state, and finalization deterministic instead of relying on incidental thread timing.

File tools now return a SHA-256 revision from `read_file`. `edit_file` and `write_file` optionally accept that value as `expected_sha256`; a mismatch raises `ConcurrentModification` before writing. New-file creation can use the `missing` sentinel as a compare-and-swap precondition. Successful writes use a same-directory temporary file plus atomic replacement, preventing a crash or reader from observing partially written UTF-8 content.

Session JSONL records now contain `schema_version` and monotonically increasing `event_seq`, and appends are serialized within one logger instance. This is an append-only event-log pattern for diagnosis; it is intentionally not claimed as full event sourcing because runtime state is not reconstructed from the log on startup.
