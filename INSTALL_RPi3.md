# NanoPrint — RPi3 Install Guide
Lean OctoPrint fork. N-printer capable on one host (default 2). Optimized for responsiveness on RPi3.

---

## Quick Install (recommended)

After Step 1 (flash the SD card, boot, SSH in), everything in Steps 2–9 below
is automated by `install.sh`:

```bash
git clone <repo-url> ~/nanoprint-src && cd ~/nanoprint-src
./install.sh

# Or for more than 2 printers on this host:
PRINTER_COUNT=4 ./install.sh
```

Sets up all printer instances (lean config, CORS for the dashboard), nginx,
serial group membership, and the dashboard at `http://<host>.local/dashboard/`
in one run. Safe to re-run — never overwrites an existing `config.yaml`, and
raising `PRINTER_COUNT` on a re-run only adds the new instances. Instance ports
are `5000, 5001, 5002, ...`; the dashboard's "+ Add Printer" button matches
that scheme automatically for instances 3+. Skip to Step 10+ below only if you
need to customize something the script doesn't cover (custom USB port
mapping, webcam stream URLs — see Step 12).

**RPi3 hardware note:** the lean tuning in `LEAN_OCTOPRINT_RPi3.md` was only
validated with 2 concurrent instances on an RPi3's 1GB/4-core-burst profile.
`PRINTER_COUNT` above 2 on the same board is untested — watch `htop` during a
real print before trusting it unattended. More capable boards (RPi4/5) have
more headroom for a real "mini farm" on one host.

The manual steps below are the reference this script automates — read them if
`install.sh` fails partway and you need to finish by hand.

---

## Prerequisites

- Raspberry Pi 3B or 3B+
- Raspberry Pi OS Lite (64-bit recommended) — Bookworm or Bullseye
- microSD 16GB+ (Class 10 / A1 rating minimum)
- Python 3.10+ (included in Bookworm)
- SSH access or keyboard/monitor

---

## Step 1 — First Boot Setup

Flash Raspberry Pi OS Lite via Raspberry Pi Imager.
In Imager settings: set hostname (`nanoprint`), enable SSH, set username/password.

Boot and SSH in:
```bash
ssh pi@nanoprint.local
```

Update system:
```bash
sudo apt update && sudo apt upgrade -y
```

---

## Step 2 — System Optimization (before install)

### GPU memory (no display needed):
```bash
echo "gpu_mem=16" | sudo tee -a /boot/firmware/config.txt
# Bullseye: /boot/config.txt instead
```

### zram (swap in RAM, avoids SD card thrash):
```bash
sudo apt install -y zram-tools
echo -e "ALGO=lz4\nPERCENT=50" | sudo tee -a /etc/default/zramswap
sudo systemctl restart zramswap
```

### Disable unused services:
```bash
sudo systemctl disable bluetooth cups triggerhappy hciuart
sudo systemctl stop bluetooth cups triggerhappy 2>/dev/null || true
# DO NOT disable avahi-daemon — needed for nanoprint.local hostname
```

---

## Step 3 — Install Dependencies

```bash
sudo apt install -y \
    python3-pip python3-venv python3-dev \
    libyaml-dev libffi-dev libssl-dev \
    build-essential git \
    nginx \
    haproxy
```

---

## Step 4 — Get NanoPrint Source

Copy the source to RPi (from your dev machine):
```bash
# On your dev machine:
scp -r /path/to/NanoPrint-source pi@nanoprint.local:/home/pi/nanoprint-src
```

Or use git if you have a repo:
```bash
git clone <your-repo-url> /home/pi/nanoprint-src
```

---

## Step 5 — Python Virtual Environment

```bash
python3 -m venv /home/pi/nanoprint-venv
source /home/pi/nanoprint-venv/bin/activate

# Install NanoPrint and dependencies
cd /home/pi/nanoprint-src
pip install --upgrade pip wheel
pip install -e .

# Verify install
octoprint --version
```

---

## Step 6 — Configure NanoPrint

First run creates config structure:
```bash
~/.nanoprint/   # data directory (NanoPrint, not OctoPrint)
```

Create lean config at `~/.nanoprint/config.yaml`:
```bash
mkdir -p ~/.nanoprint
cat > ~/.nanoprint/config.yaml << 'EOF'
server:
  host: 127.0.0.1
  port: 5000

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
```

---

## Step 7 — Logging Config (reduce SD I/O)

```bash
cat > ~/.nanoprint/logging.yaml << 'EOF'
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
```

---

## Step 8 — Systemd Service

```bash
sudo tee /etc/systemd/system/nanoprint.service << 'EOF'
[Unit]
Description=NanoPrint - Lean 3D Printer Web Interface
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
ExecStart=/home/pi/nanoprint-venv/bin/octoprint serve
WorkingDirectory=/home/pi
Restart=on-failure
RestartSec=5
Nice=-5
IOSchedulingClass=best-effort
IOSchedulingPriority=4
Environment=HOME=/home/pi

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable nanoprint
sudo systemctl start nanoprint

# Watch startup logs:
sudo journalctl -u nanoprint -f
```

---

## Step 9 — nginx Reverse Proxy

nginx handles static files and WebSocket — Python never serves CSS/JS:

