#!/usr/bin/env bash
# nanoPrint one-click installer — RPi, N printers on one host, lean config, dashboard.
# Run as the normal pi user (needs passwordless or interactive sudo), from a
# checkout of this repo on the target Pi:
#   git clone <repo-url> ~/nanoprint-src && cd ~/nanoprint-src && ./install.sh
#
# Number of printer instances defaults to 2; override with:
#   PRINTER_COUNT=4 ./install.sh
#
# Idempotent: safe to re-run. Existing config.yaml files are never overwritten.
# Note: RPi3-class hardware was only validated with 2 instances (see
# LEAN_OCTOPRINT_RPi3.md) — going higher on the same board is untested; watch
# `htop` during a real print if you push PRINTER_COUNT up.
set -euo pipefail

PRINTER_COUNT="${PRINTER_COUNT:-2}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$REPO_DIR/OctoPrint-2.0.0rc4"
DASHBOARD_DIR="$REPO_DIR/dashboard"
VENV_DIR="$HOME/nanoprint-venv"
BASE_PORT=5000
USER_NAME="$(whoami)"

log() { printf '\n\033[1;32m==> %s\033[0m\n' "$1"; }

if [[ ! -d "$SRC_DIR" ]]; then
  echo "Expected OctoPrint source at $SRC_DIR — run this script from the repo root." >&2
  exit 1
fi
if ! [[ "$PRINTER_COUNT" =~ ^[0-9]+$ ]] || (( PRINTER_COUNT < 1 )); then
  echo "PRINTER_COUNT must be a positive integer, got: $PRINTER_COUNT" >&2
  exit 1
fi

# Per-instance naming: instance 1 keeps the original names (nanoprint /
# ~/.nanoprint) for backward compatibility with existing installs; instance
# N>1 is nanoprintN / ~/.nanoprintN.
svc_name()  { local i="$1"; [[ "$i" == 1 ]] && echo "nanoprint" || echo "nanoprint${i}"; }
data_dir()  { local i="$1"; [[ "$i" == 1 ]] && echo "$HOME/.nanoprint" || echo "$HOME/.nanoprint${i}"; }
port_for()  { local i="$1"; echo "$((BASE_PORT + i - 1))"; }

log "1/9 System optimization"
CONFIG_TXT=/boot/firmware/config.txt
[[ -f "$CONFIG_TXT" ]] || CONFIG_TXT=/boot/config.txt
if ! grep -q '^gpu_mem=16' "$CONFIG_TXT" 2>/dev/null; then
  echo "gpu_mem=16" | sudo tee -a "$CONFIG_TXT" >/dev/null
fi

if ! dpkg -s zram-tools >/dev/null 2>&1; then
  sudo apt-get install -y zram-tools
  grep -q '^ALGO=' /etc/default/zramswap 2>/dev/null || \
    echo -e "ALGO=lz4\nPERCENT=50" | sudo tee -a /etc/default/zramswap >/dev/null
  sudo systemctl restart zramswap
fi

sudo systemctl disable --now bluetooth cups triggerhappy hciuart 2>/dev/null || true

log "2/9 Install dependencies"
sudo apt-get update -qq
sudo apt-get install -y \
  python3-pip python3-venv python3-dev \
  libyaml-dev libffi-dev libssl-dev \
  build-essential nginx

log "3/9 Python virtual environment"
if [[ ! -d "$VENV_DIR" ]]; then
  python3 -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade pip wheel
pip install --quiet -e "$SRC_DIR"
deactivate

