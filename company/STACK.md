# The advanced stack — going beyond GitHub

`INFRA.md` describes the zero-cost version that runs entirely on GitHub. This file
is the other end: what the best-resourced version looks like in 2026, based on
what people actually running agent companies have converged on, and what has
measurably failed for them.

Read `INFRA.md` first if you have not run a ticket end to end yet. The advanced
stack is a substrate upgrade, not a replacement for the operating model — the
authority split, the role boundaries, the gates, and the kill switch all survive
intact. What changes is what they run on.

## What the evidence actually says

Four findings should shape the design more than any product choice.

**Orchestration complexity is the killer, not model capability.** Roughly 40% of
multi-agent deployments fail within six months, and the failure is almost always
in the coordination layer rather than in what any individual agent could do. This
is the single most important number in this document. It means *advanced* must
mean a stronger substrate, not more agents.

**The exemplars are architecturally boring.** Pieter Levels runs roughly $3M/year
of products solo on vanilla PHP, jQuery and SQLite — deliberately, because models
debug well-documented boring stacks far better than novel ones. Midjourney reached
around $200M ARR with about eleven people. The leverage came from the operating
model, not from an exotic framework.

**The scale ceiling is real but not a template.** NVIDIA runs on the order of 100
agents per human employee internally. That is a datapoint about what the ceiling
looks like with a platform team behind it, not a target for one person.

**Agents that verify their own work beat ones that do not.** Ramp reports lower
revert rates from agent-written code than human-written, attributed to agents
testing and self-checking before submitting. Verification is where the quality
comes from — which is why the SRE role exists and why evals get their own layer
below.

The synthesis: **be aggressive about infrastructure, conservative about
application code, and ruthless about the number of moving agents.**

## The seven layers

Ordered by how much they change your life, not by how the diagram flows.

### 1. Durable execution — the spine

The biggest single upgrade over cron. Agent work is long, flaky, and expensive to
redo; a 40-minute run that dies at minute 38 because an API blipped is the normal
case, not the edge case. Durable execution gives you automatic state persistence,
exactly-once semantics, retries, and replay — the run resumes from the step that
failed instead of from the beginning.

This became mainstream in late 2025: AWS shipped Durable Functions, Cloudflare
took Workflows to GA, Vercel launched its Workflow DevKit. The category now
markets itself explicitly at agents.

- **Temporal** — the incumbent. Workflow-as-code with event-history replay across
  seven language SDKs, a $300M Series D in February 2026, and an OpenAI Agents SDK
  integration GA since March. Temporal Cloud means no backend to run. **Pick this
  if you want the thing serious agent shops run.**
- **Inngest** — event-driven step functions, no stateful backend at all, plus
  AgentKit as a first-party multi-agent layer. **Pick this if you want durable
  agents shipping this week and you are comfortable in TypeScript.**
- **Restate** — virtual objects per agent session, exactly-once tool dispatch. The
  most elegant model for per-agent state; smallest ecosystem.

**Recommendation:** Temporal, **self-hosted**, at least to begin with. Being
polyglot means the Python data work in the market repo and the TypeScript site
work live under one scheduler.

The pricing is the deciding factor and it cuts against the obvious choice:
Temporal Cloud starts at **$100/month with no free tier**. A 15-minute heartbeat
produces a few tens of thousands of Actions against a 1,000,000 Action
allowance — enterprise rates for a rounding error, and more than everything else
in this document put together. The $1,000 of trial credits make Cloud a fine
place to *try* it, but that is a cliff about ten months out.

Self-hosting is two containers and a Postgres. Move to Cloud when losing workflow
history would genuinely hurt, not before. Inngest is the right answer if you would
rather not think about workflow semantics at all.

### 2. Sandboxes — where agents are allowed to run

Stripe's rule, and it should be yours: **air-gapped sandboxes are non-negotiable,
because agent write-access to production is an enormous blast radius.**

Measured cold-start and resume, which matters because it multiplies across every
run:

- **E2B** — Firecracker microVMs, fastest and most consistent at roughly 717ms to
  create and 662ms to resume. True VM isolation. ~$0.05/vCPU-hr, billed per second.
- **Daytona** — pre-warmed Docker snapshots, ~742ms create but slower to resume;
  has a free tier, so it is the cheapest way to evaluate. Container-tier isolation
  means a shared kernel — weaker for untrusted code.
- **Modal** — Python-native serverless, and the only one that drops compute
  charges to zero when idle. The right answer for bursty batch and GPU work.
- **Cloudflare Sandboxes** — cheap and scale-to-zero, shared kernel, integrates
  with Workers and Durable Objects.

**Recommendation:** E2B for anything running agent-authored code, on isolation
grounds. Modal alongside it for the market repo's batch and model training, where
scale-to-zero billing is worth more than microVM isolation on code you wrote.

