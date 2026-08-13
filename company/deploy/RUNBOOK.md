# Where to run this, and how

Two processes have to exist somewhere. They are different in kind, and conflating
them is the usual confusion.

| | What it is | Must survive |
|---|---|---|
| **Temporal server** | Holds all workflow state and history | Everything. If it loses data, runs vanish |
| **Worker** | Stateless process that executes the code | Nothing. Kill it any time; runs resume |

The worker is disposable — that is the entire point of durable execution. The
server is not. So the decision is really about where the *server* lives; the
worker can go almost anywhere.

## What will not work

- **GitHub Actions.** Jobs cap at six hours and the worker must run continuously.
  Actions stays useful for the Tier 0 fallback and the watchdog, not for this.
- **Your laptop.** It closes. Fine for development, not for the company.
- **This session's container.** It is reclaimed after inactivity. I ran the tests
  here; nothing survives.

## Recommended: one small VPS + Temporal Cloud

**~$4–7/month for the box, plus Temporal Cloud.** Verify current Temporal Cloud
pricing yourself — it starts with trial credits, and the published entry point has
moved more than once.

The reasoning is the roadmap, not this step. `STACK.md` later wants self-hosted
Langfuse (step 4), Graphiti (step 6), and `INFRA.md` Tier 1 wants Ollama for the
free local model tier plus a self-hosted Actions runner. Those all land on the
same box. Buying it now means step 1 pays for infrastructure you need anyway.

Hetzner CX22 or similar, Ubuntu 24.04, 2 vCPU / 4 GB. Get 8 GB if you intend to
run a local model on it later.

```bash
# On the fresh box, as root:
curl -fsSL https://raw.githubusercontent.com/andyDgreat12345/andyDgreat12345.github.io/main/company/deploy/bootstrap.sh | bash
```

That installs Python, creates an unprivileged `company` user, clones the repo to
`/opt/company`, builds a virtualenv, installs the systemd unit, and turns on
unattended security updates. It stores **no secrets** and starts nothing.

Then:

```bash
sudo nano /etc/company/worker.env      # see "Credentials" below
sudo systemctl start company-worker
sudo journalctl -u company-worker -f   # expect: worker up on task queue 'company-hq'

cd /opt/company
sudo -u company .venv/bin/python company/temporal/schedule.py create
sudo -u company .venv/bin/python company/temporal/schedule.py trigger
sudo -u company .venv/bin/python company/temporal/schedule.py describe
```

## Alternative: Fly.io, no box to administer

**~$2–5/month.** Right if you would rather not own a server, accepting that the
later self-hosted pieces will need somewhere else to live.

```bash
fly launch --no-deploy --copy-config --config company/deploy/fly.toml
fly secrets set GITHUB_TOKEN=ghp_... TEMPORAL_API_KEY=...
fly deploy --config company/deploy/fly.toml --dockerfile company/deploy/Dockerfile
fly logs
```

Railway and Render take the same Dockerfile with their own config.

## Cheapest: one box running both, self-hosted Temporal

**~$7/month total, no Temporal Cloud.** Run the server next to the worker with
Postgres for persistence. Honest trade: you now operate a Temporal cluster and a
database, and if the box dies you lose workflow history. For a 15-minute heartbeat
that is survivable; it stops being survivable once real work runs through it.

Set `TEMPORAL_ADDRESS=localhost:7233` in `worker.env` and leave the key blank. Use
a production compose file with Postgres — **not** `company/temporal/docker-compose.yml`,
which is an in-memory dev server that loses everything on restart.

## Credentials

### GitHub token

Create a **fine-grained personal access token** scoped to the four repos, not a
classic token. Minimum permissions for what the heartbeat actually does:

- **Issues:** Read and write — triage labels and the shift report
- **Pull requests:** Read — the WIP limit counts PRs in review
- **Metadata:** Read (implied)
- **Variables:** Read — only if you want the `COMPANY_PAUSED` fallback read; the
  env var in `worker.env` works without it

Nothing else. No `contents:write`, no admin. The worker does not push code.

Set an expiry and put a calendar reminder to rotate. Per `CHARTER.md`, agents
propose rotation; they never perform it.

### Temporal Cloud

Create a namespace, then an API key. Put both in `worker.env`:

```
TEMPORAL_ADDRESS=<namespace>.<account>.tmprl.cloud:7233
TEMPORAL_NAMESPACE=<namespace>.<account>
TEMPORAL_API_KEY=...
```

`worker.py` turns TLS on automatically when a key is present.

## Start paused

`bootstrap.sh` and `fly.toml` both set `COMPANY_PAUSED=1` deliberately. The
heartbeat runs and reports on schedule but starts no work. Watch a few cycles,
read the shift-report comments, confirm it is triaging sensibly — then set it to
`0` and restart. Bringing an unattended system up live against a real board on day
one is how you get a surprise.

## Verifying it works

1. `schedule.py describe` shows recent actions and a `next →` time.
2. The Temporal UI shows a `HeartbeatWorkflow` run every 15 minutes, each with its
   activities, inputs, outputs, and any retries.
3. A "Shift report — <date>" issue exists on the repo with one comment per run.
4. Kill the worker (`systemctl stop company-worker`) mid-run, start it again, and
   watch the run finish. That is the property you paid for — worth confirming once
   with your own eyes.

## When it breaks

| Symptom | Cause | Fix |
|---|---|---|
| No heartbeats, worker log quiet | Schedule paused | `schedule.py describe`, then `resume` |
| Heartbeats run, nothing happens | `COMPANY_PAUSED=1` | Expected until you flip it |
| Workflow starts, never finishes | Workflow task failing and retrying forever — presents as a hang | Temporal UI → pending workflow task → stack trace |
| `403` in the worker log | Token expired or under-scoped | Reissue with the permissions above |
| Worker restart-looping | Bad `worker.env` | `journalctl -u company-worker -n 50` |
| Everything fine, no shift report | Token lacks Issues write | Reissue |

## What I could not do for you

Everything above is a command you run, not one I ran. Provisioning a box, creating
accounts, and holding your credentials are yours by necessity — a token that
reaches me is a token to rotate. The code is tested and the deployment is
scripted; the account-shaped parts are the boundary.