log "4/9 Instance configs (lean tuning + webcam CORS) for $PRINTER_COUNT printer(s)"
write_config() {
  local dir="$1" port="$2"
  if [[ -f "$dir/config.yaml" ]]; then
    echo "  $dir/config.yaml already exists — leaving it alone"
    return
  fi
  mkdir -p "$dir"
  cat > "$dir/config.yaml" <<EOF
server:
  host: 127.0.0.1
  port: $port

api:
  allowCrossOrigin: true

temperature:
  cutoff: 30
  interval: 4

serial:
  timeout:
    temperature: 5
    sdStatus: 10
  maxCommunicationTimeouts:
    idle: 2
    printing: 5

feature:
  gCodeVisualizer: false

webcam:
  timelapseEnabled: false
  bitrate: "4000k"
  timelapse:
    renderAfterPrint: success

plugins:
  _disabled:
    - achievements
    - announcements
    - tracking
    - errortracking
    - gcodeviewer
    - softwareupdate
    - discovery
EOF
  cat > "$dir/logging.yaml" <<EOF
version: 1
loggers:
  octoprint.comm.protocol:
    level: WARNING
  octoprint.printer:
    level: WARNING
  octoprint.server:
    level: WARNING
root:
  level: WARNING
EOF
}

log "5/9 Serial port access"
sudo usermod -aG dialout "$USER_NAME"

log "6/9 Per-instance configs + systemd services"
write_service() {
  local name="$1" basedir="$2" delay="$3"
  sudo tee "/etc/systemd/system/${name}.service" >/dev/null <<EOF
[Unit]
Description=nanoPrint - ${name}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${USER_NAME}
ExecStartPre=/bin/sleep ${delay}
ExecStart=${VENV_DIR}/bin/octoprint serve --basedir ${basedir}
WorkingDirectory=${HOME}
Restart=on-failure
RestartSec=5
Nice=-5
IOSchedulingClass=best-effort
IOSchedulingPriority=4
Environment=HOME=${HOME}

[Install]
WantedBy=multi-user.target
EOF
}

ALL_SERVICES=()
for ((i = 1; i <= PRINTER_COUNT; i++)); do
  dir="$(data_dir "$i")"
  port="$(port_for "$i")"
  name="$(svc_name "$i")"
  delay=$(( (i - 1) * 10 ))  # stagger startup so N instances don't hit connect/handshake at once
  write_config "$dir" "$port"
  write_service "$name" "$dir" "$delay"
  ALL_SERVICES+=("$name")
done
sudo systemctl daemon-reload
sudo systemctl enable --now "${ALL_SERVICES[@]}"

log "7/9 nginx (static assets + dashboard, fronts instance 1)"
sudo tee /etc/nginx/sites-available/nanoprint >/dev/null <<EOF
server {
    listen 80;
    server_name _;

    location /static/ {
        alias ${SRC_DIR}/src/octoprint/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
        gzip on;
        gzip_types text/css application/javascript image/svg+xml;
    }

    location /dashboard/ {
        alias ${DASHBOARD_DIR}/;
        index index.html;
    }

    location / {
        proxy_pass http://127.0.0.1:${BASE_PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 86400;
        client_max_body_size 2G;
    }
}
EOF
sudo ln -sf /etc/nginx/sites-available/nanoprint /etc/nginx/sites-enabled/nanoprint
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

log "8/9 Wait for services"
sleep 3
sudo systemctl --no-pager status "${ALL_SERVICES[@]}" | grep -E "●|Active" || true

log "9/9 Done"
HOSTNAME_LOCAL="$(hostname).local"
echo
echo "nanoPrint is up — ${PRINTER_COUNT} printer instance(s)."
echo
for ((i = 1; i <= PRINTER_COUNT; i++)); do
  port="$(port_for "$i")"
  if [[ "$i" == 1 ]]; then
    echo "  Printer 1 UI   : http://${HOSTNAME_LOCAL}/          (also http://${HOSTNAME_LOCAL}:${port})"
  else
    echo "  Printer ${i} UI   : http://${HOSTNAME_LOCAL}:${port}"
  fi
done
cat <<EOF
  Dashboard      : http://${HOSTNAME_LOCAL}/dashboard/

First run of each printer UI will show the OctoPrint setup wizard — connect
each to its own USB serial port there. Open the dashboard, click "+ Add
Printer" for each instance beyond the first two — it defaults to
raspberrypi.local:$((BASE_PORT + 1)), :$((BASE_PORT + 2))... matching the ports above.

You were added to the 'dialout' group — log out and back in (or reboot) for
serial port access to take effect.
EOF