### 3. Model access and spend control — the gateway

Everything goes through one gateway. This is where the Controller role stops being
a Python script you maintain and becomes infrastructure.

The feature that matters is **virtual keys with per-key budget caps.** One key per
role, each with a hard monthly ceiling. An engineer agent that goes haywire burns
its own budget and stops; it cannot reach the researcher's. LiteLLM and Portkey
both ship this. OpenRouter does not.

- **OpenRouter** — 300+ models behind one key, zero infrastructure. Right for v0.
- **LiteLLM** — self-hosted, no lock-in, virtual keys and budgets. The standard
  advice is to switch once inference crosses about $1K/month.
- **Portkey** — observability and 50+ guardrails built in; worth it if compliance
  is ever a factor.

**Recommendation:** start on OpenRouter, move to self-hosted LiteLLM when spend
justifies it. The cost playbook it unlocks, in priority order: **cache, batch,
route, right-size the model.** Prompt caching alone typically beats every other
optimisation on this list.

### 4. Memory — what the company knows

The company needs to remember what it learned last month, and for research work it
specifically needs to remember *when a fact was true*.

- **Zep / Graphiti** — a temporal knowledge graph that tracks how facts change over
  time. Scores 63.8% on LongMemEval against Mem0's 49.0%, a 15-point gap on
  temporal retrieval specifically. Graphiti is the open-source engine underneath
  and is self-hostable.
- **Mem0** — vector-first, portable, cheapest per retrieval: reported 92.5% on
  LoCoMo at under 7,000 tokens per call. Fastest path to production.
- **Letta** — the Berkeley MemGPT project, a stateful agent runtime with core,
  recall and archival tiers. Use if you want memory and runtime as one thing.

**Recommendation:** Zep/Graphiti as the company knowledge graph. "This analyst
believed X in March and revised to Y in June" is precisely the market-research
problem, and it is the one thing vector memory handles badly. Mem0 is the right
call if you would rather have something cheap and portable and move on.

### 5. Observability and evals — the layer that separates a company from a hobby

**Most agent incidents are tool-call failures, context truncation, and runaway
loops — not model errors — and standard monitoring cannot see any of them.** If
you add one thing from this document beyond durable execution, add this.

Serious practice has three parts: unit evals on discrete steps, LLM-as-judge
regression suites for subjective quality, and continuous sampling of production
traces to catch drift. Notably, 89% of surveyed organisations run agent
observability but only 52% run offline evals and 37% run online evals — the gap
between watching and *measuring* is where most setups sit.

- **Langfuse** — open source, self-hostable, the pragmatic default.
- **Braintrust** — eval-first philosophy; pick it if you want evals to be the
  center of gravity rather than an add-on.
- **LangSmith** — best if you standardise on LangGraph; now gives a unified cost
  view across LLM calls, retrieval, tools and external APIs.
- **Arize Phoenix** — the most rigorous on eval methodology.

**Recommendation:** self-hosted Langfuse for tracing from day one, Braintrust for
evals once you have a role whose quality you cannot eyeball. Every role card's
"artifact" becomes an eval target — that is the connection between the operating
model and this layer.

### 6. The coding fleet

Every major platform shipped parallel agents in 2026: Claude Code Agent Teams,
OpenAI's Codex app, VS Code multi-agent, Cursor 2.0 Composer.

The universal mechanism is **git worktrees** — each agent gets its own working
copy so a bad merge in one cannot contaminate another. Fleet management reduces to
three primitives: **observe** (who is stuck, finished, or about to conflict),
**route** (send work to the agent that fits, by capability and cost), and **kill**
(terminate a misbehaving agent in isolation).

Orchestrators worth knowing: **Orca** (open source, 27 supported CLI agents, each
in its own worktree, with a mobile interface — directly relevant to the iPad
question), **GitHub Copilot `/fleet`**, and **Composio Agent Orchestrator**.

Two patterns to steal:

- **Parallel fan-out** — several agents attempt the same `risk:high` ticket
  independently, and the best result wins. Expensive and worth it where a defect
  is costly.
- **Adversarial review panel** — spawn three reviewers on one PR through security,
  performance, and test-coverage lenses. This is a strictly better version of the
  single-reviewer gate in `ORG.md`.

One caution: **Claude Code Agent Teams is an experimental research preview**,
enabled behind a flag. It is excellent for parallel research and review and is not
where you should put unattended production shipping yet. Routing still matters —
Claude for multi-file refactors, Codex for targeted functions and test writing.

### 7. Identity, authority, and money

The industry converged in 2026 on treating an agent as a **first-class non-human
identity**: its own principal, cryptographically attested, with short-lived
runtime credentials, and the human preserved as the delegating subject via token
exchange. The CSA published an Agentic Trust Framework in February 2026 applying
zero-trust principles to autonomous agents. Meanwhile over 16% of organisations do
not track the creation of AI identities at all, which is roughly where an
enthusiastic solo setup lands by default.

