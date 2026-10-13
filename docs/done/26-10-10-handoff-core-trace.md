> **Archived 26-10-11.** The current, reconciled account is [logicrom-core.md](../knowledge/logicrom-core.md). This note is kept as the dated record of the work; statements here may be superseded there.

# Handoff: offline trace of the Logicrom core (2026-10-10)

For a model picking this up with no memory of the session. Times are UTC (Lisbon is
UTC+1). Written about 14:30 UTC on 2026-10-10. Start with `docs/in-process/26-10-10-agents-summary.md`; this
note only adds what the offline trace of the corrected 0.5.1 core found.

**No hardware was touched.** 412 was last recorded restored to vendor firmware (see the
summary). Nothing here is a measurement on a device: every claim below was read from
the core's bytes, not observed running. Addresses are core addresses
(`0x88000000` + flash offset); a MIPS16 call target has bit 0 set in the listing
(`0x88232e09` is the function at `0x88232e08`).

## What was done

1. Cut the corrected core out of `v24-412-trial-nvmfix.bin` (first `0x250000` bytes,
   NVM fix, no USB experiment) and disassembled it as MIPS16 and MIPS32.
2. Named the core's SDK exports (358 of 367) from the hashes in the SDK's stub objects.
3. Read the app loader, the USB open/close routines, every caller of the reset
   function, the network state machine's reset branches, and the console strings.
4. Ran the existing Ghidra recipe against the core (8,124 functions, 0 failed). The
   export has not been read yet.
5. Extended the Mac capture tool (below). **The probe `main.c` was not changed and no
   instrumented core image exists.**

## Findings

### 1. The application is accepted by the core's loader, offline

- Loader `0x88238d44`: magic `0x41505031` at `0x88250000`, size, CRC32 (the message
  `invalid appimg crc/0x%x calc/0x%x`), then a table of sections: copy, zero-fill, and
  a symbol-patch section.
- Symbols are resolved by hash against a **sorted 367-entry (hash, address) table at
  file offset `0x241a40`**. Lookup is `0x88230038`. Each SDK stub is 16 bytes and its
  hash is `((w0 & 0xffff) << 16) | (w1 & 0xffff)` of its first two words.
- Our probe has 87 stubs; **all 87 resolve** against that table. The image builder
  already checks magic, size and CRC. So a bad header, CRC or unresolved symbol is not
  the reason the probe prints nothing.
- Not resolved: the branch at `0x88230330` that compares the app's string (pointed to
  by the first word of its init data at `0x88250080`) with `LROM_SDK_APPCODE` and
  decides whether `0x82300000` ends up pointing at the app's descriptor or at a
  built-in one (`0x88244434`). The built-in one is the likely owner of the
  pre-activation console. The Ghidra export should settle it.

### 2. The reset function and all six of its callers

`0x88232e08(reason)` asks `0x88232dcc`, which calls the callback registered through
`system_set_reboot_callback` (stored at `0x823009b8`, setter `0x88232dc0`). With no
callback it allows the reset; otherwise the callback's return value decides. Then it
calls through the core's function table. The reasons match `reboot_reason_e` in
`sdk/include/lib.h`.

| Call site | Reason | Context (string) |
| --- | --- | --- |
| `0x88232474` | 1 no SIM | `NW: No SIM, reset`; counter `0x82300814`, resets at 60 passes (`slti 60`) |
| `0x88232780` | 2 and 3 | shared call. `NW: Reg. fail, rebooting` sets 2 and branches here; `NW: GPRS Act timeout, rebooting...` sets 3 |
| `0x882319e2` | 3 data fail | `NW: GPRS enable timeout, rebooting...` |
| `0x88233650` | 5 param reset | `PARAM: Reset complete, rebooting` |
| `0x8823bebc` | 4 FOTA | after a 1000 ms sleep; context not read |
| `0x88240aa0` | 4 FOTA | `SYSTEM: Device will now reboot and upgrade` |

`sys_reset` (`0x88232de8`) passes reason 0 through the same gate. Its callers are
`0x88233932` (STK enable/disable), `0x8823aa62`, `0x8823ad1c` (`reboot` command) and
`0x8823b2ae`. The reasons 2 and 3 are read from register setup at the shared site; a
trace through Ghidra should confirm them.