```bash
sudo tee /etc/nginx/sites-available/nanoprint << 'EOF'
server {
    listen 80;
    server_name _;

    # Static assets served directly by nginx — bypass Python
    location /static/ {
        alias /home/pi/nanoprint-src/src/octoprint/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
        gzip on;
        gzip_types text/css application/javascript image/svg+xml;
    }

    # Everything else → NanoPrint
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
        client_max_body_size 2G;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/nanoprint /etc/nginx/sites-enabled/nanoprint
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx
```

---

## Step 10 — Access NanoPrint

Open browser:
```
http://nanoprint.local
```

First run: wizard will guide initial setup.

---

## Step 11 — Second Printer Setup (second instance, not a printer profile)

NanoPrint (like upstream OctoPrint) runs **one printer per process** — there's no
multi-printer manager inside a single instance. Two printers = two separate
NanoPrint processes, each with its own port, config dir, and systemd unit.

Identify which USB port is which first:
```bash
ls /dev/ttyUSB* /dev/ttyACM*
# Plug/unplug to identify
dmesg | grep tty | tail -5
```

Add pi user to dialout group (serial port access):
```bash
sudo usermod -aG dialout pi
# Logout and back in for effect
```

Create the second instance's config, pointed at its own data dir and port:
```bash
mkdir -p ~/.nanoprint2
cp ~/.nanoprint/config.yaml ~/.nanoprint2/config.yaml
sed -i 's/port: 5000/port: 5001/' ~/.nanoprint2/config.yaml
```

Second systemd unit:
```bash
sudo tee /etc/systemd/system/nanoprint2.service << 'EOF'
[Unit]
Description=NanoPrint - Printer 2
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
ExecStart=/home/pi/nanoprint-venv/bin/octoprint serve --basedir /home/pi/.nanoprint2
WorkingDirectory=/home/pi
Restart=on-failure
RestartSec=5
Nice=-5
IOSchedulingClass=best-effort
IOSchedulingPriority=4
Environment=HOME=/home/pi

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now nanoprint2
```

Each instance connects to whichever `/dev/ttyUSB*`/`/dev/ttyACM*` you assign it under
Settings → Serial Connection, in that instance's own web UI (`:5000` and `:5001`).

Consider staggering the two services' startup by ~10s (`ExecStartPre=/bin/sleep 10`
on the second unit) so both don't hit connect/handshake at once on boot.

---

## Step 12 — Webcams (optional, per printer)

The webcam *stream* is not proxied through NanoPrint's Python process — set
`stream`/`snapshot` URLs to point directly at each printer's `mjpg_streamer`
(optionally behind nginx). See `LEAN_OCTOPRINT_RPi3.md` Factor 6 for CPU tuning
(resolution/fps, timelapse bitrate) — relevant on RPi3 with two cameras running.

Minimal per-instance config (`~/.nanoprint/config.yaml` / `~/.nanoprint2/config.yaml`):
```yaml
plugins:
  classicwebcam:
    stream: "http://nanoprint.local:8080/?action=stream"     # instance 1 camera
    # stream: "http://nanoprint.local:8081/?action=stream"   # instance 2 camera
    snapshot: "http://127.0.0.1:8080/?action=snapshot"
webcam:
  timelapseEnabled: false
  bitrate: "4000k"
  timelapse:
    renderAfterPrint: success
```

Also enable cross-origin API access so the dashboard in Step 13 can reach both
instances from a single page:
```yaml
api:
  allowCrossOrigin: true
```

---

## Step 13 — Two-Printer Progress Dashboard

`dashboard/index.html` (in this repo) is a single static HTML file — no server,
no Docker, no Mongo — that polls both instances' REST APIs directly from the
browser and shows progress/temps/webcam side by side. Chosen over OctoFarm
specifically because this Pi has no other always-on host to run OctoFarm's
Node+Mongo footprint on without bogging down the two print instances it's meant
to be lean for.

1. Confirm Step 12's `api.allowCrossOrigin: true` is set on both instances, restart both.
2. Open `dashboard/index.html` via a local static server (file:// is blocked by
   some browser extensions/CSPs):
   ```bash
   cd dashboard && python3 -m http.server 8931
   ```
   Then browse to `http://nanoprint.local:8931/index.html`.
3. Per card → "Connection settings" → set host/port/API key for each instance → Save.
4. Click a printer's name to rename it, or to open its detail view (progress,
   temps, live webcam). "Upload & Print" sends a file straight to that printer.

---

## Troubleshooting

### NanoPrint won't start:
```bash
sudo journalctl -u nanoprint -n 50
```

### Port conflict:
```bash
sudo lsof -i :5000
```

### Check memory usage:
```bash
free -h
ps aux --sort=-%mem | head -5
```

### Serial port permission denied:
```bash
sudo usermod -aG dialout pi && sudo reboot
```

### nginx 502 Bad Gateway:
```bash
# NanoPrint not running or still starting
sudo systemctl status nanoprint
```

---

## Performance Validation

After full setup, verify:
```bash
# RAM should be under 600MB used
free -h

# CPU during idle should be < 10%
top -b -n 3 | grep -E "Cpu|octoprint"

# Confirm plugins disabled
grep -A 20 "_disabled:" ~/.nanoprint/config.yaml
```

Expected: UI response < 150ms, stable during G-code streaming on both printers.
