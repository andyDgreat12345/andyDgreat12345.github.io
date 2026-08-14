# HQ — a one-person company that runs on agents

This directory is the operating system for a small company where the work is done
by AI agents on a schedule, and you are the owner rather than the operator.

The central design decision: **no agent is the boss.** A manager-agent that hands
out orders is a single point of hallucination with no ground truth. Instead the
*process* holds authority — a queue, role boundaries, and mechanical gates. Agents
are workers that pull tickets and produce artifacts. The repo state and CI are the
ground truth. You hold the keys that matter.

## Read in this order

| File | What it answers |
|---|---|
| [`CHARTER.md`](CHARTER.md) | What the company is for, who holds which authority, how to stop it |
| [`ORG.md`](ORG.md) | The org chart, the ticket lifecycle, and the gates between stages |
| [`OPERATING.md`](OPERATING.md) | What the owner actually does, how failures are caught, and the order roles get hired |
| [`MODELS.md`](MODELS.md) | Which of Claude Code / Codex / DeepSeek / local models does which job |
| [`INFRA.md`](INFRA.md) | Where to physically build it, how it stays up 24/7, how you drive it from an iPad |
| [`STACK.md`](STACK.md) | The funded version: durable execution, sandboxes, evals, memory — what to buy and in what order |
| [`ROLLOUT.md`](ROLLOUT.md) | 90-day plan, real costs, and the failure modes that kill setups like this |
| [`roles/`](roles/) | One job description per role — these are literal agent system prompts |
| [`ops/board.py`](ops/board.py) | Every routing decision, as pure logic. Change how work is routed here and nowhere else |
| [`ops/labels.py`](ops/labels.py) | The label vocabulary — run it from the Actions tab via **Company bootstrap** |
| [`ops/dispatch.py`](ops/dispatch.py) | The Tier 0 dispatcher: reads the queue, routes tickets, has no opinions, no dependencies |
| [`temporal/`](temporal/) | The same heartbeat as a durable workflow — step 1 of `STACK.md`, and the one to run in production |
| [`deploy/RUNBOOK.md`](deploy/RUNBOOK.md) | Where the worker actually lives, what it costs, the token scopes, and what to do when it breaks |

## The one-paragraph version

GitHub is the company. Repos are departments, Issues are work orders, Projects is
the board, Actions cron is the clock, pull requests are the review gate, and Pages
is the dashboard. A heartbeat workflow wakes a dispatcher every 15 minutes; the
dispatcher matches ticket labels to roles and starts the right worker with the
right model. Cheap models triage, capable models decide, a *different* model
reviews, and you turn the key on anything irreversible. It costs about $0 to start
and about $25/month once it is doing real work.

## Start here

Week 1 is five tasks and it is spelled out at the bottom of [`ROLLOUT.md`](ROLLOUT.md).
Do not build the whole thing before running it. Get one ticket through the full
lifecycle end to end, then add roles.
