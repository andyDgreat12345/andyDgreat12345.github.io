# Hiring the workers

The heartbeat claims tickets and writes briefs. Nothing in this repo *executes*
them — that is what a worker is, and this is how you start one.

## Why the workers pull instead of being pushed

The engineer is a Claude Code Routine. It wakes on a schedule with no memory of
the heartbeat that claimed its ticket, does one thing, and stops. Nothing can
push work into it, and it authenticates with a claude.ai subscription rather
than an API key — which is the entire reason this company runs without an
Anthropic wallet.

So the protocol is a board, not a queue: **the heartbeat leaves a claim and a
brief; the worker wakes, finds its own claim, and reads the brief cold.** Every
design decision in `company/ops/assign.py` falls out of that one constraint.

## The claim protocol

Every worker, whatever model is behind it, follows the same four steps:

1. **Find your claim.** Open issues labelled `claim:<your role>`. Take the
   lowest-numbered one. If there are none, stop — an idle worker is correct.
2. **Read the brief.** It is the most recent comment starting `## Work order`.
   It is self-contained on purpose; you were not present when it was written.
3. **Do exactly that one ticket.**
4. **Release.** Move the stage label, remove `claim:<your role>`, and comment
   what you did and how you checked it.

**Step 4 is not optional.** The claim is the company's only lock. A finished
ticket still wearing one blocks the next worker for the full 90-minute lease.

If you get stuck, that is a legitimate outcome: label `needs:human`, drop the
claim, say what you tried. The board is designed to wait for you.

## Hiring the engineer (Claude Code Routine)

In a Claude Code session on this repo, run `/schedule` and give it this. It
authenticates with your subscription — no API key, no billing to set up.

> Every hour, check `andyDgreat12345/andyDgreat12345.github.io` for open issues
> labelled `claim:engineer`. If there are none, stop and do nothing — an empty
> queue is the normal state and is not a problem to solve.
>
> If there is one, take the lowest-numbered one and read the most recent comment
> beginning `## Work order`. Read `company/roles/02-engineer.md` before you
> start; that is your job description and the work order is only the assignment.
>
> Do that one ticket. Open a draft PR. Then move the ticket's stage label to
> `status:verify`, remove the `claim:engineer` label, and comment what you did
> and how you checked it.
>
> Do not merge your own pull request under any circumstances. Do not work on any
> ticket that is not claimed for you. If you cannot finish, label the ticket
> `needs:human`, remove your claim, and say what you tried and what you would
> need — stopping is a valid outcome and guessing is not.

**One hour is the floor** — Routines cannot run more often, which is why
`LEASE_MINUTES` is 90 rather than 30. Routine runs draw on a separate daily cap
from ordinary usage; `COMPANY_DAILY_RUN_CAP` is the controller's mirror of it,
and the shift report shows how much is left.

Verify the hire the same way you would with a person: file one small ticket,
watch it get claimed on the next heartbeat, and check that a PR appears within
the hour. If nothing happens, `/schedule list` shows whether the routine exists
and when it last ran.

## Hiring the reviewer (DeepSeek V4 Pro)

Not yet built — it needs a `DEEPSEEK_API_KEY`, and writing an API client against
a key nobody has produces code that has never once been run. **The reviewer is
the gate, and a gate that has never been tested is worse than no gate**, because
you would trust it.

What is already true: `models.py` routes `capable-alt + public` to
`deepseek-v4-pro`, the label and capacity exist, and the fan-out will claim
review work the moment something answers to `claim:reviewer`. Until then,
**you are the reviewer** — which is the correct interim state, not a gap. The
branch protection on `main` enforces it whether or not a worker exists.

## What a worker may never do

These are mechanical, not advisory — CHARTER.md is the authority and branch
protection enforces the first one regardless of what any prompt says.

- **Merge its own work.** Builder, reviewer, and merger are three different
  actors. This is the single rule the whole design rests on.
- **Clear `COMPANY_PAUSED`, or raise a cap.** Both are the owner's alone.
- **Claim a ticket the heartbeat did not claim for it.** The lock only works if
  everyone respects it, including a worker that is confident it could help.
- **Send personal data to the bulk tier.** `models.py` raises rather than
  routing it. That refusal is correct; do not work around it.
