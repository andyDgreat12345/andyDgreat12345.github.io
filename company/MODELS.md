# Model routing — who gets hired for what

Two rules generate almost every decision below.

> **The cost ladder.** Never let an expensive model do a cheap model's job, and
> never let a cheap model's output ship without a capable model reviewing it.

> **Diversity at the gate.** The reviewer runs on a different model family than
> the builder. Same-family review is an echo chamber — models share training and
> therefore share blind spots, and two Claude instances will happily agree on the
> same wrong thing.

And one constraint that shapes the table as much as either rule:

> **There is no Anthropic API wallet.** Every automated worker therefore runs on
> a small DeepSeek balance or on your own hardware. That single constraint is why
> the engineer is DeepSeek, why the reviewer must not be, and why personal data
> has no automated worker at all.

## The routing table

| Job | Tool | Why this one |
|---|---|---|
| Multi-file changes, refactors, building tickets | **OpenHands agent on DeepSeek V4 Pro** | A tested open-source coding agent (MIT, ~84k stars) rather than a harness we maintain ourselves; strong SWE-bench numbers at cents per ticket |
| Running 24/7 with the laptop shut | **GitHub Actions, on `issues.labeled`** | Event-driven, so the engineer starts the moment a ticket is claimed. No scheduler, no cloud session, no laptop in the critical path |
| A custom always-on daemon (dispatcher, watchers) | **Plain Python on Temporal** | Already built, stdlib only, no model needed — see `company/ops/` |
| Adversarial review of the engineer's PR | **You** (a Claude reviewer when one is built) | The diversity rule, pointed the other way now: the builder is DeepSeek, so the reviewer must not be. Nothing automated answers to this yet, and branch protection enforces it regardless |
| Second independent implementation of a hard ticket | **DeepSeek V4 Pro, run twice** | Cheap enough that two attempts are affordable — but same family, so pick between them yourself rather than letting one grade the other |
| Bulk summarising: 500 news items, filings, changelogs | **DeepSeek V4 Flash** | Roughly an order of magnitude cheaper per token; the job is volume, not judgement |
| Chinese ↔ English source ingestion for the market repo | **DeepSeek V4 Flash** | Strong Chinese-language handling on public sources, at bulk-tier price |
| Cheap deep reasoning: backtest post-mortems, ranking hypotheses | **DeepSeek V4 Pro** | Reasoning-grade output when you can tolerate latency and the input is public |
| Data labelling, test fixtures, first-pass classification | **DeepSeek V4 Flash** | Reviewed downstream anyway; the cheap tier is the right tier |
| The 1-minute filter: dedupe, "is this worth waking a paid model?" | **Local model via Ollama** (Qwen or Llama 8B) | Zero marginal cost means you can run it constantly, which is what makes a high-cadence company affordable |
| Anything touching personal data | **You, or a local model** | No automated worker may see real records. Refused in two independent places — see below |
| Counting tokens, enforcing budgets, tripping the breaker | **No model** | Arithmetic. A model that decides whether to stop spending is a bad idea |

**Codex is deliberately absent, and is now the obvious reviewer.** DeepSeek took
the engineer's seat, which vacates the gate: a reviewer must be a different
family from the builder, and Codex is one. It costs a second paid account, which
is the only reason it is not already wired. Swapping it in is one line in
`company/ops/models.py`.

## Per-department assignment

**`andyDgreat12345.github.io` — front office.** The OpenHands engineer builds the
Astro site and the HQ dashboard; Comms runs on the cheap tier to draft changelog
copy from merged PRs; you approve anything public-facing. `risk:med` by default
because it is your public face.

**`Ai-case-writer-tool` — handles user text.** No automated worker, end to end.
The engineer's workflow refuses `dept:casewriter` before it composes a prompt.
This is a data-policy call, not a quality one.

