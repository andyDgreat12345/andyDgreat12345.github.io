# Model routing — who gets hired for what

Two rules generate almost every decision below.

> **The cost ladder.** Never let an expensive model do a cheap model's job, and
> never let a cheap model's output ship without a capable model reviewing it.

> **Diversity at the gate.** The reviewer runs on a different model family than
> the builder. Same-family review is an echo chamber — models share training and
> therefore share blind spots, and two Claude instances will happily agree on the
> same wrong thing.

And one constraint that shapes the table as much as either rule:

> **There is no Anthropic API wallet.** The capable tier therefore runs on the
> claude.ai subscription through Claude Code Routines, which authenticate with a
> subscription login rather than an API key. Everything else is either a small
> DeepSeek balance or free.

## The routing table

| Job | Tool | Why this one |
|---|---|---|
| Multi-file changes, refactors, writing the harness itself | **Claude Code** (subscription) | Longest reliable horizon on real repos; skills, hooks, subagents, and permission scoping are the harness features this whole design leans on. No API key involved |
| Running 24/7 with the laptop shut | **Claude Code Routines** | Scheduled cloud sessions, started and approved from a browser — this is what removes your laptop from the critical path. Minimum interval one hour |
| A custom always-on daemon (dispatcher, watchers) | **Plain Python on Temporal** | Already built, stdlib only, no model needed — see `company/ops/` |
| Adversarial review of a Claude-written PR | **DeepSeek V4 Pro** | The diversity rule: a different vendor *and* a different family, so it cannot inherit the builder's blind spots. Costs cents per review |
| Second independent implementation of a hard ticket | **DeepSeek V4 Pro** | Statistically tied with frontier models on SWE-bench Verified, at bulk-tier prices — two attempts from different families is affordable now in a way it was not |
| Bulk summarising: 500 news items, filings, changelogs | **DeepSeek V4 Flash** | Roughly an order of magnitude cheaper per token; the job is volume, not judgement |
| Chinese ↔ English source ingestion for the market repo | **DeepSeek V4 Flash** | Strong Chinese-language handling on public sources, at bulk-tier price |
| Cheap deep reasoning: backtest post-mortems, ranking hypotheses | **DeepSeek V4 Pro** | Reasoning-grade output when you can tolerate latency and the input is public |
| Data labelling, test fixtures, first-pass classification | **DeepSeek V4 Flash** | Reviewed downstream anyway; the cheap tier is the right tier |
| The 1-minute filter: dedupe, "is this worth waking a paid model?" | **Local model via Ollama** (Qwen or Llama 8B) | Zero marginal cost means you can run it constantly, which is what makes a high-cadence company affordable |
| Anything touching personal data or shipping to users | **Claude Code + you** | Data policy plus accountability |
| Counting tokens, enforcing budgets, tripping the breaker | **No model** | Arithmetic. A model that decides whether to stop spending is a bad idea |

**Codex is deliberately absent.** It was the reviewer in the first draft of this
table, and it is a fine one. It lost the slot on price: it needs a second paid
account to do a job DeepSeek V4 Pro now does for cents, from an equally
independent family. If the DeepSeek relationship ever becomes a problem — an
outage, a policy change, a quality drop — Codex is the drop-in replacement, and
swapping it back is one line in `company/ops/models.py`.

## Per-department assignment

**`andyDgreat12345.github.io` — front office.** Claude Code builds the Astro
site and the HQ dashboard; Comms runs on the cheap tier to draft changelog copy
from merged PRs; you approve anything public-facing. `risk:med` by default because
it is your public face.

**`Ai-case-writer-tool` — handles user text.** Claude only, end to end. No bulk
tier anywhere in the request path. This is a data-policy call, not a quality one.

**`Chinese-ai-stocks-prediction-model` — the heaviest agent user.** DeepSeek does
the volume work: ingest Chinese-language news and filings, summarise, translate,
label sentiment, all against public sources. Claude does the model code, the
backtest logic, and the interpretation. Local model runs the market-hours poller
that decides whether anything interesting happened. This repo alone justifies the
three-tier setup.

**`College-acceptance-prediction-ai-` — personal data.** Claude only for anything
touching real applicant records. The bulk tier may work on synthetic or public
aggregate data only, and the Analyst must state in the spec which kind a ticket
involves before an Engineer starts.

## How a role picks its model

The role card names a **tier**, never a specific model. The dispatcher resolves
tier plus data class to a concrete model, so you re-price the whole company by
editing one map instead of eight prompts.

This table is not documentation of the code — it *is* the code, in
`company/ops/models.py`, and `test_controller.py` fails if the two drift.

```
tier           + data class   →  model
──────────────────────────────────────────────────────
capable        + any          →  claude-code        (subscription, no API key)
capable-alt    + public       →  deepseek-v4-pro    (reviewer / second attempt)
capable-alt    + personal     →  claude-code        (diversity yields to data policy)
cheap-bulk     + public       →  deepseek-v4-flash
cheap-bulk     + personal     →  REFUSED (never routed to bulk)
reasoning-bulk + public       →  deepseek-v4-pro
reasoning-bulk + personal     →  REFUSED
local          + any          →  ollama/qwen        (on your own hardware)
mixed          + any          →  claude-code        (the SRE's ceiling)
deterministic                 →  no model; a Python function
```

`REFUSED` is literal: `resolve()` raises `RoutingError` rather than quietly
downgrading, because a silent fallback to a cheaper model is precisely how
personal data reaches the bulk tier. The refusal is the enforcement of
CHARTER.md's data policy; everything else about that policy is prose.

The one place the diversity rule bends is personal data: a cross-family reviewer
is worth less than not sending applicant essays to a second vendor. On those
tickets, the reviewer is a Claude instance with a review-only prompt and no write
access, and you read the diff yourself before merging.

## Two meters, because zero dollars is not free

Subscription work is not billed per token, so a dollar cap cannot see it. Left
alone that is a hole big enough to drive the company through: the engineer is
the busiest role, it now prices at $0.00 a run, and the breaker would have
reported 0% of cap while it worked all night.

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
