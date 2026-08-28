from __future__ import annotations

from loop_detector import LoopDetector


def test_blocks_identical_repetition_without_state_change():
    detector = LoopDetector(repeat_limit=3)
    args = '{"path":"a.py"}'
    assert detector.check("read_file", args) is None
    detector.record("read_file", args, succeeded=True)
    assert detector.check("read_file", args) is None
    detector.record("read_file", args, succeeded=True)
    warning = detector.check("read_file", args)
    assert warning is not None
    assert "Repeated tool call" in warning


def test_successful_edit_allows_re_read_in_new_generation():
    detector = LoopDetector(repeat_limit=3)
    read_args = '{"path":"a.py"}'
    for _ in range(2):
        detector.record("read_file", read_args, succeeded=True)
    detector.record(
        "edit_file",
        '{"path":"a.py","old_text":"x","new_text":"y"}',
        succeeded=True,
    )
    assert detector.check("read_file", read_args) is None


def test_detects_short_periodic_cycle():
    detector = LoopDetector(repeat_limit=3)
    sequence = [
        ("read_file", '{"path":"a.py"}'),
        ("search_files", '{"query":"foo"}'),
    ] * 2
    for name, args in sequence:
        assert detector.check(name, args) is None
        detector.record(name, args, succeeded=True)
    # Fifth call alone is not enough; after recording it, the sixth completes ABABAB.
    name, args = "read_file", '{"path":"a.py"}'
    assert detector.check(name, args) is None
    detector.record(name, args, succeeded=True)
    warning = detector.check("search_files", '{"query":"foo"}')
    assert warning is not None
    assert "cycle" in warning.lower()
