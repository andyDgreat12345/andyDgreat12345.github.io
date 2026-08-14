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

## Fly, end to end

**~$10–20/month all in.** No box to administer, no ID document at signup, and
the later self-hosted pieces can move to a VPS when you get to them.

Two apps: the Temporal server and the worker. The server has **no public
address** — Fly's private 6PN network gives it `company-temporal.internal`, so
only the worker can reach it, which is stronger isolation than a firewalled port.

### Why not Temporal Cloud

Temporal Cloud starts at **$100/month with no free tier**. A 15-minute heartbeat
generates a few tens of thousands of Actions a month against a 1,000,000 Action
allowance — enterprise rates for a rounding error, and more than the rest of the
stack combined. There are $1,000 in trial credits, so Cloud is a reasonable
*trial*, but it is a cliff you would rather not walk off in ten months.

Self-host now. Revisit when real agent work runs through it and losing workflow
history would actually hurt.

### 1. Postgres

```bash
fly postgres create --name company-temporal-db --region fra --initial-cluster-size 1 --vm-size shared-cpu-1x --volume-size 10
```

Keep the credentials it prints — they are shown once.

### 2. The Temporal server

```bash
fly launch --no-deploy --copy-config --config company/deploy/fly-temporal/fly.toml
fly secrets set --app company-temporal \
  POSTGRES_SEEDS=company-temporal-db.internal \
  POSTGRES_USER=postgres \
  POSTGRES_PWD='<password from step 1>'
fly deploy --config company/deploy/fly-temporal/fly.toml
fly logs --app company-temporal        # expect schema setup, then "Temporal server started"
```

### 3. The worker

```bash
fly launch --no-deploy --copy-config --config company/deploy/fly.toml
fly secrets set --app company-hq-worker GITHUB_TOKEN=github_pat_...
fly deploy --config company/deploy/fly.toml --dockerfile company/deploy/Dockerfile
fly logs --app company-hq-worker       # expect "worker up on task queue 'company-hq'"
```

Both apps must be in the **same region** — 6PN spans regions but you are paying
latency for nothing.

### 4. The clock

```bash
fly ssh console --app company-hq-worker -C "python company/temporal/schedule.py create"
fly ssh console --app company-hq-worker -C "python company/temporal/schedule.py trigger"
fly ssh console --app company-hq-worker -C "python company/temporal/schedule.py describe"
```

### 5. Watch it

There is no public Temporal UI in this setup, which is the point. To look at it,
tunnel in from your laptop:

```bash
fly proxy 7233:7233 --app company-temporal
temporal --address localhost:7233 workflow list
```

Or run the UI locally against the tunnel. Do **not** give the server a public IP
just to get a dashboard.

### Turning the cron heartbeat off

Once Temporal has run clean for a day, disable the Actions heartbeat so the two
clocks are not both triaging the same board: Actions → Company heartbeat → ⋯ →
Disable workflow. Keep the **watchdog** enabled — it is what tells you the
Temporal worker died.

Railway and Render take the same Dockerfile with their own config.

## Cheapest: one box running both, self-hosted Temporal

**~$7/month total, no Temporal Cloud.** Run the server next to the worker with
Postgres for persistence. Honest trade: you now operate a Temporal cluster and a
database, and if the box dies you lose workflow history. For a 15-minute heartbeat
that is survivable; it stops being survivable once real work runs through it.

Set `TEMPORAL_ADDRESS=localhost:7233` in `worker.env` and leave the key blank. Use
a production compose file with Postgres — **not** `company/temporal/docker-compose.yml`,
which is an in-memory dev server that loses everything on restart.

## Choosing a provider and region

Price is not the binding constraint. **Egress is.** The worker must reach
`api.github.com`, your Temporal endpoint, and — once roles actually run —
`api.anthropic.com`. A host that cannot reach those is unusable at any price.

This rules out more than it looks like:

| Region | Verdict | Why |
|---|---|---|
| **Mainland China** (Tencent, Alibaba, Huawei) | **No** | Anthropic does not serve mainland China and has blocked mainland IPs server-side since March 2026. GitHub is unreliable through the GFW and `raw.githubusercontent.com` is frequently unreachable, which breaks the bootstrap one-liner |
| **Hong Kong / Macau** | **No** | Also not on Anthropic's supported-regions list; HK IPs are turned away. This surprises people — HK is outside the GFW, but that is not the constraint here |
| **Singapore, Tokyo, Frankfurt, Silicon Valley** | **Yes** | Supported regions, ordinary egress |

So a Chinese provider is fine **only** in an international region. Tencent Cloud
Lighthouse in Singapore or Tokyo is genuinely cheap and should work; the same
product in Guangzhou or Hong Kong will not.

Two cautions if you go that route:

- **Enforcement is IP-based**, and provider ranges are identifiable. Anthropic
  tightened restrictions on Chinese-controlled entities in 2025. You are an
  individual, not an entity, but there is real residual risk that a
  Tencent-owned range gets treated differently than a Hetzner one. **Test before
  you prepay.**
- **Buy monthly first.** The headline prices on Chinese clouds are first-year
  new-user promotions that renew at standard rates. A one-year prepay on a box
  that turns out to be blocked is the expensive mistake here.

### The five-minute test that settles it

On the smallest instance in the region you are considering, before committing:

```bash
curl -sS -o /dev/null -w 'github    %{http_code}  %{time_total}s\n' https://api.github.com
curl -sS -o /dev/null -w 'anthropic %{http_code}  %{time_total}s\n' https://api.anthropic.com/v1/messages
curl -sS -o /dev/null -w 'pypi      %{http_code}  %{time_total}s\n' https://pypi.org/simple/
```

Expect `401`/`405` from the first two — that means you *reached* them, which is
the whole question. A timeout, a connection reset, or `403` from an edge you did
not authenticate to means the region is blocked. Slow but non-zero times on PyPI
are fixable with a mirror; the other two are not fixable.

### If a provider demands an ID document

Chinese cloud providers require real-name registration (实名认证) by law, so
Tencent, Alibaba and Huawei will all ask for a government ID. That requirement is
**specific to Chinese providers**, not a norm of the VPS industry. Most Western
providers treat a valid credit card as the verification and never ask for a
document. So the fix is not to hunt for a special host — it is simply to use a
non-Chinese one.

Policies do vary by country and account, and any provider may escalate to a
manual review if a signup looks unusual. Signup is free everywhere, so the honest
test is to create the account and find out in two minutes before paying.

**Avoid the "no-KYC / anonymous offshore VPS" segment.** It markets itself hard to
exactly this search, and it is the wrong tool here. Those hosts optimise for
untraceability, not for a box that stays up for years — and they change terms
abruptly. In March 2026 one long-running no-KYC provider suspended all services
and demanded verification from existing customers with no notice. You want a
boring host with an accounts department.

### Sizing

The worker alone fits in 512 MB. But `STACK.md` steps 4 and 6 add self-hosted
Langfuse and Graphiti, and `INFRA.md` Tier 1 adds Ollama — those want 8 GB. A
1 GB instance is correct for step 1 and wrong for the roadmap, so either size up
now or accept moving later.

### One charter note

`CHARTER.md` binds personal data — admissions records, case files — to
first-party providers. Where the *infrastructure* lives is a separate question
from where the model calls go, but the two interact once real user data flows
through this box. Worth a decision now rather than after.

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
