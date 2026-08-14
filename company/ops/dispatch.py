#!/usr/bin/env python3
"""The dispatcher, Tier 0: read the board, decide who works on what, claim it.

Deliberately boring. It has no model, no opinions and no authority — it matches
labels to roles, claims work for the roles that have workers, and reaps leases
that expired. The rules live in board.py and assign.py, both shared with the
Temporal workflow, so the cheap path and the funded path cannot drift apart.

It starts nothing directly: it applies a `claim:<role>` label and the worker
wakes on that label. Which is why the token matters — see the warning about
COMPANY_CLAIMS_WAKE_WORKERS below.

Stdlib only, so it runs on a bare runner with no install step. The Temporal
version in company/temporal/ is the durable equivalent — see that README for when
to move across.

    GITHUB_TOKEN=...  python company/ops/dispatch.py --repo owner/name

Outputs a JSON plan on stdout and, under Actions, sets the `plan` and `paused`
step outputs. Pass --apply to also write labels and post the heartbeat comment.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

from assign import LEASE_MINUTES, brief, claim_label, claimed_role, fan_out
from assign import render as render_fanout
from board import attempts, build_plan, labels_of, render, triage

API = "https://api.github.com"


class GitHub:
    def __init__(self, repo: str, token: str) -> None:
        self.repo = repo
        self.token = token

    def _request(self, method: str, path: str, body: dict | None = None):
        url = path if path.startswith("http") else f"{API}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if data:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req) as resp:
            payload = resp.read()
        return json.loads(payload) if payload else None

    def issues(self) -> list[dict]:
        """Open issues, pull requests filtered out — a PR is not a ticket."""
        out: list[dict] = []
        page = 1
        while True:
            q = urllib.parse.urlencode({"state": "open", "per_page": 100, "page": page})
            batch = self._request("GET", f"/repos/{self.repo}/issues?{q}") or []
            out += [i for i in batch if "pull_request" not in i]
            if len(batch) < 100:
                return out
            page += 1

    def open_prs(self) -> list[dict]:
        q = urllib.parse.urlencode({"state": "open", "per_page": 100})
        return self._request("GET", f"/repos/{self.repo}/pulls?{q}") or []

    def variable(self, name: str) -> str | None:
        try:
            got = self._request("GET", f"/repos/{self.repo}/actions/variables/{name}")
            return (got or {}).get("value")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def add_labels(self, number: int, labels: list[str]) -> None:
        self._request("POST", f"/repos/{self.repo}/issues/{number}/labels", {"labels": labels})

    def remove_label(self, number: int, label: str) -> None:
        """404 means the label was already off the issue, which is the state we
        wanted — so it is success, not an error. That is what makes a retry after
        an ambiguous failure safe."""
        try:
            self._request(
                "DELETE",
                f"/repos/{self.repo}/issues/{number}/labels/{urllib.parse.quote(label)}",
            )
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise

    def comment(self, number: int, body: str) -> None:
        self._request("POST", f"/repos/{self.repo}/issues/{number}/comments", {"body": body})

    def claim_since(self, number: int, label: str) -> str | None:
        """When the current claim was applied, as an ISO timestamp.

        From label events, for the same reason stall.py uses them: `updated_at`
        also moves on comments, so a worker that comments busily and finishes
        nothing would keep renewing its own lease forever — which is exactly the
        worker the lease exists to reap.

        Reads the LAST time the label was applied, not the first, so a ticket
        legitimately re-claimed after an earlier release starts a fresh lease.
        """
        events = self._request(
            "GET", f"/repos/{self.repo}/issues/{number}/events?per_page=100") or []
        stamps = [
            e["created_at"] for e in events
            if e.get("event") == "labeled" and (e.get("label") or {}).get("name") == label
        ]
        return max(stamps) if stamps else None

    def find_or_create_shift_report(self) -> int:
        """One shift-report issue per day; every heartbeat comments on it."""
        title = f"Shift report — {date.today().isoformat()}"
        q = urllib.parse.urlencode(
            {"q": f'repo:{self.repo} is:issue is:open in:title "{title}"'}
        )
        found = self._request("GET", f"/search/issues?{q}") or {}
        for item in found.get("items", []):
            if item["title"] == title:
                return item["number"]
        made = self._request(
            "POST",
            f"/repos/{self.repo}/issues",
            {
                "title": title,
                "body": "Automated heartbeat log. One comment per dispatcher run.",
                "labels": ["dept:hq"],
            },
        )
        return made["number"]


def _when(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def emit(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as fh:
            fh.write(f"{name}={value}\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    ap.add_argument("--apply", action="store_true", help="write labels and comment")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not args.repo or not token:
        print("need --repo (or GITHUB_REPOSITORY) and GITHUB_TOKEN", file=sys.stderr)
        return 2

    gh = GitHub(args.repo, token)

    # The kill switch is checked before anything else, always. See CHARTER.md.
    # Under Actions the workflow passes `vars.COMPANY_PAUSED` straight through as
    # an env var; the API read is the fallback for running this off a runner,
    # where the default token may not carry variables-read permission.
    switch = os.environ.get("COMPANY_PAUSED")
    if switch is None:
        switch = gh.variable("COMPANY_PAUSED") or "0"
    if switch.strip() == "1":
        report = render([], [], [], paused=True)
        print(report)
        emit("paused", "true")
        emit("plan", "[]")
        if args.apply:
            gh.comment(gh.find_or_create_shift_report(), report)
        return 0

    issues = gh.issues()

    triaged: list[str] = []
    for issue in issues:
        if "status:inbox" not in labels_of(issue):
            continue
        add, remove, note = triage(issue)
        if add or remove:
            if args.apply:
                if add:
                    gh.add_labels(issue["number"], add)
                for name in remove:
                    gh.remove_label(issue["number"], name)
            # Reflect the writes locally so build_plan below sees the board as it
            # now is, rather than as it was when we read it.
            current = [l for l in issue.get("labels", []) if l["name"] not in remove]
            issue["labels"] = current + [{"name": n} for n in add]
            triaged.append(f"#{issue['number']} → {', '.join(add)}")
        if note:
            triaged.append(f"#{issue['number']} ({note})")

    in_review = sum(1 for pr in gh.open_prs() if not pr.get("draft"))
    plan, skipped = build_plan(issues, in_review)

    # Fan-out. This used to live only in the Temporal workflow, which meant the
    # free tier planned work and then never claimed it — the engineer waits on a
    # `claim:engineer` label that nothing produced, and every ticket sat at
    # status:ready looking healthy. The two paths share assign.py for the same
    # reason they share board.py: so they cannot disagree about who holds what.
    now = datetime.now(timezone.utc)
    held = []
    for issue in issues:
        role = claimed_role(labels_of(issue))
        if role is None:
            continue
        since = gh.claim_since(issue["number"], claim_label(role))
        # An unreadable lease fails toward release, never toward holding forever.
        held.append({
            "issue": issue["number"],
            "role": role,
            "since": _when(since or issue["created_at"]),
        })

    claims, releases, deferred = fan_out(plan, held, now)
    by_number = {i["number"]: i for i in issues}

    # A claim applied with the default GITHUB_TOKEN does not trigger the
    # `issues.labeled` workflow the worker wakes on. The label lands, the board
    # looks busy, the heartbeat looks green, and nothing ever starts. That is the
    # quietest failure this company has, so it is said out loud on every report
    # that issues a claim while running in that state.
    wake = (os.environ.get("COMPANY_CLAIMS_WAKE_WORKERS") or "yes").strip() != "no"
    warning = ""
    if claims and not wake:
        warning = (
            "\n\n**Claims applied with the default token — no worker will wake.** "
            "A label applied by `GITHUB_TOKEN` does not trigger `issues.labeled`, "
            "so the engineer will not start. Add the `PAT_TOKEN` repository "
            "secret (see `company/workers/README.md`); the ticket is claimed and "
            "waiting either way."
        )

    # Releases first, so capacity freed this cycle is capacity a claim can use.
    for rel in releases:
        n = attempts(by_number.get(rel["issue"], {}))
        if args.apply:
            gh.add_labels(rel["issue"], [f"attempt:{n + 1}"])
            gh.remove_label(rel["issue"], claim_label(rel["role"]))
            if n:
                gh.remove_label(rel["issue"], f"attempt:{n}")

    for claim in claims:
        if args.apply:
            # Brief first, then the label. The label is what wakes the worker, so
            # taking it before the instructions exist is a race the worker loses.
            gh.comment(claim["issue"],
                       brief(claim, by_number.get(claim["issue"], {}), now, LEASE_MINUTES))
            gh.add_labels(claim["issue"], [claim["label"]])

    report = render(plan, skipped, triaged, paused=False)
    fanout = render_fanout(claims, releases, deferred)
    if fanout:
        report = f"{report}\n\n{fanout}{warning}"
    print(report)
    emit("paused", "false")
    emit("plan", json.dumps(plan))

    if args.apply:
        gh.comment(gh.find_or_create_shift_report(), report)

    return 0


if __name__ == "__main__":
    # `board` resolves because Python puts a script's own directory on sys.path.
    raise SystemExit(main())
