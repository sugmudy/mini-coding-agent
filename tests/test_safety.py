from __future__ import annotations

import pytest

from safety import RiskLevel, SafetyPolicy
from tools.file_tools import FileTools, WorkspaceError
from tools.shell_tool import CommandPolicyError, ShellTool


def test_command_safety_classification():
    policy = SafetyPolicy("balanced")
    assert policy.classify_command("git status").level is RiskLevel.SAFE
    assert policy.classify_command("pip install requests").level is RiskLevel.REVIEW
    assert policy.classify_command("git reset --hard HEAD").level is RiskLevel.BLOCKED
    assert policy.classify_command("git push --force origin main").level is RiskLevel.BLOCKED


@pytest.mark.parametrize(
    "command",
    [
        "git -C . push origin main",
        "git -c user.name=test commit -m test",
        "git reset --hard=HEAD",
        "git -c alias.ship=push ship origin main",
        "git -calias.ship=push ship origin main",
    ],
)
def test_git_option_prefixes_and_flag_values_cannot_bypass_blocked_policy(command):
    assert SafetyPolicy("permissive").classify_command(command).level is RiskLevel.BLOCKED


@pytest.mark.parametrize(
    "command",
    [
        "python -m pip install sampleproject",
        "python -m pip --disable-pip-version-check install sampleproject",
        "python3 -m pip uninstall sampleproject",
        "pip --disable-pip-version-check install sampleproject",
        "npm i",
        "npm --silent install package-name",
        "npm add package-name",
        "npx some-package",
    ],
)
def test_dependency_command_aliases_require_review(command):
    assert SafetyPolicy("balanced").classify_command(command).level is RiskLevel.REVIEW


def test_unknown_git_subcommand_fails_closed_to_review():
    assert SafetyPolicy("balanced").classify_command("git custom-helper").level is RiskLevel.REVIEW


def test_blocked_git_action_cannot_be_overridden_by_permissive_mode(tmp_path):
    shell = ShellTool(tmp_path, safety_policy=SafetyPolicy("permissive"), approval_callback=lambda _: True)
    with pytest.raises(CommandPolicyError, match="SafetyPolicy denied"):
        shell.run_command("git reset --hard HEAD")


def test_review_action_requires_approval_in_balanced_mode():
    policy = SafetyPolicy("balanced")
    decision = policy.classify_command("pip install requests")
    assert policy.authorize(decision, lambda _: False) is False
    assert policy.authorize(decision, lambda _: True) is True
    assert SafetyPolicy("strict").authorize(decision, lambda _: True) is False
    assert SafetyPolicy("permissive").authorize(decision, None) is True


def test_large_full_file_rewrite_requires_approval(tmp_path):
    path = tmp_path / "large.py"
    path.write_text("\n".join(f"line_{i} = {i}" for i in range(200)) + "\n", encoding="utf-8")
    denied = FileTools(
        tmp_path,
        safety_policy=SafetyPolicy("balanced"),
        approval_callback=lambda _: False,
    )
    with pytest.raises(WorkspaceError, match="SafetyPolicy denied"):
        denied.write_file("large.py", "x = 1\n")
    assert "line_199" in path.read_text(encoding="utf-8")

    approved = FileTools(
        tmp_path,
        safety_policy=SafetyPolicy("balanced"),
        approval_callback=lambda _: True,
    )
    result = approved.write_file("large.py", "x = 1\n")
    assert result["safety"]["level"] == "review"
    assert result["safety"]["approved"] is True
    assert path.read_text(encoding="utf-8") == "x = 1\n"
