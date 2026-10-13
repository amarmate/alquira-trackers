# Alquira Trackers

Firmware work on Reachfar V24 GPS trackers that Alquira owns. The goal is to run
our own firmware on these units, built on the Logicrom SDK, in place of the stock
firmware.

Everything here targets our own hardware on the bench, connected by USB cable. Nothing
in this repo targets devices, networks or accounts that belong to anyone else.

## What the work involves

- Reading and backing up the flash of our own units, and restoring it when a trial
  goes wrong.
- Decompiling the stock firmware and the boot ROM to learn the pin map, the flash
  layout and the boot sequence.
- Talking to the RDA boot ROM over USB to read, erase and write flash.
- Building and flashing Logicrom images, then reading their console output.

## Layout

- `docs/` — grouped by status. `knowledge/` holds living reference docs (undated; the
  entry points are `logicrom-core.md` and `rom-flash-access.md`), `in-process/` open work and
  the working summary, `done/` finished work as the dated record. Dated files are named
  `YY-MM-DD-name.md`; move a file between folders when its status changes. See
  `docs/README.md`. Read `in-process/26-10-10-agents-summary.md` first.
- `firmware/backup/` — flash dumps from our units.
- `firmware/decompiled/`, `firmware/ghidra/` — stock firmware analysis.
- `firmware/logicrom/` — our firmware and its build scripts.
- `tools/` — Python tools for the RDA ROM (`rda_*.py`), the Logicrom console, and
  their tests (`test_*.py`).

## Constraints

- Mac only (Apple Silicon). No Windows tools.
- The trackers stay closed: cable, button and RST hole only. No pad probing or soldering.
- Other sessions edit this checkout. Stage exact files, never `git add -A`.
