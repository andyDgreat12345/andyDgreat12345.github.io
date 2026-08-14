#!/usr/bin/env python3
"""The dispatcher, Tier 0: read the board, decide who works on what, start nothing.

Deliberately boring. It has no model, no opinions and no authority — it matches
labels to roles and emits a routing plan for the workflow to act on. The routing
rules themselves live in board.py and are shared with the Temporal workflow, so
the cheap path and the funded path cannot drift apart.

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
from datetime import date

from board import build_plan, labels_of, render, triage

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

    report = render(plan, skipped, triaged, paused=False)
    print(report)
    emit("paused", "false")
    emit("plan", json.dumps(plan))

    if args.apply:
        gh.comment(gh.find_or_create_shift_report(), report)

    return 0


if __name__ == "__main__":
    # `board` resolves because Python puts a script's own directory on sys.path.
    raise SystemExit(main())
