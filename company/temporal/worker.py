#!/usr/bin/env python3
"""The worker: the always-on process that actually executes heartbeats.

This is the one thing that must stay running. It holds no state — Temporal does —
so it is safe to restart at any moment, and a run in flight resumes on whichever
worker picks it up next. That property is the whole reason for this layer.

    python company/temporal/worker.py

Connects to a local dev server by default. For Temporal Cloud set
TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE and either the API key or the mTLS pair —
see this directory's README.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from temporalio.client import Client, TLSConfig
from temporalio.worker import Worker

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from activities import (  # noqa: E402
    apply_labels,
    check_kill_switch,
    place_claim,
    post_report,
    read_board,
    read_spend,
    release_claim,
    today,
)
from workflows import HeartbeatWorkflow  # noqa: E402

TASK_QUEUE = os.environ.get("COMPANY_TASK_QUEUE", "company-hq")


async def connect() -> Client:
    address = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    namespace = os.environ.get("TEMPORAL_NAMESPACE", "default")

    # Temporal Cloud accepts either an API key or a client certificate pair.
    # Local dev servers want neither, which is why both are optional.
    api_key = os.environ.get("TEMPORAL_API_KEY")
    cert_path = os.environ.get("TEMPORAL_TLS_CERT")
    key_path = os.environ.get("TEMPORAL_TLS_KEY")

    tls: TLSConfig | bool = False
    if cert_path and key_path:
        with open(cert_path, "rb") as c, open(key_path, "rb") as k:
            tls = TLSConfig(client_cert=c.read(), client_private_key=k.read())
    elif api_key:
        tls = True

    logging.info("connecting to %s (namespace %s)", address, namespace)
    return await Client.connect(
        address,
        namespace=namespace,
        tls=tls,
        api_key=api_key,
    )


async def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not os.environ.get("GITHUB_TOKEN"):
        logging.warning("GITHUB_TOKEN is unset — activities will fail on first run")

    client = await connect()
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[HeartbeatWorkflow],
        activities=[
            check_kill_switch, read_board, read_spend, apply_labels,
            place_claim, release_claim, post_report, today,
        ],
        # One heartbeat every 15 minutes is not a throughput problem. Keeping the
        # ceiling low means a bug cannot fan out into hundreds of concurrent
        # GitHub calls before anyone notices.
        max_concurrent_activities=8,
        max_concurrent_workflow_tasks=8,
    )
    logging.info("worker up on task queue %r — ctrl-c to stop", TASK_QUEUE)
    await worker.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("worker stopped")
