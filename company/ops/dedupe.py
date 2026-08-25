#!/usr/bin/env python3
"""Catch a ticket that has already been filed, before anyone pays to build it.

Not a role — a janitor. It exists because the board produced the bug it
prevents: #12 and #13 were the same ticket filed twice, and nothing noticed.
The second one would have been triaged, claimed, worked and paid for, and the
only sign would have been two pull requests changing the same file in slightly
different ways.

Duplicates of CLOSED tickets matter as much as open ones — more, really. An open
duplicate wastes a claim; a duplicate of something already shipped wastes a
claim and then produces a change nobody needed.

The threshold is high on purpose. A dedupe check that flags cousins gets
ignored, and an ignored check is worse than none because it makes the board look
supervised. When it does fire it labels `needs:human` rather than closing
anything: deciding two tickets are the same is a judgement, and this has none.

    GITHUB_TOKEN=... python company/ops/dedupe.py --repo owner/name --issue 13

Stdlib only, like everything in company/ops.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stall import is_ticket  # noqa: E402 — the same paperwork filter

# Above this, two titles are the same ticket. Tuned so #12 and #13 (identical
# titles) fire and ordinary neighbours do not: "Add a dark mode toggle" against
# "Add a print stylesheet" scores far below.
TITLE_THRESHOLD = 0.80

# Body agreement alone is not enough — two tickets from the same template share
# most of their words. It only breaks a tie on a title that is already close.
BODY_THRESHOLD = 0.60
NEAR_TITLE = 0.65

# Words that carry no signal about what a ticket is about. Without this, "Add
# the X page" and "Add the Y page" score higher than they deserve.
NOISE = {"a", "an", "and", "the", "to", "for", "on", "in", "of", "is", "it",
         "add", "fix", "update", "make", "show", "each", "who", "how"}


# How alike two WORDS must be to count as the same word. Catches "lease" and
# "leases", refuses "lease" and "ledger".
WORD_MATCH = 0.85


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in NOISE]


def normalise(text: str) -> str:
    """Lowercase, strip punctuation and noise words, collapse whitespace."""
    return " ".join(tokens(text))


def similarity(a: str, b: str) -> float:
    """Agreement between two texts, by matched words rather than by characters.

    Character similarity is the obvious choice and it is wrong here, in a way
    that took a false positive to see: "lease dashboard" and "ledger dashboard"
    score 0.84 against each other because they share letters, not meaning. Two
    genuinely different tickets would have been flagged as one.

    Words are matched fuzzily so "lease" still finds "leases" — a plural or a
    typo should not hide a duplicate — but "ledger" is not close enough to
    "lease" to count. Then Dice over the matched words, which is stable when the
    two titles are different lengths.
    """
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0

    taken = [False] * len(tb)
    shared = 0
    for word in ta:
        best, best_i = 0.0, None
        for i, other in enumerate(tb):
            if taken[i]:
                continue
            ratio = 1.0 if word == other else difflib.SequenceMatcher(None, word, other).ratio()
            if ratio > best:
                best, best_i = ratio, i
        # Each word may only be spent once, so "page page page" against "page"
        # does not score three times.
        if best_i is not None and best >= WORD_MATCH:
            taken[best_i] = True
            shared += 1

    return 2 * shared / (len(ta) + len(tb))


def find_duplicates(new: dict, existing: list[dict]) -> list[dict]:
    """Tickets that look like `new`, most similar first. Pure.

    Compares against open AND closed tickets, and skips the company's own
    paperwork — the shift report is filed daily with the same title every time,
    which would otherwise be flagged as a duplicate of itself forever.
    """
    out = []
    for other in existing:
        if other["number"] == new["number"]:
            continue
        if not is_ticket(other.get("title", "")):
            continue

        title = similarity(new.get("title", ""), other.get("title", ""))
        body = similarity(new.get("body", ""), other.get("body", ""))

        # A very close title is enough on its own. A merely near one needs the
        # body to agree as well, which is what stops a family of similarly
        # named tickets flagging each other.
        if title >= TITLE_THRESHOLD or (title >= NEAR_TITLE and body >= BODY_THRESHOLD):
            out.append({
                "number": other["number"],
                "title": other.get("title", ""),
                "state": other.get("state", "open"),
                "title_score": round(title, 3),
                "body_score": round(body, 3),
            })

    return sorted(out, key=lambda d: -d["title_score"])


def render(new: dict, matches: list[dict]) -> str:
    lines = [
        f"**Possible duplicate.** This looks like "
        + ", ".join(f"#{m['number']}" for m in matches)
        + ".",
        "",
        "| # | state | title | title match |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| #{m['number']} | {m['state']} | {m['title'][:60]} | {m['title_score']:.0%} |"
        for m in matches
    ]
    closed = [m for m in matches if m["state"] != "open"]
    lines += [
        "",
        "Labelled `needs:human` so it is not claimed before you look. Deciding "
        "two tickets are the same is a judgement and this check has none — it "
        "compares text and nothing else.",
    ]
    if closed:
        lines += [
            "",
            "**One of those is already closed**, which is the expensive case: "
            "without this the company would have built something it had already "
            "shipped, and the only sign would have been two pull requests "
            "changing the same file.",
        ]
    lines += [
        "",
        "If it is not a duplicate, remove `needs:human` and the board picks it "
        "up on the next heartbeat.",
    ]
    return "\n".join(lines)


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

    def issue(self, number: int) -> dict:
        return self._request("GET", f"/repos/{self.repo}/issues/{number}")

    def recent(self, limit: int = 100) -> list[dict]:
        """Open and recently closed issues. Closed ones are included because a
        duplicate of shipped work is the costlier miss."""
        q = urllib.parse.urlencode(
            {"state": "all", "per_page": limit, "sort": "created", "direction": "desc"})
        got = self._request("GET", f"/repos/{self.repo}/issues?{q}") or []
        return [i for i in got if "pull_request" not in i]

    def flag(self, number: int, body: str) -> None:
        self._request("POST", f"/repos/{self.repo}/issues/{number}/comments",
                      {"body": body})
        self._request("POST", f"/repos/{self.repo}/issues/{number}/labels",
                      {"labels": ["needs:human"]})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    ap.add_argument("--issue", type=int, required=True)
    ap.add_argument("--apply", action="store_true", help="comment and label")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not args.repo or not token:
        print("need --repo (or GITHUB_REPOSITORY) and GITHUB_TOKEN", file=sys.stderr)
        return 2

    gh = GitHub(args.repo, token)
    new = gh.issue(args.issue)

    # A ticket already wearing needs:human is already the owner's. Flagging it
    # again would be noise on a ticket nobody is going to claim anyway.
    if any(l["name"] == "needs:human" for l in new.get("labels", [])):
        print(f"#{args.issue} already needs:human — nothing to add")
        return 0

    matches = find_duplicates(new, gh.recent())
    if not matches:
        print(f"#{args.issue} looks new")
        return 0

    report = render(new, matches)
    print(report)
    if args.apply:
        gh.flag(args.issue, report)
        print("flagged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