**`Chinese-ai-stocks-prediction-model` — the heaviest agent user.** DeepSeek does
the volume work: ingest Chinese-language news and filings, summarise, translate,
label sentiment, all against public sources. Claude does the model code, the
backtest logic, and the interpretation. Local model runs the market-hours poller
that decides whether anything interesting happened. This repo alone justifies the
three-tier setup.

**`College-acceptance-prediction-ai-` — personal data.** You, for anything
touching real applicant records; the engineer is refused at the gate. A local
model may work on real data because it sends nothing anywhere, and the bulk tier
may work on synthetic or public aggregate data only. The Analyst must state in
the spec which kind a ticket involves before an Engineer starts.

## How a role picks its model

The role card names a **tier**, never a specific model. The dispatcher resolves
tier plus data class to a concrete model, so you re-price the whole company by
editing one map instead of eight prompts.

This table is not documentation of the code — it *is* the code, in
`company/ops/models.py`, and `test_controller.py` fails if the two drift.

```
tier           + data class   →  model
──────────────────────────────────────────────────────
capable        + public       →  deepseek-v4-pro    (the OpenHands engineer)
capable        + personal     →  REFUSED
capable-alt    + public       →  claude-code        (reviewer — different vendor)
capable-alt    + personal     →  REFUSED
cheap-bulk     + public       →  deepseek-v4-flash
cheap-bulk     + personal     →  REFUSED
reasoning-bulk + public       →  deepseek-v4-pro
reasoning-bulk + personal     →  REFUSED
local          + any          →  ollama/qwen        (on your own hardware)
mixed          + public       →  deepseek-v4-pro    (the SRE's ceiling)
mixed          + personal     →  REFUSED
deterministic                 →  no model; a Python function
```

**Every worker tier is closed on personal data.** That is stronger than the rule
it replaced. The engineer runs on DeepSeek — a third party — so the old
compromise of routing personal work to a first-party model has nothing left to
route to, and rather than pick whatever is closest to acceptable, the company
simply has no automated worker for those tickets. You do them. `local` is the
single exception: a model on your own hardware sends nothing anywhere.

`REFUSED` is literal: `resolve()` raises `RoutingError` rather than quietly
downgrading, because a silent fallback to a cheaper model is precisely how
personal data reaches the bulk tier. The refusal is the enforcement of
CHARTER.md's data policy; everything else about that policy is prose.

## Two meters, because zero dollars is not free

Subscription work is not billed per token, so a dollar cap cannot see it. The
engineer is metered work again now that it runs on DeepSeek, but the second meter
stays: the moment any role runs on a subscription seat, a dollars-only breaker
goes blind to the busiest worker in the company. That failure is silent, so the
meter that catches it stays wired whether or not it currently reads anything.

So the Controller runs two meters and the tightest one decides:

| Meter | Cap | What it protects |
|---|---|---|
| Dollars today / this month | `COMPANY_DAILY_CAP`, `COMPANY_MONTHLY_CAP` | The DeepSeek balance |
| Subscription runs today | `COMPANY_DAILY_RUN_CAP` | The claude.ai seat's daily routine allowance |

A run cap matters for a reason that has nothing to do with money: the
subscription has its own daily ceiling on routine runs, and a company that burns
it at 03:00 has no engineer when you wake up. Both meters feed the same
ok → warn → degrade → tripped ladder, so "out of runs" stops the company in the
same words, and with the same escalation, as "out of money".

## Guardrails

- **A tier is a ceiling, not a target.** If a ticket resolves at `capable` but the
  work is mechanical, the Engineer should say so and re-label it. Cost discipline
  is part of the job, not the Controller's problem alone.
- **Bulk-tier output is input, never product.** A DeepSeek summary enters the
  system as a note attached to a ticket. It never becomes a merged file without a
  capable model in between.
- **Log the model on every artifact.** Every PR body and every generated note
  records which tier and model produced it. When quality drops you need to know
  where, and six weeks later you will not remember.
- **Re-run the table quarterly.** Prices and capabilities move fast enough that a
  routing table is a perishable document. Put it on the calendar.
