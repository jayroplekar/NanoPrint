# OctoPrint Lean Build — RPi3, 2 Printers, Max Responsiveness

## Problem
OctoPrint 2.0.0rc4 on RPi3 (1GB RAM, 4x A53 @ 1.4GHz) becomes sluggish under dual-printer load.
Primary bottleneck: UI responsiveness (websocket push frequency, static asset serving, plugin overhead).

---

## Root Causes (Responsiveness)

1. **Websocket flood**: state monitor pushes at 500ms interval per printer — x2 printers = constant serialization + emit load
2. **Temperature history in RAM**: unbounded ring buffer per printer grows during long prints
3. **Bundled plugins always loaded**: tracking, announcements, errortracking, achievements, gcodeviewer all run even when unused
4. **Static asset serving through Python**: Tornado serves JS/CSS — uncompressed, blocking
5. **No response caching**: API endpoints re-compute on every request
6. **GCode viewer**: parses entire gcode file in memory for 3D preview — huge on large prints
7. **Serial read thread**: 0.5s poll loop per printer × 2 = 4 threads fighting on single-core burst

---

## Changes — Factored by Impact

### Factor 1: Reduce Websocket Push Rate (HIGH IMPACT, LOW RISK)

**Where**: `src/octoprint/printer/standard.py` line ~176 and ~2041
Default `interval=0.5` (500ms) state monitor push.

**Change**:
```python
# standard.py ~line 176
interval=2.0,   # was 0.5 — 4x fewer pushes, still feels live
```

**Also**: In `config.yaml` (runtime config on RPi):
```yaml
temperature:
  cutoff: 30          # keep only 30 min of temp history (was 60)
  interval: 4         # seconds between temp requests to printer (default: 2)
```

---

### Factor 2: Disable Heavy Bundled Plugins (HIGH IMPACT, ZERO RISK)

**Where**: OctoPrint Settings UI or `~/.octoprint/config.yaml`

Disable these plugins (they run background threads/timers):
- `achievements` — cosmetic, useless overhead
- `announcements` — polls external URL on schedule
- `tracking` — sends telemetry, uses network + disk
- `errortracking` — Sentry integration, adds hooks everywhere
- `gcodeviewer` — parses gcode in memory for 3D view (HUGE on large files)
- `softwareupdate` — polls GitHub API periodically
- `discovery` — mDNS/SSDP/UPnP broadcast, not needed if IP known

**Keep**: `serial_connector`, `classicwebcam`, `backup`, `logging`

In `config.yaml`:
```yaml
plugins:
  _disabled:
    - achievements
    - announcements
    - tracking
    - errortracking
    - gcodeviewer
    - softwareupdate
    - discovery
```

---

### Factor 3: Serve Static Assets via nginx (MEDIUM IMPACT, ONE-TIME SETUP)

Put nginx in front of Tornado. Nginx serves `/static/` directly, caches aggressively.
Tornado only handles API + WebSocket.

**nginx config** (`/etc/nginx/sites-available/octoprint`):
```nginx
server {
    listen 80;
    
    # Serve static assets directly — bypass Python entirely
    location /static/ {
        alias /home/pi/.octoprint/static/;
        expires 7d;
        add_header Cache-Control "public, immutable";
        gzip_static on;
    }
    
    # Proxy everything else to OctoPrint
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }
}
```

---

### Factor 4: OctoPrint Server Tuning (MEDIUM IMPACT)

In `~/.octoprint/config.yaml`:
```yaml
server:
  host: 127.0.0.1    # bind only localhost if nginx fronts it
  port: 5000
  
  # Reduce worker threads — RPi3 has 4 cores, don't over-subscribe
  threads: 4

feature:
  gCodeVisualizer: false   # belt-and-suspenders off for gcodeviewer

serial:
  timeout:
    connection: 10
    communication: 30
    temperature: 5         # was 0-1s, reduce temp request spam
    temperatureTargetSet: 2
    sdStatus: 10           # SD card status poll interval
  maxCommunicationTimeouts:
    idle: 2
    printing: 5
```

---

### Factor 5: System-Level (HIGH IMPACT, ONE-TIME)

**zram** (swap in RAM — avoids SD card thrash):
```bash
sudo apt install zram-tools
echo "ALGO=lz4" | sudo tee -a /etc/default/zramswap
echo "PERCENT=50" | sudo tee -a /etc/default/zramswap
sudo systemctl restart zramswap
```

