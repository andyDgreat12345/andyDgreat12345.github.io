#!/usr/bin/env python3
"""Tests for stall detection.

    python company/ops/test_stall.py

Every acceptance criterion on #9 is a case here. The ones that matter most are
the negatives: an alarm that fires when the company is behaving correctly gets
muted within a week, and a muted alarm is worse than none.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import stall

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def ticket(number, stage, hours_ago, labels=None, title="a ticket"):
    return {
        "number": number,
        "title": title,
        "stage": stage,
        "labels": labels if labels is not None else ([stage] if stage else []),
        "moved_at": NOW - timedelta(hours=hours_ago),
    }


def test_stalls_when_nothing_has_moved():
    v = stall.assess([ticket(1, "status:ready", 9), ticket(2, "status:inbox", 30)], NOW, 6)
    assert v["stalled"], v
    assert [t["number"] for t in v["stuck"]] == [2, 1], "oldest first"


def test_one_recent_move_is_enough():
    v = stall.assess([ticket(1, "status:ready", 9), ticket(2, "status:inbox", 1)], NOW, 6)
    assert not v["stalled"], v


def test_empty_board_is_not_a_stall():
    v = stall.assess([], NOW, 6)
    assert not v["stalled"]
    assert "empty" in v["reason"]


def test_paused_company_is_not_a_stall():
    """Deliberate idleness is not failure — otherwise pausing the company would
    page you about the company being paused."""
    v = stall.assess([ticket(1, "status:ready", 99)], NOW, 6, paused=True)
    assert not v["stalled"]
    assert "paused" in v["reason"]


def test_needs_human_is_not_a_stall():
    """The company waiting on its owner is the system working. Alarming here
    would mean every unanswered question becomes a second unanswered question."""
    v = stall.assess([ticket(1, None, 99, labels=["dept:hq", "needs:human"])], NOW, 6)
    assert not v["stalled"], v
    assert "waiting on the owner" in v["reason"]


def test_blocked_is_not_a_stall():
    v = stall.assess([ticket(1, "status:blocked", 99, labels=["status:blocked"])], NOW, 6)
    assert not v["stalled"], v


def test_a_mix_still_stalls_on_the_unexcused_one():
    v = stall.assess([
        ticket(1, None, 99, labels=["needs:human"]),
        ticket(2, "status:ready", 99, labels=["status:ready"]),
    ], NOW, 6)
    assert v["stalled"], v
    assert [t["number"] for t in v["stuck"]] == [2]


def test_threshold_is_respected():
    board = [ticket(1, "status:ready", 5)]
    assert not stall.assess(board, NOW, 6)["stalled"]
    assert stall.assess(board, NOW, 4)["stalled"]


def test_report_names_the_stuck_tickets_and_stages():
    """The alert has to be actionable without opening the board."""
    v = stall.assess([ticket(7, "status:ready", 9, title="Wire up the engineer")], NOW, 6)
    body = stall.render(v, NOW, 6)
    assert "#7" in body
    assert "status:ready" in body
    assert "Wire up the engineer" in body
    assert "9h" in body


def test_stage_is_read_off_the_labels():
    assert stall.stage_of({"labels": [{"name": "dept:site"}, {"name": "status:verify"}]}) == "status:verify"
    assert stall.stage_of({"labels": [{"name": "dept:site"}]}) is None


def test_excused_labels_are_real_labels():
    """A typo here would silently disable the exemptions, so assert they exist
    in the vocabulary the rest of the company uses."""
    import labels as label_defs
    defined = {name for name, _, _ in label_defs.LABELS}
    assert stall.EXCUSED <= defined, stall.EXCUSED - defined


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  ok    {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
