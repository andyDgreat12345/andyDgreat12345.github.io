"""The heartbeat as a durable workflow.

What this buys over the cron version in .github/workflows/company-heartbeat.yml:

  * A run that dies after triaging eight tickets resumes at the ninth. The cron
    version starts over and re-does the first eight.
  * Each step retries on its own schedule with backoff, so a GitHub 502 costs
    seconds rather than a whole cycle.
  * Every decision is in the workflow history, so "why did it route that ticket
    to the analyst on Tuesday" is answerable by replay rather than by guessing.
  * Overlap is handled by the schedule, not by a concurrency group that silently
    drops runs.

The workflow itself makes no network calls and reads no clock. All of that is in
activities.py; the decisions come from company/ops/board.py, which the Tier 0
dispatcher also imports so the two paths cannot disagree.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

# Imports used by deterministic workflow code are passed through Temporal's
# sandbox rather than re-imported per run. board.py is pure by construction —
# see its module docstring — which is what makes it legal here.
with workflow.unsafe.imports_passed_through():
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ops")
    )
    from board import build_plan, labels_of, render, triage

    # Activities are referenced by function rather than by string name. The
    # difference is not cosmetic: a string name carries no return type, so
    # Temporal hands back a raw dict, and a workflow that then touches an
    # attribute fails its workflow task — which retries forever and presents as
    # a hang rather than an error. Function references keep the types.
    # Stubbing still works, because Temporal dispatches on the registered name.
    from activities import (
        BoardSnapshot,
        LabelWrite,
        apply_labels,
        check_kill_switch,
        post_report,
        read_board,
    )


@dataclass
class HeartbeatResult:
    paused: bool
    plan: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    triaged: list[str] = field(default_factory=list)
    report: str = ""
    reported_on: int | None = None


# Reads are cheap and safe to hammer; writes are not. Both are retried, but a
# write that keeps failing should surface quickly rather than churn.
READ = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=5,
)
WRITE = RetryPolicy(
    initial_interval=timedelta(seconds=3),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=3,
)


@workflow.defn
class HeartbeatWorkflow:
    """One heartbeat. Started every 15 minutes by the schedule in schedule.py."""

    def __init__(self) -> None:
        self._result = HeartbeatResult(paused=False)

    @workflow.query
    def status(self) -> HeartbeatResult:
        """Queryable while in flight — `temporal workflow query` answers "what is
        the company doing right now" without waiting for the run to finish."""
        return self._result

    @workflow.run
    async def run(self, apply: bool = True) -> HeartbeatResult:
        # 1. The kill switch, before anything else. Always.
        paused = await workflow.execute_activity(
            check_kill_switch,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=READ,
        )
        if paused:
            self._result = HeartbeatResult(paused=True, report=render([], [], [], paused=True))
            if apply:
                self._result.reported_on = await workflow.execute_activity(
                    post_report,
                    self._result.report,
                    start_to_close_timeout=timedelta(seconds=60),
                    retry_policy=WRITE,
                )
            return self._result

        # 2. One consistent read of the board.
        snapshot: BoardSnapshot = await workflow.execute_activity(
            read_board,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=READ,
        )

        # 3. Triage. Each label write is its own activity, so a failure partway
        #    through resumes at the ticket it stopped on instead of redoing them.
        issues = snapshot.issues
        triaged: list[str] = []
        for issue in issues:
            if "status:inbox" not in labels_of(issue):
                continue
            add, remove, note = triage(issue)
            if add or remove:
                if apply:
                    await workflow.execute_activity(
                        apply_labels,
                        LabelWrite(issue=issue["number"], labels=add, remove=remove),
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=WRITE,
                    )
                # Reflect the write locally so build_plan below sees the board as
                # it now is, rather than as it was when we read it. This is what
                # lets a ticket be triaged and picked up in the same cycle instead
                # of waiting 15 minutes to be looked at.
                kept = [l for l in issue.get("labels", []) if l["name"] not in remove]
                issue["labels"] = kept + [{"name": n} for n in add]
                triaged.append(f"#{issue['number']} → {', '.join(add)}")
            if note:
                triaged.append(f"#{issue['number']} ({note})")

        # 4. The decision. Pure, deterministic, replayable.
        plan, skipped = build_plan(issues, snapshot.prs_in_review)
        report = render(plan, skipped, triaged, paused=False)
        self._result = HeartbeatResult(
            paused=False, plan=plan, skipped=skipped, triaged=triaged, report=report
        )

        # 5. Report. Always, including on runs that started nothing — a silent
        #    heartbeat is indistinguishable from a dead one.
        if apply:
            self._result.reported_on = await workflow.execute_activity(
                post_report,
                report,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=WRITE,
            )

        # Worker fan-out goes here: one child workflow per plan entry, each
        # starting the named role at the named tier. Left out on purpose — a
        # half-built company should not be able to spend money. See ROLLOUT.md.
        return self._result