**GPU memory split** (give RAM back to CPU — no display needed):
```bash
# /boot/config.txt
gpu_mem=16
```

**Disable unused services**:
```bash
sudo systemctl disable bluetooth cups
sudo systemctl disable triggerhappy hciuart
# NOTE: do NOT disable avahi-daemon — it powers raspberrypi.local hostname resolution
# The OctoPrint 'discovery' plugin is separate from avahi and safe to disable
```

**OctoPrint service nice priority**:
```bash
# /etc/systemd/system/octoprint.service  [Service] section
Nice=-5
IOSchedulingClass=realtime
IOSchedulingPriority=4
```

**Log rotation** (SD card I/O kills responsiveness during big log writes):
```bash
# ~/.octoprint/logging.yaml
loggers:
  octoprint.comm.protocol:
    level: WARNING    # was DEBUG — serial logs are enormous
  octoprint.printer:
    level: WARNING
```

---

### Factor 6: Webcam / Timelapse Tuning (HIGH IMPACT if cameras used, LOW RISK)

**Good news first**: the webcam *live view* itself costs the NanoPrint/OctoPrint Python process almost nothing. Checked `src/octoprint/plugins/classicwebcam/__init__.py` — the plugin only stores a `stream` URL (config value); the browser's `<img>`/MJPEG connection goes **directly** to whatever serves that URL (normally `mjpg_streamer` on its own port, optionally fronted by nginx). Tornado never proxies or touches the video bytes. The only Python-side work is `take_webcam_snapshot()` — one `requests.get()` per snapshot, guarded by a mutex — used for timelapse frames and UI thumbnails.

**Where the real CPU actually goes** (all outside/adjacent to NanoPrint, not fixable by tuning `standard.py`):

1. **`mjpg_streamer` capture/encode loop** — runs continuously once started, independent of how many browsers are watching. Resolution × fps is the dominant cost (software YUV→JPEG conversion per frame).
2. **Timed-timelapse snapshot polling** — cheap, one HTTP GET per interval, ignore this one.
3. **Timelapse video rendering** (`ffmpeg`, `libx264`, default `bitrate: 10000k`, `ffmpegThreads: 1`) — a single-threaded CPU burst at the end of each print. Two printers finishing near-simultaneously = two concurrent single-threaded x264 encodes competing for the RPi3's 4 cores.

**Changes**:

```yaml
# ~/.octoprint/config.yaml (or ~/.octoprint2/config.yaml for instance 2)
webcam:
  timelapseEnabled: false   # if you don't actually watch timelapse videos — kills periodic snapshot GETs too
  bitrate: "4000k"          # was 10000k — noticeably lighter x264 encode, still fine for a shop-floor timelapse
  ffmpegThreads: 1          # keep at 1 per instance so 2 concurrent renders don't fight for the same cores
  timelapse:
    renderAfterPrint: success   # was "always" — skip encoding failed/aborted prints entirely
```

**mjpg_streamer** (not part of this repo — it's the separate process feeding the `stream` URL, typically launched by OctoPi's `webcamd` or a systemd unit): drop resolution/fps, e.g.:

```bash
# typical mjpg_streamer input args — halve both resolution and fps from OctoPi defaults
-r 640x480 -f 5
```

If your USB camera supports UVC MJPEG natively (`v4l2-ctl --list-formats-ext` shows `MJPG`), make sure `mjpg_streamer`'s `input_uvc.so` is *not* forcing YUYV→software-JPEG conversion — passing the camera's native MJPEG straight through skips that CPU-bound recompression step entirely.

