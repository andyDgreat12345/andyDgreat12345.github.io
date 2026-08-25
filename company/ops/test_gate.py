#!/usr/bin/env python3
"""Tests for the deterministic gate.

    python company/ops/test_gate.py

A gate is trusted more than it is read, so its failure modes matter more than
its successes. Two shapes are tested hardest:

  * It must not block correct work. A gate that cries wolf gets routed around
    within a week, and then it is worse than nothing because everyone believes
    the merge was checked.
  * It must not pass the specific things it was written to catch. Each blocking
    rule has a test that fails without it.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gate


def pr(body="Closes #12\n\n## How I checked\n\n`npm test` — 16/16 pass.", draft=True):
    return {"number": 16, "body": body, "draft": draft, "head": {"ref": "agent/issue-12"}}


def diff(*paths, added=()):
    """A unified diff touching `paths`, with optional added lines."""
    out = []
    for p in paths:
        out += [f"diff --git a/{p} b/{p}", f"--- a/{p}", f"+++ b/{p}", "@@ -1 +1,2 @@"]
        out += [f"+{line}" for line in added] or ["+something"]
    return "\n".join(out)


GOOD = diff("src/lib/hq.mjs", "src/lib/hq.test.mjs", added=["export const x = 1;", "assert.ok(x);"])


def rules(findings, level="fail"):
    return {f["rule"] for f in findings if f["level"] == level}


# ---------- it must not block correct work ----------

def test_a_good_pull_request_passes_cleanly():
    """The engineer's real PR #16, in shape. If this ever fails, the gate has
    started costing more than it saves."""
    assert rules(gate.check(pr(), GOOD, 12)) == set()


def test_a_docs_only_change_needs_no_test():
    """Demanding a test for a typo fix trains people to ignore the gate."""
    assert "no-test" not in rules(gate.check(pr(), diff("company/ORG.md"), 12))


def test_a_clear_gate_says_it_is_not_an_approval():
    text = gate.render([], 16)
    assert "not an approval" in text


# ---------- it must catch what it exists for ----------

def test_touching_a_workflow_is_blocked():
    """The boundary that protects every other boundary."""
    f = gate.check(pr(), diff(".github/workflows/ci.yml", "x.test.mjs"), 12)
    assert "forbidden-path" in rules(f)


def test_a_pull_request_with_no_ticket_is_blocked():
    f = gate.check(pr(body="Did some work."), GOOD, 12)
    assert "no-ticket" in rules(f)


def test_closing_a_different_ticket_than_it_was_claimed_for_is_blocked():
    """A worker that wandered onto other work. Invisible unless something
    compares the branch it was claimed on against the ticket it closes."""
    f = gate.check(pr(body="Closes #99\n\nnpm test passes"), GOOD, 12)
    assert "wrong-ticket" in rules(f)


def test_an_unticked_criterion_is_blocked():
    """The author telling you it did not finish."""
    body = "Closes #12\n\n- [x] one\n- [ ] two\n\nnpm test passes"
    assert "unticked-criteria" in rules(gate.check(pr(body=body), GOOD, 12))


def test_changing_source_without_a_test_is_blocked():
    f = gate.check(pr(), diff("src/lib/hq.mjs"), 12)
    assert "no-test" in rules(f)


def test_a_test_with_no_assertion_is_blocked():
    """Adding an empty test is worse than adding none: it turns a gap into a
    green tick."""
    d = diff("src/lib/hq.test.mjs", added=["test('it works', () => {", "  // TODO", "});"])
    assert "test-without-assertion" in rules(gate.check(pr(), d, 12))


def test_an_assertion_anywhere_in_the_diff_satisfies_the_rule():
    d = diff("company/ops/test_x.py", added=["def test_x():", "    assert 1 == 1"])
    assert "test-without-assertion" not in rules(gate.check(pr(), d, 12))


# ---------- advisory, not blocking ----------

def test_missing_evidence_warns_rather_than_blocks():
    """Evidence is a judgement call at the margins, and a gate that blocks on
    judgement gets routed around. Say it and let it through."""
    f = gate.check(pr(body="Closes #12"), GOOD, 12)
    assert "no-evidence" in rules(f, "warn")
    assert "no-evidence" not in rules(f, "fail")


def test_a_ready_pull_request_warns_rather_than_blocks():
    f = gate.check(pr(draft=False), GOOD, 12)
    assert "not-draft" in rules(f, "warn")
    assert rules(f, "fail") == set()


# ---------- the plumbing ----------

def test_the_claimed_ticket_is_read_off_the_branch():
    assert gate.claimed_from_branch("agent/issue-12") == 12
    assert gate.claimed_from_branch("claude/some-feature") is None
    assert gate.claimed_from_branch("") is None


def test_a_human_branch_skips_the_ticket_comparison():
    """Rule 3 only makes sense for a claimed branch. On anything else there is
    nothing to compare against, and inventing a comparison would block humans."""
    f = gate.check(pr(body="Closes #99\n\nnpm test passes"), GOOD, None)
    assert "wrong-ticket" not in rules(f)


def test_changed_files_are_read_off_the_diff():
    assert gate.changed_files(diff("a/b.py", "c.mjs")) == ["a/b.py", "c.mjs"]


def test_test_files_are_recognised_in_both_languages():
    assert gate.is_test("company/ops/test_board.py")
    assert gate.is_test("src/lib/hq.test.mjs")
    assert not gate.is_test("src/lib/hq.mjs")
    assert not gate.is_test("company/ops/board.py")


def test_an_advisory_report_never_says_blocking():
    """Telling someone their pull request has "2 blocking" findings when nothing
    is blocked is how a gate loses its meaning — the next time it says blocking,
    it reads as noise. This is the exact comment the gate posted on #17."""
    f = gate.check(pr(body="Some work."), diff(".github/workflows/ci.yml"), None)
    text = gate.render(f, 17, advisory=True)
    assert "blocking" not in text.lower().replace("none blocking", "")
    assert "not a worker's" in text
    assert "forbidden-path" in text          # still says what it found


def test_the_same_findings_block_on_a_worker_branch():
    """Advisory changes the words, not the findings."""
    f = gate.check(pr(body="Some work."), diff(".github/workflows/ci.yml"), 12)
    assert "FAIL" in gate.render(f, 16, advisory=False)


def test_the_report_names_the_rule_and_where_it_lives():
    """Someone reading a blocked PR needs to know the rule is a line of code
    they can go argue with, not a model's opinion they have to persuade."""
    f = gate.check(pr(body="nothing"), diff("src/x.mjs"), 12)
    text = gate.render(f, 16)
    assert "company/ops/gate.py" in text
    assert "nothing here to persuade" in text
    assert "FAIL" in text


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  ok    {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
