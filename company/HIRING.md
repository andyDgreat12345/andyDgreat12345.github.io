# Hiring the rest of the company

One role is filled. This is the plan for the other five, and the rule that
decides how each gets built.

> **Buy the worker, build the company.** Today cost a working day, and almost
> none of it went on the agent — the agent was adopted in an afternoon from
> [OpenHands](https://github.com/OpenHands/OpenHands). It went on the wiring:
> which token applies a label, what happens when a lease dies, whether a
> vacancy is a failure. Nobody else's repository knows those answers for your
> company, and every hour spent writing another agent loop is an hour not spent
> on the part only you can get right.

## What exists already

[`OpenHands/extensions`](https://github.com/OpenHands/extensions) is a public
registry of plugins and skills for the same SDK the engineer already runs. The
relevant ones, by role:

| Role | Component | What it does |
|---|---|---|
| Reviewer | [`plugins/pr-review`](https://github.com/OpenHands/extensions/tree/main/plugins/pr-review) | Inline review comments, evidence enforcement, sub-agent delegation for large diffs, A/B model testing |
| Analyst | `skills/prd`, `skills/linear-triage` | Turning a vague request into a specification |
| SRE | `plugins/qa-changes`, `skills/incident-retrospective` | Exercising a change and writing up what broke |
| Comms | `plugins/release-notes`, `skills/technical-writing` | Changelog from merged PRs |
| Researcher | `skills/research-brief`, `skills/github-repo-monitor` | Structured notes from outside sources |
| — | [`plugins/issue-duplicate-checker`](https://github.com/OpenHands/extensions/tree/main/plugins/issue-duplicate-checker) | Would have caught #12/#13 filing the same ticket twice |

## The order, and why

**1. The duplicate checker.** Not a role — a janitor. It is the cheapest thing
on this list and the board already produced the bug it prevents: #12 and #13
were the same ticket, and the second one would have been claimed, worked and
paid for. Deterministic enough to trust, small enough to land in an hour.

**2. The analyst.** `status:needs-spec` has no worker, so today you write the
acceptance criteria yourself for every ticket. An analyst means you file one
line and the company turns it into a specification you approve.

It goes second because it is the **lowest-risk** hire: the worst an analyst can
do is write bad acceptance criteria, and you see those on the ticket *before*
any code is written or any money is spent. A bad specification is visible; bad
review is not.

**3. The reviewer.** The biggest gap — right now the owner is reviewer *and*
merger, which is the one place the charter is weaker than designed. And the
most dangerous hire, for exactly the reason the reviewer matters: **a gate you
trust that does not work is worse than no gate.**

Two problems have to be solved before it is worth having, both below.

**4. Comms, then the SRE, then the researcher.** All optional. Hire one when a
stage starts stalling for lack of it, and not before — `ORG.md` has said so
since the first draft and it is still right.

## The two problems with the reviewer

### Diversity

`MODELS.md` requires the reviewer to run on a different model family than the
builder, because two instances of one model share training and therefore share
blind spots. The engineer is DeepSeek V4 Flash. So a DeepSeek reviewer is not a
reviewer, it is an echo.

Three options, honestly ranked:

| Option | Cost | Honest assessment |
|---|---|---|
| A second vendor key (Codex, Gemini, Mistral) | One more account | The only one that satisfies the rule as written |
| DeepSeek V4 **Pro** reviewing V4 **Flash** | Nothing | Different model, same vendor and same training lineage. A partial mitigation, not the rule. Do not pretend otherwise |
| A local model via Ollama | Your hardware | Genuinely independent, and probably too weak to catch what matters |

### Fork PRs on a public repository

The pr-review plugin triggers on `pull_request_target`, which runs with **your
secrets** against **a contributor's code**. This repository is public, so anyone
can open a PR. A malicious one could be written specifically to exfiltrate
`LLM_API_KEY` while the agent reads it.

The plugin mitigates this by passing keys as SDK secrets rather than
environment variables. That is a mitigation, not an exemption — restrict the
trigger to non-fork PRs until there is a reason not to.

## The reviewer worth having first: no model at all

Before any of that, there is a gate that costs nothing and cannot hallucinate.
Most of what a reviewer catches on agent output is not subtle:

- Acceptance criteria boxes ticked but the diff does not touch the file they
  describe
- `.github/workflows/` modified, which the work order forbids
- No evidence section — what was run, what came back
- Tests added but no assertion in them
- The PR closing a ticket that is not the one it was claimed for

Every item is checkable by a Python function against the diff. **No model, no
echo chamber, no API key, no fork risk, and no possibility of a confident
wrong answer.** It should exist whether or not a model reviewer ever does, and
it is the cheapest bug-prevention on this page.

## What not to adopt

The frameworks that look most relevant are the ones to leave alone. MetaGPT and
ChatDev simulate a software company with roles; CrewAI and LangGraph orchestrate
agents. All of them would replace `board.py`, `assign.py` and the gates — code
that is tested, that has already caught real bugs, and that encodes decisions
nobody else's framework knows about your company.

Adopt workers. Keep the company.
