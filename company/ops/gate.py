#!/usr/bin/env python3
"""The deterministic gate: what a reviewer checks that needs no judgement.

A model reviewer is the plan, and it is not the first thing worth having. Most
of what goes wrong with agent output is not subtle — it is a workflow file
quietly edited, a pull request that closes a different ticket than the one it
was claimed for, a test with no assertion in it, a "verified" claim with nothing
behind it. Every one of those is checkable by a function against the diff.

Which makes this gate strictly better than a model at its own job:

  * It cannot hallucinate a finding, and cannot miss one it was written to catch.
  * It costs nothing and needs no API key, so it cannot be switched off by a
    spend cap or leak one to a fork.
  * It shares no training with the builder, so it cannot agree with the builder's
    blind spots — which is the entire reason MODELS.md wants a different family
    at the gate.

It does not replace a reviewer. It catches the boring half so a reviewer, human
or otherwise, spends its attention on the half that needs judgement.

    GITHUB_TOKEN=... python company/ops/gate.py --repo owner/name --pr 16

Exit code 1 when anything FAILS, which is what makes it a gate rather than a
comment. Stdlib only, like everything in company/ops.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request

# Paths a worker may never touch. A worker that can rewrite its own gates has
# none — this is the same rule the work order states, enforced where a prompt
# cannot be talked out of it.
FORBIDDEN = (".github/workflows/",)

# Source that, when changed, ought to come with a test. Docs and config are
# deliberately absent: demanding a test for a typo fix trains people to ignore
# the gate, and a gate that is routinely ignored is worse than no gate.
NEEDS_TESTS = (".py", ".mjs", ".js", ".ts", ".astro")
TEST_MARKERS = ("test_", ".test.", "_test.")

# Phrases that indicate the author actually ran something. Deliberately generous:
# this catches "I claimed it works and showed nothing", not "I described my
# evidence in words I did not anticipate".
EVIDENCE = (
    "npm test", "npm run build", "pytest", "python company/ops/test",
    "passed", "pass\n", "exit 0", "how i checked", "verification", "verified",
)


def _added_lines(diff: str) -> list[str]:
    return [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]


def changed_files(diff: str) -> list[str]:
    """Paths touched by a unified diff."""
    out = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            out.append(line[6:].strip())
    return out


def is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return any(m in name for m in TEST_MARKERS)


def check(pr: dict, diff: str, claimed_issue: int | None) -> list[dict]:
    """Every finding, as {level, rule, detail}. Pure — no network, no clock.

    `level` is "fail" or "warn". Warnings are printed and do not stop the merge;
    a gate that blocks on taste rather than on rules gets routed around.
    """
    findings: list[dict] = []
    body = (pr.get("body") or "")
    lower = body.lower()
    files = changed_files(diff)

    def fail(rule, detail):
        findings.append({"level": "fail", "rule": rule, "detail": detail})

    def warn(rule, detail):
        findings.append({"level": "warn", "rule": rule, "detail": detail})

    # 1. The boundary that protects every other boundary.
    touched = [f for f in files if any(f.startswith(p) for p in FORBIDDEN)]
    if touched:
        fail("forbidden-path",
             "changes " + ", ".join(f"`{f}`" for f in touched) +
             " — a worker that can rewrite its own gates has none")

    # 2. A pull request has to say which ticket it closes, or the board cannot
    #    follow it and the ticket will sit at verify forever.
    closes = {int(n) for n in re.findall(r"(?:closes|fixes|resolves)\s+#(\d+)", lower)}
    if not closes:
        fail("no-ticket",
             "body does not say `Closes #N`, so nothing links this back to the board")

    # 3. And it has to be the ticket it was CLAIMED for. A worker that wandered
    #    onto other work is the failure `one ticket, this one` exists to prevent,
    #    and it is invisible unless something compares the two.
    elif claimed_issue is not None and claimed_issue not in closes:
        fail("wrong-ticket",
             f"claimed for #{claimed_issue} but closes "
             + ", ".join(f"#{n}" for n in sorted(closes)))

    # 4. Unticked boxes in the author's own body. The engineer's template ticks
    #    each acceptance criterion as it is met, so an unticked one is the author
    #    telling you it did not finish.
    unticked = [l.strip() for l in body.splitlines() if l.strip().startswith("- [ ]")]
    if unticked:
        fail("unticked-criteria",
             f"{len(unticked)} unticked checkbox(es) in the description: "
             + "; ".join(u[:60] for u in unticked[:3]))

    # 5. Source changed and no test changed with it.
    src = [f for f in files if f.endswith(NEEDS_TESTS) and not is_test(f)]
    tests = [f for f in files if is_test(f)]
    if src and not tests:
        fail("no-test",
             "changes " + ", ".join(f"`{f}`" for f in src[:4]) +
             " without touching any test file")

    # 6. Tests that assert nothing. Adding an empty test is worse than adding
    #    none: it turns a gap into a green tick.
    if tests:
        added = _added_lines(diff)
        if any(re.match(r"\s*(def test_|test\()", l) for l in added) and not any(
                re.search(r"\bassert\b", l) for l in added):
            fail("test-without-assertion",
                 "adds a test but no assertion — an empty test turns a gap into a green tick")

    # 7. Evidence. Not proof, just a sign that something was actually run.
    if not any(marker in lower for marker in EVIDENCE):
        warn("no-evidence",
             "body shows no sign of anything being run — say what you ran and what came back")

    # 8. A draft is what the engineer is asked to produce, so this is a note
    #    rather than a finding: it exists so a human skimming the gate output
    #    knows the state without opening the PR.
    if not pr.get("draft"):
        warn("not-draft",
             "not a draft — workers open drafts; a ready PR means a human marked it so")

    return findings


def render(findings: list[dict], pr_number: int) -> str:
    fails = [f for f in findings if f["level"] == "fail"]
    warns = [f for f in findings if f["level"] == "warn"]

    if not fails and not warns:
        return (f"**Gate — clear.** Nothing mechanical to say about #{pr_number}.\n\n"
                "This checks only what needs no judgement: forbidden paths, the "
                "ticket link, unticked criteria, missing tests, assertionless "
                "tests. A clear gate is not an approval — it means the boring "
                "half is done and the half that needs a reviewer is not.")

    lines = [f"**Gate — {len(fails)} blocking, {len(warns)} advisory.**", ""]
    for f in fails:
        lines.append(f"- **FAIL `{f['rule']}`** — {f['detail']}")
    for w in warns:
        lines.append(f"- warn `{w['rule']}` — {w['detail']}")
    lines += [
        "",
        "Blocking findings are rules, not opinions — each one is a line in "
        "`company/ops/gate.py` and none of them involve a model. Fix or argue "
        "with the rule; there is nothing here to persuade.",
    ]
    return "\n".join(lines)


class GitHub:
    def __init__(self, repo: str, token: str) -> None:
        self.repo, self.token = repo, token

    def _get(self, path: str, accept: str = "application/vnd.github+json"):
        req = urllib.request.Request(f"https://api.github.com{path}")
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", accept)
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
        return raw if "diff" in accept else json.loads(raw)

    def pr(self, number: int) -> dict:
        return self._get(f"/repos/{self.repo}/pulls/{number}")

    def diff(self, number: int) -> str:
        return self._get(f"/repos/{self.repo}/pulls/{number}",
                         accept="application/vnd.github.v3.diff").decode()

    def comment(self, number: int, body: str) -> None:
        data = json.dumps({"body": body}).encode()
        req = urllib.request.Request(
            f"https://api.github.com/repos/{self.repo}/issues/{number}/comments",
            data=data, method="POST")
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("Content-Type", "application/json")
        urllib.request.urlopen(req).read()


def claimed_from_branch(ref: str) -> int | None:
    """`agent/issue-12` → 12. Anything else → None, and rule 3 is skipped."""
    m = re.fullmatch(r"agent/issue-(\d+)", ref or "")
    return int(m.group(1)) if m else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--comment", action="store_true", help="post the result on the PR")
    ap.add_argument("--advisory", action="store_true",
                    help="report findings but always exit 0")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not args.repo or not token:
        print("need --repo (or GITHUB_REPOSITORY) and GITHUB_TOKEN", file=sys.stderr)
        return 2

    gh = GitHub(args.repo, token)
    pr = gh.pr(args.pr)
    findings = check(pr, gh.diff(args.pr), claimed_from_branch(pr["head"]["ref"]))
    report = render(findings, args.pr)
    print(report)

    if args.comment:
        gh.comment(args.pr, report)

    # Advisory mode exists for pull requests a human wrote. The rules encode how
    # a WORKER is asked to submit work — branch naming, a ticket link, ticked
    # criteria — and blocking a human on a worker's conventions would teach
    # everyone to route around the gate, which is how a gate stops meaning
    # anything.
    if args.advisory:
        return 0
    return 1 if any(f["level"] == "fail" for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
