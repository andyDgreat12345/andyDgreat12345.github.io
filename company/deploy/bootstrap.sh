#!/usr/bin/env bash
# Provision a fresh Ubuntu box to run the company worker. Idempotent — safe to
# re-run after changing anything.
#
# On a brand-new Hetzner/DigitalOcean/Oracle box, as root:
#
#   curl -fsSL https://raw.githubusercontent.com/andyDgreat12345/andyDgreat12345.github.io/main/company/deploy/bootstrap.sh | bash
#
# or, if you have already cloned the repo:  sudo bash company/deploy/bootstrap.sh
#
# It does NOT ask for or store any secret. After it finishes you write
# /etc/company/worker.env yourself and start the service — see RUNBOOK.md.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/andyDgreat12345/andyDgreat12345.github.io.git}"
BRANCH="${BRANCH:-main}"
APP_DIR=/opt/company
SERVICE_USER=company

log() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] || { echo "run as root (sudo bash $0)"; exit 1; }

log "Packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git ca-certificates curl

log "Service user (no login shell, owns nothing else on the box)"
id -u "$SERVICE_USER" &>/dev/null || useradd --system --create-home \
  --home-dir /home/"$SERVICE_USER" --shell /usr/sbin/nologin "$SERVICE_USER"

log "Code at $APP_DIR"
if [[ -d $APP_DIR/.git ]]; then
  git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
  git -C "$APP_DIR" checkout --quiet "$BRANCH"
  git -C "$APP_DIR" reset --hard --quiet "origin/$BRANCH"
else
  git clone --quiet --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"

log "Virtualenv"
if [[ ! -x $APP_DIR/.venv/bin/python ]]; then
  python3 -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/company/temporal/requirements.txt"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR/.venv"

log "Secrets directory (empty — you fill it in)"
install -d -m 700 -o root -g root /etc/company
if [[ ! -f /etc/company/worker.env ]]; then
  cat > /etc/company/worker.env <<'ENV'
# Fill these in, then: systemctl restart company-worker
# This file is root-only and must never be committed.

COMPANY_REPO=andyDgreat12345/andyDgreat12345.github.io
GITHUB_TOKEN=

# Temporal Cloud. For a self-hosted server on this same box use
# TEMPORAL_ADDRESS=localhost:7233 and leave the key and certs blank.
TEMPORAL_ADDRESS=
TEMPORAL_NAMESPACE=
TEMPORAL_API_KEY=

# Start paused. Flip to 0 once you have watched a heartbeat and trust it.
COMPANY_PAUSED=1
ENV
  chmod 600 /etc/company/worker.env
  echo "created /etc/company/worker.env — fill it in before starting"
fi

log "systemd unit"
cp "$APP_DIR/company/temporal/company-worker.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable company-worker >/dev/null

log "Unattended security updates"
apt-get install -y -qq unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades

cat <<'DONE'

Provisioned. The service is enabled but NOT started, because it has no
credentials yet.

Next:
  1. sudo nano /etc/company/worker.env     # GITHUB_TOKEN + Temporal settings
  2. sudo systemctl start company-worker
  3. sudo journalctl -u company-worker -f  # expect "worker up on task queue"
  4. cd /opt/company && sudo -u company .venv/bin/python \
       company/temporal/schedule.py create

Note COMPANY_PAUSED=1 is set by default: heartbeats will run and report but
start no work. Set it to 0 once you have watched one and believe it.

To update later:  sudo bash /opt/company/company/deploy/bootstrap.sh \
                  && sudo systemctl restart company-worker
DONE
