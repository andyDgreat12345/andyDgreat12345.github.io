"""Activities: every side effect the heartbeat has.

Temporal's contract is that workflow code is deterministic and replayable, and
anything that touches the outside world — network, clock, randomness — lives in
an activity. That split is why durable execution works: activities are retried
independently, and a workflow that dies mid-run resumes from the last activity
that completed rather than from the beginning.

Granularity here is chosen for exactly that reason. `post_report` is its own
activity so that a run which triaged twelve tickets and then failed to comment
retries only the comment, and does not re-triage anything.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import date

from temporalio import activity
from temporalio.exceptions import ApplicationError

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ops"))

from dispatch import GitHub  # noqa: E402  — the Tier 0 client, reused verbatim


@dataclass
class BoardSnapshot:
    """What the workflow needs to decide, fetched in one activity so the decision
    is made against a single consistent read rather than a torn one."""

    issues: list[dict]
    prs_in_review: int


@dataclass
class LabelWrite:
    issue: int
    labels: list[str]


def _client() -> GitHub:
    repo = os.environ.get("COMPANY_REPO") or os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GITHUB_TOKEN")
    if not repo or not token:
        # Non-retryable: no amount of retrying fixes a missing credential, and
        # burning the retry budget on it only delays the alert.
        raise ApplicationError(
            "COMPANY_REPO and GITHUB_TOKEN must be set for the worker",
            non_retryable=True,
        )
    return GitHub(repo, token)


@activity.defn
async def check_kill_switch() -> bool:
    """First activity of every run, always. See CHARTER.md.

    Reads the env var the worker was started with, falling back to the repository
    variable so the switch can be flipped from a phone without restarting anything.
    """
    switch = os.environ.get("COMPANY_PAUSED")
    if switch is None:
        switch = _client().variable("COMPANY_PAUSED") or "0"
    paused = switch.strip() == "1"
    activity.logger.info("kill switch: %s", "PAUSED" if paused else "running")
    return paused


@activity.defn
async def read_board() -> BoardSnapshot:
    gh = _client()
    issues = gh.issues()
    # Draft PRs are still being written, so they do not count against the WIP
    # limit — the limit exists to cap what is waiting on a reviewer.
    in_review = sum(1 for pr in gh.open_prs() if not pr.get("draft"))
    activity.logger.info("board: %d issues, %d PRs in review", len(issues), in_review)
    return BoardSnapshot(issues=issues, prs_in_review=in_review)


@activity.defn
async def apply_labels(write: LabelWrite) -> None:
    """Idempotent by GitHub's own semantics — adding a label twice is a no-op,
    which is what makes this safe to retry after an ambiguous failure."""
    if not write.labels:
        return
    _client().add_labels(write.issue, write.labels)
    activity.logger.info("#%d += %s", write.issue, ", ".join(write.labels))


@activity.defn
async def post_report(body: str) -> int:
    """Comment on today's shift report, creating it if this is the first run of
    the day. Returns the issue number so it lands in the workflow history."""
    gh = _client()
    number = gh.find_or_create_shift_report()
    gh.comment(number, body)
    activity.logger.info("reported on #%d", number)
    return number


@activity.defn
async def today() -> str:
    """The date, as an activity because a workflow may not read the clock
    directly — Temporal replays history, and a bare date.today() would produce a
    different answer on replay and break determinism."""
    return date.today().isoformat()
