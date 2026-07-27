# nanoPrint — Shared Install/Network Spec

This is the single canonical list of values that `install.sh`, `dashboard/index.html`,
and `INSTALL.html`/`INSTALL_RPi3.md` all assume **independently** — there's no
build step or shared config file wiring them together, so if one of these
changes, grep the other three files for it and update by hand. This doc exists
so a human (or a future me) knows what to check.

| Parameter | Value | Defined in | Consumed by |
|---|---|---|---|
| Default hostname | `raspberrypi.local` | `dashboard/index.html` → `defaultCfgFor()` | User's browser, when a fresh dashboard has no saved printer config |
| Base port | `5000` | `install.sh` → `BASE_PORT`; `dashboard/index.html` → `BASE_PORT` | Both — must stay identical or a fresh install's dashboard defaults point at the wrong port |
| Port formula | `BASE_PORT + n - 1` for printer *n* (1-indexed) | `install.sh` → `port_for()`; `dashboard/index.html` → `defaultCfgFor()` | Both |
| Instance naming | `nanoprint` for #1, `nanoprintN` for #2+ | `install.sh` → `svc_name()` (systemd unit name) | systemd, `sudo systemctl status/restart <name>` |
| Data dir naming | `~/.nanoprint` for #1, `~/.nanoprintN` for #2+ | `install.sh` → `data_dir()` | `octoprint serve --basedir <dir>`, each instance's `config.yaml`/`logging.yaml` |
| Startup stagger | `(n - 1) * 10` seconds | `install.sh` → `write_service()` delay arg | systemd `ExecStartPre=/bin/sleep <delay>`, per `LEAN_OCTOPRINT_RPi3.md` → Two-Printer Specific Notes |
| Default printer count | `2` | `install.sh` → `PRINTER_COUNT` default; `dashboard/index.html` → `loadSlots()` fallback `["printer1","printer2"]` | Both — a fresh Pi and a fresh browser agree on "2 printers" with no config exchanged |
| Slot ID format | `printerN` (1-indexed) | `dashboard/index.html` → `SLOTS`/`slotNumber()` | localStorage keys `nanoprint_slots`, `nanoprint_printerN` |
| CORS requirement | `api.allowCrossOrigin: true` | `install.sh` → `write_config()` | Required for `dashboard/index.html` to fetch each instance's REST API cross-origin |
| nginx front | Instance 1 only, on port 80; dashboard at `/dashboard/`; static assets at `/static/` | `install.sh` → nginx `server {}` block | Browser access to `http://<host>.local/` and `/dashboard/` |

**Why no single source of truth file:** this project deliberately has zero
build tooling (no templating, no codegen) — every artifact here is a plain
file you can open and read top to bottom. Wiring these three files together
via a shared config would add a build step for one table's worth of values.
If `PRINTER_COUNT` regularly needs to go beyond what one RPi3 can hold, or
the port/naming scheme needs to change, that's the point to reconsider this
tradeoff — until then, this doc is the check-before-you-change list.

**When changing anything in this table:** update it here first, then grep
`install.sh`, `dashboard/index.html`, `INSTALL.html`, and `INSTALL_RPi3.md`
for the old value before editing any of them.
