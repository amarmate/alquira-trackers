# Handoff: blank-word test, part two (2026-10-09)

For a model picking this work up with no memory of the earlier sessions. Times are
UTC; the user is in Lisbon (UTC+1). Everything here was true at 13:50 UTC on
2026-10-09.

**Completion update, 14:20:47 UTC:** Steps A and B passed on spare 412. The ROM
answered after the user's RST with the boot word blank and the force bit clear.
The separate restoration then returned all 4 MiB exactly to step B's pre-start
image. The boot word is valid again; after the user's final RST, vendor `RDA Usb`
returned with normal `Reset_Cause=0x00200000`. Full power-loss recovery and Logicrom
compatibility remain untested. The original handoff below is retained with state
updates; full evidence is at the end of `docs/done/26-10-08-loader-audit.md`.

**Subsequent offline preparation:** [Logicrom trial preparation](../in-process/26-10-09-logicrom-trial.md)
now records the compiled probe, unit-bound core/app image, full `--finish` recovery,
trial installer and simulated interruption/recovery tests. No additional hardware
run was performed. The older description below of `--finish` as block-0-only is
historical; it now restores all changed unprotected sectors from the saved image.

## The goal, and where this task sits in it

The user wants their own firmware on the ReachFar V24 GPS tracker (RDA8955 chip),
built with the Logicrom SDK. Three things decide that: the pin map
(`docs/knowledge/pin-map.md`), a way to write flash from the Mac, and whether Logicrom's
closed core suits the board. This task is the second one.

Writing flash from the Mac now works. What is not yet known is whether a unit can
always be recovered from outside its case once the vendor firmware is gone. The
candidate answer is the chip's boot word: the ROM starts the firmware only if the
32-bit word at flash offset 0 is `0xd9ef0045`. With any other value the ROM stays in
its USB monitor at every start and does not time out
(`boot_monitor.c:131-139,229-240`). If that monitor is reachable over USB after a
hardware reset, an install can be done with the word withheld and is always
recoverable. Part one showed it after a soft reset. Part two is the hardware reset,
the RST hole.

## Rules the user has set

- Mac only (Apple Silicon). No Windows, no Coolwatcher. Tools are the repo's own
  Python and libusb.
- The tracker will not be opened again. Only the magnetic USB cable, the power
  button and the RST hole are available. No pads, no soldering, no UART adapter. A
  state that needs the pads to recover is a lost unit: say so when a step risks it.
- Ask for an explicit go before every erase or program on any unit. A go for one
  run does not cover the next.
- The user has five spare V24 units. Do not suggest buying more.
- The original unit `1403167417` is the untouched reference. The tool refuses to
  rewrite its block 0. Leave that refusal in place.
- Other sessions edit this same checkout. `git add` only exact files you were asked
  to change. Never `git add -A`, `git add .` or `git clean`. Commit only when asked.
  Nothing from this session is committed.
- `~/.claude/CLAUDE.md` has the working rules: least code, no new dependencies,
  look at the data first, fail loudly, verify before claiming.

## Hardware facts needed

| Thing | Value |
| --- | --- |
| Test unit | Spare `1403167412`. Backup `firmware/backup/v24_1403167412_2026-10-09_a_flash.bin`, SHA-256 `b0250296…a2c4`; the `_b` copy is identical |
| Flash | 4 MiB, JEDEC `c8 60 16`. Read at `0xa8000000` in the ROM and programmer, `0x88000000` through the vendor firmware |
| Layout | Code `0x000000`-`0x362000`; the vendor's settings store above it; calibration and factory data from `0x3fa000` (never written) |
| Erase blocks | 64 KiB below `0x3f0000`, 4 KiB above. Block 0 is the first 64 KiB |
| USB id | Always `1e04:0900`. Interface name `RDA Usb` is the vendor firmware; `Coolsand Usb` is the ROM monitor, and stays the name while the programmer runs |
| Reset register | `Reset_Cause` at `0x01a000a0`. Normal `0x00200000`. Bit 17 forces the ROM monitor on the next soft reset; RST clears it |
| Programmer | `firmware/live/usb-programmer-build/clean/artifacts/usb_8955_flsh_spi32m_ramrun_noclk_200ma.lod`, SHA-256 `c238911d…6c65`, loaded into RAM over USB |

The vendor firmware rewrites a few sectors of its own store whenever it runs
(`0x382000`, `0x3a3000`, `0x3a7000`, `0x3ac000`, `0x3d4000` so far). Compare code
and the protected tail against the backup, never the whole image.

