# Where to build it, and how it stays up

Your laptop cannot be the company. It closes. The whole infrastructure question is
therefore: *what is always on, and how do you drive it from something that is not?*

## Tier 0 — GitHub is the company (start here, ~$0)

You already run a working example of this. `Chinese-ai-stocks-prediction-model`
wakes on a cron, does work, persists growing state to the `oracle-state` branch,
rebuilds a static dashboard, and emails you by opening an issue that @mentions
you. That is a complete unattended department with no server. The company is that
pattern, generalised to eight roles and four repos.

| Company function | GitHub feature |
|---|---|
| The clock | `schedule:` in Actions workflows |
| The work queue | Issues + Projects |
| Departments | Repos |
| Job descriptions | `company/roles/*.md`, `CLAUDE.md`, `AGENTS.md` |
| Authority / who can merge | Branch protection + CODEOWNERS + required checks |
| Compute | Actions runners |
| Persistent state | An orphan `*-state` branch, or repo artifacts |
| Secrets | Actions secrets + environments |
| Notifications | Issues that @mention you → your email |
| Dashboard | Pages, rebuilt each heartbeat |
| Audit log | Run history + PR history, permanent and free |

**Constraints worth knowing before you design around them** (verify current
numbers — these move):

- Scheduled workflows **only run on the default branch**. Your cron will not fire
  from a feature branch. This bites everyone once; your repo's own workflow file
  already carries a note about it.
- Actions minutes are unlimited on public repos, and metered on private ones
  (2,000/month on the Free plan at last check). Four repos on a 15-minute
  heartbeat will exhaust a private-repo allowance — so either keep HQ public, or
  attach a self-hosted runner in Tier 1.
- Schedules get disabled after ~60 days without repo activity. A company that is
  committing daily never hits this, but a paused one will.
- A job is capped at 6 hours. Long jobs get chunked into tickets, which is better
  design anyway.
- Cron times are UTC. The market department cares — CST is UTC+8.

## Tier 1 — one small always-on box (~$4–6/month, add around week 3)

You need this the first time you want something Actions is bad at: a long-running
watcher, a local model, a real queue, or a webhook endpoint that answers instantly.

**What it runs:** Docker, the dispatcher as a service (Claude Agent SDK), Ollama
for the free local filter tier, SQLite or Postgres, and a **self-hosted Actions
runner** — which also makes your private-repo minutes unlimited, paying for the
box on its own.

**Options, honestly:**

- **Hetzner** small ARM/x86 VPS, a few euros a month — the default recommendation.
  Cheap, reliable, plenty for this.
- **Oracle Cloud Always Free** ARM instance — genuinely free and generously
  specced enough to run a local model, but capacity is frequently unavailable in
  popular regions and the account can be reclaimed. Fine as a bonus, bad as a
  foundation.
- **Hardware at home** — an old laptop, a Mac mini, a Raspberry Pi 5. Free and it
  can run Ollama well. You own the uptime, the power, and the dynamic DNS. Good if
  you want to run local models seriously; a distraction otherwise.
- **Fly.io / Railway** — more expensive per unit, less to maintain. Reasonable if
  you would rather not administer a box.

Rule of thumb: **anything under 6 hours and stateless stays on Actions; anything
persistent moves to the box.**

## Tier 2 — paid services (only once something earns)

A Claude subscription for Claude Code usage, API credit for the bulk and alt
tiers, a managed Postgres free tier when SQLite-on-a-branch stops fitting, and a
Cloudflare Worker as the webhook front door for phone control. Do not buy any of
this before Tier 0 has run a ticket end to end.

## The 24-hour schedule

Shifts, in your local time. The point is that different hours use different tiers,
so the expensive models are only awake when they are needed.

| Window | Who | What | Tier |
|---|---|---|---|
| Continuous, every 15 min | Dispatcher | Read board, start workers, report | local/cheap |
| Every 5 min, market hours (09:30–15:00 CST) | Market watcher | Poll prices, decide if anything happened | local |
| 00:00–06:00 | Researcher | Overnight ingest: news, filings, feeds | cheap-bulk |
| 01:00 | SRE | Nightly full test run across all four repos | capable |
| 05:00 CST | Market department | Existing morning job: US close + analysis | mixed |
| 07:00 | Comms | Morning brief issue → your inbox | cheap |
| Daytime | Engineer / Reviewer | Ticket work as the board fills | capable |
| 15:15 CST | Market department | Existing afternoon job: China close + reflection | mixed |
| 23:00 | Controller | Daily spend report; trip breaker if over | deterministic |
| Monday 09:00 | Comms | Weekly digest + retro | cheap |
| Every hour | Watchdog | Did the heartbeat run? If not, alert | deterministic |

The watchdog matters more than it looks. **The default failure of an unattended
system is not chaos, it is silence** — a cron that stopped firing three weeks ago
and nobody noticed. Something must fail loudly when nothing happens.

## Driving it from a laptop and an iPad

Think of it as two different buildings. **The iPad is the boardroom: you approve,
direct, and read. The laptop is the workshop: you build, debug, and hold secrets.**
Do not try to make the iPad a workshop; you will be miserable.

### From the iPad

- **GitHub mobile app** — the primary console. Read the board, review diffs,
  approve and merge PRs, and give orders by commenting on issues. PR review is
  already the perfect mobile approval UI; you do not need to build one.
- **Claude Code on the web** (claude.ai/code in Safari) — start a cloud session
  from the sofa, describe a task, close the lid. It runs in a container, opens a
  PR, and keeps working without you. This is the single biggest unlock for
  laptop-free operation.
- **A control bot** (Telegram or Discord, an afternoon's work) — `/status`,
  `/pause`, `/resume`, `/ship 42`, `/spend`. The bot is a webhook into a
  Cloudflare Worker that fires `repository_dispatch` at GitHub. It is the fastest
  path from "I'm on a bus" to "the company did the thing."
- **The HQ dashboard** — a static page on this site, rebuilt every heartbeat:
  open tickets by stage, last run per cron, spend today, anything wearing
  `needs:human`. One glance answers "is it alive and does it need me?"
- **Issue comments as commands.** `/agent build`, `/agent spec`, `/agent hold`
  parsed by a workflow. Every command lands in the audit trail for free, which is
  why this beats a chat interface.

### From the laptop

Local Claude Code for deep work, running and evaluating models, anything touching
credentials, and the occasional 40-minute debugging session that would be
unbearable on glass.

### The rule that keeps it sane

**Every command is a written artifact** — an issue comment, a PR review, a bot
command that logs to an issue. Nothing is instructed through an ephemeral chat
that only one device can see. This is what lets you pick the company up on either
device without reconstructing what you told it yesterday.

## Security

- Secrets in Actions secrets and the runner env, never in prompts, never in repo files.
- The agent's GitHub token gets the narrowest scope that works — `contents:write`
  and `issues:write` for most roles; a reviewer role gets read plus review only.
- Run agents against a branch, never `main`. Branch protection is what stops a
  confused agent from rewriting history at 4am.
- Secret-scanning and dependency alerts on for all four repos.
- Agents propose credential rotation; they never perform it.
- Assume anything an agent reads from the internet may be trying to instruct it.
  The Researcher's output is *data*, and it is written into a ticket as data — no
  role should treat fetched text as orders.
