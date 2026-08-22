# DeepTutor — where to run it, and how the iPad gets in

[DeepTutor](https://github.com/HKUDS/DeepTutor) (HKUDS, Apache 2.0) is an
agent-native learning workspace: chat, solve, quiz, research, visualize and a
mastery path over shared knowledge bases, with persistent Memory, a learner
Profile, and a Heartbeat that schedules your review sessions. It is the study
tool. This directory is where it runs.

## The one fact that decides everything

DeepTutor is a **stateful, always-on server** — a Python/FastAPI backend behind a
Next.js 16 frontend, with a `data/` tree that holds your knowledge bases, chat
history, notebooks, question banks and memory. Its whole value is that it
remembers you across months. That rules out most of the obvious places:

| Place | Why not |
|---|---|
| **This repo / GitHub Pages** | Pages is a static file host. It serves HTML. It cannot run Python, hold a socket open, or keep a disk. |
| **GitHub Actions** | Six-hour job cap, and nothing survives the run. `INFRA.md` already draws this line: *anything persistent moves to the box.* |
| **The iPad itself** | iPadOS has no Docker, no background daemons, no real filesystem for a server to own. iSH/a-Shell are toys for this. |
| **A Claude Code session container** | Reclaimed after inactivity. Fine for building this file; useless for hosting. |
| **Vercel / Netlify** | Next.js yes, FastAPI + a persistent volume no. |

So it is Tier 1 in `INFRA.md` terms — it lives on the box. The iPad is the
boardroom, exactly as that document says: **the iPad is a browser pointed at the
box, and that is the whole architecture.** DeepTutor is browser-native, so this
costs no extra work at all.

## Recommendation

**A Hetzner CPX32 (4 vCPU / 8 GB / 160 GB), Ubuntu 24.04, running the published
Docker image, reachable from the iPad over Tailscale.**

Three decisions inside that, each with a reason:

**8 GB, not 4.** `company/deploy/RUNBOOK.md` specs a CX22 (2 vCPU / 4 GB) for the
Temporal worker. DeepTutor does not fit beside Temporal + Postgres + the worker in
4 GB — the Next.js server and the Python backend are two long-lived runtimes
before any document parsing starts, and MinerU/Docling pull real ML models into
memory when you feed them a PDF. Either give DeepTutor the 8 GB box and leave the
company on its own, or size the shared box at 8 GB from the start.

**CPX, not CX.** The obvious pick was a CX32, and it is the wrong one: Hetzner's
cost-optimized CX line reads *currently not available* on their own cloud page,
having been superseded by the CX Gen3 / CPX Gen2 refresh. **CPX32** is the live
4 vCPU / 8 GB plan (160 GB NVMe), available in Nuremberg, Falkenstein, Helsinki
and Singapore. Check the price in the console rather than trusting a number from
here — Hetzner raised cloud prices in June 2026 and the third-party trackers
disagree with each other by more than the plan costs.

**x86, not ARM.** The image is genuinely multi-arch — I verified both
`linux/amd64` and `linux/arm64` in the registry — and a CAX21 would work. But the
document-parsing stack sits on PyTorch, and arm64 wheels are still the fragile
path when something needs building. x86 is the boring choice and this is a place
to be boring.

**Disk is a non-issue.** The image is ~450 MB compressed, ~1.5 GB unpacked. Your
knowledge bases will grow into 160 GB slowly.

If you would rather not administer a box at all, Fly.io works — one machine with a
2–4 GB VM and a persistent volume — but the same caveat in `company/deploy/fly.toml`
applies here: this box is also where Ollama, a self-hosted Actions runner, and the
rest of `STACK.md` eventually land, so buying it once pays for itself.

## How the iPad gets in: Tailscale, not a public port

This is the part to not improvise, because of two upstream defaults that combine
badly:

1. **Authentication is off by default.** DeepTutor ships open.
2. **Code execution is on by default.** The sandbox runs untrusted shell for its
   office skills; without the runner sidecar it degrades to bwrap, or to a
   restricted subprocess.

An open `:3782` on a public IP is therefore a remote shell for whoever port-scans
it, which on a fresh VPS is a matter of hours. So: **never publish the port.**

Tailscale solves this completely and has a first-class iPad app. The compose file
here binds to `127.0.0.1` only; `tailscale serve` then puts HTTPS on a stable
`*.ts.net` name that exists only inside your tailnet. No public port, no domain to
buy, no certificate to renew, no reverse proxy to maintain. On the iPad: install
Tailscale, sign in, open the URL in Safari, **Share → Add to Home Screen**. It
gets an icon and opens chromeless, which is as close to a native app as this
needs to be.

Then enable auth anyway, in `data/user/settings/auth.json` — defense in depth, and
the first account you register becomes admin.

## Models — where your existing constraint bites

`company/MODELS.md` says it plainly: there is no Anthropic API wallet, and
automated work runs on a DeepSeek balance. DeepTutor takes any OpenAI-compatible
endpoint, so pointing it at DeepSeek is a settings change, not a fork. **V4 Flash**
for bulk explanation and quiz generation, **V4 Pro** when you want it to actually
think through a hard derivation.

One gap to decide before you load a knowledge base: **DeepSeek does not serve
embeddings**, and the RAG features (LlamaIndex, LightRAG, GraphRAG, PageIndex) need
them. Options, cheapest first: run an embedding model locally on the same box via
Ollama — which `INFRA.md` Tier 1 wants there anyway for the free filter tier — or
add a small Gemini/OpenAI key used only for embeddings. Chat works fine without
either; you only need this when you start indexing your own documents.

## Files here

| File | What it is |
|---|---|
| `cloud-init.yaml` | Paste-once box provisioning — the recommended path |
| `docker-compose.yml` | The single-container deployment, pinned, loopback-bound |
| `bootstrap.sh` | Same thing for a box that already exists |

## Standing it up

### Before you create the server

Two of these are easy to forget and both strand you afterwards.

1. **Tailscale auth key** — from
   [the admin console](https://login.tailscale.com/admin/settings/keys). Make it
   **ephemeral, pre-approved, single-use**. It goes into cloud-init metadata,
   which anything on the box can read; single-use means it is spent the moment
   this machine joins and is worthless to a later reader.
2. **Tailscale → DNS: enable MagicDNS and HTTPS Certificates.** `tailscale serve`
   cannot issue a certificate without them, and the serve step will quietly skip.
3. **An SSH key uploaded to Hetzner.** The config disables password login, so a
   box created without a key attached locks you out permanently.

### Create the server

Hetzner console → **Create Server**:

| Field | Value |
|---|---|
| Image | Ubuntu 24.04 |
| Type | **CPX32** — shared vCPU, 4 vCPU / 8 GB / 160 GB |
| Location | Nuremberg, Falkenstein or Helsinki |
| SSH key | yours, attached |
| Cloud config | paste `cloud-init.yaml`, with the auth key filled in |

Nothing else needs changing. Do **not** add a firewall rule for 3782 — the port
is deliberately not reachable from outside the box.

### After it boots

Two or three minutes. Then, over SSH or the console:

```bash
tailscale serve status     # prints the https://deeptutor.<tailnet>.ts.net URL
docker compose -f /opt/deeptutor/docker-compose.yml ps   # expect "healthy"
```

Open that URL on the iPad — Tailscale app installed and signed in — then
**Share → Add to Home Screen**. Add your provider key under **Settings → Models**,
register your account, then enable auth in `data/user/settings/auth.json` and:

```bash
cd /opt/deeptutor && docker compose restart
```

### If the box already exists

`bootstrap.sh` does the same work against a running machine:

```bash
sudo bash study/deeptutor/bootstrap.sh
```

It installs Docker and Tailscale but authenticates neither and stores no secret;
you run `tailscale up` yourself afterwards.

> Note: the `curl | bash` one-liner in that script's header fetches from `main`
> and only works once this has merged. Until then, run it from a clone.

### Keeping the two compose copies in sync

`cloud-init.yaml` inlines `docker-compose.yml` rather than fetching it, so that
provisioning depends on no branch, no merge and no network. The cost is two
copies. If you change one, change the other:

```bash
python3 - <<'PY'
import yaml
a = yaml.safe_load(open('docker-compose.yml'))['services']['deeptutor']
w = yaml.safe_load(open('cloud-init.yaml'))['write_files']
b = yaml.safe_load(next(f for f in w if f['path'].endswith('docker-compose.yml'))['content'])['services']['deeptutor']
d = [k for k in ('image','ports','volumes','environment','mem_limit','healthcheck','restart','logging') if a.get(k) != b.get(k)]
print('drift in:', d or 'none')
PY
```

## Upgrade path: the hardened sandbox

The compose file here runs the published all-in-one image with
`DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS=0` — code execution off, which is the right
default for a box you are not watching. If you later want the office skills
(generating docx/xlsx/pptx/pdf from a study session), do not just flip that to `1`.
Clone the upstream repo and use *its* compose file, which adds a `sandbox-runner`
sidecar: unprivileged, `cap_drop: ALL`, read-only rootfs, no host socket, and
deliberately never given `data/system` where the credentials live. That is a real
isolation boundary and worth the build step.

## Cost

Roughly **€7/month** for the box, plus DeepSeek usage, which for one person
studying is small. Nothing else here costs anything.

---

*Upstream: <https://github.com/HKUDS/DeepTutor> · <https://deeptutor.info/> ·
verified against image tag `1.5.12`.*
