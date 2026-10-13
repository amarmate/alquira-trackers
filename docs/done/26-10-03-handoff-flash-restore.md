# Handoff: "can we always flash it back?" (2026-10-03)

Goal: before any foreign firmware goes on a V24 tracker, be able to restore the original
flash. Session rule: nothing is written to a tracker's flash until the steps below are done.
User is on an Apple Silicon Mac only (no Windows, no Coolwatcher).

## Latest continuation: start-only run and recovery, 2026-10-09 Lisbon

User authorized loading/starting the programmer on original 417, without flash
commands. `tools/rda_programmer_start.py` verified both pre-start flash reads and
the pinned SRAM load; ROM acknowledged execution, but no READY arrived in 30 s.
The tool stopped without retry. No mailbox/erase/program/finalize command was sent.
User pressed RST; vendor USB returned. Two matching full recovery dumps show
unchanged firmware code and calibration/factory bytes, with 533 changed bytes in
two runtime-data sectors after reboot. Reset fields are normal (`0x00200000`).
See [full report and evidence paths](26-10-09-programmer-start.md).
Writer gates remain unchanged. Programmer startup and flash writing are unproven.
Do not automatically repeat the failed start; diagnose the startup path offline.
52 offline tests passed. The older status sections below are chronological.

## Previous continuation: host writer implementation and audit, 2026-10-08

