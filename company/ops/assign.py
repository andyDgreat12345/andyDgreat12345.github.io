"""Fan-out: turning a plan into claimed work.

`board.py` decides *what should happen*. This decides *who is holding it right
now*, which is a different and more dangerous question — it is the only part of
the company where two workers can collide, or where a ticket can be held by
something that has already died.

The shape is forced by how the workers actually run. The engineer is an
OpenHands agent in a GitHub Actions job: it starts cold, with no memory of the
heartbeat that claimed its ticket, does one thing, and stops. So the heartbeat
cannot dispatch — it leaves a claim on the board and a brief the worker reads
cold, and the worker answers.

That makes the claim label the company's only lock, which forces four rules:

  * **A claim is a lease, not a lock.** It expires. A lock with no expiry
    deadlocks the moment a worker dies mid-ticket, and these workers die
    silently — a Routine that hits its daily run cap simply never wakes up.
  * **An expired lease costs an attempt.** Something started this ticket and did
    not finish. If that were free, a ticket that reliably kills its worker would
    be re-claimed forever, which is the overnight retry storm MAX_ATTEMPTS
    exists to prevent.
  * **Capacity is per role, not per board.** One job works one ticket. Claiming
    four tickets for a role produces one ticket of progress and three expired
    leases, on a board that looked busy the whole time.
  * **A role with no worker is never claimed for.** Otherwise the lease expires
    unworked, the attempt counter advances, and the ticket escalates as though
    the work had been tried and failed. A vacancy is not a failure.

Pure, like board.py — no clock, no network — so the Temporal workflow can call
it inside the sandbox and every branch is testable.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from board import MAX_ATTEMPTS, has_acceptance_criteria

CLAIM_PREFIX = "claim:"

# How long a worker may hold a ticket before the lease is considered dead.
#
# Tuned to the slowest worker, not the average one. The engineer's job has a
# 30-minute timeout and is queued behind whatever else Actions is running, so a
# short lease would reap work that is merely waiting for a runner. Ninety
# minutes is one full run plus room for the queue.
LEASE_MINUTES = 90

# How many tickets each role may hold at once.
#
# The engineer's 1 is not conservatism, it is arithmetic: the workflow has a
# concurrency group of one, so a second claim would sit waiting and expire
# unworked. The reviewer gets 2 because a review is a short API call rather than
# a sandboxed run, and those are genuinely parallel.
ROLE_CAPACITY = {
    "analyst": 1,
    "engineer": 1,
    "reviewer": 2,
    "sre": 1,
    "researcher": 2,
    "comms": 1,
}
DEFAULT_CAPACITY = 1

# Which roles actually have something that answers to a claim.
#
# This is the difference between a vacancy and a failure, and getting it wrong
# is expensive in a specific way: claiming a ticket for a role nobody has hired
# means the lease expires unworked, the attempt counter advances, and after
# three cycles the ticket escalates wearing `needs:human` as though the work had
# been TRIED AND FAILED. It was never attempted. The board would fill with
# false failures on tickets whose only problem is that the company has not
# hired for that stage yet.
#
# So an unhired stage is reported as waiting on the owner — which is what it is,
# and which the stall alarm already knows not to alarm about.
#
# Add a role here the moment a worker exists for it, and not before. The cost of
# being late is a ticket that waits; the cost of being early is a ticket that
# lies about having failed.
HIRED = {
    "engineer",   # .github/workflows/company-engineer.yml — OpenHands on DeepSeek
}


def claim_label(role: str) -> str:
    return f"{CLAIM_PREFIX}{role}"


def claimed_role(labels: set[str] | list[str]) -> str | None:
    """The role currently holding this ticket, if any."""
    for name in sorted(labels):
        if name.startswith(CLAIM_PREFIX):
            return name[len(CLAIM_PREFIX):]
    return None


def capacity_for(role: str) -> int:
    return ROLE_CAPACITY.get(role, DEFAULT_CAPACITY)


def fan_out(plan: list[dict], held: list[dict], now: datetime,
            allows_capable: bool = True,
            lease_minutes: int = LEASE_MINUTES,
            hired: set[str] | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    """Decide which planned work to claim, and which dead leases to release.

    `held` is what the board says is already claimed: dicts of
    `{issue, role, since}` where `since` is an aware datetime taken from the
    label event that applied the claim — not `updated_at`, which also moves on
    comments and would keep a dead lease looking alive.

    `hired` names the roles that actually have a worker; it defaults to HIRED
    and is injectable so the capacity, lease and budget rules stay testable
    independently of who happens to be hired this week.

    Returns (claims, releases, deferred).
    """
    hired = HIRED if hired is None else hired
    deadline = now - timedelta(minutes=lease_minutes)

    releases = [
        {
            "issue": h["issue"],
            "role": h["role"],
            "held_for_minutes": int((now - h["since"]).total_seconds() // 60),
            "why": f"lease expired after {lease_minutes}m without finishing",
        }
        for h in held
        if h["since"] <= deadline
    ]
    expired = {r["issue"] for r in releases}
    live = [h for h in held if h["issue"] not in expired]
    live_by_issue = {h["issue"]: h["role"] for h in live}

    load: dict[str, int] = {}
    for h in live:
        load[h["role"]] = load.get(h["role"], 0) + 1

    claims: list[dict] = []
    deferred: list[dict] = []

    for entry in plan:
        ref = {"issue": entry["issue"], "role": entry["role"]}

        # Vacancy, not failure. Claiming for a role nobody has hired burns the
        # ticket's whole retry budget on work that was never attempted.
        if entry["role"] not in hired:
            deferred.append({
                **ref,
                "why": f"no {entry['role']} hired — this stage is the owner's",
                "vacancy": True,
            })
            continue

        holder = live_by_issue.get(entry["issue"])
        if holder is not None:
            deferred.append({**ref, "why": f"already claimed by the {holder}"})
            continue

        # A ticket whose lease just expired is deliberately NOT re-claimed in the
        # same cycle. The expiry is evidence that something went wrong here, and
        # handing it straight back to an identical worker is how a tight failure
        # loop starts. The next heartbeat picks it up, one attempt poorer.
        if entry["issue"] in expired:
            deferred.append({**ref, "why": "lease just expired — cooling off for one cycle"})
            continue

        # The controller's degrade state. `mixed` deliberately continues: its
        # floor is the cheap tier, and the SRE is how you find out the company is
        # broken — switching off your only diagnostics to save money is how a
        # degraded company becomes a dead one.
        if entry["tier"] == "capable" and not allows_capable:
            deferred.append({**ref, "why": "controller has held capable-tier work"})
            continue

        used, cap = load.get(entry["role"], 0), capacity_for(entry["role"])
        if used >= cap:
            deferred.append({**ref, "why": f"{entry['role']} at capacity ({used}/{cap})"})
            continue

        load[entry["role"]] = used + 1
        claims.append({**entry, "label": claim_label(entry["role"])})

    return claims, releases, deferred


def brief(entry: dict, issue: dict, now: datetime,
          lease_minutes: int = LEASE_MINUTES) -> str:
    """The work order, posted as a comment when the claim lands.

    Written to be read cold. The worker is a fresh session that was not present
    for the heartbeat, has never seen this ticket, and will not get a follow-up
    question answered — anything it needs to do the job correctly has to be in
    here, including the parts a human would consider obvious.
    """
    expires = now + timedelta(minutes=lease_minutes)
    dept = entry.get("dept", "dept:hq")
    risk = entry.get("risk", "risk:med")
    body = issue.get("body") or ""

    lines = [
        f"## Work order — {entry['role']}",
        "",
        f"You are the **{entry['role']}**. Your standing instructions are in "
        f"`company/roles/` — read your own card before you start; it is the job "
        f"description, and this comment is only the assignment.",
        "",
        "| | |",
        "|---|---|",
        f"| Ticket | #{entry['issue']} — {entry['title']} |",
        f"| Department | `{dept}` |",
        f"| Risk | `{risk}` |",
        f"| Tier | `{entry['tier']}` — resolve it through `company/ops/models.py`, "
        f"never pick a model by hand |",
        f"| Attempt | {entry['attempt']} of {MAX_ATTEMPTS} — after {MAX_ATTEMPTS} "
        f"the ticket stops being retried and escalates to the owner |",
        f"| Lease expires | {expires.isoformat(timespec='minutes')} |",
        "",
    ]

    if has_acceptance_criteria(body):
        lines += [
            "**Done means the acceptance criteria in the ticket body are met** — "
            "all of them, checked off, with the evidence that they are. Not "
            "\"the code looks right\".",
        ]
    else:
        lines += [
            "**This ticket has no acceptance criteria.** That is a routing bug, "
            "not an invitation to invent them. Label it `status:needs-spec`, drop "
            "your claim, and say so in a comment.",
        ]

    lines += [
        "",
        "### Boundaries",
        "",
        "- **One ticket.** This one. If you find another problem, file it; do not fix it here.",
        f"- **The lease is real.** If you have not finished by {expires.isoformat(timespec='minutes')} "
        "the claim is released and this counts as a failed attempt. Prefer "
        "handing back a small honest result to holding the lease.",
        "- **You do not merge your own work.** Separation of duties is the whole "
        "design — see `company/CHARTER.md`.",
        "- **Stuck is a valid outcome.** Label the ticket `needs:human`, say what "
        "you tried and what you would need, and stop. A ticket waiting on the "
        "owner is the system working; a ticket being guessed at is not.",
    ]

    if risk == "risk:high":
        lines += [
            "- **`risk:high`.** Money, credentials, personal data, or something "
            "public. Do not act unilaterally — propose the change and get the "
            "owner's approval before it lands.",
        ]
    if dept in ("dept:admissions", "dept:casewriter"):
        lines += [
            f"- **`{dept}` handles real personal data.** The bulk tier is not "
            "available to you here and `models.py` will refuse to route it. "
            "That refusal is correct; do not work around it.",
        ]

    lines += [
        "",
        "### When you finish",
        "",
        "Move the stage label, remove your `" + claim_label(entry["role"]) + "` claim, "
        "and comment what you did and how you checked it. **The claim is the lock** "
        "— a finished ticket still wearing one blocks the next worker for "
        f"{lease_minutes} minutes.",
    ]
    return "\n".join(lines)


def render(claims: list[dict], releases: list[dict], deferred: list[dict]) -> str:
    """The fan-out section of the heartbeat comment."""
    if not claims and not releases and not deferred:
        return ""

    lines = [f"**Fan-out** — {len(claims)} claimed, {len(releases)} released."]
    if claims:
        lines += ["", "| # | role | tier | attempt |", "|---|---|---|---|"]
        lines += [
            f"| #{c['issue']} | {c['role']} | {c['tier']} | {c['attempt']} |" for c in claims
        ]
    if releases:
        # Released leases are reported loudly. Each one is a worker that started
        # something and vanished, and a run of them is the shape of a broken
        # worker rather than a broken ticket.
        lines += ["", "*Released (worker did not finish):*"]
        lines += [
            f"- #{r['issue']} — {r['role']} held it {r['held_for_minutes']}m; {r['why']}"
            for r in releases
        ]
    # Vacancies are reported apart from deferrals, and as a count. A deferral is
    # transient — capacity, a lease, the budget — and worth a line each. A
    # vacancy is a standing fact about the company, and printing the same three
    # lines every fifteen minutes is how a shift report becomes wallpaper.
    vacancies = [d for d in deferred if d.get("vacancy")]
    waiting = [d for d in deferred if not d.get("vacancy")]

    if waiting:
        lines += ["", "*Deferred:*"] + [f"- #{d['issue']} — {d['why']}" for d in waiting]
    if vacancies:
        roles = sorted({d["role"] for d in vacancies})
        lines += [
            "",
            f"*{len(vacancies)} ticket(s) waiting on you* — no "
            + ", ".join(roles)
            + " hired: "
            + ", ".join(f"#{d['issue']}" for d in vacancies),
        ]
    return "\n".join(lines)