## What has been done

All on 2026-10-09. Full records: `docs/done/26-10-09-programmer-start.md` (unit 417)
and `docs/done/26-10-08-loader-audit.md` from line 790 (unit 412).

| Run | Unit | Result |
| --- | --- | --- |
| Start, query | 417 | The programmer starts and answers; flash unchanged |
| Write test | 417 | Program and erase of a blank sector at `0x3e0000` work; flash ends as it started |
| Button test | 417 | Holding the power button during RST does not force the ROM monitor |
| Reset test 1 | 412 | A debug reset from inside the programmer session: the ROM port did not come back by itself |
| Reset test 2 | 412 | Same reset, then a port reset from the Mac (`usb.core.Device.reset`): ROM port back in 3.1 s |
| Blank-word part one | 412 | Passed, see below |

Part one, 13:37-13:41 UTC, journal `firmware/live/2026-10-09-blank-word-412/`:

1. Block 0 erased and programmed back without the boot word. Whole flash equal to
   the pre-start read except bytes 0-3.
2. Debug reset inside the session, Mac port reset, ROM handshake.
3. 40 s with no USB traffic, then a full read through the ROM: it answered. With a
   valid word the ROM leaves an idle monitor at 30 s.
4. A fresh programmer, the writer's `restore()` of block 0, END wrote the word.
5. Whole flash equal to the pre-start read (SHA-256 `6c53d5e4…91bf`).

The unit had no boot word for 122 s. After the user's RST it came back as
`RDA Usb` with `Reset_Cause=0x00200000`, and a two-pass dump has block 0, all the
code and the protected tail identical to the backup.

Before that run a bug was found by reading `run()`: the restore step called
`query()` a second time, `query()` saved its reads under fixed names, and the
journal never overwrites, so the run would have stopped with the word blank. Fixed
(the second query saves as `before-restore.bin`). Two tests now drive the real
`run()` against the simulated chip with a journal on disk. 114 tests pass.

## State right now

**Latest update, 14:20:47 UTC:** Step B restoration passed, journal
`firmware/live/2026-10-09-rst-blank-412-restore/`, exit 0. Both full post-restore
reads exactly match the step B pre-start image, SHA-256
`a09f61a9c67b4f1c4830173432d6682bc33dc9a556d2c24d23e9fafff6f51f75`.
Boot word `0xd9ef0045` is valid again. After the user's final RST, `RDA Usb`
returned and a read at 14:20:47 UTC confirmed `Reset_Cause=0x00200000`.
The unit is now in vendor firmware, with USB connected. No additional erase/program is
needed for this experiment, and none is authorized. The original 417 was untouched.

**Earlier update, 14:16:10 UTC:** Step B's RST test passed on 412. After the user's
RST report, `Coolsand Usb` answered the ROM handshake with `Reset_Cause=0x00200000`
(force bit cleared) and word 0 still `0xffffffff`. A full flash read exactly
matches the saved blank-word image. No port reset, debug reset, load or flash
write was sent during this check. Journal:
`firmware/live/2026-10-09-rst-blank-412-rom-check/`. The descriptor watches missed
the transition, so the exact RST time and enumeration delay are unknown.
The unit remains in the ROM monitor with its boot word blank. Obtain a separate
go for the prepared step B `--finish` restoration command. Full power-loss
recovery and Logicrom compatibility remain untested.

**Earlier update, 14:11:37 UTC:** Step B blank-and-stop passed on 412, journal
`firmware/live/2026-10-09-rst-blank-412/`, exit 0. The boot word is now blank;
only bytes 0-3 differ from this run's pre-start image. USB remains connected.
A descriptor-only watch (`2026-10-09-rst-blank-412-watch-01.jsonl`) was started
and the user instructed to press RST once. Post-RST observation is pending.
Restore only after its separate go, using `--finish` on the step B journal and
new journal `firmware/live/2026-10-09-rst-blank-412-restore`.
Target SHA-256: `a09f61a9c67b4f1c4830173432d6682bc33dc9a556d2c24d23e9fafff6f51f75`.
The updates below describe earlier states.

