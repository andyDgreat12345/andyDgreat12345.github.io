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

**A Hetzner CX32 (4 vCPU / 8 GB / 80 GB), Ubuntu 24.04, running the published
Docker image, reachable from the iPad over Tailscale.**

Three decisions inside that, each with a reason:

**8 GB, not 4.** `company/deploy/RUNBOOK.md` specs a CX22 (2 vCPU / 4 GB) for the
Temporal worker. DeepTutor does not fit beside Temporal + Postgres + the worker in
4 GB — the Next.js server and the Python backend are two long-lived runtimes
before any document parsing starts, and MinerU/Docling pull real ML models into
memory when you feed them a PDF. Either give DeepTutor the 8 GB box and leave the
company on its own, or size the shared box at 8 GB from the start.

**x86, not ARM.** The image is genuinely multi-arch — I verified both
`linux/amd64` and `linux/arm64` in the registry — and a CAX21 would work. But the
document-parsing stack sits on PyTorch, and arm64 wheels are still the fragile
path when something needs building. At current Hetzner pricing the ARM box is not
even cheaper (roughly €7.99 for CAX21 against €6.80 for CX32 after the June 2026
increase — verify both, these moved recently). x86 is the boring choice and this
is a place to be boring.

**Disk is a non-issue.** The image is ~450 MB compressed, ~1.5 GB unpacked. 80 GB
is ample; your knowledge bases will grow into it slowly.

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
| `docker-compose.yml` | The single-container deployment, pinned, loopback-bound |
| `bootstrap.sh` | Fresh Ubuntu box → Docker, Tailscale, service running |

## Standing it up

On a fresh Ubuntu 24.04 box, as root:

```bash
curl -fsSL https://raw.githubusercontent.com/andyDgreat12345/andyDgreat12345.github.io/main/study/deeptutor/bootstrap.sh | bash
```

It installs Docker and Tailscale, drops the compose file at `/opt/deeptutor`,
pulls the image and starts it bound to loopback. It stores **no secrets** and
exposes nothing publicly. Then:

```bash
tailscale up                                  # authenticate the box to your tailnet
tailscale serve --bg 3782                     # HTTPS inside the tailnet only
tailscale serve status                        # prints the https://<host>.ts.net URL
```

Open that URL on the iPad, walk the setup, add your DeepSeek key under
**Settings → Models**, then turn on auth and restart:

```bash
cd /opt/deeptutor && docker compose restart
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
