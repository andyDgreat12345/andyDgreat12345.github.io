#!/usr/bin/env python3
"""Release the claim after a worker run, and say honestly what happened.

The claim label is the company's only lock (see assign.py). A worker that
finishes and does not release it blocks the ticket for the rest of the lease,
and a worker that *crashes* never releases it at all — so the release cannot be
the worker's own last instruction. It is a separate step that runs whether the
worker succeeded, failed, or died.

Success is judged by artifact, not by assertion: was a pull request actually
opened for this ticket? ORG.md is explicit that a run producing no PR, no
comment and no file did not happen, and an agent reporting its own success is
exactly the claim that rule exists to distrust.

    GITHUB_TOKEN=... python company/ops/handoff.py --repo owner/name --issue 12 \
        --branch agent/issue-12 [--apply]

Stdlib only, like everything in company/ops.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from assign import claim_label  # noqa: E402
from board import MAX_ATTEMPTS, attempts, labels_of  # noqa: E402


def decide(issue: dict, role: str, pr_number: int | None) -> tuple[list[str], list[str], str]:
    """What to do with the ticket now the worker has stopped.

    Returns (labels_to_add, labels_to_remove, comment). Pure.
    """
    have = labels_of(issue)
    claim = claim_label(role)
    n = attempts(issue)

    if pr_number is not None:
        # Handed on to the SRE. The stage moves and the lock comes off; the
        # attempt counter is deliberately left alone, because the attempt
        # succeeded and a later failure should not inherit its cost.
        return (
            ["status:verify"],
            [claim, "status:ready", "status:building"],
            f"**Engineer finished.** Opened #{pr_number} and handed this to verify.\n\n"
            f"Released `{claim}`. The pull request is the evidence — this ticket "
            f"advanced because a PR exists, not because the run reported success.",
        )

    # No PR. Something ran and produced nothing, which is a failed attempt
    # whether it crashed, refused, or quietly did nothing.
    used = n + 1
    add = [f"attempt:{used}"]
    remove = [claim] + ([f"attempt:{n}"] if n else [])

    if used >= MAX_ATTEMPTS:
        # Three strikes. Never retried automatically — infinite retries are how
        # you wake up to a bill and no progress.
        add.append("needs:human")
        note = (
            f"**Engineer produced no pull request — attempt {used} of {MAX_ATTEMPTS}.**\n\n"
            f"That is the last attempt, so this ticket is now yours: labelled "
            f"`needs:human` and it will not be picked up again automatically.\n\n"
            f"Three failed runs usually means the ticket is unclear rather than "
            f"the work being hard. Read the acceptance criteria before re-queueing it."
        )
    else:
        note = (
            f"**Engineer produced no pull request — attempt {used} of {MAX_ATTEMPTS}.**\n\n"
            f"Released `{claim}` so the ticket can be picked up again. The run log "
            f"in Actions says what it did before stopping."
        )
    return add, remove, note


class GitHub:
    def __init__(self, repo: str, token: str) -> None:
        self.repo, self.token = repo, token

    def _request(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"https://api.github.com{path}", data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if data:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req) as resp:
            payload = resp.read()
        return json.loads(payload) if payload else None

    def issue(self, number: int) -> dict:
        return self._request("GET", f"/repos/{self.repo}/issues/{number}")

    def pr_for_branch(self, branch: str) -> int | None:
        """The open PR whose head is this branch, if any.

        Includes drafts on purpose: a draft PR is exactly what the engineer is
        asked to produce, and treating it as "no PR" would fail every successful
        run.
        """
        owner = self.repo.split("/")[0]
        q = urllib.parse.urlencode({"head": f"{owner}:{branch}", "state": "open"})
        found = self._request("GET", f"/repos/{self.repo}/pulls?{q}") or []
        return found[0]["number"] if found else None

    def apply(self, number: int, add: list[str], remove: list[str], comment: str) -> None:
        if add:
            self._request("POST", f"/repos/{self.repo}/issues/{number}/labels", {"labels": add})
        for name in remove:
            try:
                self._request(
                    "DELETE",
                    f"/repos/{self.repo}/issues/{number}/labels/{urllib.parse.quote(name)}",
                )
            except urllib.error.HTTPError as exc:
                if exc.code != 404:  # already off is the state we wanted
                    raise
        self._request("POST", f"/repos/{self.repo}/issues/{number}/comments", {"body": comment})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    ap.add_argument("--issue", type=int, required=True)
    ap.add_argument("--role", default="engineer")
    ap.add_argument("--branch", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not args.repo or not token:
        print("need --repo (or GITHUB_REPOSITORY) and GITHUB_TOKEN", file=sys.stderr)
        return 2

    gh = GitHub(args.repo, token)
    pr = gh.pr_for_branch(args.branch)
    add, remove, comment = decide(gh.issue(args.issue), args.role, pr)

    print(f"#{args.issue}: pr={pr} += {add} -= {remove}")
    print(comment)
    if args.apply:
        gh.apply(args.issue, add, remove, comment)
        print("applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
