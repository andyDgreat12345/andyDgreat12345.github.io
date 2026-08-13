# Role: Controller

**Tier:** deterministic — **no model.** This is a Python function.
**Wakes on:** after every worker run; daily at 23:00

You count what was spent and you stop the company when it goes over. You are code,
not an agent, on purpose: a model deciding whether to stop spending money on
models is a conflict of interest and a failure mode.

## Job

1. After every worker run, record: ticket, role, model, input tokens, output
   tokens, and computed cost, appended to the ledger on the state branch.
2. Maintain running totals: today, this week, this month, split by department and
   by role.
3. Enforce the caps:
   - At **70%** of the daily cap, comment a warning on the shift report.
   - At **90%**, refuse any new `capable`-tier work. Cheap and local tiers continue.
   - At **100%**, set `COMPANY_PAUSED=1` and open an issue with `needs:human`.
     Work in flight finishes; nothing new starts.
4. At 23:00, post the daily spend report for Comms to fold into the morning brief.
5. Flag anomalies against the trailing 7-day average: a single ticket costing more
   than 5× the median, a role whose daily cost doubled, or a retry storm.

## Boundary — never do these

- Never raise a cap. Only the owner raises caps, and only by editing the config.
- Never estimate a cost you did not measure. Unmeasured spend is reported as
  unmeasured, not as zero — silent gaps are how bills surprise people.
- Never resume a paused company. Un-pausing is a human act.
- Never delete ledger history.

## Input

Token counts reported by each worker run, and a price table.

## Artifact

An append-only ledger, a daily report, and the state of `COMPANY_PAUSED`.

## Escalation

Open a `needs:human` issue when: the cap trips, a single ticket exceeds 5× the
median cost, spend has risen for three consecutive days, or a worker finished
without reporting its token usage — an unmeasured run is a hole in the ledger and
gets fixed rather than tolerated.
