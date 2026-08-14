#!/usr/bin/env python3
"""Tests for the fan-out.

    python company/ops/test_assign.py

This is the only part of the company where two workers can hold the same
ticket, or where work can be held by something that has already died. The
collision and dead-lease cases below are the point of the file; the rest is
bookkeeping.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import assign

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def planned(issue=1, role="engineer", tier="capable", attempt=1, **kw):
    return {
        "issue": issue, "title": f"ticket {issue}", "role": role, "tier": tier,
        "dept": kw.get("dept", "dept:hq"), "risk": kw.get("risk", "risk:med"),
        "attempt": attempt,
    }


def holding(issue=1, role="engineer", minutes_ago=5):
    return {"issue": issue, "role": role, "since": NOW - timedelta(minutes=minutes_ago)}


# ---------- the lock ----------

def test_a_claimed_ticket_is_not_claimed_twice():
    """The collision case. Two workers on one ticket is the failure the claim
    label exists to prevent."""
    claims, _, deferred = assign.fan_out([planned(issue=7)], [holding(issue=7)], NOW)
    assert claims == []
    assert "already claimed" in deferred[0]["why"]


def test_an_unclaimed_ticket_is_claimed():
    claims, releases, _ = assign.fan_out([planned(issue=7)], [], NOW)
    assert [c["issue"] for c in claims] == [7]
    assert claims[0]["label"] == "claim:engineer"
    assert releases == []


def test_role_capacity_is_per_role_not_per_board():
    """The engineer is one Routine session — a second claim is guaranteed to
    expire unworked, so it is never issued."""
    plan = [planned(issue=1), planned(issue=2), planned(issue=3, role="reviewer")]
    claims, _, deferred = assign.fan_out(plan, [], NOW)
    assert [c["issue"] for c in claims] == [1, 3], claims
    assert "at capacity" in deferred[0]["why"]


def test_existing_claims_count_against_capacity():
    """Capacity is measured against what is really held, not against this cycle."""
    claims, _, deferred = assign.fan_out([planned(issue=2)], [holding(issue=1)], NOW)
    assert claims == [] and "at capacity (1/1)" in deferred[0]["why"]


def test_a_reviewer_may_hold_two():
    plan = [planned(issue=i, role="reviewer") for i in (1, 2, 3)]
    claims, _, _ = assign.fan_out(plan, [], NOW)
    assert len(claims) == 2


# ---------- the lease ----------

def test_a_dead_lease_is_released():
    """A Routine that hits its daily cap never wakes again. Without expiry its
    ticket is held forever by a worker that no longer exists."""
    _, releases, _ = assign.fan_out([], [holding(issue=7, minutes_ago=200)], NOW)
    assert [r["issue"] for r in releases] == [7]
    assert releases[0]["held_for_minutes"] == 200


def test_a_lease_shorter_than_one_wake_is_not_reaped():
    """Routines run hourly at best. Reaping at 30 minutes would kill work that is
    merely waiting for its next wake — so the default lease outlives one cycle."""
    _, releases, _ = assign.fan_out([], [holding(issue=7, minutes_ago=61)], NOW)
    assert releases == []


def test_expiry_frees_the_capacity_it_was_holding():
    claims, releases, _ = assign.fan_out(
        [planned(issue=2)], [holding(issue=1, minutes_ago=200)], NOW)
    assert [r["issue"] for r in releases] == [1]
    assert [c["issue"] for c in claims] == [2], "expired lease still blocked the role"


def test_an_expired_ticket_is_not_reclaimed_in_the_same_cycle():
    """Handing a ticket that just killed its worker straight back to an identical
    worker is how a tight failure loop starts."""
    claims, releases, deferred = assign.fan_out(
        [planned(issue=7)], [holding(issue=7, minutes_ago=200)], NOW)
    assert releases and claims == []
    assert "cooling off" in deferred[0]["why"]


def test_the_lease_boundary_is_inclusive():
    """Exactly at the deadline counts as expired — a lease that needs one more
    second is a lease nobody can reason about."""
    _, releases, _ = assign.fan_out(
        [], [holding(issue=7, minutes_ago=assign.LEASE_MINUTES)], NOW)
    assert len(releases) == 1


# ---------- the controller's brake ----------

def test_degrade_holds_capable_work():
    claims, _, deferred = assign.fan_out(
        [planned(issue=1, tier="capable")], [], NOW, allows_capable=False)
    assert claims == [] and "capable-tier" in deferred[0]["why"]


def test_degrade_does_not_switch_off_the_sre():
    """Turning off your only diagnostics to save money is how a degraded company
    becomes a dead one."""
    claims, _, _ = assign.fan_out(
        [planned(issue=1, role="sre", tier="mixed")], [], NOW, allows_capable=False)
    assert [c["issue"] for c in claims] == [1]


# ---------- the brief ----------

def test_the_brief_is_self_contained():
    """The worker is a fresh session that was not present for the heartbeat and
    cannot ask a follow-up question."""
    issue = {"number": 7, "body": "- [ ] the page renders\n- [ ] tests pass"}
    text = assign.brief(planned(issue=7), issue, NOW)
    assert "company/roles/" in text            # where its job description is
    assert "1 of 3" in text and "escalates to the owner" in text  # rope left, and what runs out
    assert "acceptance criteria" in text       # what done means
    assert "do not merge your own work" in text.lower()
    assert "claim:engineer" in text            # how to release the lock


def test_the_brief_names_the_lease_deadline_as_a_time():
    text = assign.brief(planned(), {"number": 1, "body": "- [ ] x"}, NOW)
    assert "13:30" in text, "worker cannot honour a deadline it was not told"


def test_a_ticket_with_no_criteria_is_sent_back_not_guessed_at():
    text = assign.brief(planned(), {"number": 1, "body": "please fix the thing"}, NOW)
    assert "routing bug" in text and "status:needs-spec" in text


def test_an_empty_checkbox_does_not_count_as_criteria():
    """The work-order template pre-fills an empty box; if that counted, every
    ticket would look specified."""
    text = assign.brief(planned(), {"number": 1, "body": "- [ ] "}, NOW)
    assert "routing bug" in text


def test_personal_data_departments_are_told_so_explicitly():
    for dept in ("dept:admissions", "dept:casewriter"):
        text = assign.brief(planned(dept=dept), {"number": 1, "body": "- [ ] x"}, NOW)
        assert "personal data" in text and "do not work around it" in text


def test_high_risk_work_is_told_not_to_act_alone():
    text = assign.brief(planned(risk="risk:high"), {"number": 1, "body": "- [ ] x"}, NOW)
    assert "owner's approval" in text


# ---------- reporting ----------

def test_released_leases_are_reported_loudly():
    """A run of releases is the shape of a broken worker, not a broken ticket —
    it has to be visible on the shift report."""
    _, releases, _ = assign.fan_out([], [holding(issue=7, minutes_ago=200)], NOW)
    text = assign.render([], releases, [])
    assert "did not finish" in text and "#7" in text


def test_a_quiet_fan_out_renders_nothing():
    """No claims, no releases, nothing deferred — do not pad the shift report."""
    assert assign.render([], [], []) == ""


def test_every_claimable_role_has_a_real_label():
    """The claim label is the lock. A role whose label was never created would
    fail to claim at write time, at 3am, on a board nobody is watching."""
    import labels
    from board import STAGE_OWNER

    defined = {name for name, _, _ in labels.LABELS}
    for role, _ in STAGE_OWNER.values():
        assert assign.claim_label(role) in defined, role
    for role in assign.ROLE_CAPACITY:
        assert assign.claim_label(role) in defined, role


def test_claimed_role_reads_the_lock_off_the_labels():
    assert assign.claimed_role({"status:ready", "claim:engineer"}) == "engineer"
    assert assign.claimed_role({"status:ready"}) is None


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
