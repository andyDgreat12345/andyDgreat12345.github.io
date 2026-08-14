#!/usr/bin/env python3
"""Create the company's label vocabulary. Idempotent — safe to re-run.

The labels ARE the routing table: the dispatcher in board.py reads nothing else,
so this file and that one have to agree. Keep them in sync.

Runs two ways:

    # In Actions, via the company-bootstrap workflow — no local setup, works
    # from a phone. This is the normal path.

    # Or locally, against any of the four repos:
    GITHUB_TOKEN=... python company/ops/labels.py --repo owner/name
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

# (name, colour, description). Grouped as in ORG.md.
LABELS = [
    # Departments — which product line owns the ticket.
    ("dept:site", "1f6feb", "Personal site / front office"),
    ("dept:casewriter", "1f6feb", "AI case writer tool"),
    ("dept:market", "1f6feb", "Chinese stocks prediction model"),
    ("dept:admissions", "1f6feb", "College acceptance model"),
    ("dept:hq", "1f6feb", "The company itself"),
    # Size — size:l requires the owner's approval before an engineer starts.
    ("size:s", "c5def5", "Under an agent-hour"),
    ("size:m", "c5def5", "A few agent-hours"),
    ("size:l", "c5def5", "Needs owner approval on the spec first"),
    # Risk — drives who may merge, and whether auto-merge is allowed at all.
    ("risk:low", "0e8a16", "Reversible, no user impact; auto-merge eligible"),
    ("risk:med", "fbca04", "User-visible or awkward to undo"),
    ("risk:high", "d93f0b", "Money, credentials, personal data, or public"),
    # Stages — exactly one on a ticket at a time; the dispatcher routes on these.
    ("status:inbox", "ededed", "Filed, not yet triaged"),
    ("status:needs-spec", "ededed", "Analyst: write acceptance criteria"),
    ("status:ready", "ededed", "Engineer: build it"),
    ("status:building", "ededed", "Claimed by an engineer"),
    ("status:verify", "ededed", "SRE: prove it runs"),
    ("status:ship", "ededed", "Owner: merge and deploy"),
    ("status:done", "ededed", "Shipped and reported"),
    ("status:blocked", "b60205", "Cannot proceed; reason in a comment"),
    # Claims — the company's only lock. A worker holds one of these while it
    # works, and the fan-out will not hand a claimed ticket to anyone else.
    # They are LEASES: the heartbeat releases one that has been held too long,
    # because a worker that dies mid-ticket cannot release its own claim.
    ("claim:analyst", "d4c5f9", "Held by the analyst"),
    ("claim:engineer", "d4c5f9", "Held by the engineer"),
    ("claim:reviewer", "d4c5f9", "Held by the reviewer"),
    ("claim:sre", "d4c5f9", "Held by the SRE"),
    ("claim:researcher", "d4c5f9", "Held by the researcher"),
    ("claim:comms", "d4c5f9", "Held by comms"),
    # The escalation flag. The dispatcher will not touch anything wearing this.
    ("needs:human", "5319e7", "Owner's call — agents must not act"),
]

API = "https://api.github.com"


def request(method: str, path: str, token: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        payload = resp.read()
    return json.loads(payload) if payload else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not args.repo or not token:
        print("need --repo (or GITHUB_REPOSITORY) and GITHUB_TOKEN", file=sys.stderr)
        return 2

    created = updated = 0
    for name, color, description in LABELS:
        payload = {"name": name, "color": color, "description": description}
        try:
            request("POST", f"/repos/{args.repo}/labels", token, payload)
            created += 1
            print(f"  + {name}")
        except urllib.error.HTTPError as exc:
            if exc.code != 422:  # 422 == already exists
                raise
            # Update in place so a colour or description change propagates.
            request("PATCH", f"/repos/{args.repo}/labels/{name}", token, payload)
            updated += 1
            print(f"  = {name}")

    print(f"\n{created} created, {updated} already present, {len(LABELS)} total.")
    print("Next: make a Project board with one column per status label.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
