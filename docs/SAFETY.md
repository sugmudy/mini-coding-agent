# Safety Model

V3 treats safety as an explicit runtime policy rather than a sentence in the system prompt. Prompt instructions can guide the model, but local code must decide whether an operation is actually allowed.

## 1. Workspace confinement

Every file path is resolved relative to the configured workspace. Resolved paths outside that root are rejected before reading or writing. This blocks direct path traversal such as `../secret.txt`.

This does not prevent code executed *inside* a local process from accessing the host if that process itself chooses to do so; the project is not a container sandbox.

## 2. Precise edits

`edit_file` requires one exact unique match. It refuses:

- missing snippets;
- ambiguous snippets with multiple occurrences;
- empty `old_text`.

This prevents the model from silently applying a broad replacement to an unintended location.

## 3. Large rewrite guard

`write_file` is useful for new files and complete replacements, but a model can accidentally regenerate only a small fragment of a large existing file. V3 detects suspicious shrinkage.

A replacement becomes review-level when, for example, a substantial existing file would fall below roughly 35% of its previous line/character size. In balanced mode the user must approve before the write occurs. If approval is denied, the original file is left unchanged and the model receives a structured failure.

## 4. Command execution layers

`run_command` first tokenizes the command and validates the executable. It never passes the string through `shell=True`.

Git classification parses global options before locating the real subcommand, so forms such as `git -C . push` and `git -c ... commit` cannot bypass policy. Flags are also recognized in both separate and `--flag=value` forms. Unknown Git subcommands fail closed to review instead of being assumed read-only. Python/npm package-manager wrappers and aliases such as `python -m pip install` and `npm i` are classified consistently.

Allowed executables are limited to common development tools such as Python/pytest/pip, Git, Node tooling, Java/C/C++ build tools, Cargo and Go. The command runs with the workspace as its current working directory, captures stdout/stderr, bounds output and enforces a timeout.

## 5. Risk classification

`SafetyPolicy` classifies an otherwise allowed command:

### Safe

Typical validation/read-oriented actions, for example:

```text
pytest -q
python main.py
git status
git diff
```

They run automatically.

### Review

Actions that mutate the environment or repository state, for example:

```text
pip install ...
npm install ...
git add ...
git switch ...
git restore <specific file>
```

Balanced mode asks the user before execution. Strict mode rejects them. Permissive mode allows them automatically.

### Blocked

The agent never performs repository-history or strongly destructive Git operations such as:

```text
git reset --hard
git clean
git commit
git push
git push --force
git rebase
git cherry-pick
```

Blocked actions remain blocked even with `--yes` or permissive mode. Development Git history remains under the user's control.

## 6. Safety modes

- `balanced` — default; safe auto-run, review requires confirmation, blocked denied.
- `strict` — safe auto-run, review denied, blocked denied.
- `permissive` — safe/review auto-run, blocked denied.

`--yes` only auto-confirms review actions in an interactive run. It does not disable blocked rules.

## 7. Logging and secrets

Credentials are expected only through local environment configuration. JSONL traces redact common secret-like values, including API-key/token/secret/password fields, `Bearer ...`, and `sk-...` style values. Log fields also have size limits.

Redaction is defense-in-depth, not a reason to deliberately put credentials in prompts or source files.

## 8. Concurrent file updates

`read_file` returns the SHA-256 revision of the complete file. A caller can pass it to `edit_file` or `write_file` as `expected_sha256`. If another process or worker changed the file after the read, the stale write is rejected. Writes are staged and atomically replaced, so another reader does not observe a half-written file.

This is optimistic concurrency control, not a distributed lock. Callers that omit `expected_sha256` retain backward-compatible last-writer-wins behavior. Multi-agent writers must provide revisions or use isolated worktrees.

## 9. Threat model and limitations

The policy is designed to reduce accidental destructive behavior during local coding tasks. It is **not** a security boundary against malicious source code. A permitted `python`/test/build command can execute project code with the same OS permissions as the user running the agent.

For untrusted repositories, a stronger design would execute tools inside a disposable container/VM with network, filesystem and resource isolation. That is intentionally outside this assessment version.