**Superseding update, 14:08:40 UTC:** Step A is complete on 412. Blank-and-stop
passed (`firmware/live/2026-10-09-finish-check-412-blank/`), followed by the separately
authorized `--finish` (`firmware/live/2026-10-09-finish-check-412-restore/`). Both
processes exited 0. The boot word is valid again (`0xd9ef0045`); both post-restore
full reads exactly match the blanking run's pre-start image, SHA-256
`47f9966f4e2e753e6cbf1432062f7fdcb7c43c846b4401a1fc780b517b674c47`.
After the user's RST, `RDA Usb` returned and a read at 14:08:40 UTC confirmed
`Reset_Cause=0x00200000`. USB remains connected; vendor firmware is running.
Next: a new per-run go for step B. Its commands and failure table are prepared at the end of the audit
document. `--finish` is now hardware-tested; RST with a blank word is still unproven.
The bullets below describe the earlier 13:50 state.

- 412 is on the cable in vendor firmware (`RDA Usb`), boot word valid, reset
  register normal. Nothing is running against it.
- 417 is not on the cable.
- Uncommitted work in the tree, from this and other sessions:
  `tools/rda_programmer_start.py`, `tools/test_rda_programmer_start.py`,
  `docs/done/26-10-08-loader-audit.md`, this file, and others.

## What is next

Both steps have now passed, including step B restoration and final read-only
confirmation of vendor firmware after RST. Nothing remains for this experiment. The remaining text in
this section is the original plan and preparation history, not pending flash work.

Step A has since passed on hardware; use the superseding state update above and
the run records at the end of the audit document. The notes below retain the
earlier preparation history.

Update at 13:59 UTC: `--blank-word-stop` is now implemented. Its end-to-end test
uses a real on-disk journal, verifies the stopped state, and runs `--finish` from
that same journal on the simulated chip. The test failed before the change.
Offline validation passed. Read-only preflight found `RDA Usb` and normal
`Reset_Cause=0x00200000`. No live erase/program has been performed in this follow-up.
Step A's two commands and failure table are prepared at the end of
`docs/done/26-10-08-loader-audit.md`; the next action is the per-run go for the
blank-and-stop command on spare 412. The implementation-needed text below is the
original recommendation, now superseded by this update.

My recommendation, not something the user has agreed to. Each step needs its own go.

**Step A: run `--finish` on real hardware.** It is the only way back once a unit
has a blank word, and it has only run against the simulated chip. It needs a mode
that does part one's step 1 and then stops, which does not exist:
`--blank-word-test` goes straight on to the restart and the restore. Build that
mode (call it what you like; it is `blank_boot_word()` followed by nothing), with
an end-to-end test through `run_on` in the test file. Then: blank and stop, run
`--finish` on the stopped run's journal, require the pre-start image. The risk is
the same kind as part one's. If `--finish` stops part-way the unit is still in a
ROM or programmer session with USB up, so the tool can be fixed and run again, as
long as nobody presses RST or unplugs.

**Step B: part two.** Blank and stop with the same mode. The user presses RST.
Watch USB. If `Coolsand Usb` is there, or the tracker is listed but silent, run
`--finish`: it starts with a port reset of its own. If nothing is listed, the user
replugs the cable, then `--finish`.

What part two decides:

- The ROM port returns after RST: a blank boot word is a safe state, reachable
  with the RST hole alone. An install can then be done with the word withheld, the
  new firmware started with the monitor's exit command (the ROM jumps to
  `0x88000010` whatever word 0 holds), and the word written only once the firmware
  is seen to run. Whether Logicrom's core reads the word itself is not checked.
- It does not return, even after a replug: the unit is in a monitor nothing can
  reach, with no firmware to boot. That unit is lost unless it is opened, and the
  user will not open it. Things to try from outside first are a replug, the power
  button, and letting the battery run flat before plugging in again. None of these
  is known to help.

Why this is in doubt: the ROM does not set up power itself. Every time its USB
has come up, the vendor firmware or the programmer had run earlier in the same
power session. Whether the USB regulator and PHY are on after a hardware reset is
not documented (audit doc, "What is still not proven", line 726). No test without
a blank word can show it, because with a valid word RST boots the firmware and the
monitor is never entered.

Open choices for the user: which unit takes part two (412 is the proven one; any
other spare needs two matching dumps with `rda_dump.py`, a line in
`firmware/backup/SHA256SUMS`, and an entry in `UNITS`), and whether to do step A
first.

## Commands

Run from the repo root. Journals must be new directories under `firmware/live/`.

