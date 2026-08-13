# Charter

## Mission

Run four product lines with the labor of one person and a staff of agents, such
that work continues while the owner sleeps, and nothing irreversible happens
without a human turning a key.

## Product lines (departments)

| Department | Repo | Ships to |
|---|---|---|
| Front office / public face | `andyDgreat12345.github.io` | The public + the internal dashboard |
| Case writer | `Ai-case-writer-tool` | End users, handles their text |
| Market research | `Chinese-ai-stocks-prediction-model` | You; research output, not advice |
| Admissions modelling | `College-acceptance-prediction-ai-` | Users, handles personal data |
| HQ | this directory | The company itself |

## Non-goals

Stated so agents stop asking, and so scope does not drift while you are asleep:

- Not a chatroom of AIs discussing strategy. Discussion produces no artifact.
- Not an autonomous trading system. The market repo produces research, never orders.
- Not a headcount contest. Adding a role is a cost; roles are added only when a
  ticket type is repeatedly stalling for lack of one.
- Not real-time. This company runs in batches, minutes to hours. Anything needing
  sub-second response is a service you write, not an agent you run.

## The authority model

This is the part that makes it a company instead of a swarm.

### Authority you keep, permanently

Encoded mechanically, not by asking agents nicely:

- **Merging to `main`** on any repo that faces users or money.
- **Spending increases** — new paid services, raised token budgets, new hardware.
- **New product lines**, deprecations, and anything with a public announcement.
- **Anything irreversible**: deleting data, force-pushing, rotating credentials,
  publishing to a package registry, sending mail to a real person.
- **Turning the kill switch on and off.**

### Authority the process holds

Not held by any agent:

- **Routing.** The dispatcher matches labels to roles. It cannot re-prioritise,
  cannot approve, cannot merge, cannot invent tickets. It is a mail room.
- **Sequencing.** A ticket moves stage by stage because it has the exit artifact
  for the stage it is in, not because an agent decided it was ready.
- **Admission.** CI, tests, and required checks decide whether work is done.
  No agent's assessment substitutes for a green check.

### Authority each agent holds

Every role card in [`roles/`](roles/) states five things, and an agent that
cannot fill them in is not a role yet:

1. **Job** — the one kind of output it produces.
2. **Boundary** — what it must never do, named explicitly.
3. **Input** — the exact label or event that wakes it.
4. **Artifact** — what must exist when it finishes. No artifact means no work happened.
5. **Escalation** — the condition under which it stops and asks instead of guessing.

### Separation of duties

Three rules, each enforced by machinery rather than instruction:

- **Builder ≠ reviewer.** The agent that wrote a diff never approves it. Enforced
  by branch protection requiring a review, and by the reviewer running on a
  different model family (see [`MODELS.md`](MODELS.md)). Two instances of the same
  model reviewing each other is an echo chamber, not a review.
- **Reviewer ≠ merger.** Approval is a signal, merging is an act. For `risk:low`
  tickets the merge may be automated on a green review; for everything else you
  merge.
- **Two keys for irreversible acts.** One agent proposes, a different agent
  verifies against reality (runs it, diffs it, reproduces it), and you turn the key.

## The kill switch

Every agent's first action, before any other work, is to check the switch. An
agent that skips this check is broken and should be fixed, not reasoned with.

- **The switch** is the GitHub repository variable `COMPANY_PAUSED` on the HQ repo.
  Set it to `1` to halt everything.
- **From an iPad**: repo → Settings → Variables, or `/pause` in the control bot.
- **Effect**: the heartbeat still runs and still reports, but the dispatcher
  starts no workers. Work in flight finishes; nothing new begins.
- **Budget breaker**: the cost controller sets the same variable automatically
  when the daily spend cap is hit. See [`roles/07-controller.md`](roles/07-controller.md).

A company with no stop button is not autonomous, it is unattended. The switch is
the thing that makes it safe to let this run while you sleep.

## Data policy

Binding on every role, and the reason model routing is not purely about price.

- **Personal data never leaves first-party providers.** Admissions essays, user
  case files, and anything identifying a real person go to Anthropic's API only.
  They do not go to the cheap bulk tier.
- **Public data may go anywhere.** Public filings, news, market prices, docs,
  and your own source code that is already in a public repo.
- **Secrets go nowhere.** No agent reads a credential into its context. Secrets
  live in GitHub Actions secrets and the runner's environment; agents reference
  names, never values.
- **When in doubt the data is personal.** The escalation is free; the leak is not.
