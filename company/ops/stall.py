#!/usr/bin/env python3
"""Detect a board that is running but not moving.

The watchdog in .github/workflows/company-watchdog.yml catches a heartbeat that
STOPPED. This catches one that runs perfectly and achieves nothing — green
heartbeats, quiet watchdog, tickets piling up. OPERATING.md ranks that shape as
the failure most likely to kill an unattended company, and the Inbox stall bug
(#4) was exactly it.

    GITHUB_TOKEN=... python company/ops/stall.py --repo owner/name [--apply]

Split the way board.py is: `assess()` is pure and decides, everything else does
I/O. Stdlib only — company/ops carries no dependencies so a bare runner can
always run it, and CI asserts that.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from board import STAGES, labels_of  # noqa: E402

ALERT_TITLE = "Watchdog: board has stalled"
DEFAULT_THRESHOLD_HOURS = 6

# Tickets in these states are not stalled — they are correctly waiting.
# `needs:human` is the company asking the owner a question; `status:blocked`
# is a documented dead end. Counting either as a stall would train you to
# ignore the alarm, which is worse than not having one.
EXCUSED = {"needs:human", "status:blocked"}


def stage_of(issue: dict) -> str | None:
    return next((n for n in labels_of(issue) if n in STAGES), None)


def assess(tickets: list[dict], now: datetime, threshold_hours: int = DEFAULT_THRESHOLD_HOURS,
           paused: bool = False) -> dict:
    """Decide whether the board has stalled.

    `tickets` are dicts with: number, title, stage, moved_at (aware datetime),
    and labels. Pure — no clock, no network — so every branch is testable.
    """
    cutoff = now - timedelta(hours=threshold_hours)

    if paused:
        return {"stalled": False, "reason": "company is paused", "stuck": []}
    if not tickets:
        return {"stalled": False, "reason": "board is empty", "stuck": []}

    candidates = [t for t in tickets if not (set(t.get("labels", [])) & EXCUSED)]
    if not candidates:
        return {
            "stalled": False,
            "reason": "every open ticket is waiting on the owner or blocked",
            "stuck": [],
        }

    recent = [t for t in candidates if t["moved_at"] > cutoff]
    if recent:
        return {
            "stalled": False,
            "reason": f"{len(recent)} ticket(s) moved within {threshold_hours}h",
            "stuck": [],
        }

    stuck = sorted(candidates, key=lambda t: t["moved_at"])
    return {
        "stalled": True,
        "reason": f"no ticket has changed stage in {threshold_hours}h",
        "stuck": stuck,
    }


def render(verdict: dict, now: datetime, threshold_hours: int) -> str:
    lines = [
        f"The board has {len(verdict['stuck'])} open ticket(s) and none has changed "
        f"stage in {threshold_hours} hours. The heartbeat may well be running — "
        "this alarm is for the case where it runs and nothing moves.",
        "",
        "| # | stage | stuck for | title |",
        "|---|---|---|---|",
    ]
    for t in verdict["stuck"]:
        hours = int((now - t["moved_at"]).total_seconds() // 3600)
        age = f"{hours}h" if hours < 48 else f"{hours // 24}d"
        lines.append(f"| #{t['number']} | {t['stage'] or '—'} | {age} | {t['title'][:60]} |")
    lines += [
        "",
        "Likely causes, cheapest first:",
        "",
        "- No role is wired up for the stage these are sitting in — check "
        "`company/ORG.md` for who owns it.",
        "- The worker is up but has no schedule, so it polls an empty queue forever.",
        "- Triage is classifying tickets without advancing them (this is what #4 was).",
        "",
        "Silence this by moving a ticket, pausing the company, or labelling the "
        "stuck tickets `needs:human` if they are genuinely yours.",
    ]
    return "\n".join(lines)


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

    def open_issues(self) -> list[dict]:
        q = urllib.parse.urlencode({"state": "open", "per_page": 100})
        got = self._request("GET", f"/repos/{self.repo}/issues?{q}") or []
        return [i for i in got if "pull_request" not in i]

    def last_stage_change(self, number: int, created_at: str) -> datetime:
        """When this ticket last entered or left a stage.

        Deliberately NOT `updated_at`: that also moves on comments, so a board
        where agents chat but never advance anything would look healthy — which
        is precisely the failure being detected. Label events are the only
        honest signal.
        """
        events = self._request("GET", f"/repos/{self.repo}/issues/{number}/events?per_page=100") or []
        stamps = [
            e["created_at"]
            for e in events
            if e.get("event") in ("labeled", "unlabeled")
            and (e.get("label") or {}).get("name") in STAGES
        ]
        # A ticket with no stage event yet has been sitting since it was filed.
        return _parse(max(stamps) if stamps else created_at)

    def find_open_alert(self) -> int | None:
        q = urllib.parse.urlencode(
            {"q": f'repo:{self.repo} is:issue is:open in:title "{ALERT_TITLE}"'}
        )
        found = self._request("GET", f"/search/issues?{q}") or {}
        for item in found.get("items", []):
            if item["title"] == ALERT_TITLE:
                return item["number"]
        return None

    def open_alert(self, body: str) -> int:
        made = self._request(
            "POST",
            f"/repos/{self.repo}/issues",
            {
                "title": ALERT_TITLE,
                "body": body,
                "labels": ["dept:hq", "needs:human", "risk:med"],
            },
        )
        return made["number"]

    def close_alert(self, number: int, comment: str) -> None:
        self._request("POST", f"/repos/{self.repo}/issues/{number}/comments", {"body": comment})
        self._request("PATCH", f"/repos/{self.repo}/issues/{number}",
                      {"state": "closed", "state_reason": "completed"})


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    ap.add_argument("--hours", type=int,
                    default=int(os.environ.get("COMPANY_STALL_HOURS", DEFAULT_THRESHOLD_HOURS)))
    ap.add_argument("--apply", action="store_true", help="open or close the alert issue")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not args.repo or not token:
        print("need --repo (or GITHUB_REPOSITORY) and GITHUB_TOKEN", file=sys.stderr)
        return 2

    gh = GitHub(args.repo, token)
    paused = (os.environ.get("COMPANY_PAUSED") or "0").strip() == "1"
    now = datetime.now(timezone.utc)

    tickets = []
    for issue in gh.open_issues():
        names = labels_of(issue)
        if issue["title"] == ALERT_TITLE:
            continue  # the alarm is not a ticket, and would otherwise stall itself
        tickets.append({
            "number": issue["number"],
            "title": issue["title"],
            "stage": stage_of(issue),
            "labels": list(names),
            "moved_at": gh.last_stage_change(issue["number"], issue["created_at"]),
        })

    verdict = assess(tickets, now, args.hours, paused)
    existing = gh.find_open_alert()

    print(f"{'STALLED' if verdict['stalled'] else 'ok'} — {verdict['reason']}")

    if verdict["stalled"]:
        if existing:
            print(f"alert #{existing} already open — not duplicating")
            return 0
        body = render(verdict, now, args.hours)
        print(body)
        if args.apply:
            print(f"opened alert #{gh.open_alert(body)}")
    elif existing:
        # Recovery is as worth reporting as the failure: an alert nobody closes
        # becomes wallpaper, and then the next real one is ignored too.
        print(f"recovered — closing alert #{existing}")
        if args.apply:
            gh.close_alert(existing, f"Board is moving again — {verdict['reason']}. Closing.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
