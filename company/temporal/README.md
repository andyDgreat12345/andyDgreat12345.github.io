# Step 1 — the heartbeat on Temporal

This is step 1 of the build order in [`../STACK.md`](../STACK.md): move the company
clock off cron and onto durable execution. It is the highest-leverage change in
the whole stack, because everything added later inherits the property it gives you.

## What changes

The cron heartbeat in `.github/workflows/company-heartbeat.yml` still works and is
still the fallback. The difference is what happens when a run dies halfway.

| | Cron (Actions) | Temporal |
|---|---|---|
| Run dies at step 9 of 12 | Whole run lost; next cycle starts over | Resumes at step 9 |
| GitHub returns 502 | Cycle wasted, 15-minute wait | Activity retries in seconds |
| Two runs overlap | Concurrency group queues or cancels | `overlap=SKIP`, explicit |
| "Why did it route that ticket?" | Read the log, if still retained | Replay the workflow history |
| Worker restarts mid-run | Run lost | Another worker picks it up |
| Partial side effects | Labels written twice on retry | Written once |

The last row is the one that matters most in practice. A cron dispatcher that
crashes after posting a comment will post it again next cycle. This one will not.

## Layout

```
company/ops/board.py        pure routing logic — no I/O, shared by both paths
company/ops/dispatch.py     Tier 0 entry point (stdlib only, no Temporal)
company/temporal/
  activities.py             every side effect: GitHub reads and writes
  workflows.py              HeartbeatWorkflow — deterministic orchestration
  worker.py                 the always-on process
  schedule.py               create/pause/trigger the 15-minute clock
  test_heartbeat.py         end-to-end test with stubbed activities
```

The split is the design. **`board.py` contains every routing decision and touches
nothing external**, so the cheap path and the durable path cannot drift apart —
change how work is routed in one place and both follow. It is also what makes the
workflow legal: Temporal replays workflow code during recovery, so it must be
deterministic, and a module with no clock and no network is deterministic by
construction.

## Run it locally

```bash
pip install -r company/temporal/requirements.txt

# 1. A dev server (in-memory, no setup, Web UI on :8233)
temporal server start-dev

# 2. The worker, in another shell
export COMPANY_REPO=andyDgreat12345/andyDgreat12345.github.io
export GITHUB_TOKEN=ghp_...
python company/temporal/worker.py

# 3. The clock
python company/temporal/schedule.py create
python company/temporal/schedule.py trigger     # don't wait 15 minutes
python company/temporal/schedule.py describe
```

Watch it at http://localhost:8233 — every heartbeat, every activity, every retry,
with full input and output. That view is most of the value of this step.

## Test it

```bash
temporal server start-dev --headless
python company/temporal/test_heartbeat.py
```

Runs the real workflow against a real server with stubbed GitHub activities. Four
cases: normal routing, the kill switch, **durability** (an activity is failed once
on purpose, and the test asserts the run resumed without repeating earlier work),
and a dry run that writes nothing.

Expect a `RuntimeError: simulated GitHub 502` traceback in case 3. That is the
point of case 3.

## Temporal Cloud

Same code, four environment variables:

```bash
export TEMPORAL_ADDRESS=<namespace>.<account>.tmprl.cloud:7233
export TEMPORAL_NAMESPACE=<namespace>.<account>
export TEMPORAL_API_KEY=...                 # or the mTLS pair below
# export TEMPORAL_TLS_CERT=/path/client.pem
# export TEMPORAL_TLS_KEY=/path/client.key
```

`worker.py` picks TLS automatically: certificate pair if both are set, otherwise
TLS-on when an API key is present, otherwise plaintext for the dev server.

## Keep the worker up

The worker is the one thing that must always run. It holds no state — Temporal
does — so restarting it is free and a run in flight survives.

**systemd** (`company/temporal/company-worker.service`) on the Tier 1 box from
[`../INFRA.md`](../INFRA.md):

```bash
sudo cp company/temporal/company-worker.service /etc/systemd/system/
sudo systemctl enable --now company-worker
journalctl -u company-worker -f
```

**Docker** — `docker compose -f company/temporal/docker-compose.yml up -d` brings
up a dev server and the worker together, for trying the whole thing on a laptop.

## Two kill switches now

They are different and you want both:

- **`COMPANY_PAUSED=1`** — stops the *work*. Heartbeats still run and still report,
  so you can see the company is alive and deliberately idle. This is the one from
  [`../CHARTER.md`](../CHARTER.md) and the one to reach for normally.
- **`schedule.py pause`** — stops the *clock*. No heartbeats at all. Records a note
  saying why. Use when you are changing the workflow itself.

## Notes for whoever changes this next

- **Never call an activity by string name.** A string carries no return type, so
  Temporal hands back a raw dict; the workflow then fails its workflow task, which
  retries forever and looks exactly like a hang rather than an error. Pass the
  function. This cost an hour the first time.
- **Anything non-deterministic goes in an activity** — clock, network, randomness,
  `uuid4()`. `date.today()` is an activity here for precisely that reason.
- **Changing a running workflow's shape breaks in-flight runs.** For a 15-minute
  heartbeat the easy answer is to pause the schedule, let it drain, then deploy.
- **Test with a timeout.** A broken workflow hangs rather than fails, so a test
  without a deadline hangs with it.

## Next

Step 2 in [`../STACK.md`](../STACK.md) — sandboxes, so the worker fan-out this
workflow leaves as a stub can run agent-authored code somewhere that does not
matter.
