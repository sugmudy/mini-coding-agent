from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from safety import SafetyDecision


@dataclass
class FinalReport:
    final_text: str
    state: dict[str, Any]
    session_log: str | None


class BaseUI:
    def session_started(self, *, workspace: Path, model: str | None, max_steps: int, session_id: str) -> None:
        pass

    def task(self, text: str) -> None:
        pass

    def llm_step(self, step: int, max_steps: int) -> None:
        pass

    def tool_called(self, name: str, raw_arguments: str) -> None:
        pass

    def tool_result(self, name: str, result: str) -> None:
        pass

    def warning(self, text: str) -> None:
        pass

    def info(self, text: str) -> None:
        pass

    def confirm(self, decision: SafetyDecision) -> bool:
        return False

    def final_report(self, report: FinalReport) -> None:
        pass


class NullUI(BaseUI):
    pass


class PlainUI(BaseUI):
    def __init__(self, *, enabled: bool = True, assume_yes: bool = False) -> None:
        self.enabled = enabled
        self.assume_yes = assume_yes

    def _print(self, text: str) -> None:
        if self.enabled:
            print(text)

    def session_started(self, *, workspace: Path, model: str | None, max_steps: int, session_id: str) -> None:
        self._print(f"Mini Coding Agent | session={session_id} | model={model or '(unset)'}")
        self._print(f"Workspace: {workspace.resolve()} | max_steps={max_steps}")

    def task(self, text: str) -> None:
        self._print(f"Task: {text}")

    def llm_step(self, step: int, max_steps: int) -> None:
        self._print(f"\n[step {step}/{max_steps}] Asking model...")

    def tool_called(self, name: str, raw_arguments: str) -> None:
        preview = raw_arguments if len(raw_arguments) <= 300 else raw_arguments[:300] + "..."
        self._print(f"[tool] {name}({preview})")

    def tool_result(self, name: str, result: str) -> None:
        preview = result if len(result) <= 600 else result[:600] + "..."
        self._print(f"[result:{name}] {preview}")

    def warning(self, text: str) -> None:
        self._print(f"[warning] {text}")

    def info(self, text: str) -> None:
        self._print(f"[info] {text}")

    def confirm(self, decision: SafetyDecision) -> bool:
        if self.assume_yes:
            self._print(f"[approved] {decision.reason}")
            return True
        if not self.enabled:
            return False
        try:
            answer = input(f"Safety approval required: {decision.reason}\nAction: {decision.action}\nApprove? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            return False
        return answer.strip().lower() in {"y", "yes"}

    def final_report(self, report: FinalReport) -> None:
        self._print("\n=== Final Answer ===")
        self._print(report.final_text or "(empty response)")
        state = report.state
        self._print("\n=== Run Report ===")
        self._print(f"Changed files: {', '.join(state.get('changed_files', [])) or '(none)'}")
        self._print(f"Commands run: {len(state.get('commands_run', []))}")
        self._print(f"LLM calls: {state.get('llm_calls', 0)} | Tool calls: {state.get('tool_calls', 0)}")
        self._print(
            f"Tokens: {state.get('prompt_tokens', 0)} in + {state.get('completion_tokens', 0)} out "
            f"= {state.get('total_tokens', 0)} total | Duration: {state.get('duration_ms', 0) / 1000:.2f}s"
        )
        if state.get("estimated_cost_usd") is not None:
            self._print(f"Estimated cost: ${state['estimated_cost_usd']:.6f}")
        if report.session_log:
            self._print(f"Session log: {report.session_log}")


class RichUI(BaseUI):
    def __init__(self, *, no_color: bool = False, assume_yes: bool = False) -> None:
        try:
            from rich.console import Console
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise RuntimeError("Rich terminal UI requires the 'rich' package.") from exc
        self.console = Console(no_color=no_color)
        self.assume_yes = assume_yes

    def session_started(self, *, workspace: Path, model: str | None, max_steps: int, session_id: str) -> None:
        from rich.table import Table

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_row("Workspace", str(workspace.resolve()))
        table.add_row("Model", model or "(unset)")
        table.add_row("Max steps", str(max_steps))
        table.add_row("Session", session_id)
        self.console.rule("[bold]Mini Coding Agent v0.3")
        self.console.print(table)

    def task(self, text: str) -> None:
        from rich.panel import Panel

        self.console.print(Panel(text, title="Task", border_style="blue"))

    def llm_step(self, step: int, max_steps: int) -> None:
        self.console.print(f"\n[bold cyan]Step {step}/{max_steps}[/]  [dim]asking model[/]")

    @staticmethod
    def _args_summary(raw_arguments: str) -> str:
        try:
            value = json.loads(raw_arguments or "{}")
        except json.JSONDecodeError:
            return raw_arguments[:400]
        if not isinstance(value, dict):
            return str(value)[:400]
        rows = []
        for key, item in value.items():
            if key in {"content", "old_text", "new_text"}:
                text = str(item).replace("\n", "\\n")
                item = text[:160] + ("..." if len(text) > 160 else "")
            rows.append(f"{key}={item}")
        return ", ".join(rows)

    def tool_called(self, name: str, raw_arguments: str) -> None:
        self.console.print(f"[bold magenta]→ {name}[/] [dim]{self._args_summary(raw_arguments)}[/]")

    def _render_diff(self, diff: str) -> None:
        from rich.syntax import Syntax

        self.console.print(Syntax(diff, "diff", word_wrap=False, line_numbers=False))

    def tool_result(self, name: str, result: str) -> None:
        try:
            payload = json.loads(result)
        except json.JSONDecodeError:
            self.console.print(result)
            return

        if not payload.get("ok"):
            error = payload.get("error", "Tool failed")
            detail = payload.get("message")
            self.console.print(f"[bold red]✗ {name}[/] {error}")
            if detail:
                self.console.print(f"  [yellow]{detail}[/]")
            return

        value = payload.get("result")
        if name == "edit_file" and isinstance(value, dict):
            self.console.print(f"[green]✓ edited[/] {value.get('path', '')}")
            if value.get("diff"):
                self._render_diff(str(value["diff"]))
            return
        if name == "write_file" and isinstance(value, dict):
            verb = "created" if value.get("created") else "wrote"
            self.console.print(f"[green]✓ {verb}[/] {value.get('path', '')}")
            if value.get("diff"):
                self._render_diff(str(value["diff"]))
            return
        if name == "search_files" and isinstance(value, dict):
            matches = value.get("matches", [])
            self.console.print(f"[green]✓[/] {len(matches)} match(es) across {value.get('scanned_files', 0)} scanned file(s)")
            for match in matches[:12]:
                self.console.print(
                    f"  [cyan]{match.get('path')}:{match.get('line')}[/] {str(match.get('text', ''))[:180]}"
                )
            if value.get("truncated") or len(matches) > 12:
                self.console.print("  [dim]results truncated in terminal; full bounded result remains in agent context[/]")
            return
        if name == "run_command" and isinstance(value, dict):
            code = value.get("exit_code")
            style = "green" if code == 0 else "red"
            self.console.print(f"[{style}]✓ command exit={code}[/] {value.get('command', '')}")
            stdout = str(value.get("stdout") or "").strip()
            stderr = str(value.get("stderr") or "").strip()
            if stdout:
                self.console.print(stdout[-2500:])
            if stderr:
                self.console.print(f"[red]{stderr[-2500:]}[/]")
            if value.get("error"):
                self.console.print(f"[red]{value['error']}[/]")
            return
        if name == "read_file" and isinstance(value, dict):
            self.console.print(
                f"[green]✓ read[/] {value.get('path')} lines {value.get('start_line')}-{value.get('end_line')} / {value.get('total_lines')}"
            )
            return
        if name == "list_files" and isinstance(value, dict):
            self.console.print(f"[green]✓ listed[/] {len(value.get('entries', []))} entries")
            return
        self.console.print(f"[green]✓ {name}[/]")

    def warning(self, text: str) -> None:
        self.console.print(f"[bold yellow]⚠[/] {text}")

    def info(self, text: str) -> None:
        self.console.print(f"[dim]{text}[/]")

    def confirm(self, decision: SafetyDecision) -> bool:
        from rich.prompt import Confirm

        self.console.print(f"[bold yellow]Safety approval required[/]\n{decision.reason}\n[dim]{decision.action}[/]")
        if self.assume_yes:
            self.console.print("[yellow]Auto-approved because --yes was supplied.[/]")
            return True
        try:
            return Confirm.ask("Approve this action?", default=False, console=self.console)
        except (EOFError, KeyboardInterrupt):
            return False

    def final_report(self, report: FinalReport) -> None:
        from rich.panel import Panel
        from rich.table import Table

        self.console.print(Panel(report.final_text or "(empty response)", title="Final Answer", border_style="green"))
        state = report.state
        table = Table(title="Run Report", show_header=False, box=None, padding=(0, 2))
        changed = state.get("changed_files", [])
        table.add_row("Changed files", ", ".join(changed) if changed else "(none)")
        table.add_row("Validation", str(state.get("last_validation", "(none)")))
        table.add_row("LLM calls", str(state.get("llm_calls", 0)))
        table.add_row("Tool calls", str(state.get("tool_calls", 0)))
        table.add_row("API retries", str(state.get("api_retries", 0)))
        table.add_row("Context compactions", str(state.get("context_compactions", 0)))
        table.add_row(
            "Tokens",
            f"{state.get('prompt_tokens', 0)} input + {state.get('completion_tokens', 0)} output = {state.get('total_tokens', 0)}",
        )
        if state.get("estimated_cost_usd") is not None:
            table.add_row("Estimated cost", f"${state['estimated_cost_usd']:.6f}")
        table.add_row("LLM latency", f"{state.get('llm_duration_ms', 0) / 1000:.2f}s")
        table.add_row("Tool latency", f"{state.get('tool_duration_ms', 0) / 1000:.2f}s")
        table.add_row("Total duration", f"{state.get('duration_ms', 0) / 1000:.2f}s")
        if report.session_log:
            table.add_row("Session log", report.session_log)
        self.console.print(table)
