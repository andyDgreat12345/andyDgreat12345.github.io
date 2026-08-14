# Operating the company

`CHARTER.md` says who holds which authority. `ORG.md` says how a ticket moves.
This file is the part that is easy to skip and is the reason most of these
attempts die: what the owner actually does, how failures are caught, and the
order in which roles get hired.

## What guide this follows

None. There isn't one worth following yet, and anyone selling *the* playbook for
agent companies is selling. Roughly 40% of multi-agent deployments fail within
six months, and the failure is in the coordination layer rather than in what the
models could do — that number is the single most important input to this design.

What it is actually built from, in order of how load-bearing each is:

1. **The pattern already proven in this account.** `Chinese-ai-stocks-prediction-model`
   runs cron → work → state on a branch → issue as notification, unattended. Every
   structural decision here is that pattern generalised. It is first because it is
   the only input that has already survived contact with reality *here*.
2. **Operations practice that predates AI entirely.** Work queues, separation of
   duties, branch protection, CI as the gate, runbooks, kill switches, watchdogs,
   blast-radius limits. These are decades old and boring. The agents are new; the
   discipline is not, and almost every failure below is a discipline failure
   wearing new clothes.
3. **What the 2026 operators publish.** Air-gapped sandboxes because agent write
   access to production is an enormous blast radius. Agents that verify their own
   work having lower revert rates than humans. Fleet management reducing to
   observe / route / kill. The cost ladder.
4. **Judgement about what is load-bearing versus decorative.**

### What is not proven

Be honest about the seams, because that is where it will break:

- **The eight-role shape is a hypothesis.** Nobody has run this exact org. The
  parts to defend hardest are the boring ones — the queue, the gates, the kill
  switch, the artifact rule. The parts most likely to be wrong are the role
  boundaries and the number of roles.
- **Role cards are guesses until a role has run twenty tickets.** They are meant
  to be edited weekly, and a card nobody has edited in a month has drifted from
  what the role actually does.
- **The economics are unproven at this scale.** The cost model is arithmetic, not
  experience.

## How the failures actually happen

Ranked by how likely each is to be the one that gets you.

**1. Building the org before running a ticket.** The most common and the most
seductive. A fully specified eight-role company that has never moved a ticket is
a document. Two roles that shipped something real beat eight that exist on paper.

**2. Healthy but idle.** *This is the dangerous one.* Crashes are loud and get
fixed. The failure that kills unattended systems is the one where every dashboard
is green and nothing is happening — heartbeats posting, watchdog quiet, and no
work moving. Both real bugs found while building this were of that kind:

- Triage classified tickets and left them in `status:inbox`, a stage no role
  owns. Tickets would have accumulated silently behind green heartbeats.
- A Temporal activity called by string name returned an untyped dict, the
  workflow task failed, and Temporal retried it forever — presenting as a slow
  run rather than an error.

Neither was visible by reading the code. Both were obvious within seconds of
running it. **Alarms must fire on absence, not only on error.**

**3. No checkable definition of done.** An agent will report success against a
vague goal every time. The acceptance-criteria checklist is not bureaucracy — it
is the only thing standing between you and confident nothing.

**4. Cost blowup.** Usually a retry storm, not a big model. Hence the three-strike
cap and per-role budgets.

**5. Echo-chamber review.** Two instances of the same model share blind spots and
will agree on the same wrong thing. Hence a different family at the gate.

**6. Scope drift.** A small ticket returns a 900-line refactor. Hence acceptance
criteria and a reviewer whose job includes rejecting out-of-scope diffs.

**7. Doc rot.** The role cards describe a company that no longer exists.

## How bugs get prevented here

Seven defences, in the order they catch things.

| Defence | Catches |
|---|---|
| **Run it, don't read it** | The stall-shaped bugs above. Every stage gets exercised with real data before you trust it |
| **Tests on the decision layer** | `board.py` holds every routing decision and both entry points import it, so a mistake there is a mistake everywhere. It has the most tests for that reason |
| **No artifact means it did not happen** | Agents reporting success they did not achieve |
| **Alarms on absence** | Dead crons, stalled boards, silent workers |
| **A different model at the gate** | Correlated blind spots |
| **Blast-radius limits** | Sandboxes, branch protection, per-role budget caps, the kill switch — what turns a bad night into an annoyance |
| **CI as the actual gate** | Everything mechanical, and the reviewer stops being the last line |

## How the owner communicates

The shift that makes this a company rather than a chat:

> **You talk to the board, not to the agents.**

Every instruction is a written artifact — an issue, a comment, a review. Never
instruct an agent through an ephemeral chat only one device saw, because tomorrow
neither you nor any agent can reconstruct what was decided.

### The four things only you do

| Act | Where | Cadence |
|---|---|---|
| **File work** | New issue from the work-order template | Whenever it occurs to you |
| **Decide** | Comment on the ticket wearing `needs:human` | Daily, ~2 minutes |
| **Approve** | PR review, merge | On demand — mobile is fine |
| **Stop** | `COMPANY_PAUSED=1`, or pause the schedule | Rarely, instantly |

### The rhythm

- **Morning, 2 minutes.** Read the brief. Everything wearing `needs:human` is
  yours; nothing else needs you. If the brief takes longer than two minutes, the
  escalation threshold is set wrong.
- **Whenever.** File tickets as ideas arrive. A thought that does not become a
  ticket does not exist.
- **On demand.** Review and merge. This is the real bottleneck — be honest about
  which risks need you, and auto-merge `risk:low`.
- **Weekly, 20 minutes.** The retro. Read what jammed, and **edit exactly one
  role card.** This is what keeps the company true; skip it for a month and the
  cards become fiction.

### What you should never be doing

Chasing agents for status, re-explaining context you already wrote down, or
approving things that carry no risk. Each is a signal: status-chasing means the
brief is inadequate, re-explaining means a role card is missing a line, and
pointless approvals mean the risk labels are wrong.

## When to put a model behind each role

Not all at once. This is where the eight-role diagram becomes a trap.

**Hand-run a role before you automate it.** Take the role card, paste it into a
session, do the work yourself with it a few times. If you edit the card every
run, it is not ready to be a cron job — automating it just makes the same
correction happen without you watching.

**The hiring test:** a stage has jammed at least three times for lack of a role.
Not "the org chart has a gap."

| Order | Role | Hire it when |
|---|---|---|
| 1 | **Engineer** | Immediately. It is the only role that produces the thing you want; everything else supports or checks it. One agent means this one |
| 2 | **Reviewer** | Immediately after, never later. Engineer + reviewer is the minimum viable company — an engineer running unreviewed for even a week builds debt you cannot see |
| 3 | **Controller** | Before the first unattended overnight run. Not a model, arithmetic. Wire it before the first surprise bill, not after |
| — | *wait* | **Run 1–3 on real work for two to four weeks.** You will learn which stage actually jams. Everything below is a guess until then |
| 4 | Analyst | You keep writing acceptance criteria by hand |
| 5 | SRE | Something passed review and did not run |
| 6 | Researcher | A real ingest need appears — the market repo is the obvious one |
| 7 | Comms | You have stopped reading the raw board |
| 8 | Dispatcher-as-agent | Never, ideally. It is code, and it should stay code |

The order is not arbitrary: it runs from *produces value* to *protects value* to
*explains value*. Hire in that direction and a half-built company still works. Hire
backwards and you get a company that reports beautifully on nothing.
