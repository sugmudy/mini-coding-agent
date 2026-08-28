from __future__ import annotations

from main import build_parser
from version import __version__


def test_v3_cli_options_exist():
    parser = build_parser()
    args = parser.parse_args(["--safety", "strict", "--yes", "--no-color", "task"])
    assert args.safety == "strict"
    assert args.yes is True
    assert args.no_color is True
    assert args.task == "task"


def test_version_is_v3():
    assert __version__.startswith("0.3.")
