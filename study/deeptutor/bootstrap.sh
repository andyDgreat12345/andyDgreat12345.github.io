#!/usr/bin/env bash
# Provision a fresh Ubuntu box to run DeepTutor. Idempotent — safe to re-run.
#
# On a brand-new Hetzner/DigitalOcean box, as root:
#
#   curl -fsSL https://raw.githubusercontent.com/andyDgreat12345/andyDgreat12345.github.io/main/study/deeptutor/bootstrap.sh | bash
#
# It stores NO secrets and publishes NOTHING to the internet. DeepTutor comes up
# bound to 127.0.0.1; you then run `tailscale up` and `tailscale serve` yourself
# to reach it from the iPad. See README.md.

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/deeptutor}"
RAW_BASE="${RAW_BASE:-https://raw.githubusercontent.com/andyDgreat12345/andyDgreat12345.github.io/main/study/deeptutor}"

log() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] || { echo "run as root (sudo bash $0)"; exit 1; }

log "Base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg

log "Docker engine + compose plugin"
if ! command -v docker &>/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker

log "Tailscale"
# The access path. Installed but NOT authenticated — `tailscale up` is
# interactive and yours to run, because it mints a credential for this box.
if ! command -v tailscale &>/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi

log "Unattended security updates"
apt-get install -y -qq unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades

log "Compose file at $APP_DIR"
mkdir -p "$APP_DIR"
if [[ -f docker-compose.yml && -z "${FORCE_FETCH:-}" ]]; then
  # Running from a clone of the repo rather than piped from curl.
  cp docker-compose.yml "$APP_DIR/docker-compose.yml"
else
  curl -fsSL "$RAW_BASE/docker-compose.yml" -o "$APP_DIR/docker-compose.yml"
fi

log "Pulling image (~450 MB) and starting"
cd "$APP_DIR"
docker compose pull --quiet
docker compose up -d

log "Waiting for health"
for _ in $(seq 1 30); do
  status=$(docker inspect -f '{{.State.Health.Status}}' deeptutor 2>/dev/null || echo starting)
  [[ $status == healthy ]] && break
  sleep 10
done

cat <<'EOF'

==> Done. DeepTutor is running on 127.0.0.1:3782 and is NOT reachable from
    the internet. That is intentional.

    Next, to reach it from the iPad:

      tailscale up                  # authenticate this box to your tailnet
      tailscale serve --bg 3782     # HTTPS, inside the tailnet only
      tailscale serve status        # prints the https://<host>.ts.net URL

    On the iPad: install Tailscale, sign in, open that URL in Safari,
    then Share -> Add to Home Screen.

    Then, in the web UI: Settings -> Models, add your provider key. Once you
    have registered your account, turn on authentication in
    data/user/settings/auth.json and `docker compose restart`.

    Useful:
      docker compose logs -f        # what it is doing
      docker compose restart        # after changing settings
      docker compose pull && docker compose up -d   # after bumping the tag

EOF
