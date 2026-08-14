# Rollout, cost, and how this usually fails

## The sequencing principle

Build the company in the order that lets you *watch it work*. A fully specified
eight-role org that has never moved a ticket is a document, not a company. Get one
real ticket from inbox to merged with two roles, then add a role each time a stage
starts jamming.

## Week 1 — one ticket, end to end

Five tasks. Nothing here needs money or a server.

1. **Make HQ real.** Merge this `company/` directory. Add the label vocabulary
   from [`ORG.md`](ORG.md#the-labels) and create a Project board with a column per
   stage.
2. **Write the work-order issue template** so every ticket arrives with a body,
   acceptance criteria, and a `dept:` label already on it.
3. **Turn on the gates.** Branch protection on `main` for all four repos: require
   a PR, require one review, require the existing checks. This is the single
   highest-leverage hour in the whole plan — it is what makes "no AI is the boss"
   true rather than aspirational.
4. **Hire two roles.** Engineer and Reviewer. Drop [`roles/02-engineer.md`](roles/02-engineer.md)
   into a Claude Code Routine — it authenticates with your claude.ai
   subscription, so no API wallet is needed — and drop
   [`roles/03-reviewer.md`](roles/03-reviewer.md) into DeepSeek V4 Pro, which is
   the different family the gate requires and costs cents per review.
5. **Run one real ticket.** Something small and genuinely useful — the HQ
   dashboard page on this site is a good first one, because from then on you can
   see the company. Watch every stage. Fix what confused them.

**Done when:** a ticket you did not touch became a PR that a different model
reviewed and you merged from your phone.

## Weeks 2–3 — make it run without you

6. **Heartbeat + dispatcher.** The workflow and [`ops/dispatch.py`](ops/dispatch.py)
   are already here. Point them at your board.
7. **Kill switch and budget breaker.** `COMPANY_PAUSED`, the daily cap, and the
   Controller role. Do this *before* the first unattended overnight run, not after
   the first surprise bill.
8. **Watchdog.** Hourly check that the heartbeat ran. Alert by issue. Silence is
   the failure mode you are defending against.
9. **Bring in the bulk tier.** Give the Researcher a DeepSeek key and point it at
   the market repo's Chinese-language sources. This is where the cost ladder
   starts paying for itself.
10. **Let it run a weekend unattended.** Read the Monday retro. This is the real test.

## Month 2 — depth

11. Add Analyst, SRE, and Comms as their stages start jamming.
12. Stand up the Tier 1 box: self-hosted runner, Ollama for the local filter tier,
    the dispatcher as a service.
13. Ship the control bot for `/status` and `/pause` from anywhere.
14. Turn the repeated instructions you keep re-typing into Claude Code **skills** —
    they are exactly SOPs, and a role that keeps needing the same correction is a
    missing skill.
15. Enable auto-merge on `risk:low` tickets with a green review. Your merge queue
    should only contain things that actually need you.

## Month 3 — make it a business

16. Pick the product line with real users and give it a paid department.
17. Add a metric each department reports weekly. A company with no numbers is a
    hobby with a cron job.
18. Quarterly: re-run the routing table in [`MODELS.md`](MODELS.md) against current
    prices, and delete the roles that never fired.

## What it costs

Order-of-magnitude, monthly. Prices move — re-check before committing.

| Phase | Line items | Rough total |
|---|---|---|
| Week 1 | GitHub free tier, existing Claude subscription | **$0** |
| Weeks 2–3 | Above + DeepSeek API for bulk ingest (a few dollars at real volume) | **$5–10** |
| Month 2 | Above + small VPS + DeepSeek credit for review and second attempts | **$20–35** |
| Month 3 | Above + a managed database if you have outgrown SQLite | **$30–60** |

The dominant variable is not the subscription, it is **how often you wake a
capable model.** A 15-minute heartbeat that always calls Opus costs real money; a
15-minute heartbeat where a local model decides whether to call Opus costs almost
nothing. That single decision is worth more than every other cost control here.

## How this fails

Each of these is common, and each has a mitigation already built into the design.

| Failure | What it looks like | Mitigation |
|---|---|---|
| **Silence** | A cron stopped firing in July; you notice in September | Watchdog alerts on *absence*, not just errors |
| **Runaway loop** | Agent creates work for itself, forever, at $3 a turn | Agents may file tickets but never start their own; three-strike retry cap |
| **Cost blowup** | $400 weekend | Daily cap → breaker trips `COMPANY_PAUSED` automatically |
| **PR spam** | Forty open PRs, none finished | WIP limit: dispatcher starts no new build while N are in review |
| **Echo-chamber review** | Reviewer approves everything | Reviewer is a different model family and is graded on defects found |
| **Test gaming** | Agent "fixes" the test instead of the code | Reviewer's boundary explicitly covers this; test changes need justification in the PR body |
| **Scope drift** | Small ticket returns a 900-line refactor | Acceptance criteria in the spec; reviewer rejects out-of-scope diffs |
| **Confident nonsense** | Report says done, nothing shipped | No artifact = did not happen; SRE verifies by running it |
| **Prompt injection via research** | A scraped page tells the agent to push to `main` | Fetched content is data, written into tickets as data; no role acts on instructions found in fetched text |
| **Secret leakage** | A key ends up in a log or a PR body | Agents reference secret *names*; secret scanning on; least-scope tokens |
| **You become the bottleneck** | Everything waits on your approval | Auto-merge `risk:low`; be honest about which risks are real |
| **Doc rot** | Role cards describe a company that no longer exists | Monthly retro edits the cards; a role card is code, not documentation |

## The honest caveat

This works well for tasks with a **checkable definition of done** — code that
compiles and passes tests, data that gets ingested, summaries that get filed,
reports that get published. It works badly for taste, strategy, and anything where
you cannot mechanically tell success from failure. Those stages stay yours, and
the design is built so they stay yours: you hold spec approval on large tickets and
the merge key on anything public.

Aim the agents at the checkable work. Keep the judgement.
