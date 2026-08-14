#!/usr/bin/env python3
"""Tests for the Tier 0 dispatcher's wiring.

    python company/ops/test_dispatch.py

board.py and assign.py are tested as pure logic elsewhere. What is tested here
is that dispatch.py actually *calls* them and actually writes the result —
because the bug this file exists for was not a logic bug at all. The free-tier
heartbeat planned work correctly, printed it correctly, and never claimed it.
Every ticket sat at `status:ready` looking healthy while the engineer waited on
a `claim:engineer` label that nothing in the free path produced.

Pure functions cannot catch that. Only the wiring can.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dispatch


class FakeGitHub:
    """Records what the dispatcher would have written."""

    def __init__(self, issues, prs_in_review=0, claim_since=None):
        self._issues = issues
        self._prs = [{"draft": False}] * prs_in_review
        self._claim_since = claim_since
        self.added: list[tuple] = []
        self.removed: list[tuple] = []
        self.comments: list[tuple] = []

    def issues(self):
        return self._issues

    def open_prs(self):
        return self._prs

    def variable(self, name):
        return None

    def add_labels(self, number, labels):
        self.added.append((number, tuple(labels)))

    def remove_label(self, number, label):
        self.removed.append((number, label))

    def comment(self, number, body):
        self.comments.append((number, body))

    def claim_since(self, number, label):
        return self._claim_since

    def find_or_create_shift_report(self):
        return 99


def ticket(number, labels, body="- [ ] it works", created="2026-08-14T12:00:00Z"):
    return {"number": number, "title": f"ticket {number}", "body": body,
            "created_at": created,
            "labels": [{"name": n} for n in labels]}


def run(gh, apply=True, **env):
    """Run the dispatcher against a fake client, returning it for inspection."""
    real = dispatch.GitHub
    dispatch.GitHub = lambda *a, **k: gh
    argv, environ = sys.argv, dict(os.environ)
    sys.argv = ["dispatch.py", "--repo", "o/r"] + (["--apply"] if apply else [])
    os.environ["GITHUB_TOKEN"] = "x"
    os.environ["COMPANY_PAUSED"] = env.pop("paused", "0")
    os.environ["COMPANY_CLAIMS_WAKE_WORKERS"] = env.pop("wake", "yes")
    os.environ.pop("GITHUB_OUTPUT", None)
    try:
        # The report is asserted on through the recorded comment; printing ten
        # of them would bury the test results it sits between.
        with contextlib.redirect_stdout(io.StringIO()):
            code = dispatch.main()
    finally:
        dispatch.GitHub = real
        sys.argv = argv
        os.environ.clear()
        os.environ.update(environ)
    return code, gh


def test_a_ready_ticket_is_actually_claimed():
    """THE regression test. Planning is not claiming, and for one release the
    free tier did the first and not the second."""
    gh = FakeGitHub([ticket(12, ["dept:site", "status:ready"])])
    _, gh = run(gh)
    assert (12, ("claim:engineer",)) in gh.added, gh.added


def test_the_work_order_is_posted_before_the_claim():
    """The label is what wakes the worker, so taking it before the instructions
    exist is a race the worker loses — it would arrive to a claimed ticket with
    nothing telling it what to do."""
    gh = FakeGitHub([ticket(12, ["dept:site", "status:ready"])])
    _, gh = run(gh)
    order = [b for n, b in gh.comments if n == 12]
    assert order and "Work order" in order[0]


def test_a_paused_company_claims_nothing():
    gh = FakeGitHub([ticket(12, ["dept:site", "status:ready"])])
    _, gh = run(gh, paused="1")
    assert gh.added == [] and not any(n == 12 for n, _ in gh.comments)


def test_a_dry_run_writes_nothing():
    """--apply is the difference between deciding and acting. A dry run that
    quietly acted would be the worst possible bug in this file."""
    gh = FakeGitHub([ticket(12, ["dept:site", "status:ready"])])
    _, gh = run(gh, apply=False)
    assert gh.added == [] and gh.removed == [] and gh.comments == []


def test_an_inbox_ticket_is_triaged_and_claimed_in_one_cycle():
    """The local write-back: a new ticket does not wait a full cycle to be
    looked at twice."""
    gh = FakeGitHub([ticket(20, ["dept:site", "status:inbox"])])
    _, gh = run(gh)
    # Flattened, not keyed by issue: triage and the claim are two separate label
    # writes on the same ticket, and a dict would silently keep only the last.
    written = {label for _, labels in gh.added for label in labels}
    assert "status:ready" in written, gh.added
    assert "claim:engineer" in written, gh.added
    assert (20, "status:inbox") in gh.removed


def test_a_dead_lease_is_reaped_and_charged():
    gh = FakeGitHub(
        [ticket(12, ["dept:site", "status:ready", "claim:engineer"])],
        claim_since="2020-01-01T00:00:00Z",
    )
    _, gh = run(gh)
    assert (12, "claim:engineer") in gh.removed
    assert (12, ("attempt:1",)) in gh.added


def test_an_unclaimable_stage_is_not_claimed_for():
    """No SRE is hired, so a ticket at verify waits on the owner rather than
    burning its retry budget on a role that does not exist."""
    gh = FakeGitHub([ticket(12, ["dept:site", "status:verify"])])
    _, gh = run(gh)
    assert not any(str(ls).startswith("('claim:") for _, ls in gh.added), gh.added


def test_the_report_warns_when_claims_cannot_wake_a_worker():
    """A claim applied with GITHUB_TOKEN does not trigger `issues.labeled`. The
    label lands, the board looks busy, and nothing starts — the quietest failure
    this company has."""
    gh = FakeGitHub([ticket(12, ["dept:site", "status:ready"])])
    _, gh = run(gh, wake="no")
    report = [b for n, b in gh.comments if n == 99][0]
    assert "no worker will wake" in report
    assert "PAT_TOKEN" in report


def test_no_warning_when_the_token_can_wake_workers():
    """A warning that appears on every report stops being read."""
    gh = FakeGitHub([ticket(12, ["dept:site", "status:ready"])])
    _, gh = run(gh, wake="yes")
    report = [b for n, b in gh.comments if n == 99][0]
    assert "no worker will wake" not in report


def test_the_shift_report_is_always_written():
    """Including on a cycle that did nothing — a silent heartbeat is
    indistinguishable from a dead one."""
    gh = FakeGitHub([])
    _, gh = run(gh)
    assert any(n == 99 for n, _ in gh.comments)


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
            failed += 1
            print(f"  ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
