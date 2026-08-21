# Rehearsing a work order on your own machine

You have DeepSeek Harness (`dsh`) on Windows. It runs the same vendor and the
same models the company's workers run, on the key you already have — which makes
it the one place you can watch a work order play out **before it costs a ticket
an attempt.**

## What it is for, and what it is not

**It is your cockpit.** A rehearsal room, a debugger, and the hands you use for
work no automated worker may touch.

**It is not the engineer.** This matters more than it sounds. The company runs in
GitHub Actions specifically so no machine of yours is in the critical path — a
worker on your Windows PC stops when the machine sleeps, drops Wi-Fi, or reboots
for an update, and it stops *silently*: the board looks healthy and tickets sit
claimed until their leases expire. `OPERATING.md` ranks that shape as the failure
most likely to kill an unattended company, and moving the engineer onto your
desk would build it in on purpose.

So: rehearse locally, run in the cloud.

## Rehearsing a real work order

The prompt a worker receives is not written in the workflow — it is composed by
`company/ops/work_order.py`, which is a tested pure function. That means you can
generate the exact prompt for any ticket and paste it into `dsh`:

```bash
# The prompt the engineer would get for ticket 21
GITHUB_TOKEN=<your PAT> python company/ops/work_order.py --issue 21 --role engineer

# The prompt the analyst would get for the same ticket
GITHUB_TOKEN=<your PAT> python company/ops/work_order.py --issue 21 --role analyst
```

Paste the output into `dsh` and watch. **Byte for byte what runs in Actions** —
if it goes wrong here, it would have gone wrong there, and you found out for the
price of your own time instead of one of the ticket's three attempts.

## The three things worth rehearsing

**A ticket you are not sure is specified well enough.** Run the analyst prompt
against it. If the criteria that come back are vague, the ticket is vague, and
you learned that before an engineer built the wrong thing.

**A prompt change.** Editing `work_order.py` changes what every future worker is
told. Rehearse it against a real ticket before merging — a boundary that reads
clearly to you may read as optional to an agent.

**A worker that failed twice.** The board will escalate it on the third attempt.
Rehearsing locally tells you whether the ticket is impossible or the prompt is
unclear, and those need opposite fixes.

## Work only you can do

Some tickets have no automated worker and never will:

- **`dept:admissions` and `dept:casewriter`** hold real records. The workflow
  gate refuses them before a prompt is composed, and `models.py` refuses to
  choose a model at all. `dsh` runs on your hardware against your key — you may
  work those tickets yourself, but the same rule applies to what you paste in.
- **Anything wearing `needs:human`.** That label means the company has stopped
  and is asking you a question.

## What not to do with it

**Do not push from a rehearsal.** A local run that opens a pull request produces
work the board never claimed, with no work order, no lease, and no ledger entry.
The gate will flag it (`no-ticket`), which is the system working — but the
cleaner path is to file a ticket and let the company claim it.

The company's authority comes from the board being the only source of work. A
worker that appears from your desktop is exactly the manager-agent shortcut
`CHARTER.md` exists to prevent, wearing your face instead of a model's.