**Serving**: keep the stream URL pointed at nginx (`/webcam1/`, `/webcam2/` locations proxying to each `mjpg_streamer` port), same principle as Factor 3 — bypasses Python, and nginx re-broadcasting an already-encoded JPEG stream to extra viewers (e.g. the dashboard's detail-view `<img>`) adds negligible cost on top of what's already running for the main UI.

**Given usage pattern (rarely both printers active, pick fastest for big jobs)**: the two-concurrent-encode collision in point 3 is an edge case, not the steady state — don't over-invest here. The `renderAfterPrint: success` + lower bitrate change is the one worth keeping regardless.

---

## How To Try — Step by Step

### Step 1: Baseline (measure before touching anything)

SSH into RPi:
```bash
# Watch CPU/RAM during normal print
htop

# Check OctoPrint memory specifically
ps aux | grep octoprint

# Measure websocket message rate (in browser DevTools → Network → WS tab)
# Count messages per second — baseline should be ~2/sec per printer
```

### Step 2: Plugin disable (safest, biggest win)

1. Open OctoPrint UI → Settings → Plugin Manager
2. Disable each plugin in Factor 2 list, one at a time
3. Restart OctoPrint after each batch
4. Measure: `ps aux | grep octoprint` — watch RSS (RAM) drop

### Step 3: Config changes (no code edit)

Edit `~/.octoprint/config.yaml` directly or via OctoPrint Settings UI:
```bash
nano ~/.octoprint/config.yaml
# Add entries from Factor 1 and Factor 4 above
sudo systemctl restart octoprint
```

### Step 4: System tuning

```bash
# zram
sudo apt install -y zram-tools
echo -e "ALGO=lz4\nPERCENT=50" | sudo tee -a /etc/default/zramswap
sudo systemctl restart zramswap

# GPU memory
sudo bash -c 'echo "gpu_mem=16" >> /boot/config.txt'
sudo reboot

# Disable unused services
sudo systemctl disable bluetooth avahi-daemon
```

### Step 5: nginx static serving (most effort, good gain)

```bash
sudo apt install -y nginx
sudo nano /etc/nginx/sites-available/octoprint
# Paste config from Factor 3

sudo ln -s /etc/nginx/sites-available/octoprint /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx
```

Bind OctoPrint to localhost only so it's not directly accessible:
```bash
# ~/.octoprint/config.yaml
server:
  host: 127.0.0.1
```

### Step 6: websocket interval (code change — test carefully)

```bash
cd /Data/srujan/WIP/nanoPrint/OctoPrint-2.0.0rc4
# Edit src/octoprint/printer/standard.py
# Line ~176: change interval=0.5 to interval=2.0
# Line ~2041: same change

# Rebuild/reinstall
pip install -e .
sudo systemctl restart octoprint
```

Test: move a slider in UI — should still feel snappy. Temperature graph updates every 2s instead of 0.5s. Acceptable tradeoff.

### Step 6.5: Webcam / timelapse tuning (if cameras attached)

```bash
nano ~/.octoprint/config.yaml   # and ~/.octoprint2/config.yaml
# Add entries from Factor 6 above
sudo systemctl restart octoprint   # and octoprint2
```

If using `mjpg_streamer`, edit its launch args/systemd unit to drop resolution/fps per Factor 6, restart that service too.

### Step 7: Validate

After all changes:
```bash
# RAM usage
free -h
ps aux --sort=-%mem | head -5

# CPU during print
top -b -n 5 | grep octoprint

# Responsiveness: open UI, click buttons, measure subjective lag
# Target: <200ms UI response, stable during G-code streaming
```

---

## Expected Gains

| Change | RAM saved | CPU reduction | Effort |
|--------|-----------|---------------|--------|
| Disable 7 plugins | ~80-150MB | 20-30% | 5 min |
| Websocket interval 0.5→2s | ~5MB | 15% | 10 min |
| System tuning (zram, gpu) | +200MB effective | 5% | 15 min |
| nginx static serve | negligible | 10-15% | 30 min |
| Serial timeout tuning | ~0 | 10% | 5 min |
| mjpg_streamer res/fps cut (per camera) | ~0 (separate process) | 15-30% of a core, per camera | 10 min |
| Timelapse bitrate/renderAfterPrint tuning | ~0 | removes ffmpeg CPU spikes at print-end | 5 min |

**Total realistic win**: RPi3 goes from ~850MB used / constantly paging → ~550MB, UI lag drops from ~500ms to <150ms.

---

## Two-Printer Specific Notes

Correction to an earlier version of this doc: OctoPrint 2.0 does **not** support multiple printers natively within one instance — checked `src/octoprint/printer/` directly, no `PrinterManager`/`printer_id`/multi-instance abstraction exists. "Two printers" here means **two separate OctoPrint processes** (two ports, two config dirs, two systemd units), each driving one USB-serial connection. Each printer instance runs:
- Own serial read thread (0.5s poll)
- Own state monitor (0.5s push)
- Own temperature ring buffer

With 2 printers, doubling all timers above is critical. Both `interval=2.0` changes must be in place — otherwise 4 threads hammering at 500ms each saturates RPi3 single-core burst.

Consider staggering printer connection times by 10s at startup to avoid serialization spikes.
