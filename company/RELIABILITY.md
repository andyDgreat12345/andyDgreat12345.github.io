# What can and cannot be promised

The owner asked for a company promised to be 100% functioning. That promise
cannot honestly be made, by anyone, about any system — and a document that made
it would be the least reliable thing in this repository.

What *can* be done is this: name every way it can fail, say what stands in the
way of each, and be explicit about which ones are still open. A system whose
failure modes are written down and defended is worth far more than one somebody
promised was fine.

The evidence for that is the last two days. Every serious bug found was in
something already believed to be working, and **none of them were in logic** —
every pure function was correct the whole time. They were all in the seams.

## The failures already found, and what now stops them

| What went wrong | Why it was invisible | What stops it now |
|---|---|---|
| Triage classified tickets and left them in Inbox | Heartbeats stayed green; tickets accumulated behind them | Triage must advance the stage; `test_board.py` asserts it |
| Fan-out planned work but never claimed it | The report looked perfect. The engineer waited on a label nothing produced | `test_dispatch.py` — tests the *wiring*, not the logic |
| A label applied with `GITHUB_TOKEN` woke nothing | GitHub silently does not trigger workflows from its own token | Heartbeat uses `PAT_TOKEN`; the shift report says so loudly when it cannot |
| A PR opened with `GITHUB_TOKEN` got no CI | Zero checks looks identical to passing checks | Engineer opens PRs with the PAT; verified live on #16 |
| Watchdog would alarm on its own logbook | It only fires when the board is quiet — so the first quiet day | Paperwork filtered inside `assess()`, the tested function |
| A vacancy counted as a failed attempt | Escalated tickets as unworkable that were never attempted | `assign.HIRED`; unstaffed stages report as waiting on the owner |
| A missing secret charged to the ticket | Three of them and a good ticket is buried | Gate checks configuration first, releases without charging |
| Handoff would lose a run to a quick merge | Only on a fast merge — rare, and silent | `state=all`; a merged PR still counts as finished |
| Subscription work invisible to the budget breaker | It priced at $0.00 a run, so the cap never moved | Three meters; the tightest one decides |
| The same ticket filed twice | Nothing compared new tickets to old | `dedupe.py` on `issues.opened`, closed tickets included |

Ten failures. Every one would have been survivable-but-silent, which is the
shape that kills unattended systems: not a crash, a *quiet wrongness* that looks
like health.

## The rule that generated most of those fixes

> **A component that reports success is not evidence. An artifact is.**

The handoff never asks an agent how it went — it asks GitHub whether a pull
request exists, whether the ticket now has acceptance criteria, whether
verification was posted. `ORG.md` has said since the first draft that a run
producing nothing did not happen. Most of the table above is that rule applied
somewhere it had been forgotten.

## What is still open, honestly

**No independent reviewer.** The deterministic gate catches the mechanical half
— forbidden paths, wrong ticket, missing tests, assertionless tests. The half
that needs judgement is the owner's, and will be until a reviewer runs on a
different model family than DeepSeek. Branch protection enforces it meanwhile.

**One vendor for both hired roles.** Engineer and analyst are both DeepSeek. If
DeepSeek has an outage or a quality regression, both stop together. Cheap to
fix later, worth knowing now.

**The gate has never blocked a real bad PR.** It passed the one real PR cleanly
and its rules are tested, but no worker has yet produced output it had to stop.
Until then it is *probably* correct rather than *demonstrably* correct.

**Nothing has run unattended overnight.** Every cycle so far has had someone
watching. The stall alarm, the watchdog and the spend breaker exist for the
night nobody is, and they have not yet had that night.

**External access can vanish.** Mid-session, this repository's push access
disappeared for an hour — a credential changed outside anyone's control. The
company kept running the whole time: Actions has its own token. That is the
right lesson to take. **Not "it never breaks", but "when a piece breaks, the
rest keeps its shape."**

## What "functioning" should mean here

Not that nothing fails. That when something does:

- **It says so.** The stall alarm fires on absence, not just on error.
- **It stops rather than guesses.** Every role is told stopping is a valid
  outcome and guessing is not.
- **It cannot spend without limit.** Three meters, and the owner alone raises a
  cap or resumes a paused company.
- **It cannot do the irreversible thing alone.** No worker merges its own work;
  branch protection enforces that whoever wrote the code is not who lands it.
- **It leaves a record.** Every claim, release, attempt and cost is on the board
  or in the ledger, readable from a phone.

That is a company that survives its own bugs. It is not a promise that it has
none, and anyone offering you that promise is selling something.
