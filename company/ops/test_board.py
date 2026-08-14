#!/usr/bin/env python3
"""Tests for the routing logic. Stdlib only, no server needed.

    python company/ops/test_board.py

board.py decides who works on what, and both the Tier 0 dispatcher and the
Temporal workflow import it, so a mistake here is a mistake everywhere. The
Temporal test covers orchestration; this covers the decisions.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import board
import labels


def issue(number, names, body="do a thing", title="t"):
    return {"number": number, "title": title, "body": body,
            "labels": [{"name": n} for n in names]}


def test_routes_each_stage_to_its_owner():
    plan, _ = board.build_plan([
        issue(1, ["dept:site", "status:ready"]),
        issue(2, ["dept:hq", "status:needs-spec"]),
        issue(3, ["dept:site", "status:verify"]),
    ], in_review=0)
    assert [p["role"] for p in plan] == ["engineer", "analyst", "sre"], plan
    assert [p["tier"] for p in plan] == ["capable", "capable", "mixed"], plan


def test_never_touches_needs_human():
    """The escalation flag is the owner's; agents must not act on it."""
    plan, skipped = board.build_plan(
        [issue(1, ["dept:market", "status:ready", "needs:human"])], in_review=0)
    assert plan == []
    assert "owner" in skipped[0]["why"]


def test_three_strikes_stops_retrying():
    """The guard between a broken ticket and an overnight retry storm."""
    plan, skipped = board.build_plan(
        [issue(1, ["dept:market", "status:ready", f"attempt:{board.MAX_ATTEMPTS}"])],
        in_review=0)
    assert plan == []
    assert "escalating" in skipped[0]["why"]


def test_wip_limit_blocks_engineers_only():
    """A queue of unreviewed PRs is worse than an idle engineer — but the limit
    must not stall the stages that would drain it."""
    plan, skipped = board.build_plan([
        issue(1, ["dept:site", "status:ready"]),
        issue(2, ["dept:hq", "status:needs-spec"]),
        issue(3, ["dept:site", "status:verify"]),
    ], in_review=board.WIP_LIMIT)
    assert [p["role"] for p in plan] == ["analyst", "sre"], plan
    assert "WIP limit" in skipped[0]["why"]


def test_triage_never_guesses_a_department():
    """Classifying is allowed; guessing is not."""
    add, remove, note = board.triage(issue(1, ["status:inbox"]))
    assert add == [] and remove == []
    assert "no dept label" in note


def test_triage_always_moves_a_ticket_out_of_inbox():
    """The bug this test exists for: triage used to classify a ticket and leave
    it in Inbox, which no role owns — so it sat there forever."""
    for body in ["", "a real description", "- [ ] check this\n"]:
        add, remove, _ = board.triage(issue(1, ["dept:site", "status:inbox"], body=body))
        assert remove == ["status:inbox"], f"body={body!r} left the ticket in inbox"
        assert set(add) & set(board.STAGE_OWNER), f"body={body!r} gave it no next stage"


def test_triage_fills_defaults_and_picks_the_next_stage():
    add, remove, note = board.triage(issue(1, ["dept:site", "status:inbox"], body=""))
    assert set(add) == {"size:m", "risk:med", "status:needs-spec"}, add
    assert "empty body" in note

    # A description without checkable criteria still needs the analyst.
    add, _, note = board.triage(issue(2, ["dept:site", "status:inbox"], body="make it nice"))
    assert "status:needs-spec" in add, add
    assert "no acceptance criteria" in note

    # One that already states how it will be checked can skip straight to build.
    add, _, note = board.triage(
        issue(3, ["dept:site", "status:inbox"], body="Do X.\n\n- [ ] page lists tickets\n"))
    assert "status:ready" in add, add
    assert "straight to build" in note


def test_empty_checkbox_does_not_count_as_criteria():
    """The work-order template pre-fills a bare `- [ ]`. If that counted, every
    ticket would look specified and skip the analyst entirely."""
    assert not board.has_acceptance_criteria("Do the thing.\n\n- [ ]\n")
    assert not board.has_acceptance_criteria("Do the thing.\n\n- [ ]   \n")
    assert board.has_acceptance_criteria("- [ ] something checkable")
    assert board.has_acceptance_criteria("- [x] already done")


def test_triage_never_drags_a_ticket_backwards():
    """A ticket already mid-flight keeps its stage; triage only classifies it."""
    add, remove, note = board.triage(
        issue(1, ["dept:site", "status:inbox", "status:building"], body="x"))
    assert remove == [], remove
    assert not (set(add) & set(board.STAGE_OWNER)), add


def test_blocked_tickets_are_skipped_not_routed():
    plan, skipped = board.build_plan(
        [issue(1, ["dept:site", "status:ready", "status:blocked"])], in_review=0)
    assert plan == []
    assert skipped[0]["why"] == "blocked"


def test_render_always_says_something():
    """A silent heartbeat is indistinguishable from a dead one."""
    assert "PAUSED" in board.render([], [], [], paused=True)
    assert "Board is clear" in board.render([], [], [], paused=False)


def test_label_vocabulary_covers_every_routing_key():
    """labels.py and board.py must agree: the dispatcher reads nothing but
    labels, so a key it routes on that no one can apply is dead code."""
    defined = {name for name, _, _ in labels.LABELS}
    routed = board.DEPTS | board.SIZES | board.RISKS | board.STAGES | {"needs:human"}
    assert not routed - defined, f"board.py routes on labels nobody creates: {routed - defined}"


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
        except Exception as exc:  # noqa: BLE001
            # An unexpected exception is a failure, not a reason to abort the
            # run. Aborting hides every test after the first broken one, which
            # is exactly when you most want the full picture.
            failed += 1
            print(f"  ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