**Consequence:** an application that registers the reboot callback sees the reason of
every network-driven reset and can deny it. It sees nothing if the app never runs.

### 3. The USB "close" is a mode switch, and the callers are now complete (for direct calls)

- `0x880fcd6c(mode)` compares `mode` with the stored mode at `0x820a1000` and does
  nothing if equal. Mode 0 and mode 1 take different paths; mode 1 builds descriptors
  with the string `USB Controller 1.0` (`0x881e2098`). The charger handler calls it
  with 1; `0x880fcb34(2)` opens the CDC modem (`1782:4d11`).
- Direct callers of close: `0x8808b002`, `0x8808b056`, `0x8823ca30` (the patched
  charger handler). Direct callers of open: `0x8808b050`, `0x8823c9fc`. The two in
  `0x8808b0xx` sit in one function that also references the string `USB Calib`
  (`0x8808b048`). **That function has not been read.** It is the first untested
  candidate for what ends the port at 9.9 s.
- No word in the core holds the address of the open or close function, so there is no
  function-pointer call to them. The MIPS32 linear decode found no extra callers, but
  that decode is unreliable over MIPS16 code.
- **New lead:** the core has a second USB path that prints `USB: cable connected`,
  `USB: cable disconnected`, `USB: Port open`, `USB: Port close` (`0x8823cb86`,
  `0x8823cba0`, `0x8823cbbc`, `0x8823cbde`), and the system task prints
  `SYS: USB cable %s` (`0x8823028e`). These are the callbacks the USB driver's own
  cable events reach. They are **not** the charger handler that trial 4 patched.

### 4. The "zeros" are one regular stream, and the core does answer

Re-reading the five saved console captures:

- Every second the port delivers about **868 bytes** of NUL, split into two or three
  reads (for example 192 + 647 + 29, 128 + 740, 64 + 775 + 29; a few seconds give 869
  or 893). The sum is read from the printed summaries, not recomputed over the raw
  hex.
- The only non-zero bytes in any capture are `devinfo\r\n\n`, **received 20–30 ms
  after `devinfo\r\n` was sent**. So receive, input handling and echo work on that
  port, and the core is alive up to the USB loss.
- No `devinfo` reply (`Core:`, `UUID:`, `IMEI:` per `0x243f3d–0x243f8d`) was ever
  received. The built-in console has a login (`Username:` at `0x882440a0`, prompt
  `devuser@dev #`, banner `WAYBYTE SOLUTIONS`; used near `0x8823adac`). Whether the
  echo means "waiting at the username prompt" is **not read yet**.
- What produces a constant 868 bytes per second of zeros is unexplained. No theory is
  recorded here.

### 5. A serial/licence-validity timer starts with the system task

Recorded as an observation, **not as a patch target or a plan**:

- `0x882302f0` (system task) registers a timer of `600000` units
  (`0x000927c0`, `generic_timer_register` at `0x88237328`) with callback
  `0x882301fc`. The callback calls `system_serialvalid` (`0x88233afc`, which checks a
  96-byte blob at `0x82300014`); if valid it frees the timer (`0x882371e0`), if not it
  calls `0x8823307c`, which walks the task list at `0x8230000c` and calls into the
  core's function table.
- The tick unit is not worked out. If the unit is milliseconds this is 600 s, which
  is not the 296.7–308 s measured; so it neither explains nor excludes the
  five-minute reset. It does not depend on the SIM, which is what the third start
  (SIM inserted, reset still came at 308 s) needs from a candidate.
- Activation remains a normal-procedure prerequisite (`getlic`, account/device
  registration). Nothing here proposes bypassing it.

### 6. The no-SIM reset is probably not the five-minute reset

The no-SIM branch fires after 60 passes of state 1 and is skipped when the SIM is
ready. The third start had a working SIM and still reset at 308.0 s. Its tick
arithmetic is also unresolved (60 passes × 20 timer calls, timer re-armed with 100 by
`0x88232968`). Treat the no-SIM path as an unlikely cause until the tick unit says
otherwise.

