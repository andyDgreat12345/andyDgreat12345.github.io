#!/usr/bin/env python3
"""Turn a claimed ticket into the prompt an agent actually receives.

The fan-out writes a work order as a comment (see assign.py). The engineer that
reads it is now an OpenHands agent rather than a Claude Code session, and it
starts with no context at all — not even the conversation the work order was
written into. So this composes the whole thing: the work order, the ticket, and
the boundaries that are not negotiable.

    GITHUB_TOKEN=... python company/ops/work_order.py --repo owner/name --issue 12

Composing here rather than in the workflow YAML matters for one reason: `compose`
is a pure function and is tested. A prompt assembled by shell interpolation is
not, and the prompt is the only thing standing between an autonomous agent and
the rest of the repository.

Stdlib only, like everything in company/ops.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from board import DEPTS, RISKS, labels_of  # noqa: E402

WORK_ORDER_MARKER = "## Work order"

# Departments whose tickets touch real people. The agent is told plainly; the
# refusal is still enforced in models.py, because a boundary that exists only in
# a prompt is a boundary an agent can talk itself out of.
PERSONAL_DATA_DEPTS = {"dept:admissions", "dept:casewriter"}


def latest_work_order(comments: list[dict]) -> str | None:
    """The most recent work order on the ticket.

    Most recent, not first: a ticket on its second attempt has two, and the
    stale one describes a lease that has already been reaped.
    """
    orders = [c["body"] for c in comments if (c.get("body") or "").lstrip().startswith(WORK_ORDER_MARKER)]
    return orders[-1] if orders else None


def compose(issue: dict, work_order: str | None, repo: str) -> str:
    """Build the agent's prompt. Pure — every branch is testable."""
    have = labels_of(issue)
    dept = next((d for d in have if d in DEPTS), "dept:hq")
    risk = next((r for r in have if r in RISKS), "risk:med")
    number = issue["number"]

    parts = [
        f"You are the Engineer for a small agent-run company. You are working in "
        f"the repository {repo}, on issue #{number}: {issue['title']}",
        "",
        "Read `company/roles/02-engineer.md` before you start. That is your job "
        "description; what follows is only this one assignment.",
        "",
        f"## The ticket (#{number})",
        "",
        (issue.get("body") or "").strip() or "_(no body)_",
    ]

    if work_order:
        parts += ["", "## The work order left for you", "", work_order.strip()]
    else:
        # Should not happen — the fan-out writes the order before it applies the
        # claim. If it did, the ticket is malformed and guessing is the wrong
        # response, so say so explicitly rather than improvising a task.
        parts += [
            "",
            "## No work order was found on this ticket",
            "",
            "This is a bug in the dispatcher, not an invitation to decide what "
            "the ticket meant. Add the label `needs:human`, remove the label "
            "`claim:engineer`, comment explaining that the work order is missing, "
            "and stop. Do not change any other file.",
        ]

    parts += [
        "",
        "## How to finish",
        "",
        "1. Make the change on a new branch named `agent/issue-" + str(number) + "`.",
        "2. Run the tests yourself before you open anything. `npm test` and "
        "`npm run build` for site work; the Python suites `company/ops/test_*.py` "
        "for company logic. A change you have not run is not finished.",
        "3. Open a **draft** pull request against `main` whose body says `Closes "
        f"#{number}` and states what you did and how you checked it.",
        "",
        "## Boundaries — these are not advisory",
        "",
        "- **Never merge your own pull request.** Builder, reviewer and merger are "
        "three different actors; that separation is the entire design of this "
        "company. Open it as a draft and stop.",
        f"- **Work on issue #{number} and nothing else.** If you notice another "
        "problem, mention it in your PR body. Do not fix it, and do not open a "
        "second pull request.",
        "- **Never edit or remove the `needs:human` label**, never change the "
        "repository variable `COMPANY_PAUSED`, and never raise a spending cap. "
        "Those are the owner's alone.",
        "- **Do not modify files under `.github/workflows/`.** A worker that can "
        "rewrite its own gates has no gates.",
        "- **If you cannot finish** — blocked, ambiguous, or the acceptance "
        "criteria do not actually say what done means — add `needs:human`, remove "
        "`claim:engineer`, and comment what you tried and what you would need. "
        "Stopping is a valid outcome. Guessing is not.",
    ]

    if risk == "risk:high":
        parts += [
            "- **This ticket is `risk:high`** — money, credentials, personal data, "
            "or something public-facing. Do not act unilaterally: make the "
            "smallest defensible change, and say clearly in the PR body what you "
            "want the owner to check before it lands.",
        ]

    if dept in PERSONAL_DATA_DEPTS:
        parts += [
            f"- **`{dept}` handles real personal data.** Do not copy record "
            "contents into commit messages, PR bodies, comments, test fixtures or "
            "logs. If you need an example, invent one.",
        ]

    return "\n".join(parts)


class GitHub:
    def __init__(self, repo: str, token: str) -> None:
        self.repo, self.token = repo, token

    def _get(self, path: str):
        req = urllib.request.Request(f"https://api.github.com{path}")
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def issue(self, number: int) -> dict:
        return self._get(f"/repos/{self.repo}/issues/{number}")

    def comments(self, number: int) -> list[dict]:
        q = urllib.parse.urlencode({"per_page": 100})
        return self._get(f"/repos/{self.repo}/issues/{number}/comments?{q}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    ap.add_argument("--issue", type=int, required=True)
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not args.repo or not token:
        print("need --repo (or GITHUB_REPOSITORY) and GITHUB_TOKEN", file=sys.stderr)
        return 2

    gh = GitHub(args.repo, token)
    issue = gh.issue(args.issue)
    print(compose(issue, latest_work_order(gh.comments(args.issue)), args.repo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
