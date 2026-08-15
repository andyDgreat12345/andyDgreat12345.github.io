# Hiring the workers

The heartbeat claims tickets and writes work orders. A worker is the thing that
answers. This is how one is hired, and what it may never do.

## Why the workers pull instead of being pushed

The board is the queue: **the heartbeat leaves a claim and a work order; the
worker finds its own claim and reads the order cold.** Nothing pushes work into
a worker, and no worker chooses what to work on. That separation is what makes
"no AI is the boss" mechanical rather than aspirational.

## The engineer: OpenHands on DeepSeek V4 Flash

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
| `PAT_TOKEN` | GitHub PAT, read/write on **contents, issues, pull requests** — and deliberately NOT workflows |
| `PAT_USERNAME` | your GitHub username |

Withholding the **workflows** permission is deliberate. The work order tells the
engineer never to edit `.github/workflows/`; withholding the scope makes that
mechanical rather than a request, so the push simply fails if it ever tries. A
worker that can rewrite its own gates has none.

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

## The gate that needs no model

`company/ops/gate.py`, run by `.github/workflows/company-gate.yml` on every pull
request. It checks the half of review that needs no judgement:

| Rule | Why it blocks |
|---|---|
| `forbidden-path` | `.github/workflows/` touched — a worker that can rewrite its own gates has none |
| `no-ticket` | No `Closes #N`, so nothing links the work back to the board |
| `wrong-ticket` | Closes a different ticket than the branch was claimed for |
| `unticked-criteria` | An unticked box is the author saying it did not finish |
| `no-test` | Source changed, no test file touched |
| `test-without-assertion` | An empty test turns a gap into a green tick |

Missing evidence and a non-draft PR are **warnings**, not blocks. A gate that
blocks on judgement gets routed around, and a routed-around gate is worse than
none because the merge still looks checked.

**Blocking for `agent/*` branches, advisory for everyone else.** These rules
encode how a *worker* is asked to submit work; blocking a human on a worker's
conventions would teach everyone to ignore it.

Three things make this better than a model at its own job: it cannot hallucinate
a finding, it cannot be switched off by a spend cap or leak a key to a fork, and
it **shares no training with the builder** — which is the entire reason
`MODELS.md` wants a different family at the gate. It does not replace a
reviewer; it means a reviewer spends attention on the half that needs judgement.

## The janitor: duplicate detection

`company/ops/dedupe.py`, run on `issues.opened`. It exists because the board
produced the bug it prevents — #12 and #13 were the same ticket filed twice, and
the second would have been claimed, worked and paid for.

Closed tickets are compared too, and that is the costlier catch: a duplicate of
something already shipped wastes a claim *and* produces a change nobody needed.

Similarity is measured over **words, not characters**, and that took a false
positive to get right. Character matching scores "lease dashboard" against
"ledger dashboard" at 0.84 — they share letters, not meaning. Words are matched
fuzzily so "lease" still finds "leases", but "ledger" is not close enough to
count.

When it fires it labels `needs:human` and says plainly that it has no judgement,
because deciding two tickets are the same is one. `GITHUB_TOKEN` is enough here
and deliberately so: `needs:human` is a label no worker wakes on, so a token
that cannot trigger workflows is exactly right.

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

## What a run costs, and who writes it down

The controller prices work from a table in `models.py`. That is good enough to
trip a cap, and it is not what happened — the provider knows the real number and
the agent can read it back. So every run banks its actual cost to
`company/ops/bank.py`, which appends one line to `ledger.jsonl` on the
**`company-state`** orphan branch.

Three details that are deliberate:

- **Banked before the handoff, and on failure too.** The money is spent whether
  or not a PR came out of it, and a run that fails *expensively* is exactly the
  one the controller needs to see.
- **An unreadable cost is recorded as a hole, not a zero.** The controller
  counts holes separately and says so on the report; spend written down as
  $0.00 is how a bill surprises someone.
- **A failed ledger write never fails the run.** A ticket that was built and
  handed on should not be reported as failed because bookkeeping lost a race —
  but it prints loudly, because a silent bookkeeping failure is how a ledger
  quietly stops being true.

Entries carry `"source": "provider"` so they can be told apart from the
controller's own estimates. When the two disagree, the estimate is the one
that's wrong.

## Known gaps

- **DeepSeek V4 with OpenHands is unproven here.** Its SWE-bench numbers are
  strong and OpenHands is model-agnostic, but OpenHands documents performing
  best with frontier models. Watch the first few tickets before trusting it with
  anything `risk:med` or above.
