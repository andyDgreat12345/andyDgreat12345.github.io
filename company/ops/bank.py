#!/usr/bin/env python3
"""Bank what a run actually cost, onto the ledger branch.

The controller prices work from a table. That is a good enough estimate to trip
a cap, and it is not what happened — the model provider knows the real number
and the agent can read it back. An estimate that is never reconciled against
reality drifts silently, and a budget breaker running on a drifting estimate is
a breaker you cannot trust at the moment it matters.

So a run reports what it spent, and this writes it down.

    GITHUB_TOKEN=... python company/ops/bank.py --repo owner/name \\
        --ticket 12 --role engineer --model deepseek/deepseek-v4-flash --usd 0.0143

The ledger is append-only and lives on an orphan branch — `company-state` — for
the same reason `Chinese-ai-stocks-prediction-model` keeps `oracle-state` there:
accumulated state that versions itself, costs nothing, and never collides with
the working tree. Orphan, not branched from main, so the ledger's history is the
ledger's history and nothing else.

Stdlib only, like everything in company/ops.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

BRANCH = "company-state"
PATH = "ledger.jsonl"


class GitHub:
    def __init__(self, repo: str, token: str) -> None:
        self.repo, self.token = repo, token

    def _request(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"https://api.github.com{path}", data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if data:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req) as resp:
            payload = resp.read()
        return json.loads(payload) if payload else None

    def read_ledger(self) -> tuple[str, str | None]:
        """Returns (contents, blob sha). Absent file and absent branch both mean
        an empty ledger — a first run is not an error."""
        try:
            got = self._request(
                "GET", f"/repos/{self.repo}/contents/{PATH}?ref={BRANCH}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return "", None
            raise
        return base64.b64decode(got["content"]).decode(), got["sha"]

    def branch_exists(self) -> bool:
        try:
            self._request("GET", f"/repos/{self.repo}/git/ref/heads/{BRANCH}")
            return True
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return False
            raise

    def create_orphan_branch(self, contents: str) -> None:
        """Create `company-state` with no parent commit.

        Deliberately orphan rather than cut from main: the ledger's history
        should be the ledger's history. A branch forked from main would carry a
        stale copy of the whole repository forever, and every ledger diff would
        be read against code that is no longer there.
        """
        blob = self._request("POST", f"/repos/{self.repo}/git/blobs",
                             {"content": contents, "encoding": "utf-8"})
        tree = self._request("POST", f"/repos/{self.repo}/git/trees", {
            "tree": [{"path": PATH, "mode": "100644", "type": "blob",
                      "sha": blob["sha"]}]})
        commit = self._request("POST", f"/repos/{self.repo}/git/commits", {
            "message": "Open the ledger", "tree": tree["sha"], "parents": []})
        self._request("POST", f"/repos/{self.repo}/git/refs", {
            "ref": f"refs/heads/{BRANCH}", "sha": commit["sha"]})

    def append(self, line: str) -> None:
        if not self.branch_exists():
            self.create_orphan_branch(line)
            return
        contents, sha = self.read_ledger()
        updated = contents + line
        body = {
            "message": "Bank a run",
            "content": base64.b64encode(updated.encode()).decode(),
            "branch": BRANCH,
        }
        if sha:
            # Without the blob sha GitHub rejects the write rather than
            # clobbering, which is the behaviour we want: two runs finishing at
            # once should collide loudly, not silently drop one's spend.
            body["sha"] = sha
        self._request("PUT", f"/repos/{self.repo}/contents/{PATH}", body)


def entry(ticket: int, role: str, model: str, usd: float | None,
          now: datetime | None = None) -> dict:
    """One ledger line. `usd=None` records a hole, not a zero.

    Unmeasured spend written down as 0.00 is exactly how a bill surprises
    someone — the controller counts these separately and says so on the report.
    """
    return {
        "at": (now or datetime.now(timezone.utc)).isoformat(),
        "ticket": ticket,
        "role": role,
        "model": model,
        "input_tokens": 0,
        "output_tokens": 0,
        "usd": round(usd, 6) if usd is not None else 0.0,
        "measured": usd is not None,
        # Distinguishes a real provider figure from the controller's estimate.
        # When the two disagree it is the estimate that is wrong, and knowing
        # which lines are which is what makes that comparison possible.
        "source": "provider",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    ap.add_argument("--ticket", type=int, required=True)
    ap.add_argument("--role", default="engineer")
    ap.add_argument("--model", required=True)
    ap.add_argument("--usd", help="actual cost; omit or pass '' to record a hole")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not args.repo or not token:
        print("need --repo (or GITHUB_REPOSITORY) and GITHUB_TOKEN", file=sys.stderr)
        return 2

    try:
        usd = float(args.usd) if args.usd not in (None, "", "None") else None
    except ValueError:
        usd = None   # an unparseable cost is a hole, not a zero

    line = json.dumps(entry(args.ticket, args.role, args.model, usd)) + "\n"
    try:
        GitHub(args.repo, token).append(line)
    except urllib.error.HTTPError as exc:
        # Never fail the engineer's run over bookkeeping. A ticket that was
        # built and handed on should not be reported as failed because the
        # ledger write lost a race — but say so loudly, because a silent
        # bookkeeping failure is how the ledger quietly stops being true.
        print(f"LEDGER WRITE FAILED ({exc.code}): {line.strip()}", file=sys.stderr)
        return 0

    print(f"banked: {line.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
