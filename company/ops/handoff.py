#!/usr/bin/env python3
"""Release the claim after a worker run, and say honestly what happened.

The claim label is the company's only lock (see assign.py). A worker that
finishes and does not release it blocks the ticket for the rest of the lease,
and a worker that *crashes* never releases it at all — so the release cannot be
the worker's own last instruction. It is a separate step that runs whether the
worker succeeded, failed, or died.

Success is judged by artifact, not by assertion. ORG.md is explicit that a run
producing no PR, no comment and no file did not happen, and an agent reporting
its own success is exactly the claim that rule exists to distrust.

WHAT the artifact is differs by role — a pull request for the engineer,
acceptance criteria on the ticket for the analyst, verification evidence for the
SRE — and that table lives in board.ROLE_ARTIFACT so adding a role is one entry
rather than a new branch in three files.

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
from board import MAX_ATTEMPTS, ROLE_ARTIFACT, ROLE_STAGE_OUT, attempts, has_acceptance_criteria  # noqa: E402


def decide(issue: dict, role: str, evidence: str | None,
           attempted: bool = True) -> tuple[list[str], list[str], str]:
    """What to do with the ticket now the worker has stopped.

    `evidence` is a short description of the artifact the role produced — "#42"
    for a pull request, "6 acceptance criteria" for a spec — or None if it
    produced nothing. What counts as the artifact differs by role and is named
    in board.ROLE_ARTIFACT; what never differs is that SOMETHING has to exist.

    `attempted=False` means the run never started — a missing secret, a paused
    company, something about the configuration rather than the ticket. That case
    exists because the alternative is worse than it looks: a misconfiguration
    charged as a failed attempt spends one of the ticket's three lives, and
    three of them escalate a perfectly good ticket as unworkable. The ticket
    would be blamed for the company's own setup.

    Returns (labels_to_add, labels_to_remove, comment). Pure.
    """
    claim = claim_label(role)
    n = attempts(issue)

    if not attempted:
        # Claim off, counter untouched. The ticket goes straight back on the
        # board and is picked up again the moment the problem is fixed.
        return (
            [],
            [claim],
            f"**{role.title()} not configured — nothing was attempted.**\n\n"
            f"Released `{claim}` and left the attempt counter alone: this ticket "
            f"did not fail, the company is not set up to work it yet. See the "
            f"run summary in Actions for which secret is missing, and "
            f"`company/workers/README.md` for where it goes.\n\n"
            f"The ticket returns to the board automatically once that is fixed.",
        )

    if evidence is not None:
        # Handed on to whoever owns the next stage. The stage moves and the lock
        # comes off; the attempt counter is deliberately left alone, because the
        # attempt succeeded and a later failure should not inherit its cost.
        stage_out = ROLE_STAGE_OUT.get(role)
        artifact = ROLE_ARTIFACT.get(role, "artifact")
        # Every stage this role could have been picked up from comes off, so a
        # ticket never wears two stages after a handoff.
        stale = [s for s in ("status:needs-spec", "status:ready", "status:building",
                             "status:verify") if s != stage_out]
        return (
            [stage_out] if stage_out else [],
            [claim] + stale,
            f"**{role.title()} finished.** {evidence}\n\n"
            f"Released `{claim}`. The {artifact} is the evidence — this ticket "
            f"advanced because it exists, not because the run reported success.",
        )

    # No artifact. Something ran and produced nothing, which is a failed attempt
    # whether it crashed, refused, or quietly did nothing.
    used = n + 1
    add = [f"attempt:{used}"]
    remove = [claim] + ([f"attempt:{n}"] if n else [])

    if used >= MAX_ATTEMPTS:
        # Three strikes. Never retried automatically — infinite retries are how
        # you wake up to a bill and no progress.
        add.append("needs:human")
        note = (
            f"**{role.title()} produced no {ROLE_ARTIFACT.get(role, 'artifact')} — "
            f"attempt {used} of {MAX_ATTEMPTS}.**\n\n"
            f"That is the last attempt, so this ticket is now yours: labelled "
            f"`needs:human` and it will not be picked up again automatically.\n\n"
            f"Three failed runs usually means the ticket is unclear rather than "
            f"the work being hard. Read the acceptance criteria before re-queueing it."
        )
    else:
        note = (
            f"**{role.title()} produced no {ROLE_ARTIFACT.get(role, 'artifact')} — "
            f"attempt {used} of {MAX_ATTEMPTS}.**\n\n"
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

    def comments(self, number: int) -> list[dict]:
        q = urllib.parse.urlencode({"per_page": 100})
        return self._request("GET", f"/repos/{self.repo}/issues/{number}/comments?{q}") or []

    def pr_for_branch(self, branch: str) -> int | None:
        """The PR whose head is this branch, if any.

        Includes drafts on purpose: a draft PR is exactly what the engineer is
        asked to produce, and treating it as "no PR" would fail every successful
        run.

        `state=all`, also on purpose. Asking only for OPEN pull requests loses a
        race that is entirely plausible: the agent opens a PR, a reviewer merges
        it quickly, and the handoff step then finds nothing open and records a
        failed attempt on a ticket that succeeded. The ticket would be sent back
        to the board and eventually escalated as unworkable on the strength of
        having worked. A closed-unmerged PR is likewise evidence the run
        produced something; whether it was any good is the reviewer's call, not
        this function's.
        """
        owner = self.repo.split("/")[0]
        q = urllib.parse.urlencode({"head": f"{owner}:{branch}", "state": "all"})
        found = self._request("GET", f"/repos/{self.repo}/pulls?{q}") or []
        # Newest first: a re-run on the same branch should be judged by the PR
        # it just produced, not by one from a previous attempt.
        return max((p["number"] for p in found), default=None)

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


def find_evidence(gh: "GitHub", role: str, issue: dict, branch: str) -> str | None:
    """What this role left behind, described in a few words, or None.

    One question per role, and each one is answered by the repository rather
    than by the run. The engineer's is the obvious case; the analyst's is the
    one worth reading twice — its artifact is a CHANGE TO THE TICKET ITSELF, so
    "did it work" means the body now says how the work will be checked.
    """
    artifact = ROLE_ARTIFACT.get(role)

    if artifact == "pull-request":
        number = gh.pr_for_branch(branch)
        return f"Opened #{number} and handed this on." if number else None

    if artifact == "acceptance-criteria":
        body = issue.get("body") or ""
        if not has_acceptance_criteria(body):
            return None
        boxes = sum(1 for l in body.splitlines()
                    if l.strip().startswith(("- [ ]", "- [x]", "- [X]")))
        return f"Wrote {boxes} acceptance criteria onto the ticket."

    if artifact == "verification-comment":
        for c in reversed(gh.comments(issue["number"])):
            if (c.get("body") or "").lstrip().startswith("## Verification"):
                return "Posted verification evidence on the ticket."
        return None

    # A role with no artifact defined cannot be judged, and guessing would be
    # worse than saying so: it would silently pass or silently fail every run.
    raise SystemExit(f"no artifact defined for role {role!r} — see board.ROLE_ARTIFACT")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    ap.add_argument("--issue", type=int, required=True)
    ap.add_argument("--role", default="engineer")
    ap.add_argument("--branch", default="")
    ap.add_argument("--not-attempted", action="store_true",
                    help="the run never started — release without charging an attempt")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not args.repo or not token:
        print("need --repo (or GITHUB_REPOSITORY) and GITHUB_TOKEN", file=sys.stderr)
        return 2

    gh = GitHub(args.repo, token)
    issue = gh.issue(args.issue)
    # Do not go looking for an artifact on a run that never started — the lookup
    # would be a lie either way.
    evidence = None if args.not_attempted else find_evidence(gh, args.role, issue, args.branch)
    add, remove, comment = decide(issue, args.role, evidence,
                                  attempted=not args.not_attempted)

    print(f"#{args.issue}: {args.role} evidence={evidence!r} += {add} -= {remove}")
    print(comment)
    if args.apply:
        gh.apply(args.issue, add, remove, comment)
        print("applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
