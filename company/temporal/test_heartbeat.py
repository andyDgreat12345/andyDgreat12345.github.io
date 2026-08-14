#!/usr/bin/env python3
"""End-to-end test of the heartbeat workflow against a real Temporal server.

Runs the actual workflow code with stubbed activities, so it exercises the thing
that matters — orchestration, determinism, and the retry/resume behaviour — while
touching no GitHub API. Start a dev server first:

    temporal server start-dev --headless

Then:

    python company/temporal/test_heartbeat.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

from temporalio import activity
from temporalio.client import Client, WorkflowFailureError
from temporalio.worker import Worker

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from activities import BoardSnapshot, ClaimWrite, LabelWrite  # noqa: E402
from workflows import HeartbeatWorkflow  # noqa: E402

import board  # noqa: E402  — on sys.path via activities

ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")

# Recorded by the stubs so assertions can check what the workflow actually did,
# not merely what it returned.
CALLS: dict[str, list] = {"labels": [], "reports": [], "claims": [], "releases": []}
FAIL_ONCE: dict[str, bool] = {}

# What the board says is already claimed, as read_board would report it. Set per
# test; `since` is an ISO string because that is what crosses the wire.
HELD: list[dict] = []


def _recent_iso() -> str:
    """A claim taken a minute ago — inside any sane lease."""
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()


def issue(number, labels, body="do a thing", title="t"):
    return {"number": number, "title": title, "body": body,
            "labels": [{"name": n} for n in labels]}


BOARD = [
    issue(1, ["dept:site", "status:ready"]),
    issue(2, ["dept:hq", "status:needs-spec"]),
    issue(3, ["dept:market", "status:ready", "needs:human"]),
    issue(4, ["dept:market", "status:ready", "attempt:3"]),
    issue(5, ["dept:site", "status:verify"]),
    issue(6, ["dept:casewriter", "status:inbox"], body=""),      # → needs-spec
    issue(7, ["status:inbox"]),                                   # no dept → note
    issue(8, ["dept:site", "status:inbox"],
          body="Add the page.\n\n- [ ] lists open tickets by stage\n"),  # → ready
]


def stubs(paused: bool = False):
    @activity.defn(name="check_kill_switch")
    async def check_kill_switch() -> bool:
        return paused

    @activity.defn(name="read_board")
    async def read_board() -> BoardSnapshot:
        import copy
        return BoardSnapshot(issues=copy.deepcopy(BOARD), prs_in_review=0,
                             held=copy.deepcopy(HELD))

    @activity.defn(name="read_spend")
    async def read_spend() -> bool:
        return not FAIL_ONCE.get("degraded", False)

    @activity.defn(name="place_claim")
    async def place_claim(write: ClaimWrite) -> None:
        CALLS["claims"].append((write.issue, write.label, write.brief))

    @activity.defn(name="release_claim")
    async def release_claim(write: LabelWrite) -> None:
        CALLS["releases"].append((write.issue, tuple(write.labels), tuple(write.remove)))

    @activity.defn(name="apply_labels")
    async def apply_labels(write: LabelWrite) -> None:
        CALLS["labels"].append((write.issue, tuple(write.labels), tuple(write.remove)))

    @activity.defn(name="post_report")
    async def post_report(body: str) -> int:
        # Fail the first attempt once, to prove the retry policy resumes the run
        # at the report step rather than restarting the whole heartbeat.
        if FAIL_ONCE.get("post_report"):
            FAIL_ONCE["post_report"] = False
            raise RuntimeError("simulated GitHub 502")
        CALLS["reports"].append(body)
        return 99

    @activity.defn(name="today")
    async def today() -> str:
        return "2026-08-13"

    return [check_kill_switch, read_board, read_spend, apply_labels,
            place_claim, release_claim, post_report, today]


async def run_once(client: Client, *, paused: bool = False, apply: bool = True, timeout=45):
    """Run one heartbeat, with a deadline.

    The deadline is not belt-and-braces. A workflow task that raises — a bad
    deserialization, a non-deterministic call — is retried by Temporal forever by
    design, so the failure mode is an indefinite hang rather than an exception.
    Without a timeout here a broken workflow looks like a slow one.
    """
    queue = f"test-{uuid.uuid4()}"
    async with Worker(client, task_queue=queue,
                      workflows=[HeartbeatWorkflow], activities=stubs(paused)):
        handle = await client.start_workflow(
            HeartbeatWorkflow.run, apply,
            id=f"heartbeat-test-{uuid.uuid4()}", task_queue=queue,
        )
        try:
            return await asyncio.wait_for(handle.result(), timeout=timeout)
        except asyncio.TimeoutError:
            raise AssertionError(
                f"workflow did not finish in {timeout}s — almost certainly a "
                f"workflow task failure retrying; check the worker log above"
            ) from None


async def main() -> int:
    client = await Client.connect(ADDRESS)
    print(f"connected to {ADDRESS}\n")

    # --- 1. Normal run -----------------------------------------------------
    for bucket in CALLS.values():
        bucket.clear()
    result = await run_once(client)

    routed = [(p["issue"], p["role"]) for p in result.plan]
    # #6 and #8 are triaged out of Inbox and picked up in the SAME cycle — the
    # workflow reflects each label write back onto its local copy of the board
    # before planning, so a new ticket is not left waiting 15 minutes to be
    # looked at. That is the point of the local write-back, not an accident.
    assert routed == [
        (1, "engineer"), (2, "analyst"), (5, "sre"), (6, "analyst"), (8, "engineer"),
    ], routed
    assert not result.paused
    skipped = {s["issue"] for s in result.skipped}
    assert skipped == {3, 4}, skipped

    # Every triaged ticket must LEAVE inbox — the stall bug this guards against.
    for number, added, removed in CALLS["labels"]:
        assert removed == ("status:inbox",), (number, removed)
        assert set(added) & set(board.STAGE_OWNER), (number, added)

    # #6 has an empty body → spec. #8 states acceptance criteria → straight to build.
    by_issue = {c[0]: c[1] for c in CALLS["labels"]}
    assert "status:needs-spec" in by_issue[6], by_issue[6]
    assert "status:ready" in by_issue[8], by_issue[8]
    # #7 has no department, so it is left exactly as it is for a human.
    assert 7 not in by_issue, "must not guess a department"
    assert any("no dept label" in t for t in result.triaged)
    assert result.reported_on == 99
    assert len(CALLS["reports"]) == 1

    # Fan-out. Five tickets were routed but only three claimed: the engineer and
    # the analyst each hold one, because each is a single session that can work
    # one ticket per wake. Claiming all five would produce three expired leases
    # and a board that looked busy the whole time.
    claimed = sorted((c[0], c[1]) for c in CALLS["claims"])
    assert claimed == [(1, "claim:engineer"), (2, "claim:analyst"), (5, "claim:sre")], claimed
    deferred = {d["issue"]: d["why"] for d in result.deferred}
    assert "at capacity" in deferred[6] and "at capacity" in deferred[8], deferred
    # Every claim carries a brief, and the brief is self-contained — the worker
    # arrives cold and cannot ask a follow-up question.
    for _, _, text in CALLS["claims"]:
        assert "Work order" in text and "company/roles/" in text and "Lease expires" in text
    print("1. normal run — routed", routed, "| claimed", [c[0] for c in claimed],
          "| skipped", sorted(skipped))

    # --- 2. Kill switch ----------------------------------------------------
    for bucket in CALLS.values():
        bucket.clear()
    result = await run_once(client, paused=True)
    assert result.paused and result.plan == [] and CALLS["labels"] == []
    assert "PAUSED" in result.report
    assert len(CALLS["reports"]) == 1, "a paused heartbeat must still report"
    print("2. kill switch — started nothing, still reported")

    # --- 3. Durability: an activity fails, the run resumes ------------------
    for bucket in CALLS.values():
        bucket.clear()
    FAIL_ONCE["post_report"] = True
    result = await run_once(client)
    assert result.reported_on == 99, "retry should have succeeded"
    assert len(CALLS["reports"]) == 1, "report posted exactly once despite the failure"
    # The triage writes happened once, not twice — the run resumed at the
    # failed step instead of replaying the side effects before it.
    assert len(CALLS["labels"]) == 2, CALLS["labels"]
    print("3. durability — post_report failed once, resumed, no work repeated")

    # --- 4. WIP limit / dry run --------------------------------------------
    for bucket in CALLS.values():
        bucket.clear()
    result = await run_once(client, apply=False)
    assert CALLS["labels"] == [] and CALLS["reports"] == [], "apply=False must not write"
    assert result.plan, "a dry run still produces a plan"
    assert CALLS["claims"] == [] and CALLS["releases"] == []
    assert result.claims, "a dry run still decides who would be claimed"
    print("4. dry run — decided without writing anything")

    # --- 5. A dead lease is reaped, and costs an attempt --------------------
    for bucket in CALLS.values():
        bucket.clear()
    HELD[:] = [{"issue": 1, "role": "engineer",
                "since": "2020-01-01T00:00:00Z"}]        # ancient — worker is gone
    result = await run_once(client)
    released = {r[0]: (r[1], r[2]) for r in CALLS["releases"]}
    assert 1 in released, CALLS["releases"]
    added, removed = released[1]
    assert "claim:engineer" in removed, removed
    # The attempt bump is the point: without it a ticket that reliably kills its
    # worker is re-claimed every cycle forever and MAX_ATTEMPTS never trips.
    assert added == ("attempt:1",), added
    # And it is not handed straight back to an identical worker in the same cycle.
    assert 1 not in [c[0] for c in CALLS["claims"]], "reclaimed the ticket that just died"
    assert any("cooling off" in d["why"] for d in result.deferred if d["issue"] == 1)
    print("5. dead lease — released #1, charged an attempt, did not re-claim")

    # --- 6. A live claim is left alone --------------------------------------
    for bucket in CALLS.values():
        bucket.clear()
    HELD[:] = [{"issue": 1, "role": "engineer",
                "since": _recent_iso()}]
    result = await run_once(client)
    assert CALLS["releases"] == [], "reaped a lease that was still alive"
    assert 1 not in [c[0] for c in CALLS["claims"]], "double-claimed a held ticket"
    # The engineer is at capacity holding #1, so #8 waits rather than colliding.
    deferred = {d["issue"]: d["why"] for d in result.deferred}
    assert "already claimed" in deferred[1], deferred
    print("6. live lease — left alone, no double claim")

    # --- 7. Degraded spend holds capable work, not the SRE ------------------
    for bucket in CALLS.values():
        bucket.clear()
    HELD[:] = []
    FAIL_ONCE["degraded"] = True
    result = await run_once(client)
    FAIL_ONCE["degraded"] = False
    claimed = [c[0] for c in CALLS["claims"]]
    assert claimed == [5], claimed  # the SRE only — capable tier held
    assert all("capable-tier" in d["why"] for d in result.deferred if d["issue"] in (1, 2))
    print("7. degraded — capable work held, SRE still running")

    print("\nall assertions passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except WorkflowFailureError as exc:
        print(f"workflow failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
