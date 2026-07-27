# nanoPrint

Lean OctoPrint fork for running multiple 3D printers off one low-power host
(built and tuned against a Raspberry Pi 3), plus a lightweight dashboard for
picking a printer, sending a print, and checking progress across all of them
without juggling browser tabs.

nanoPrint is **not** a multi-printer manager under the hood. It's one OctoPrint process per printer (own port, own
config, own systemd service), tuned to stay responsive on constrained
hardware, plus a static dashboard page that talks to each instance's REST API
directly.

## Get started

→ **[INSTALL.html](INSTALL.html)** — one-command install (`./install.sh`),
what you get, and how to add more than two printers.

That's the entry point for almost everyone. Everything below is reference.

## Repo layout

| Path | What it is |
|---|---|
| [`install.sh`](install.sh) | The installer. Provisions system tuning, one systemd service per printer, nginx, and the dashboard. `PRINTER_COUNT=N` env var controls how many instances. |
| [`dashboard/index.html`](dashboard/index.html) | Single static HTML/JS page — no server, no build step. Polls each printer's REST API directly from the browser: per-printer progress, temps, live webcam, upload-and-print, rename, add/remove printers. |
| [`OctoPrint-2.0.0rc4/`](OctoPrint-2.0.0rc4/) | Vendored OctoPrint source this fork is built on. |
| [`INSTALL.html`](INSTALL.html) | Friendly install guide — the recommended path (see above). |
| [`INSTALL_RPi3.md`](INSTALL_RPi3.md) | Full manual step-by-step install (what `install.sh` automates), plus troubleshooting. Read this if the installer fails partway. |
| [`LEAN_OCTOPRINT_RPi3.md`](LEAN_OCTOPRINT_RPi3.md) | Why and how each responsiveness/resource tweak works — websocket interval, disabled plugins, webcam/timelapse tuning, nginx offload, serial timeouts. Read this to understand *why* the configs `install.sh` writes look the way they do. |
| [`SPEC.md`](SPEC.md) | Canonical table of values `install.sh` and `dashboard/index.html` each hardcode independently (base port, port formula, instance naming, default host, default printer count). No build step ties these together — check this doc, and grep the other files, before changing any of them. |

## Two printers or twenty?

Default is 2 (`./install.sh`). For more on one host:

```bash
PRINTER_COUNT=4 ./install.sh
```

then use the dashboard's **+ Add Printer** button for instances beyond the
first two — it defaults to the next sequential port automatically. The RPi3
lean tuning in `LEAN_OCTOPRINT_RPi3.md` was only validated at 2 concurrent
instances; going higher on the same board is untested — see the hardware note
in `INSTALL.html`.

## Security

Dashboard-stored API keys and inter-instance traffic are plaintext, over
plain HTTP — a deliberate LAN-only tradeoff, not an oversight. Don't expose
these ports to the internet without a VPN or tunnel in front.
