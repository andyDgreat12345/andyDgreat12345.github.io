"""Pure board logic: how labels become routing decisions.

Deliberately free of I/O — no network, no clock, no filesystem, no randomness.
Two things depend on that:

  * `dispatch.py` (the zero-dependency Tier 0 path) and the Temporal workflow
    both import this module, so the company's routing rules have exactly one
    definition and cannot drift between the cheap path and the funded one.
  * Temporal workflow code must be deterministic and is re-executed during
    history replay. Anything that talks to the outside world belongs in an
    activity; everything in this file is safe to call from inside a workflow.

If you are changing how work is routed, this is the only file to change.
"""

from __future__ import annotations

# Which role owns which stage, and the model tier it is hired at. Tiers resolve
# to concrete models in company/MODELS.md — keeping the mapping here means
# re-pricing the company is one edit, not eight prompt rewrites.
STAGE_OWNER = {
    "status:needs-spec": ("analyst", "capable"),
    "status:ready": ("engineer", "capable"),
    "status:verify": ("sre", "mixed"),
}

DEPTS = {"dept:site", "dept:casewriter", "dept:market", "dept:admissions", "dept:hq"}
SIZES = {"size:s", "size:m", "size:l"}
RISKS = {"risk:low", "risk:med", "risk:high"}

# Guardrails from ORG.md. WIP stops the board filling with half-finished PRs;
# MAX_ATTEMPTS is what stands between a broken ticket and an overnight retry storm.
WIP_LIMIT = 3
MAX_ATTEMPTS = 3


def labels_of(issue: dict) -> set[str]:
    return {l["name"] for l in issue.get("labels", [])}


def attempts(issue: dict) -> int:
    """Attempt count is carried on the ticket as `attempt:N` — visible to a human
    scrolling the board, which a hidden counter would not be."""
    for name in labels_of(issue):
        if name.startswith("attempt:"):
            try:
                return int(name.split(":", 1)[1])
            except ValueError:
                return 0
    return 0


def triage(issue: dict) -> tuple[list[str], str | None]:
    """Apply the missing classification labels. Returns (labels_to_add, note).

    The dispatcher may classify but may never guess: an issue whose department is
    unclear, or which arrived with no body, goes to the analyst rather than being
    assigned a department at random.
    """
    have = labels_of(issue)
    add: list[str] = []

    if not (have & DEPTS):
        return [], "no dept label — needs a human or an analyst to classify"
    if not (have & SIZES):
        add.append("size:m")
    if not (have & RISKS):
        add.append("risk:med")
    if not (issue.get("body") or "").strip():
        add.append("status:needs-spec")
        return add, "empty body — routed to spec"
    return add, None


def build_plan(issues: list[dict], in_review: int) -> tuple[list[dict], list[dict]]:
    """Match tickets to roles. A pure function of the board, so its decisions can
    be replayed from the labels alone — which is what makes them reviewable."""
    plan: list[dict] = []
    skipped: list[dict] = []

    for issue in sorted(issues, key=lambda i: i["number"]):
        have = labels_of(issue)
        ref = {"issue": issue["number"], "title": issue["title"]}

        if "needs:human" in have:
            skipped.append({**ref, "why": "waiting on the owner"})
            continue
        if "status:blocked" in have:
            skipped.append({**ref, "why": "blocked"})
            continue
        if attempts(issue) >= MAX_ATTEMPTS:
            skipped.append({**ref, "why": f"{MAX_ATTEMPTS} failed attempts — escalating"})
            continue

        stage = next((s for s in STAGE_OWNER if s in have), None)
        if stage is None:
            continue

        role, tier = STAGE_OWNER[stage]

        # WIP limit: a queue of unreviewed PRs is worse than an idle engineer.
        if role == "engineer" and in_review >= WIP_LIMIT:
            skipped.append({**ref, "why": f"WIP limit — {in_review} PRs awaiting review"})
            continue

        dept = next((d for d in have if d in DEPTS), "dept:hq")
        plan.append(
            {
                **ref,
                "role": role,
                "tier": tier,
                "dept": dept,
                "risk": next((r for r in have if r in RISKS), "risk:med"),
                "attempt": attempts(issue) + 1,
            }
        )

    return plan, skipped


def render(plan: list[dict], skipped: list[dict], triaged: list[str], paused: bool) -> str:
    """The heartbeat comment. Always produced, including on runs that started
    nothing — a silent heartbeat is indistinguishable from a dead one."""
    if paused:
        return "**Heartbeat — PAUSED.** `COMPANY_PAUSED` is set. Started nothing."

    lines = [f"**Heartbeat** — {len(plan)} started, {len(skipped)} skipped."]
    if triaged:
        lines += ["", "*Triaged:* " + ", ".join(triaged)]
    if plan:
        lines += ["", "| # | role | tier | dept | attempt |", "|---|---|---|---|---|"]
        lines += [
            f"| #{p['issue']} | {p['role']} | {p['tier']} | {p['dept']} | {p['attempt']} |"
            for p in plan
        ]
    if skipped:
        lines += ["", "*Skipped:*"] + [f"- #{s['issue']} — {s['why']}" for s in skipped]
    if not plan and not skipped:
        lines += ["", "Board is clear. Nothing to start."]
    return "\n".join(lines)
