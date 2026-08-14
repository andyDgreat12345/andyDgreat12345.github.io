# The org

## Why not a manager agent

The obvious design — one "CEO agent" that reads your request, decides what to do,
and spawns workers — fails for three reasons, and it fails quietly:

1. **No ground truth.** The manager's picture of the company is whatever it last
   read into context. It drifts within hours and there is nothing to correct it.
2. **Single point of hallucination.** One bad plan at the top corrupts every
   worker downstream, and all of them will confidently report success.
3. **No audit trail.** When it goes wrong at 3am you get a chat log, not a diff.

What replaces it is boring and works: **a queue with typed stages, and a gate
between each stage.** The state of the company is the state of the board, which is
a thing you can look at on a phone. Agents do not know what the company is doing;
they know what their ticket says. That is a feature.

## The org chart

Nothing above the line issues orders. The line is the queue.

```
                     ┌──────────────────────────────┐
                     │  YOU — owner                 │
                     │  merges, money, direction    │
                     └───────────────┬──────────────┘
                                     │ approves / directs via Issues & PRs
    ═════════════════════════════════╪═══════════════════════════════════
                            THE BOARD (GitHub Issues + Projects)
                       the only thing that assigns work to anyone
    ═════════════════════════════════╪═══════════════════════════════════
                                     │
              ┌──────────────────────┴───────────────────────┐
              │  DISPATCHER — routes labels to roles          │
              │  no opinions, no approvals, no priorities     │
              └──┬────────┬────────┬────────┬────────┬────────┘
                 │        │        │        │        │
            ┌────▼───┐ ┌──▼────┐ ┌─▼─────┐ ┌▼──────┐ ┌▼────────┐
            │ANALYST │ │ENGIN- │ │REVIEW-│ │  SRE  │ │RESEARCH-│
            │ specs  │ │ EER   │ │  ER   │ │verify │ │   ER    │
            └────────┘ └───────┘ └───────┘ └───────┘ └─────────┘
                 │        │        │        │        │
            ┌────▼────────▼────────▼────────▼────────▼────────┐
            │  COMMS — changelog, site, digests                │
            │  CONTROLLER — budget, kill switch, cost reports  │
            └─────────────────────────────────────────────────┘
```

The dispatcher sits at the top of the agent block but holds no authority — read
[`CHARTER.md`](CHARTER.md#authority-the-process-holds). It is drawn there because
it is the fan-out point, not because it is in charge.

## The roster

Eight roles. Each links to its card, which is written to be used directly as an
agent system prompt.

| Role | Job in one line | Wakes on | Model tier |
|---|---|---|---|
| [Dispatcher](roles/00-dispatcher.md) | Route tickets to roles by label | Heartbeat, every 15 min | Local / cheap |
| [Analyst](roles/01-analyst.md) | Turn a vague request into acceptance criteria | `status:needs-spec` | Capable |
| [Engineer](roles/02-engineer.md) | Turn a spec into a draft PR that passes CI | `status:ready` | Capable |
| [Reviewer](roles/03-reviewer.md) | Find the defect, never write the fix | PR marked ready | Capable, *different family* |
| [SRE](roles/04-sre.md) | Prove it actually runs; watch the crons | Approved PR; watchdog | Mixed |
| [Researcher](roles/05-researcher.md) | Ingest the outside world into structured notes | Schedule, feeds | Cheap bulk |
| [Comms](roles/06-comms.md) | Write what changed, for humans | Merge to `main` | Cheap |
| [Controller](roles/07-controller.md) | Track spend, trip the breaker | Every run; daily | Deterministic |

Start with four: dispatcher, engineer, reviewer, controller. The rest are added
when a stage starts stalling for lack of them, and not before.

## The ticket lifecycle

One ticket is one GitHub Issue. It moves through eight stages by label. A stage
change requires the exit artifact — an agent claiming a stage is done is not a
stage being done.

```
 INBOX → TRIAGE → SPEC → BUILD → REVIEW → VERIFY → SHIP → REPORT
   │        │       │      │        │        │      │       │
   any   dispatch  analyst engineer reviewer  sre   YOU    comms
```

| Stage | Label | Owner | Exit artifact | Gate to leave |
|---|---|---|---|---|
| Inbox | `status:inbox` | Anyone, incl. watchers | An issue with a title | Has a body |
| Triage | — | Dispatcher | `dept:*`, `size:*`, `risk:*`, **and the next stage** | Must leave Inbox |
| Spec | `status:needs-spec` | Analyst | Acceptance criteria as a checklist | You approve if `size:L` |
| Build | `status:ready` | Engineer | A **draft PR** linked to the issue | CI green |
| Review | PR ready for review | Reviewer | An approval or a change request | Reviewer ≠ author |
| Verify | `status:verify` | SRE | Evidence it ran: output, screenshot, log | Reproducible from scratch |
| Ship | `status:ship` | **You** (auto if `risk:low`) | Merge + deploy | All gates above green |
| Report | `status:done` | Comms | Changelog entry / site update | — |

### The labels

Keep the vocabulary small. Every label is machine-readable by the dispatcher.

- `dept:site` `dept:casewriter` `dept:market` `dept:admissions` `dept:hq`
- `size:s` (< 1 agent-hour) `size:m` `size:l` (needs your spec approval)
- `risk:low` (reversible, no user impact) `risk:med` `risk:high` (money, data, public)
- `status:inbox` `status:needs-spec` `status:ready` `status:building`
  `status:verify` `status:ship` `status:done` `status:blocked`
- `needs:human` — the escalation flag. Anything wearing this is yours and the
  dispatcher will not touch it.

### Rules that keep it honest

- **One ticket, one artifact.** A run that produces no PR, no comment, and no file
  did not happen. The dispatcher marks it failed and re-queues once, then escalates.
- **No agent moves a ticket backwards** except to `status:blocked` with a reason.
- **No agent creates a ticket for itself.** Work comes from the board. An agent
  that finds new work files it in `status:inbox` and stops — it does not start it.
  This is the single most important rule against runaway loops.
- **Three strikes.** A ticket that fails three times gets `needs:human` and is
  never retried automatically. Infinite retries are how you wake up to a $400 bill.
- **The escalation is cheap.** A role that is unsure should stop and label
  `needs:human`. You would rather answer six questions at breakfast than unpick
  six confident mistakes.

## Where the state lives

- **Work state** — GitHub Issues and Projects. Visible on a phone, no app to build.
- **Product state** — the repos themselves; a merged PR is the record.
- **Accumulated data** — an orphan branch of state files, exactly the pattern
  `Chinese-ai-stocks-prediction-model` already uses for `oracle-state`. It costs
  nothing and it versions itself. Move to Postgres only when a query gets slow.
- **Run logs** — Actions run history, plus a shift report issue per day.
- **Nothing lives only in an agent's context.** Context evaporates. If it matters
  after the run ends it is written to a file or a comment.
