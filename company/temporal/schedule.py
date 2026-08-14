#!/usr/bin/env python3
"""Create, inspect and control the company clock.

The schedule is the durable replacement for the cron line in
.github/workflows/company-heartbeat.yml. Two differences matter:

  * `overlap=SKIP` means a slow heartbeat delays the next one rather than
    running two dispatchers over the same board. GitHub's concurrency groups
    either queue or cancel; neither is what you want here.
  * Pausing is first-class and reversible, and it records a note saying who
    paused it and why. That is the operational half of the kill switch — the
    switch in CHARTER.md stops the work, this stops the clock.

    python company/temporal/schedule.py create     # or update, idempotent
    python company/temporal/schedule.py describe
    python company/temporal/schedule.py trigger    # run one now
    python company/temporal/schedule.py pause --note "investigating spend"
    python company/temporal/schedule.py resume
    python company/temporal/schedule.py delete
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import timedelta

from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from worker import TASK_QUEUE, connect  # noqa: E402

SCHEDULE_ID = "company-heartbeat"
EVERY = timedelta(minutes=int(os.environ.get("COMPANY_HEARTBEAT_MINUTES", "15")))


def _schedule() -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            "HeartbeatWorkflow",
            args=[True],  # apply=True — write labels and post the report
            id="heartbeat",  # per-run IDs get the schedule's timestamp appended
            task_queue=TASK_QUEUE,
            execution_timeout=timedelta(minutes=10),
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=EVERY)]),
        policy=SchedulePolicy(
            # A heartbeat that overruns its window should yield to the board's
            # current state, not pile a second dispatcher on top of it.
            overlap=ScheduleOverlapPolicy.SKIP,
            # If the worker was down, run once on recovery rather than replaying
            # every missed tick — the board is current, the backlog is not.
            catchup_window=timedelta(minutes=30),
        ),
    )


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "command",
        choices=["create", "update", "describe", "trigger", "pause", "resume", "delete"],
    )
    ap.add_argument("--note", default="", help="reason, recorded on pause/resume")
    args = ap.parse_args()

    client = await connect()
    handle = client.get_schedule_handle(SCHEDULE_ID)

    if args.command in ("create", "update"):
        try:
            await client.create_schedule(SCHEDULE_ID, _schedule())
            print(f"created {SCHEDULE_ID}: every {EVERY}, overlap=SKIP")
        except ScheduleAlreadyRunningError:
            await handle.update(lambda _: _schedule())
            print(f"updated {SCHEDULE_ID}: every {EVERY}, overlap=SKIP")
        return 0

    if args.command == "describe":
        desc = await handle.describe()
        state: ScheduleState = desc.schedule.state
        print(f"id:       {SCHEDULE_ID}")
        print(f"paused:   {state.paused}{'  — ' + state.note if state.note else ''}")
        print(f"running:  {len(desc.info.running_actions)}")
        print(f"recent:   {len(desc.info.recent_actions)} action(s)")
        for action in desc.info.recent_actions[-5:]:
            print(f"  {action.scheduled_at.isoformat()}  {action.action.first_execution_run_id}")
        for upcoming in desc.info.next_action_times[:3]:
            print(f"  next → {upcoming.isoformat()}")
        return 0

    if args.command == "trigger":
        await handle.trigger()
        print("triggered one heartbeat now")
        return 0

    if args.command == "pause":
        await handle.pause(note=args.note or "paused from schedule.py")
        print("clock paused — the worker stays up, no new heartbeats start")
        return 0

    if args.command == "resume":
        await handle.unpause(note=args.note or "resumed from schedule.py")
        print("clock resumed")
        return 0

    if args.command == "delete":
        await handle.delete()
        print(f"deleted {SCHEDULE_ID}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
