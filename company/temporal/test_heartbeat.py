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

from activities import BoardSnapshot, LabelWrite  # noqa: E402
from workflows import HeartbeatWorkflow  # noqa: E402

ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")

# Recorded by the stubs so assertions can check what the workflow actually did,
# not merely what it returned.
CALLS: dict[str, list] = {"labels": [], "reports": []}
FAIL_ONCE: dict[str, bool] = {}


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
]


def stubs(paused: bool = False):
    @activity.defn(name="check_kill_switch")
    async def check_kill_switch() -> bool:
        return paused

    @activity.defn(name="read_board")
    async def read_board() -> BoardSnapshot:
        import copy
        return BoardSnapshot(issues=copy.deepcopy(BOARD), prs_in_review=0)

    @activity.defn(name="apply_labels")
    async def apply_labels(write: LabelWrite) -> None:
        CALLS["labels"].append((write.issue, tuple(write.labels)))

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

    return [check_kill_switch, read_board, apply_labels, post_report, today]


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
    CALLS["labels"].clear(); CALLS["reports"].clear()
    result = await run_once(client)

    routed = [(p["issue"], p["role"]) for p in result.plan]
    # #6 is triaged to needs-spec and then picked up by the analyst in the SAME
    # cycle — the workflow reflects each label write back onto its local copy of
    # the board before planning, so a new ticket does not wait 15 minutes to be
    # looked at. That behaviour is the point of the local write-back, not an
    # accident of ordering.
    assert routed == [(1, "engineer"), (2, "analyst"), (5, "sre"), (6, "analyst")], routed
    assert not result.paused
    skipped = {s["issue"] for s in result.skipped}
    assert skipped == {3, 4}, skipped
    # #6 has an empty body and so is pushed to spec; #7 has no dept and is only noted.
    assert (6, ("size:m", "risk:med", "status:needs-spec")) in CALLS["labels"], CALLS["labels"]
    assert not any(c[0] == 7 for c in CALLS["labels"]), "must not guess a department"
    assert any("no dept label" in t for t in result.triaged)
    assert result.reported_on == 99
    assert len(CALLS["reports"]) == 1
    print("1. normal run — routed", routed, "| skipped", sorted(skipped))

    # --- 2. Kill switch ----------------------------------------------------
    CALLS["labels"].clear(); CALLS["reports"].clear()
    result = await run_once(client, paused=True)
    assert result.paused and result.plan == [] and CALLS["labels"] == []
    assert "PAUSED" in result.report
    assert len(CALLS["reports"]) == 1, "a paused heartbeat must still report"
    print("2. kill switch — started nothing, still reported")

    # --- 3. Durability: an activity fails, the run resumes ------------------
    CALLS["labels"].clear(); CALLS["reports"].clear()
    FAIL_ONCE["post_report"] = True
    result = await run_once(client)
    assert result.reported_on == 99, "retry should have succeeded"
    assert len(CALLS["reports"]) == 1, "report posted exactly once despite the failure"
    # The seven triage writes happened once, not twice — the run resumed at the
    # failed step instead of replaying the side effects before it.
    assert len(CALLS["labels"]) == 1, CALLS["labels"]
    print("3. durability — post_report failed once, resumed, no work repeated")

    # --- 4. WIP limit / dry run --------------------------------------------
    CALLS["labels"].clear(); CALLS["reports"].clear()
    result = await run_once(client, apply=False)
    assert CALLS["labels"] == [] and CALLS["reports"] == [], "apply=False must not write"
    assert result.plan, "a dry run still produces a plan"
    print("4. dry run — decided without writing anything")

    print("\nall assertions passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except WorkflowFailureError as exc:
        print(f"workflow failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