The user authorized continuing implementation and qualification. The earlier
“approve specification before coding” requirement is superseded for this work.
`tools/rda_flash.py` and `tools/test_rda_flash.py` now exist; 26 offline tests pass.
See [operator guide](../knowledge/rom-flash-access.md#4-writing-and-restoring), [updated contract](../knowledge/rom-flash-access.md#4-writing-and-restoring)
and [audit findings](26-10-08-loader-audit.md#host-writer-audit).

Audited USB framing against the pinned ROM decoder and mailbox/startup/finalization
against the SDK and ELF. Fixed missing layout-pointer/capacity checks, startup
error handling, incomplete qualification binding and continuation after readback
failure. Added post-startup JEDEC comparison and whole-flash verification before
boot magic, as well as final readback. Journals are restricted to `firmware/live/`.
Qualification requires named passing reviews, exact source hash and spare scope;
it is a software gate, not independent hardware evidence.

**Original `1403167417` is still the only available tracker and live execution is
blocked.** No USB action, RAM load, reset, erase or program was performed during
this continuation. Both saved backup checksums still pass. An offline plan with
identical backup/target correctly shows zero sectors; it proves no write capability.

New startup finding: the built programmer tests PSRAM near offsets `0x3c0000` and
`0x3fff00`, beyond its three transfer buffers. Flash QE writes, PMD/power/RAM
compatibility and repeatable ROM access remain unqualified. Next hardware work
needs a spare, independently established chip identity, board/power diagnosis and
a reviewed recovery procedure. Do not repeat the failed original reset or launch
the stock programmer automatically. No passing qualification JSON was created.

All sections below are chronological history; statements that no writer exists
describe their earlier stage.

## Continuation, 2026-10-08

**Latest status: USB programmer BUILT; ROM USB recovery test FAILED; 417 restored
to vendor debug mode after user hardware RST/reconnect.** User explicitly requested
programmer readiness and ROM testing and confirmed original 417. The stock USB
LOD, ELF/map, hashes, compiler environment and binary audit are under
`firmware/live/usb-programmer-build/artifacts/`. USB polling is confirmed in the
built binary. It has not been loaded or validated against this board/flash chip.

Read 417's entire 24 KiB ROM: byte-for-byte match to SDK default/v1_1. Tried a new
entry hypothesis: volatile force-monitor bit plus one internal debug reset,
bypassing the vendor boot-sector command. No ROM USB interface appeared in the
subsequent bounded observation. A first cached-address preflight aborted without
reset; the corrected uncached write read back `0x00220000` before the one reset.
No programmer, erase, sector program or flash status-write command was sent.
The volatile boot-register writes and reset are recorded in the loader audit.

After the user pressed RST and reconnected (LED, no beep), verified `RDA Usb`,
`Reset_Cause=0x00200000`, saved boot mode `0x20`, original 1 KiB boot bytes and
unchanged ROM SHA-256. Log: `firmware/live/2026-10-08-after-rst-snapshot/`.
The device is communicating again; full runtime function was not tested here.
Do not repeat the failed reset or load the programmer automatically. Remaining
recovery work needs a new power/USB-initialization diagnosis or another physical
access path; cold recovery from a bad boot sector remains unproven.

The earlier continuation notes below are chronological history.


Latest offline continuation: searched four additional complete SDK distribution
indexes without finding a USB 8955 LOD. Confirmed build prerequisite: the SDK
requires RDA's custom xcpu compiler; the available compiler is 32-bit x86 Linux
and cannot run directly on this Mac. No compatible runtime is on PATH, so no
build was attempted. **New startup finding:** SDK `hal_SpiFlashOpen()` can write
flash status registers to enable QE before the programmer accepts commands.
Executing it is not a read-only test. ROM-entry source audit also identified an
AC_ON + board-specific key path; tracker button mapping is unverified. Full
findings and the build recipe are in the loader audit. No device requests,
resets, RAM writes or flash writes were sent in this continuation.


Later continuation in the same session: user requested further tests on original
`1403167417`; individually approved read-only diagnostics succeeded. USB interface
is `RDA Usb`; first 1 KiB matches its backup; fixed ROM reads returned monitor
pointer `0x81c001c0` and ROM version `0x51612152` (SDK v1.1 match). No reset,
RAM write, erase, or program command was sent. The sandbox hid all USB devices;
outside-sandbox enumeration works. New bounded tools are `rda_usb_watch.py` and
`rda_rom_identity.py`. See the audit below for logs and the second programmer
candidate: it too appears host-only. SDK build rules explicitly require
`FASTPF_USE_USB=1` for a `usb_8955_...` programmer. Original-unit reset/write
experiments have not been authorized by these read-only execution approvals.

Earlier offline stage:

- User confirmed the connected device is still original `1403167417`. No USB
  requests were made; hardware experiments remain pending the spare.
- Both original backup checksums pass again.
- Obtained and partially audited a real RAM programmer from an SDK fork. Its LOD
  checksum matches and its load records are in internal SRAM. The binary builds
  the expected `FA01/FB05` structure, but its idle loop has no USB polling: USB
  compatibility is an additional unresolved gate, not implied by the filename.
- Recorded provenance, addresses, disassembly findings, and an unproven direct
  RAM-execution avenue in [the loader audit](26-10-08-loader-audit.md).
- No writer implemented, no RAM code executed, and no flash writes made.

## Continuation, 2026-10-03 14:19 UTC

- User confirmed the connected unit was original `1403167417` and explicitly said
  no off-laptop copy was needed. That requirement below is waived; backups remain local.
- Rechecked both existing backups from `firmware/backup` with
  `shasum -a 256 -c SHA256SUMS`: both OK. No tracker UI/log process was running.
- Added `tools/rda_boot_mode.py`, a fixed-address, single-attempt word read. The SDK
  decoder maps physical `0x01a000a0` through KSEG0 to uncached `0xa1a000a0` for
  response generation. The existing 1 KiB flash reader was not used for MMIO.
- First live check found normal `1782:3d00` mode and sent no request. User powered
  the tracker off and reconnected it, after which it appeared as `1e04:0900`.
- **Step 2 completed:** exactly one register-read request was sent to the original:
  `ad 00 07 ff 02 a0 00 a0 01 03 ff`. Validated reply:
  `ad 00 06 ff 03 00 00 20 00 dc`.
  `Reset_Cause=0x00200000`, `BOOT_MODE=0x20`, `SW_BOOT_MODE=0x00`,
  **`USB_MONITOR_DISABLE=0`**. Log:
  `firmware/live/2026-10-03-reset-cause-ready.log` (gitignored).
- The sampled boot does not disable ROM USB via that bit. This does not prove power
  continuity during ROM entry or recovery after a bad flash. No restart was repeated
  and no flash writes were made. Do not probe the original again.
- Updated USB power-state documentation and drafted
  [the restore-tool specification](../knowledge/rom-flash-access.md#4-writing-and-restoring). No writer implemented.
- **Next pending:** user to connect only the powered-off spare and supply its printed
  ID; make two identical dump passes before recovery experiments. The specification
  needs approval before writer implementation, as required by the original handoff.

## Status: not yet true. No flash write has ever been done.

Nothing in `tools/` changed this session. The only new files are the backup, its checksum
line, this note and a probe log.

## What was done

1. **Researched the write path** from the public RDA8955 SDK (`cherryding1/RDA8955_W17.44_IDH`)
   and `hitechshell/rdatool`:
   - The chip ROM has its own USB download monitor (port string "Coolsand Usb"). The vendor
     firmware's port ("RDA Usb", string at flash `0x238e9c`) is a different thing.
   - ROM falls back to that monitor on its own only if flash word 0 is not `0xD9EF0045`
     (ours is that value), or if a boot-mode bit / key combo asks for it.
   - Writes go: restart into ROM monitor -> load a RAM flash programmer
     (`host_8955_flsh_spi32m_ramrun.lod` from Coolwatcher's package) -> command it
     (SDK `flash_prog_map.h`: erase sector, program, check FCS, restart; 64 KiB buffer).
   - No ready Mac flasher exists. `rdatool` only reads; Logicrom flasher 2.8.0 has no RDA8955.
2. **Dumped the unit again** (`1403167417`, tracker powered off on the cable, enumerates as
   `1E04:0900`), two matching passes:
   - `firmware/backup/v24_1403167417_2026-10-03_flash.bin`
     sha256 `c63a447aff0e3b457bda4cb7a049d3c2bfcb049b555f0d1398dc41b67a9982bd`
   - first backup `v24_1403167417_flash.bin` sha256 `d8d180a3...1b7428`
   - Both recorded in `firmware/backup/SHA256SUMS` (`shasum -a 256 -c` passes).
   - Code (`0x0-0x360000`), calibration (`0x3fa000-0x3fe000`) and IMEI block
     (`0x3fe000-0x400000`) are identical between the two; only settings-area sectors differ.
3. **Probe (approved by the user):** sent one frame asking the vendor firmware to restart
   into the ROM monitor:
   `ad 00 07 ff 84 05 00 00 00 ee 90` (write 0xEE to debug-host H2P_STATUS).
   Result: firmware accepted it and the tracker left USB in 0.2 s; **no ROM port appeared**
   and nothing re-enumerated for ~4 min. A plain unplug/replug of the magnetic cable
   brought it back as `1E04:0900`. Re-dump afterwards: code, calibration, IMEI unchanged.
   Log: `firmware/live/2026-10-03-rom-monitor-probe.log` (gitignored).
4. **Offline check of the vendor boot code in the dump:** it handles that request the way the
   SDK source says, so the request was the right one. What the ROM did after taking over
   cannot be seen in the flash image.

## Findings worth keeping

- Which USB mode the tracker shows depends on power state: **powered off on the cable ->
  `1E04:0900` "RDA Usb"** (dump port); running normally -> `1782:3D00` (log/`AT:` port).
  The SIM is not what selects it.
- Open question (two explanations, not separated): ROM monitor ran but did not bring up USB
  on this board, or the tracker lost power once the vendor firmware stopped.
- So "a bad flash is recoverable over USB" is **unproven, leaning negative**.

## Original next-task plan (step 2 completed above)

**Step 2: read the boot-mode bits.** One 4-byte read of `Reset_Cause`
(SDK: sysCtrl base `0x01A00000` + `0xA0`, boot-mode field bits 16-21; bit 3 of that field =
`USB_MONITOR_DISABLE`) over the `1E04:0900` port with the tracker powered off on the cable.
Use the existing read frame format from `tools/rda_dump.py` (verify how the address is
mapped for non-flash reads before sending; the decoder ORs `0x80000000` into read addresses).
Read-only, but first time we read a hardware register on this unit.

Then, in order:
1. Dump the **spare** (it is not 1403167417; the unit used so far is the original) and put a
   copy off the laptop. Do not probe or write the original again.
2. Write a short spec for a write tool (sector erase + program + verify, refuses
   `0x3fa000-0x400000`) and get approval before coding. Prove it on `0x3E0000-0x3F0000`
   (blank in the dump), restore the unit's own dump over itself, write sector 0 last.
3. Decide with the user whether to test the blank-sector-0 fallback (the one-way bet).
4. Update `docs/knowledge/firmware-analysis.md` (still says the USB-mode trigger is unknown) and
   copy `firmware/backup/*.bin` off the laptop.

## Gotchas

- `tools/tracker_ui.py` holds the USB interface; stop it before any other tool
  ("Access denied" / I/O errors otherwise).
- Use `os._exit` at the end of USB scripts (libusb teardown hangs on this Mac). The
  throwaway probe did this.
- Do not send `0xED` (calibration mode) to H2P_STATUS.
- Throwaway probe script (scratchpad, may be gone):
  `/private/tmp/claude-501/-Users-mateusamaral-Documents-Alquira-Trackers-alquira-trackers/9e2100e3-621d-4a2f-be42-317ffb3b988f/scratchpad/rom_monitor_probe.py`.
  SDK sources fetched into the same scratchpad `src/`; re-fetch if missing.
- Flash dumps and live logs contain IMEI/RF calibration; keep them out of git.
- Recovery that worked after the probe: unplug the cable, wait 5 s, replug. RST hole press
  and power button were not needed.
