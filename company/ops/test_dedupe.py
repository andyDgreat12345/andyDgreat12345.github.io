#!/usr/bin/env python3
"""Tests for the duplicate checker.

    python company/ops/test_dedupe.py

The real case is first: #12 and #13, filed four hours apart with the same title,
which nothing caught. Everything after it is about not crying wolf — a dedupe
check that flags cousins gets ignored, and an ignored check is worse than none
because it makes the board look supervised when it is not.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dedupe

# Verbatim from the board.
TWELVE = {
    "number": 12,
    "title": "Show who is holding each ticket on /hq",
    "body": "The fan-out now puts claim: labels on tickets, and those claims are "
            "leases that expire after 90 minutes. /hq doesn't know about any of it.",
    "state": "open",
}
THIRTEEN = dict(TWELVE, number=13)


def issue(number, title, body="", state="open"):
    return {"number": number, "title": title, "body": body, "state": state}


# ---------- the case that motivated it ----------

def test_the_real_duplicate_is_caught():
    """#12 and #13. Filed four hours apart, identical titles, nothing noticed —
    the second would have been triaged, claimed, worked and paid for."""
    matches = dedupe.find_duplicates(THIRTEEN, [TWELVE])
    assert [m["number"] for m in matches] == [12]
    assert matches[0]["title_score"] > 0.9


def test_a_duplicate_of_closed_work_is_caught_too():
    """The costlier miss: the company builds something it already shipped."""
    shipped = dict(TWELVE, state="closed")
    matches = dedupe.find_duplicates(THIRTEEN, [shipped])
    assert matches and matches[0]["state"] == "closed"


def test_the_report_calls_out_closed_matches_specifically():
    shipped = dict(TWELVE, state="closed")
    text = dedupe.render(THIRTEEN, dedupe.find_duplicates(THIRTEEN, [shipped]))
    assert "already closed" in text
    assert "already shipped" in text


# ---------- it must not cry wolf ----------

def test_neighbouring_tickets_are_not_duplicates():
    """Two tickets about the same page, doing different things. This is the
    shape that would make the check useless if it fired."""
    a = issue(1, "Add a dark mode toggle to the site")
    b = issue(2, "Add a print stylesheet to the site")
    assert dedupe.find_duplicates(a, [b]) == []


def test_the_same_verb_on_different_objects_is_not_a_duplicate():
    a = issue(1, "Show the claim age on /hq")
    b = issue(2, "Show the build time on /about")
    assert dedupe.find_duplicates(a, [b]) == []


def test_a_ticket_is_not_a_duplicate_of_itself():
    assert dedupe.find_duplicates(TWELVE, [TWELVE]) == []


def test_the_shift_report_is_never_a_duplicate():
    """It is filed daily with the same title every time. Without the paperwork
    filter it would flag itself as a duplicate of itself, forever."""
    today = issue(6, "Shift report — 2026-08-14")
    yesterday = issue(5, "Shift report — 2026-08-13")
    assert dedupe.find_duplicates(today, [yesterday]) == []


def test_the_watchdog_alarm_is_never_a_duplicate():
    a = issue(9, "Watchdog: board has stalled")
    b = issue(4, "Watchdog: board has stalled")
    assert dedupe.find_duplicates(a, [b]) == []


def test_an_empty_title_matches_nothing():
    """Otherwise every blank-titled ticket is a duplicate of every other."""
    assert dedupe.find_duplicates(issue(1, ""), [issue(2, "")]) == []


# ---------- how it decides ----------

def test_noise_words_do_not_carry_similarity():
    """'Add the X page' vs 'Add the Y page' should not score on 'add' and 'the'."""
    assert dedupe.normalise("Add the Fire Mask page") == "fire mask page"


def test_a_near_title_needs_the_body_to_agree():
    """A merely similar title is not enough on its own — that is what stops a
    family of similarly named tickets flagging each other."""
    a = issue(1, "Show the lease on the dashboard", body="Completely different subject matter here.")
    b = issue(2, "Show the ledger on the dashboard", body="Nothing whatsoever in common with that.")
    assert dedupe.find_duplicates(a, [b]) == []


def test_a_near_title_with_a_matching_body_is_flagged():
    shared = "The dashboard should display the current value with its age in minutes."
    a = issue(1, "Show the lease on the dashboard", body=shared)
    b = issue(2, "Show the leases on the dashboard", body=shared)
    assert dedupe.find_duplicates(a, [b])


def test_matches_come_back_most_similar_first():
    exact = dict(TWELVE, number=20)
    loose = issue(21, "Show who is holding each ticket on the board somewhere",
                  body=TWELVE["body"])
    matches = dedupe.find_duplicates(THIRTEEN, [loose, exact])
    assert matches[0]["number"] == 20


def test_the_report_says_it_has_no_judgement():
    """It compares text. Saying so is what stops a false positive being read as
    a verdict."""
    text = dedupe.render(THIRTEEN, dedupe.find_duplicates(THIRTEEN, [TWELVE]))
    assert "judgement and this check has none" in text
    assert "needs:human" in text
    assert "If it is not a duplicate" in text


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