```sh
# Tests (114)
cd tools && ../.venv/bin/python -m unittest; cd ..

# What is on USB: enumeration and descriptors only
.venv/bin/python -c "
import sys, os, json; sys.path.insert(0, 'tools')
import usb.backend.libusb1
from rda_dump import LIBUSB
from rda_usb_watch import snapshot
backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
print(json.dumps(snapshot(backend)), flush=True); os._exit(0)"

# Reset register, vendor firmware only, one read
.venv/bin/python tools/rda_boot_mode.py --read \
  --output firmware/live/2026-10-09-spare-412/$(date -u +%H%M%SZ)-LABEL-reset-cause.log

# Two-pass read-only dump through the vendor firmware, about 8 minutes
.venv/bin/python tools/rda_dump.py firmware/live/2026-10-09-spare-412/LABEL.flash.bin

# Part one again (offline check without --execute)
.venv/bin/python tools/rda_programmer_start.py --execute --blank-word-test \
  --unit 1403167412 --journal firmware/live/NEW-DIR > LOG 2>&1

# Restore block 0 from a stopped run, starting at the ROM port
.venv/bin/python tools/rda_programmer_start.py --execute --finish firmware/live/STOPPED-DIR \
  --unit 1403167412 --journal firmware/live/NEW-DIR > LOG 2>&1
```

## How `tools/rda_programmer_start.py` works

- `run()` is the whole sequence. From the vendor firmware it checks the unit
  against its backup, sets the force bit, sends a debug reset, and takes two full
  reads through the ROM. Then `load_and_start()`, `inspect_runtime()`, `query()`,
  and the selected test.
- `StartMonitor.send()` is a wire-level allowlist. After the programmer starts, a
  RAM write passes only if it is the next packet of `monitor.allowed`, which each
  step fills in advance from the pre-start image. A reset passes once, where
  `restart()` arms it.
- `blank_boot_word()` is part one's step 1. `restart()` and `reopen()` are the
  reset and the Mac port reset. `rewrite_boot_block()` starts a fresh programmer
  and calls `restore()` from `tools/rda_flash.py`, which erases, programs, checks
  the whole flash, sends END and checks again.
- END writes the boot word only if block 0 was programmed in the same programmer
  session (`flash_programmer.c:549-555,716-728`). After a restart END alone does
  nothing, so the restore rewrites the block.
- `--finish JOURNAL` restores from that journal's `before-startup.bin`. It
  refuses if anything outside block 0 differs from it.

## Things that will catch you out

- The unit tests give the pieces a mock journal and a patched `read_flash`. The
  real `Journal` creates its directory and every file exclusively. Any new mode
  needs a test through `run_on()` (in `test_rda_programmer_start.py`), which runs
  the real `run()` with a journal on disk. Check that the test fails without your
  change before trusting it.
- Send the tool's output to a file, not a pipe. A reader that dies would kill the
  tool in the middle of a write. Give the shell call a 10-minute limit; part one
  takes 4 minutes.
- With a valid boot word the ROM leaves its monitor after 30 s without a request.
  A full read through the ROM takes 30 s, through the programmer 9 s.
- A debug reset from inside a session does not drop the tracker off the bus. The
  Mac keeps a stale entry (`1e04:0900`, no answer to string requests) until it is
  asked for a port reset.
- When a run finishes, the unit is still in the programmer session, listed as
  `Coolsand Usb`. With a valid word the user's RST returns it to the vendor
  firmware. Tell the user before a run: no RST, no unplug, no power button.
- `system_profiler SPUSBDataType` shows nothing for the tracker on this macOS.
  Use `snapshot()`. Zero USB devices can also mean a sandboxed shell.
- Before any live run, `pgrep -fl rda_` to see that no other session is talking
  to the tracker.
- Scripts end with `os._exit` because libusb teardown hangs on this Mac.

## How results are written up

Each live run gets a section in `docs/done/26-10-08-loader-audit.md`: a
"prepared, not run" section first with the plan, the failure table and the
command, then a section for the run with a table of elapsed times and what it
does and does not establish. Readings that are not results are labelled as such.
Wording is plain and literal.

## Where to read more

- `docs/done/26-10-08-loader-audit.md`: line 657 on, ROM entry without the vendor
  firmware; line 790 on, the reset tests and part one.
- `docs/done/26-10-09-programmer-start.md`: how the programmer was made to start,
  and the runs on 417.
- `docs/knowledge/rom-flash-access.md#4-writing-and-restoring`: the writer `tools/rda_flash.py` and its gates.
- `docs/knowledge/pin-map.md`: the pin map.
