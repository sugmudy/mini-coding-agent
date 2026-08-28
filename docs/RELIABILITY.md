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

## Structured execution state

**Problem:** Important facts such as which files were changed should not exist only inside model memory.

**Decision:** `AgentState` tracks changed files, commands and tool counts from executed actions. This data is usable for logs, future UI summaries, and later safety policies.

## Append-only session traces

**Problem:** Without a trace, it is difficult to explain why an agent made a bad edit or got stuck.

**Decision:** Each run can produce a local JSONL trace containing model/tool events and timing. The logger redacts secret-like keys/strings and the log directory is excluded from Git.

## Testing philosophy

V2 tests deterministic harness behavior without requiring a paid/live model request. The suite covers both happy paths and boundary conditions: ambiguous edits, path escapes, invalid line ranges, search modes, tool protocol preservation during context compaction, loop cycles, retry classification, command policy, secret redaction, validation nudging, and a full fake-LLM edit/validate loop.
