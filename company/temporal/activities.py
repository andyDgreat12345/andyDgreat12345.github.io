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
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from temporalio import activity
from temporalio.exceptions import ApplicationError

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ops"))

from assign import claim_label, claimed_role  # noqa: E402
from dispatch import GitHub  # noqa: E402  — the Tier 0 client, reused verbatim


@dataclass
class BoardSnapshot:
    """What the workflow needs to decide, fetched in one activity so the decision
    is made against a single consistent read rather than a torn one."""

    issues: list[dict]
    prs_in_review: int
    # Live claims: {issue, role, since}, `since` an ISO string. The workflow
    # parses them — dataclass fields cross the wire as JSON, and a datetime does
    # not survive that round trip intact.
    held: list[dict] = field(default_factory=list)


@dataclass
class LabelWrite:
    issue: int
    labels: list[str]
    remove: list[str] = field(default_factory=list)


@dataclass
class ClaimWrite:
    """Apply a claim and post the brief that goes with it.

    One activity, not two, because the brief is what makes the claim meaningful:
    a claim with no brief is a lock on a ticket nobody has been told how to do.
    The comment goes first so the worker can never arrive at a claimed ticket
    with no instructions — a duplicate brief after a retry is noise, whereas a
    claim with no brief is a worker guessing.
    """

    issue: int
    label: str
    brief: str


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
async def read_spend() -> bool:
    """May the fan-out claim capable-tier work right now?

    This is the controller's 90% degrade rule reaching the fan-out: hold the
    expensive work, let cheap and local carry on. It is a *soft* brake, and
    deliberately so — the hard stop is `COMPANY_PAUSED`, which check_kill_switch
    reads first and which no role may clear.

    An absent ledger returns True. That is a fail-open, and worth saying out
    loud: on a worker with no ledger mounted this brake does nothing at all, and
    the Actions controller remains the real breaker. Failing closed here would
    mean a fresh worker with no spend history refuses to do any capable work,
    i.e. a company that cannot start.
    """
    import controller  # noqa: PLC0415 — heavy-ish, and only this activity needs it

    entries = controller._read(controller.LEDGER)
    if not entries:
        activity.logger.info("no ledger — capable tier allowed")
        return True
    verdict = controller.assess(entries, datetime.now(timezone.utc))
    activity.logger.info("spend: %s — %s", verdict.state, verdict.reason)
    return verdict.allows_capable


@activity.defn
async def read_board() -> BoardSnapshot:
    gh = _client()
    issues = gh.issues()
    # Draft PRs are still being written, so they do not count against the WIP
    # limit — the limit exists to cap what is waiting on a reviewer.
    in_review = sum(1 for pr in gh.open_prs() if not pr.get("draft"))

    # Claim ages cost one API call each, so they are fetched only for tickets
    # actually wearing a claim — normally a handful, and zero on an idle board.
    held = []
    for issue in issues:
        names = {l["name"] for l in issue.get("labels", [])}
        role = claimed_role(names)
        if role is None:
            continue
        since = gh.claim_since(issue["number"], claim_label(role))
        # No event means the label predates the events window, which is old
        # enough to reap on its own. Falling back to the issue's creation time
        # makes it expire rather than making it immortal — an unreadable lease
        # must fail toward release, never toward holding forever.
        held.append({
            "issue": issue["number"],
            "role": role,
            "since": since or issue["created_at"],
        })

    activity.logger.info("board: %d issues, %d PRs in review, %d claimed",
                         len(issues), in_review, len(held))
    return BoardSnapshot(issues=issues, prs_in_review=in_review, held=held)


@activity.defn
async def apply_labels(write: LabelWrite) -> None:
    """Idempotent by GitHub's own semantics — adding a label twice is a no-op and
    removing an absent one 404s, which the client treats as success. That is what
    makes this safe to retry after an ambiguous failure.

    Adds before removing, so the ticket is never briefly stage-less: a crash
    between the two calls leaves it wearing both labels, which the router handles,
    rather than none, which would strand it.
    """
    gh = _client()
    if write.labels:
        gh.add_labels(write.issue, write.labels)
    for name in write.remove:
        gh.remove_label(write.issue, name)
    if write.labels or write.remove:
        activity.logger.info(
            "#%d += %s -= %s",
            write.issue,
            ", ".join(write.labels) or "-",
            ", ".join(write.remove) or "-",
        )


@activity.defn
async def place_claim(write: ClaimWrite) -> None:
    """Post the brief, then take the lock. In that order, always — see ClaimWrite."""
    gh = _client()
    gh.comment(write.issue, write.brief)
    gh.add_labels(write.issue, [write.label])
    activity.logger.info("#%d claimed by %s", write.issue, write.label)


@activity.defn
async def release_claim(write: LabelWrite) -> None:
    """Drop a dead lease and charge it an attempt.

    The attempt bump is the point. Something started this ticket and vanished;
    if that were free, a ticket that reliably kills its worker would be re-claimed
    every cycle forever.

    It is its own activity rather than a bare apply_labels so the workflow
    history says "release_claim" — a reaped lease is the one label edit you will
    go looking for later, and it should not hide among the routine ones.
    """
    gh = _client()
    if write.labels:
        gh.add_labels(write.issue, write.labels)
    for name in write.remove:
        gh.remove_label(write.issue, name)
    activity.logger.info("#%d released: -%s", write.issue, ", ".join(write.remove) or "-")


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
