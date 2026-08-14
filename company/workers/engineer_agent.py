#!/usr/bin/env python3
"""Run one ticket as an OpenHands agent.

Adapted from the OpenHands SDK example `examples/03_github_workflows/
01_basic_action/agent_script.py` (MIT). It is vendored here rather than
downloaded at run time on purpose: the upstream workflow curls a script from a
third party's default branch and executes it in a job that holds write access to
this repository and an LLM API key. Pinning the dependency is the difference
between a dependency and an open door — see CHARTER.md on irreversible acts.

Changes from upstream:

  * The prompt is composed by company/ops/work_order.py from the ticket and its
    work order, so what the agent is told is testable rather than interpolated
    together in YAML.
  * Spend is reported. The agent knows what it actually cost, and a run that
    does not say so is a hole in the ledger — see roles/07-controller.md.
  * Stuck detection is explicit. It defaults on; it is stated here because it is
    load-bearing, not incidental: this agent runs unattended and a loop that
    nobody stops is the expensive failure.

    LLM_API_KEY=... LLM_MODEL=deepseek/deepseek-v4-pro \
        python company/workers/engineer_agent.py /tmp/prompt.txt
"""

from __future__ import annotations

import os
import sys

from openhands.sdk import LLM, Conversation, get_logger
from openhands.tools.preset.default import get_default_agent

logger = get_logger(__name__)


def summarise(text: str) -> None:
    """Put a line in the Actions run summary, if we are in Actions."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as fh:
            fh.write(text + "\n")
    print(text)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: engineer_agent.py <prompt-file>", file=sys.stderr)
        return 2

    with open(sys.argv[1]) as fh:
        prompt = fh.read().strip()
    if not prompt:
        print("refusing to run on an empty prompt", file=sys.stderr)
        return 2

    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        # Non-recoverable, and worth failing loudly: a missing key here means the
        # repository secret was never set, not that the model is unavailable.
        print("LLM_API_KEY is not set", file=sys.stderr)
        return 2

    model = os.environ.get("LLM_MODEL", "deepseek/deepseek-v4-pro")
    config = {"model": model, "api_key": api_key, "usage_id": "engineer",
              "drop_params": True}
    if os.environ.get("LLM_BASE_URL"):
        config["base_url"] = os.environ["LLM_BASE_URL"]

    logger.info("engineer starting on %s (%d char prompt)", model, len(prompt))

    conversation = Conversation(
        agent=get_default_agent(llm=LLM(**config), cli_mode=True),
        workspace=os.getcwd(),
        # Default True; stated because it is the only thing besides the job
        # timeout standing between an unattended agent and a loop.
        stuck_detection=True,
    )

    status = 0
    try:
        conversation.send_message(prompt)
        conversation.run()
    except Exception as exc:  # noqa: BLE001 — the cost report matters more
        # Report the spend even on a crash. Money is spent before the failure,
        # not instead of it, and a run that dies silently is how a bill surprises
        # someone. The handoff step judges success by whether a PR exists, so
        # failing here does not strand the ticket.
        logger.error("engineer failed: %s", exc)
        status = 1

    try:
        spend = conversation.conversation_stats.get_combined_metrics()
        summarise(
            f"**Engineer run** — model `{model}`, "
            f"cost ${spend.accumulated_cost:.4f}"
            f"{' (FAILED)' if status else ''}"
        )
    except Exception as exc:  # noqa: BLE001
        summarise(f"**Engineer run** — model `{model}`, cost UNMEASURED ({exc}). "
                  "That is a hole in the ledger, not zero spend.")

    return status


if __name__ == "__main__":
    raise SystemExit(main())
