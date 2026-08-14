#!/usr/bin/env python3
"""Tests for the worker boundary: the prompt in, the lock release out.

    python company/ops/test_worker.py

These two functions bracket an autonomous agent with write access to the
repository. The prompt is the only thing that tells it what it may not do, and
the handoff is the only thing that releases the company's lock when it stops —
including when it stops by crashing.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import handoff
import work_order

REPO = "andyDgreat12345/andyDgreat12345.github.io"


def issue(number=12, title="do a thing", body="- [ ] it works", labels=()):
    return {"number": number, "title": title, "body": body,
            "labels": [{"name": n} for n in labels]}


# ---------- the prompt ----------

def test_the_prompt_carries_the_work_order():
    text = work_order.compose(issue(), "## Work order\n\nBuild the thing.", REPO)
    assert "Build the thing." in text
    assert "#12" in text and "do a thing" in text


def test_the_prompt_points_at_the_role_card():
    """The work order is the assignment; the role card is the job."""
    assert "company/roles/02-engineer.md" in work_order.compose(issue(), "x", REPO)


def test_the_prompt_forbids_self_merge():
    """Separation of duties is the design. Branch protection enforces it, but an
    agent that never tries wastes no run finding out."""
    text = work_order.compose(issue(), "x", REPO).lower()
    assert "never merge your own pull request" in text
    assert "draft" in text


def test_the_prompt_forbids_editing_its_own_gates():
    text = work_order.compose(issue(), "x", REPO)
    assert ".github/workflows/" in text


def test_the_prompt_scopes_to_one_ticket():
    text = work_order.compose(issue(number=12), "x", REPO)
    assert "issue #12 and nothing else" in text


def test_a_missing_work_order_stops_rather_than_guesses():
    """The fan-out writes the order before applying the claim, so a missing one
    is a dispatcher bug. Inventing the task is the wrong recovery."""
    text = work_order.compose(issue(), None, REPO)
    assert "needs:human" in text and "not an invitation" in text
    assert "Do not change any other file" in text


def test_high_risk_is_named_in_the_prompt():
    text = work_order.compose(issue(labels=["risk:high"]), "x", REPO)
    assert "risk:high" in text and "unilaterally" in text


def test_personal_data_departments_are_warned_about_leakage():
    """The bulk-tier refusal is in models.py; this is the other half — an agent
    that pastes a real record into a PR body has leaked it regardless of tier."""
    for dept in ("dept:admissions", "dept:casewriter"):
        text = work_order.compose(issue(labels=[dept]), "x", REPO)
        assert "personal data" in text
        assert "invent one" in text


def test_a_public_department_gets_no_personal_data_warning():
    """Warnings that appear on every ticket stop being read."""
    text = work_order.compose(issue(labels=["dept:site"]), "x", REPO)
    assert "invent one" not in text


def test_the_newest_work_order_wins():
    """A retried ticket has two. The stale one describes a reaped lease."""
    comments = [
        {"body": "## Work order\n\nfirst"},
        {"body": "unrelated chatter"},
        {"body": "## Work order\n\nsecond"},
    ]
    assert "second" in work_order.latest_work_order(comments)


def test_chatter_is_not_mistaken_for_a_work_order():
    assert work_order.latest_work_order([{"body": "looks like a ## Work order"}]) is None
    assert work_order.latest_work_order([]) is None


# ---------- the lock release ----------

def test_a_pr_advances_the_ticket_and_frees_the_lock():
    add, remove, note = handoff.decide(issue(labels=["status:ready", "claim:engineer"]),
                                       "engineer", pr_number=42)
    assert "status:verify" in add
    assert "claim:engineer" in remove and "status:ready" in remove
    assert "#42" in note


def test_a_successful_attempt_costs_nothing():
    """The attempt counter is the retry budget. Charging a success would make a
    later failure inherit a cost it did not incur."""
    add, remove, _ = handoff.decide(issue(labels=["attempt:1", "claim:engineer"]),
                                    "engineer", pr_number=42)
    assert not any(l.startswith("attempt:") for l in add + remove)


def test_no_pr_is_a_failed_attempt_however_it_ended():
    """Crashed, refused, or quietly did nothing — ORG.md says a run that produced
    no artifact did not happen."""
    add, remove, note = handoff.decide(issue(labels=["claim:engineer"]),
                                       "engineer", pr_number=None)
    assert "attempt:1" in add
    assert "claim:engineer" in remove
    assert "no pull request" in note.lower()


def test_the_attempt_counter_advances_rather_than_duplicating():
    add, remove, _ = handoff.decide(issue(labels=["attempt:1", "claim:engineer"]),
                                    "engineer", pr_number=None)
    assert "attempt:2" in add and "attempt:1" in remove


def test_the_third_failure_escalates_and_stops():
    """Infinite retries are how you wake up to a bill and no progress."""
    add, _, note = handoff.decide(issue(labels=["attempt:2", "claim:engineer"]),
                                  "engineer", pr_number=None)
    assert "attempt:3" in add and "needs:human" in add
    assert "will not be picked up again" in note


def test_success_is_judged_by_artifact_not_by_assertion():
    """The same ticket, the same labels — only the PR differs. Nothing in decide()
    consults what the agent said about itself."""
    t = issue(labels=["status:ready", "claim:engineer"])
    won, _, _ = handoff.decide(t, "engineer", pr_number=1)
    lost, _, _ = handoff.decide(t, "engineer", pr_number=None)
    assert "status:verify" in won and "status:verify" not in lost


def test_the_release_names_the_role_it_released():
    for role in ("engineer", "reviewer", "sre"):
        _, remove, _ = handoff.decide(issue(), role, pr_number=7)
        assert f"claim:{role}" in remove


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