What this means concretely for you:

- One identity per role, not one shared token. Short-lived credentials, scoped to
  that role's actual job. The reviewer identity gets read plus review, nothing more.
- Secrets in a real manager — Infisical or Doppler self-hosted, or 1Password —
  never in prompts, never in repo files.
- **Money: give agents a prepaid or virtual card with a hard limit, not your
  real one.** The agentic payment protocols are real now — Google's AP2 with signed
  mandates, Coinbase's x402 for stablecoin machine payments (Stripe integrated it
  on Base in February 2026), OpenAI and Stripe's ACP for checkout, and Stripe and
  Tempo's MPP with pre-authorised spending sessions. This is genuinely the frontier
  and genuinely where an unattended mistake costs actual money. Adopt it when an
  agent has a recurring purchase to make, not before.

### 8. The control plane — what you touch

The upgrade that matters most day to day, and where leaving GitHub pays off
immediately.

- **Linear as the work queue**, replacing GitHub Issues. Far better mobile app,
  far better API, and the stage model in `ORG.md` maps onto its workflow states
  directly. This is the biggest quality-of-life gain in the whole document.
- **Slack as the company's nervous system.** Agents post to a channel per
  department, you reply in thread, and every instruction is an audit trail by
  construction. Slack on iPad is genuinely good, unlike almost every dashboard you
  might build.
- **One status page** — Next.js on Vercel or Cloudflare, reading Temporal, Langfuse
  and Linear. Open tickets by stage, last run per workflow, spend against cap,
  anything wearing `needs:human`.
- **GitHub keeps only what it is best at**: code hosting, PR review, and CI. PR
  review on mobile remains the right approval surface, so the merge key stays where
  it is.

## What this costs

| Layer | Pick | Monthly |
|---|---|---|
| Coding agents | Claude Max, plus Codex | $150–250 |
| Durable execution | Temporal self-hosted (Cloud is $100/mo minimum) | $10–20 |
| Sandboxes | E2B + Modal, usage-based | $25–150 |
| Gateway | OpenRouter → self-hosted LiteLLM | $0–20 |
| Model inference | Claude API + bulk tier + Codex | $100–500 |
| Memory | Graphiti self-hosted (or Zep Cloud) | $0–100 |
| Observability | Langfuse self-hosted (+ Braintrust later) | $0–100 |
| Work queue | Linear | $10–15 |
| Control plane host | Fly/Hetzner + Vercel | $30–70 |
| Secrets | Infisical self-hosted | $0–20 |
| **Total** | | **$400–1,400** |

Published solo-founder stacks land in the same band — roughly $17K/year for a full
stack including support and marketing tooling, and $200–500/month for a lean one.
The often-cited framing is that this replaces 70–80% of salary burn at 2–5% of the
cost. Treat those numbers as the ceiling of what is reasonable, not a target to
grow into.

The dominant variable remains unchanged from `INFRA.md`: **how often you wake an
expensive model.** A cheap model deciding whether to wake a capable one is still
worth more than every line item above.

## Build order

Do not build layers in parallel. Each step should be running in production before
the next starts.

1. **Durable execution — built.** The heartbeat now runs as a Temporal workflow;
   see [`temporal/README.md`](temporal/README.md) for how to run it, and note the
   `board.py` split that keeps the cron path and the durable path from drifting.
   Still to do here: move one real *role* across once the fan-out exists.
2. **Sandboxes.** Every agent-authored line of code executes in E2B, never on a
   machine that matters.
3. **Gateway with per-role budget caps.** The Controller role becomes a config
   file instead of a script you maintain.
4. **Tracing.** Langfuse on everything. Spend two weeks just watching before
   changing anything — the traces will contradict your assumptions about where
   time and money go.
5. **Linear plus Slack.** Retire GitHub Issues as the queue. Keep PR review.
6. **Memory.** Graphiti, starting with the market department where temporal facts
   matter most.
7. **Evals.** Turn each role's required artifact into a scored eval. Now you can
   change a prompt and know whether it got better.
8. **Fleet patterns.** Parallel fan-out and the adversarial review panel, on
   `risk:high` tickets only.
9. **Agent identity and payments.** Last, deliberately. This is where mistakes
   cost real money.

## What to keep boring

The Levels lesson is the one most likely to be ignored, and it is the one that
compounds. **Advanced infrastructure, boring application code.** Well-documented,
conventional, heavily-represented-in-training-data stacks — because that is what
agents debug reliably at 3am without you. An exotic framework buys you elegance
and costs you the thing you are actually optimising for, which is an agent's
ability to fix its own mess while you sleep.

Sophistication belongs in the substrate: durability, isolation, measurement,
memory. It does not belong in your web framework.