### 7. The SDK gives what the diagnostic app needs

- `cli_init(cliauth_f)` is in `console.h`; `system_set_reboot_callback` in `lib.h`.
  The probe calls neither (`firmware/logicrom/main.c`).
- `gpio_request` (`0x8823c670`) and `gpio_write` (`0x8823c1b0`) are core exports.
  The SDK's RDA8955 enum has `GPIO_0`–`GPIO_36`, so `GPIO_4` (blue) and `GPIO_27`
  (red) are nameable. GPIO 4 overlaps LogicROM UART1 pads, as the summary notes.

## Files changed (uncommitted; shared checkout)

| File | Change |
| --- | --- |
| `tools/logicrom_console.py` | `--no-open`: report the serial node only, never open it (refuses `--send`). `--ending cr\|lf\|crlf`. Each `open` event records `termios` flags, speeds and the DTR/RTS/CTS/DSR/CD lines read from the open port, and a `nodes` event logs node appearance. Millisecond timestamps. Behaviour with defaults is unchanged. |
| `tools/test_logicrom_console.py` | Three new tests (passive watch, passive refuses send, line ending) plus the line-state assertion. Run: `cd tools && ../.venv/bin/python -m unittest test_logicrom_console` — 7 tests, OK. |

Not mine, left alone: `docs/in-process/26-10-09-logicrom-trial.md` (222 added lines from an earlier
session) and `docs/in-process/26-10-10-agents-summary.md`. Nothing was staged or committed. Add exact files
only.

## Scratch material (session-temporary, will disappear)

Under `/private/tmp/claude-501/-Users-mateusamaral-Documents-Alquira-Trackers-alquira-trackers/ba9155e9-de9c-4abf-ad70-cccd66e2e8d8/scratchpad/`:

- `core/core.bin`, `core/m16.txt`, `core/m32.txt`, `core/strings.txt`, `core/q.py`
  (`dis`, `callers`, `lit`, `str`, `word` queries), `core/exports.json` (358 names).
- `ghidra/run.sh`, `ghidra/scripts/SetupCore.java`, `ghidra/out/` (8,124 functions;
  `index.tsv`, one `.c` per 64 KiB). Only flash and blank RAM blocks are mapped, so
  calls into `0x81xxxxxx`/`0x82xxxxxx` have no bodies and are unnamed.

To rebuild: take the first `0x250000` bytes of the NVM-only image, run
`objdump -D -b binary -m mips:16 -EL --adjust-vma=0x88000000` (Homebrew binutils), and
feed `tools/ghidra/FixCode.java` / `ExportC.java` after a script that makes flash
read-only. If these helpers are worth keeping they should be committed on request;
they were not added to the repo unasked.

## Next steps, in order

1. **Offline.** Read the Ghidra export for: the function around `0x8808aff4–0x8808b070`
   (`USB Calib`), the cable callbacks at `0x8823cb70–0x8823cc40`, the console at
   `0x8823ad00–0x8823b100` (login state, what `devinfo` needs), the `0x88230330`
   descriptor branch, and `0x88233a9d` (what `system_serialvalid` compares).
2. **Offline.** Work out the generic timer's tick unit from the tick routine
   `0x882373c0` and its caller, then decide which reset the five minutes belong to.
3. **Offline.** Update `firmware/logicrom/main.c`: LED marker at entry and after
   init (GPIO 4/27), one unbuffered USB message, `cli_init`, and a reboot callback
   that records the reason and allows it. Build with the existing recipe. Do not
   deny resets on the first pass.
4. **Only then**, one live run with its own go, comparing a passive observation
   (`--no-open`) against an opened port, with a ten-minute window. A core
   instrumentation hook (branch id on the LEDs) is the fallback if the app marker
   never appears; it needs its own review and does not exist.

## Constraints that still hold

Mac and magnetic cable only; no Windows, case opening, soldering or Waybyte contact; no
live erase or program without the user's go for that run; keep the blank boot word
while diagnosing; never use another unit's calibration tail; no repeats of the 9.9 s /
five-minute observation without a new measurement or a single change.
