# The worker as a container — for Fly.io, Railway, Render, or any host that
# takes an image. The VPS path in bootstrap.sh does not need this.
#
#   docker build -f company/deploy/Dockerfile -t company-worker .
#   docker run --env-file worker.env company-worker

FROM python:3.11-slim

# Non-root, because the worker holds a GitHub token and needs nothing else.
RUN useradd --system --create-home --uid 10001 company

WORKDIR /app

# Dependencies first so a code change does not re-resolve them.
COPY company/temporal/requirements.txt company/temporal/requirements.txt
RUN pip install --no-cache-dir -r company/temporal/requirements.txt

# Only what the worker actually runs: the routing logic and the Temporal layer.
COPY company/ops/board.py company/ops/board.py
COPY company/ops/dispatch.py company/ops/dispatch.py
COPY company/temporal/ company/temporal/

USER company

ENV PYTHONUNBUFFERED=1

# No healthcheck: the worker's liveness is visible in Temporal itself, and the
# watchdog in .github/workflows/company-watchdog.yml alerts on missing
# heartbeats. A container that is up but not polling would pass a naive check
# anyway, which is exactly the silence failure INFRA.md warns about.
CMD ["python", "company/temporal/worker.py"]
