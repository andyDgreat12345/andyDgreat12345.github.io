#!/usr/bin/env python3
"""The dispatcher: read the board, decide who works on what, start nothing itself.

Deliberately boring. It has no model, no opinions and no authority — it matches
labels to roles and emits a routing plan for the workflow to act on. Everything it
knows is on the board, so its behaviour is reproducible and reviewable.

Stdlib only, so it runs on a bare runner with no install step.

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

API = "https://api.github.com"

# Which role owns which stage, and the model tier it is hired at. Tiers resolve to
# concrete models in company/MODELS.md — keeping the mapping here means re-pricing
# the company is one edit, not eight prompt rewrites.
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
    """Match tickets to roles. Pure function of the board, so it is testable and
    its decisions can be replayed from the labels alone."""
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
    paused = switch.strip() == "1"
    if paused:
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
        add, note = triage(issue)
        if add:
            if args.apply:
                gh.add_labels(issue["number"], add)
            issue.setdefault("labels", []).extend({"name": n} for n in add)
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
    raise SystemExit(main())
