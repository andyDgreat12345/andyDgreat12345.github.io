# Model routing — who gets hired for what

Two rules generate almost every decision below.

> **The cost ladder.** Never let an expensive model do a cheap model's job, and
> never let a cheap model's output ship without a capable model reviewing it.

> **Diversity at the gate.** The reviewer runs on a different model family than
> the builder. Same-family review is an echo chamber — models share training and
> therefore share blind spots, and two Claude instances will happily agree on the
> same wrong thing.

## The routing table

| Job | Tool | Why this one |
|---|---|---|
| Multi-file changes, refactors, writing the harness itself | **Claude Code (Opus 5)** | Longest reliable horizon on real repos; skills, hooks, subagents, and permission scoping are the harness features this whole design leans on |
| Running 24/7 with the laptop shut | **Claude Code on the web** + Routines | Cloud sessions on a schedule, started and approved from a browser — this is what removes your laptop from the critical path |
| A custom always-on daemon (dispatcher, watchers) | **Claude Agent SDK** | A programmable agent loop you can put your own tools in, running as a normal service on a VPS |
| Second independent implementation of a hard ticket | **Codex** | Two attempts from different families, then pick — genuinely better than one attempt on `risk:high` work |
| Adversarial review of a Claude-written PR | **Codex** | The diversity rule. It is the reviewer precisely because it did not write the code |
| Bulk summarising: 500 news items, filings, changelogs | **DeepSeek V3** | Roughly an order of magnitude cheaper per token; the job is volume, not judgement |
| Chinese ↔ English source ingestion for the market repo | **DeepSeek V3** | Strong Chinese-language handling on public sources, at bulk-tier price |
| Cheap deep reasoning: backtest post-mortems, ranking hypotheses | **DeepSeek R1** | Reasoning-grade output when you can tolerate latency and the input is public |
| Data labelling, test fixtures, first-pass classification | **DeepSeek V3** | Reviewed downstream anyway; the cheap tier is the right tier |
| The 1-minute filter: dedupe, "is this worth waking a paid model?" | **Local model via Ollama** (Qwen or Llama 8B) | Zero marginal cost means you can run it constantly, which is what makes a high-cadence company affordable |
| Anything touching personal data or shipping to users | **Claude (Opus 5) + you** | Data policy plus accountability |
| Counting tokens, enforcing budgets, tripping the breaker | **No model** | Arithmetic. A model that decides whether to stop spending is a bad idea |

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

```
tier        + data class   →  model
─────────────────────────────────────────────
cheap-bulk  + public       →  deepseek-chat
cheap-bulk  + personal     →  ESCALATE (never routed to bulk)
local       + any          →  ollama/qwen (on your own hardware)
capable     + any          →  claude-opus-5
capable-alt + public       →  codex          (reviewer / second attempt)
capable-alt + personal     →  claude-opus-5  (diversity yields to data policy)
deterministic              →  no model; a Python function
```

The one place the diversity rule bends is personal data: a cross-family reviewer
is worth less than not sending applicant essays to a second vendor. On those
tickets, the reviewer is a Claude instance with a review-only prompt and no write
access, and you read the diff yourself before merging.

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
