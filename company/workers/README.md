# Hiring the workers

The heartbeat claims tickets and writes work orders. A worker is the thing that
answers. This is how one is hired, and what it may never do.

## Why the workers pull instead of being pushed

The board is the queue: **the heartbeat leaves a claim and a work order; the
worker finds its own claim and reads the order cold.** Nothing pushes work into
a worker, and no worker chooses what to work on. That separation is what makes
"no AI is the boss" mechanical rather than aspirational.

## The engineer: OpenHands on DeepSeek V4 Pro

Built. `.github/workflows/company-engineer.yml` runs on `issues.labeled`, so the
moment the fan-out applies `claim:engineer` the engineer starts — no polling, no
schedule, no waiting for the next tick.

**Event-driven rather than scheduled, twice over.** The company is already
event-shaped, so a poller would only add latency. And `claude-code-action` has a
[documented bug](https://github.com/anthropics/claude-code-action/issues/814)
where subscription auth fails specifically under `schedule` triggers; not being
a scheduled workflow avoids that entire class of problem.

### What you must set once

Repository → Settings → Secrets and variables → Actions:

| Secret | What it is |
|---|---|
| `LLM_API_KEY` | DeepSeek API key |
| `PAT_TOKEN` | GitHub PAT, read/write on contents, issues, pull requests, workflows |
| `PAT_USERNAME` | your GitHub username |

**The PAT is not optional, and the reason is subtle enough to be worth stating.**
A pull request opened using the default `GITHUB_TOKEN` **does not trigger other
workflows** — GitHub does this deliberately to prevent runaway loops. Use it here
and CI never runs on the engineer's PRs: the gate looks green because nothing
ever examined it. That is the quietest way this whole design could fail.

### What the engineer sees

`company/ops/work_order.py` composes the prompt from the ticket and its work
order. It is a tested pure function rather than shell interpolation, because
that prompt is the only thing standing between an autonomous agent and the rest
of the repository.

### What happens when it stops

`company/ops/handoff.py` releases the claim — on success, on failure, and on
crash. It cannot be the worker's own last instruction, because a worker that
dies never reaches its last instruction.

**Success is judged by artifact, not by assertion.** The handoff asks GitHub
whether a pull request exists on `agent/issue-N`. It never asks the agent how it
went. `ORG.md` is explicit that a run producing no PR did not happen, and an
agent reporting its own success is exactly the claim that rule distrusts.

No PR means a failed attempt and the counter advances. Three failures and the
ticket gets `needs:human` and is never retried automatically.

## Roles with no worker are never claimed for

`assign.py` keeps a `HIRED` set, and today it contains one name: the engineer.

This matters more than it looks. Claiming a ticket for a role nobody has hired
means the lease expires unworked, the attempt counter advances, and after three
cycles the ticket escalates wearing `needs:human` **as though the work had been
tried and failed**. It was never attempted. The board would fill with false
failures on tickets whose only problem is that the stage has no worker yet.

So an unhired stage reports as *waiting on you*, which is what it is — and the
stall alarm already knows not to alarm about that.

Add a role to `HIRED` the moment a worker exists for it, and not before. Being
late costs a ticket that waits; being early costs a ticket that lies about
having failed.

## The reviewer: still you

Not built, and the routing says so — `capable-alt` resolves to `claude-code`, a
different vendor from the engineer, and nothing answers to it yet.

That is not a gap to paper over. **The reviewer is the gate, and a gate that has
never been run is worse than no gate, because you would trust it.** Until a
worker exists and has been exercised, you are the reviewer, and branch protection
enforces that whether or not one ever appears.

If you build one, it must not be DeepSeek. The engineer is DeepSeek; two
instances of one family share training and therefore share blind spots, and will
agree on the same wrong thing.

## Personal data has no automated worker at all

`dept:admissions` and `dept:casewriter` hold real records, and the engineer runs
on a third party. So those tickets are refused — **twice, independently**:

- `company/ops/models.py` closes every worker tier on personal data, so no model
  is even chosen.
- The workflow's gate job refuses before a prompt is composed or the API key is
  used, then labels the ticket `needs:human` and drops the claim.

Two controls because one of them will eventually be edited by someone who has
forgotten why it was there. The only tier still open to personal data is
`local` — a model on your own hardware sends nothing anywhere.

## What a worker may never do

Mechanical, not advisory. `CHARTER.md` is the authority.

- **Merge its own work.** Builder, reviewer and merger are three actors.
- **Edit `.github/workflows/`.** A worker that can rewrite its own gates has none.
- **Clear `COMPANY_PAUSED` or raise a cap.** Both are yours alone.
- **Touch a ticket claimed for someone else**, or one wearing `needs:human`.
- **Work around a routing refusal.** The refusal is the policy, not an obstacle.

## Upgrading the agent

The SDK is pinned to `1.42.1` in the workflow. The upstream example instead
curls a script from a third party's default branch and executes it in a job
holding write access and an API key — `company/workers/engineer_agent.py` is
vendored from that example (MIT) precisely so that does not happen here.

Bump the pin deliberately, in a PR, like any other dependency.

## A misconfigured company does not blame the ticket

If `LLM_API_KEY` or `PAT_TOKEN` is missing, the gate notices **before** the run
starts, releases the claim, and leaves the attempt counter alone. The ticket
goes straight back on the board and is picked up again the moment the secret
exists.

The alternative is worse than it sounds: a missing secret discovered mid-run
looks like a failed run, a failed run is a failed attempt, and three of those
escalate a perfectly good ticket as unworkable. The ticket would be blamed for
the company's own setup.

## Known gaps

- **Real spend is reported but not banked.** The engineer prints its actual cost
  to the run summary; the controller's ledger is still fed by estimates. Wiring
  the two together is the obvious next ticket.
- **DeepSeek V4 with OpenHands is unproven here.** Its SWE-bench numbers are
  strong and OpenHands is model-agnostic, but OpenHands documents performing
  best with frontier models. Watch the first few tickets before trusting it with
  anything `risk:med` or above.
