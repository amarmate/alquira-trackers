# V24 start-only programmer experiment — 2026-10-09

The user authorized loading and starting the audited programmer on original
`1403167417`, recording startup events and comparing flash afterwards. This is
not authorization for flash erase, program, finalization or a restore.

## Tool and limits

`tools/rda_programmer_start.py` is separate from `rda_flash.py`. The writer's
original-unit block and five qualification reports remain unchanged.

- Default invocation validates artifacts offline, without USB access.
- Only the pinned programmer (`8a3ea625…8af9dd1`), October 8 ROM-session dump
  (`148c0d42…b32f62`) and October 3 backup (`c63a447a…9982bd`) are accepted.
- The device must start in `RDA Usb`. Boot bytes, the full protected calibration
  and factory tail, ROM hash and known boot fields are checked before writes.
- One force-monitor write and debug reset use the previously working vendor
  path. No MMIO register is written in ROM mode. No reset/load retry is made.
- ROM interface, handshake and hash are checked; two complete 4 MiB reads must
  agree. Code through offset `0x362000` and the protected tail must match the
  October 8 dump. Other differences are recorded before loading.
- The transmission allowlist accepts only the next exact SRAM packet from the
  pinned loader, then the execution-context command word. Each segment is read
  back, and the complete six-word execution context is verified before launch.
- Execute is sent once. After that, the host can send only memory reads. There
  is no mailbox command, including PING, GET_FINALIZE_INFO or END.
- Startup frames are checksummed and recorded for up to 30 seconds. Diagnostic
  payload words are consumed separately so a value `0xf0` inside a RAM-failure
  report cannot be mistaken for READY. `0xc0` permits the programmer's own RAM
  power retry; `0xce` prevents proceeding. ROM execution acknowledgement and
  READY are required before runtime reads.
- Fresh mailbox, buffers, geometry and cached JEDEC `c8 60 16` are checked. Two
  full post-start reads must both equal the fresh ROM baseline. The older dump
  comparison is recorded separately. Runtime metadata is checked again.
- Evidence is written exclusively to a new directory, with flushed/fsynced logs
  and dumps. The tool sends no exit, finalization or recovery command. Physical
  RST is needed afterwards.

The programmer itself still changes power/clocks, tests PSRAM, resets the flash
and may set its QE status bit. Matching flash data does not measure status
registers or establish flash-writing/cold-recovery qualification. Startup-event
logging records what USB delivers; device-side event timeouts can lose events.

Offline validation: all 52 `test_rda*.py` tests passed, including 10 new tests
covering forbidden frames, exact load order, short-transfer poisoning, RAM
readback failure, fragmented/coalesced diagnostics, fatal errors and bad CRC.
No additional writer permissions or qualification files were created.

## Invocation

```sh
.venv/bin/python tools/rda_programmer_start.py --unit 1403167417
.venv/bin/python tools/rda_programmer_start.py --execute --unit 1403167417 \
  --journal firmware/live/2026-10-09-programmer-start
```

## Live result: loaded and executed, no READY

Lisbon 2026-10-09 00:07:58 (UTC 2026-10-08 23:07:58), original 417.
Evidence: `firmware/live/2026-10-09-programmer-start/operations.jsonl` and
its two `before-startup*.bin` files. The directory name uses the local date;
each journal entry also records UTC.

| Elapsed | Result |
| --- | --- |
| 0.5 s | Vendor checks passed; reset fields `0x00200000`; force bit confirmed before one debug reset |
| 1.23 s | `Coolsand Usb`; validated ROM handshake and ROM hash |
| 32.1 / 62.9 s | Two 4 MiB ROM reads identical, SHA-256 `edf4f0df29b17e6115c5d1acc0e90b59cd120ee2cb8c1d9d6611d42aa12b9bf2` |
| 63.166 s | Entire pinned SRAM load read back byte-for-byte |
| 63.167 s | Six-word execution context verified; execute sent once |
| 63.168 s | ROM execution acknowledgement `0xff000004` received with valid checksum |
| 93.309 s | No further event within 30 s; stopped without retry or further writes |

The startup did **not** reach a USB-observed READY event. No RAM-failure,
memory-reset or fatal-memory event was received either. The acknowledgement
proves ROM accepted execution; it does not prove where the programmer reached.
No runtime ABI/JEDEC read or post-start flash read was attempted without READY.
No mailbox command, erase, program, finalization or monitor-exit command was sent.

The fresh ROM image already differed from the October 8 22:56 dump in 10,227
bytes, in six 4 KiB sectors: `0x38d000`, `0x398000`, `0x3a8000`, `0x3d1000`,
`0x3d8000`, `0x3d9000`. Code through `0x362000` and the entire protected tail
matched. These differences predate the programmer load and cannot be attributed
to it; the meaning of the changed runtime data has not been decoded.

After timeout, a descriptor-only check still listed `1e04:0900`, but could not
read its language/string descriptors. This is evidence of an unresponsive USB
state, not proof of a specific clock, RAM or power failure.
Log: `firmware/live/2026-10-09-programmer-start-after-timeout-usb.jsonl`.

The user pressed and released RST once. The normal `RDA Usb` interface returned
with endpoints `81,01`, recorded in
`firmware/live/2026-10-09-programmer-start-after-rst-usb.jsonl`.
`tools/rda_flash_readback.py` then completed a read-only double full-flash comparison
against the fresh pre-start image. Its first register read showed reset fields
`0x00200000`: FORCE_MONITOR cleared.

Both recovered 4 MiB dumps are identical, SHA-256
`420249dc698a2ac08714d899606c1286415d163196af202fa52cde4af9c9140e`.
They differ from the immediate pre-start snapshot in 533 bytes in sectors
`0x3d1000` and `0x3d9000` only. Firmware code through `0x362000` and all of
`[0x3fa000,0x400000)` match exactly. The changed sectors lie in the vendor's
runtime-data region, and both also changed between the October 8 dump and the
pre-start snapshot. Firmware boot writes are a plausible explanation, but the
vendor firmware ran after RST before these reads, so attribution is not proven.
This is **not** a byte-identical full-flash result across the experiment.

Recovery evidence: `firmware/live/2026-10-09-programmer-recovery-readback/`,
containing `operations.jsonl` and `flash-pass-1.bin` / `flash-pass-2.bin`.
The second pass completed at 23:11:16 UTC, October 8 (00:11:16 Lisbon, October 9).
The unit is back in the vendor debug interface; full application, radio, GPS and
sensor operation were not exercised. Flash status registers were not measured.

There was only one programmer load/execute attempt. Further starts require a
new diagnosis; do not repeat this binary automatically or weaken writer gates.

Next investigation should be offline: bound the path between the acknowledged
ROM execute and USB READY, including entry context, PMD/clock startup, RAM checks
and USB reinitialization. The missing events do not distinguish those causes.

## Offline follow-up, same night: what the evidence narrows, and a marker build

No device request was sent. The user reports 417 working normally after the run.

### The 533 bytes are the vendor's own storage writes (my reading, not a control)

- `0x3d9000`, 528 bytes: one 512-byte record appended at `0xe00` plus its index
  entry, numbered `0x6c` to `0x6d`; every changed bit goes 1 to 0, so nothing was
  erased. The same sector took the same record twice (`0x6a` to `0x6c`) between
  the October 8 dump and the pre-start snapshot, before any programmer was loaded.
- `0x3d1000`, 5 bytes: header of an otherwise empty sector. The counter at offset
  8 went `0x87` to `0x88` and the marker `0xcafebee0` appeared at offset 4. A
  counter bit going 0 to 1 needs an erase, so the firmware erased it again at
  boot. The pre-start snapshot caught it erased but unmarked, which fits our
  debug reset landing in the middle of the firmware's clean-up.

A control (RST, dump, RST, dump) would prove it; I do not think it is needed.

### What runs between execute and READY

- **The entry point `0x81c00280` is `boot_Sector`, not the loader** (linker map,
  `.boot_sector_start`). Before `main` it runs, in order: a chip metal-ID check
  that executes `break 1` below U02, the ROM version check, the boot-sector
  structure and command check, two download-key checks, then `boot_MemInit`
  (system clock to 26 MHz, PLL, EBC set-up, RAM ID read, `memd_RamOpen`), then
  `boot_Loader` (stack reset to the top of SRAM, 192 KiB of external-RAM BSS
  cleared). The image also links `boot_EbcCsOpen`, which soft-resets the chip if
  the RAM timing register does not read back; whether `memd_RamOpen` reaches it
  is not traced. The loader audit's start-up section begins at `boot_Loader` and
  does not cover any of this.
- **The programmer stays on the ROM's interrupt handler**, which services USB by
  interrupt and has two silent dead ends: any CPU exception loops forever
  (`boot_rom.S`, `_boot_romed_exception`) and any interrupt other than USB hits
  `while (1)` (`boot_IrqDispatch`). Both leave the device attached but deaf, which
  is what the after-timeout check recorded.
- **Events are sent synchronously** (`boot_HostUsbEvent`, 0.5 s timeout each), so a
  failed RAM check would have shown `0xebc0eee2` or `0xc0` first. None arrived:
  either USB died before the first event, or every later event timed out unseen.

### Power configuration: generic target against the vendor's

Decoded from both binaries with the SDK's `PMD_CONFIG_T`: the programmer's
`g_tgtPmdCfg` (`0x81c07814`, `0x150` bytes) and the vendor's at flash offset
`0x23b49c`, which is identical in the October 3 backup. The vendor's layout
differs in the last 20 bytes, so only fields before offset `0x13c` are compared.

| Field | Programmer | Vendor |
| --- | --- | --- |
| `power[CAMERA].ldo` | CAM and RF | CAM |
| `power[PA].ldo` | none | RF |
| `ldoEnableLowPower` | none | RF |
| `ldoRfIs2_8` | 1.8 V | 2.8 V |
| `batteryChargeCurrent` | 400 mA | 200 mA |
| LED level types, backlight table | differ | differ |

Every `powerOnState` is off in both, and the battery limits match. With the same
`pmd.c`, the rails left on after `pmd_Open` are the same for both; the RF rail
differs only in low-power mode and voltage. So this is not an obvious cause of
the hang. The 400 mA charge current is wrong for this board and should be fixed
before any session long enough to matter.

### Marker build, ready but not run

`firmware/live/usb-programmer-build/markers/` holds a clone of the SDK tree with
`markers.patch` applied: 39 calls to `boot_HostUsbEvent`, nothing else changed.
The pinned tree and artifacts are untouched. LOD SHA-256
`1d861ef371b303fc9bc514df86777ea934290a240d2ef8a6c0c49ae92abec256`, entry still
`boot_Sector` at `0x81c00280`, 48,312 payload bytes. A marker is sent just before
each stage, so the last one received names the stage that stopped USB.

| Events, in order | Stage |
| --- | --- |
| `0x5a000101`, `0x5a00011v` | ROM version check passed; `v` = boot-sector structure valid |
| `0x5a000102` to `0105` | command check, key check, USB key check, `boot_MemInit` |
| `0x5a000301` to `0304` | clock to 26 MHz, PLL set-up, after PLL, after ISPI divider; the first EBC set-up and RAM ID read follow |
| `0x5a00aVII` | RAM ID `II`; `V` = taken from the boot-sector structure |
| `0x5a000305` to `0307`, `0106` | second EBC set-up, `memd_RamOpen`, after it, back in `boot_Sector` |
| `0x5a000401` to `0403` | loader entered, external-RAM BSS clear, call to `main` |
| `0x5a000001`, `0002` | `hal_MapEngineOpen`, `pmd_Open` |
| `0x5a000200` to `020a` | inside `pmd_Open`: after the PMU read, after the host event, then before the power loop, level loop, LDO registers, SIM select, GPADC and `pmd_InitRdaPmu`; after it; before and after the earpiece GPIO set-up |
| `0x5a000003` to `0007` | power mode, 104 MHz, watchdog close, `hal_SpiFlashOpen`, RAM check |
| `0x5a000008` to `000a` | RAM check passed, `boot_HostUsbOpen`, after it; READY follows 0.5 s later |

No marker at all means it stopped in the metal-ID or ROM version check, or that
events cannot be sent from the programmer at all.

`tools/rda_programmer_start.py --markers` loads this build instead of the pinned
one, records every event as before and stops at READY without the runtime reads,
whose addresses belong to the pinned build. The wire allowlist is unchanged. All
55 `test_rda*.py` tests pass, three of them new.

### First marker attempt stopped before loading (tool fault, fixed)

23:51:40 UTC, October 8, user-run. Journal:
`firmware/live/2026-10-09-programmer-markers/operations.jsonl`. Vendor checks,
forced ROM entry, handshake and both 4 MiB reads passed (SHA-256
`24ab1f41…5100a`, code and protected tail unchanged). The load then stopped with
`RAM write outside pinned programmer allocations`: the writer's `write_ram`
accepts only the stock image's range, which ends at `0xa1c0bd20`, and the marker
image ends at `0xa1c0bf20`. At most the 24-byte execution-context record went
out, with command word 0. No programmer code was loaded and nothing was executed.
The unit was left in the ROM monitor with the force bit set.

`StartMonitor` now has its own `write_ram`, bounded by its exact-packet
allowlist; `rda_flash.py` is unchanged. A new test pushes the real marker image
through the whole load path, which is the check I had skipped.

```sh
.venv/bin/python tools/rda_programmer_start.py --execute --markers --unit 1403167417 \
  --journal firmware/live/2026-10-09-programmer-markers-2
```

Each run needs the user's go-ahead and carries the same risk as the first.

### Marker run 2: start-up stops in the 104 MHz clock request

23:54:52 UTC, October 8, user-run, marker build `1d861ef3…c256`. Journal:
`firmware/live/2026-10-09-programmer-markers-2/operations.jsonl`.

- Load verified and executed at 63.975 s; ROM acknowledged with `0xff000004`.
- 33 markers arrived within 47 ms, the last being `0x5a000004`, sent just before
  `hal_SwRequestClk(FOURCC_TOOL, HAL_CLK_RATE_104M)` (`flash_programmer.c:420`).
  Nothing followed for 30 s.
- So `boot_Sector`, both key checks, `boot_MemInit` including `memd_RamOpen`, the
  loader, all of `pmd_Open` and `pmd_SetPowerMode` completed with USB alive.
- `0x5a000110`: the boot-sector structure was not valid. `0x5a00a001`: RAM ID 1,
  read from the chip. The 192 KiB external-RAM clear took 25 ms.
- `0x5a000006` never arrived, so `hal_SpiFlashOpen` did not run: the flash chip
  was not reset and no status register was written in this run. Run 1 used the
  same code path, so the same holds there by inference.

Cause, from source and binary:

- `hal_SwRequestClk` calls `clk_request` (`hal/src/clock.c:585`), which disables
  interrupts and then uses the root clock object `g_clk_sw`.
- `g_clk_sw` is assigned only in `hal_ClkInit` (`hal_clk_8955.c:348`), and
  `hal_ClkInit` is called only from `hal_Open` (`hal_open.c:277`). This programmer
  is built to skip `hal_Open`.
- In the image `g_clk_sw` sits in `.srambss` (`0x81c0c024`), which the loader
  zeroes. `clk_request` therefore works on a NULL clock and calls through a
  pointer loaded from it, with interrupts off.

Whether it then traps into the ROM's exception loop or jumps somewhere wild is
not known; both give a device that stays attached and stops answering. This is a
defect of the SDK source in this configuration, not of the V24 board. **The
pinned stock LOD `8a3ea625…9dd1`, which `rda_flash.py` requires, cannot reach
READY as built.**

### Next build: markers, without the clock request

`markers/artifacts/usb_8955_flsh_spi32m_ramrun_markers_noclk.lod`, SHA-256
`025f49fea9e88f8defca6dbf7025f9719b598e78d338daf8825592c1b8a5225a`; the `.patch`
beside it is the whole difference from the pinned tree. The one change beyond
the markers is that the clock request is removed, after which the linker drops
`hal_SwRequestClk` and `clk_request` entirely. The system clock stays as
`boot_MemInit` left it; the effect on flash and USB speed is not measured.

`--markers` now loads this build and runs the same checks after READY as the
stock flow, with this build's own addresses from its linker map (ABI map
`0xa1c0bbd8`, bank table `0xa1c0963c`, layout `0xa1c09658`, flash context
`0xa1c077a0`): fresh mailbox and buffers, flash layout, cached JEDEC, then two
full flash reads through the programmer compared with the pre-start read. Still
no mailbox command. All 56 `test_rda*.py` tests pass, and the whole sequence
after the handshake was dry-run against a simulated device with the real image.

```sh
.venv/bin/python tools/rda_programmer_start.py --execute --markers --unit 1403167417 \
  --journal firmware/live/2026-10-09-programmer-markers-3
```

Unlike the two runs so far, this one is expected to reach `hal_SpiFlashOpen`,
which resets the flash chip and sets its QE status bit if it is clear.

### Marker run 4: the programmer starts, and the flash reads back unchanged

00:02:55 UTC, October 9 (01:02:55 Lisbon), user-run, build `025f49fe…225a`.
Evidence: `firmware/live/2026-10-09-programmer-markers-4/`, with
`operations.jsonl` and four 4 MiB dumps. The `-3` journal is an earlier try that
stopped at preflight with no USB device visible; nothing was sent.

| Elapsed | Result |
| --- | --- |
| 1.43 s | `Coolsand Usb`; ROM handshake |
| 32.9 / 64.3 s | Two ROM reads identical, SHA-256 `2ed0777280d0b00b5771985b8314914449ffe72706618f3c3e8be632cdf19275` |
| 64.585 s | Marker image read back byte-for-byte; execute sent once |
| 64.587 s | ROM acknowledgement `0xff000004` |
| 64.636 s | All 39 markers received, in the expected order |
| 65.136 s | **READY (`0xf0`)**, 0.55 s after execute |
| 65.139 s | Mailbox fresh, buffers at `0xa2000000`, layout as built, cached JEDEC `c8 60 16` |
| 74.7 / 84.2 s | Two full reads through the programmer, both identical to the pre-start read: 0 bytes differ |
| 84.401 s | Runtime metadata unchanged after the reads |

- This confirms the cause: with the clock request removed and nothing else
  changed, start-up runs to READY.
- No RAM-failure or memory-reset event arrived, so the buffer check, including
  the writes at RAM base + `0x3c0000` and + `0x3fff00`, passed on the first try.
- A 4 MiB read through the programmer took about 9.5 s, against about 31 s
  through the ROM, without the 104 MHz request.
- No mailbox command was sent: no erase, program or finalize.

Recovery, 00:05:55 UTC: the user pressed RST and ran `rda_flash_readback.py`
against the pre-start read. Evidence:
`firmware/live/2026-10-09-programmer-markers-4-recovery/`. Vendor `RDA Usb` was
back, reset fields `0x00200000` (force bit cleared), two reads identical (SHA-256
`f83a491f…97b2`), code and protected tail unchanged. The only difference is 528
bytes in sector `0x398000`: one 512-byte record appended at `0x600` and its index
entry, numbered `0x73` to `0x74`, bits only going 1 to 0. That is the same
per-boot record seen in `0x3d9000` after run 1, now in the store's current
sector, and here it is the whole change across the run and one boot. Full
application, radio and GPS operation were not exercised.

Not measured or not established:

- The flash status registers. `hal_SpiFlashOpen` ran, so the flash chip was reset
  and its QE bit set if it was clear; only the data is known to be unchanged.
- Flash writing. This build carries the markers and is not the binary
  `rda_flash.py` is pinned to; the writer's gates are untouched.

What this opens, in order: a clean build with only the clock-request fix and the
V24 charge current (200 mA); its own start-only run; then re-pinning the writer
to that build and its addresses, which is a writer change and needs its own
review.

### Clean build: clock fix and 200 mA, ready but not run

Built 10:25 UTC, October 9 (11:25 Lisbon). No device request was sent.
`firmware/live/usb-programmer-build/clean/` holds a copy of the pinned SDK tree
with two changes, and `artifacts/` beside it holds the LOD, ELF, map, patch and
`SHA256SUMS`. LOD SHA-256
`c238911dc478363b1dffdebbffcc407e6e1b1b51ef5c53c9d90ca2fe8bff6c65`, entry still
`boot_Sector` at `0x81c00280`, 47,416 payload bytes (stock: 47,800).

- `flash_programmer.c`: the `hal_SwRequestClk(FOURCC_TOOL, HAL_CLK_RATE_104M)`
  call is removed, as in the build that reached READY.
- `target/8955_ramrun/include/tgt_board_cfg.h`: `batteryChargeCurrent` goes from
  `PMD_CHARGER_400MA` to `PMD_CHARGER_200MA`.
- No markers. The `.patch` is the whole difference from the pinned tree.

Checks on the build itself:

- **Control.** The same copy, before the two changes, rebuilds the pinned stock
  LOD `8a3ea625…9dd1` byte-for-byte. The SDK stamps the build date into three
  words, so this needs `BUILD_DATE=20261008`; with today's date only those words
  and the checksum differ. The clean build pins `BUILD_DATE=20261009`, and a
  second build from scratch gave the same hash.
- **Against the stock ELF.** Five symbols are gone (`hal_SwRequestClk`,
  `clk_request`, `gClkRateList`, `g_consumers`, `g_sw_consumers`) and none is
  added. `main` is the only symbol whose size changed (`0xbac` to `0xba4`).
- **Power configuration.** `g_tgtPmdCfg` differs from stock in one byte, offset
  `0x128`: 6 (400 mA) became 4 (200 mA). The vendor's configuration in the
  October 3 backup holds 4 at the same offset.
- **Addresses**, from the ELF symbols: ABI map `g_flashProgDescr` `0xa1c0b9e8`,
  bank table `g_memdFlashBankLayout` `0xa1c0944c`, layout `g_memdFlashLayout`
  `0xa1c09468`, flash context `gSpiFlashCtx` `0xa1c075b0`. The same four symbols
  give the stock and marker builds' recorded addresses.

`tools/rda_programmer_start.py --clean` loads this build; `--markers` and
`--clean` exclude each other. The wire allowlist and every check are those of
marker run 4: start, READY, fresh mailbox and buffers, flash layout, cached
JEDEC, two full reads through the programmer compared with the pre-start read,
no mailbox command. All 57 `test_rda*.py` tests pass, one of them new: a build
read with another build's addresses is rejected. The sequence after the
handshake was dry-run at the USB framing level against a simulated device with
the real image.

This binary has never run on a device. It differs from the one that reached
READY by one configuration byte and by the absence of the 39 markers, each a
synchronous USB send; whether start-up depends on the time they took (about
50 ms in all in run 4) is not known, and is what the start-only run tests.

```sh
.venv/bin/python tools/rda_programmer_start.py --execute --clean --unit 1403167417 \
  --journal firmware/live/2026-10-09-programmer-clean-1
```

Same risk and same recovery as run 4: physical RST, then the read-back against
the pre-start read, whose hash is in the journal's `saved` entry.

```sh
.venv/bin/python tools/rda_flash_readback.py --read \
  --baseline firmware/live/2026-10-09-programmer-clean-1/before-startup.bin \
  --baseline-sha256 <sha256 of before-startup.bin> \
  --journal firmware/live/2026-10-09-programmer-clean-1-recovery
```

To rebuild (the builder image lives in the `rda-build` colima profile):

```sh
cd firmware/live/usb-programmer-build
colima start --profile rda-build
rm -rf clean/sdk/soft/build clean/sdk/soft/hex
docker --context colima-rda-build run --rm --platform linux/amd64 \
  -e BUILD_DATE=20261009 -v "$PWD/clean/sdk:/work/sdk" -v "$PWD/csdtk:/work/csdtk:ro" \
  -v "$PWD/build.sh:/work/build.sh:ro" rda-usb-builder:local bash /work/build.sh
```

### Clean run 1: the clean build starts, and the flash reads back unchanged

10:36:04 UTC, October 9 (11:36:04 Lisbon), user-run, build `c238911d…6c65`.
Evidence: `firmware/live/2026-10-09-programmer-clean-1/`, with `operations.jsonl`
and four 4 MiB dumps.

| Elapsed | Result |
| --- | --- |
| 0.95 s | `Coolsand Usb`; ROM handshake |
| 32.2 / 63.4 s | Two ROM reads identical, SHA-256 `44d5920c7b47bf04a8b3953b62efd854875e71baaa9a6adeaf63ba6a02ed7120` |
| 63.664 s | Clean image read back byte-for-byte; execute sent once |
| 63.665 s | ROM acknowledgement `0xff000004` |
| 64.207 s | **READY (`0xf0`)**, 0.54 s after execute, with no other event in between |
| 64.211 s | Mailbox fresh, buffers at `0xa2000000`, layout as built, cached JEDEC `c8 60 16` |
| 73.7 / 83.3 s | Two full reads through the programmer, both identical to the pre-start read: 0 bytes differ |
| 83.434 s | Runtime metadata unchanged after the reads |

- Start-up does not depend on the markers: without them it reaches READY in the
  same time as run 4.
- No RAM-failure or memory-reset event arrived.
- A 4 MiB read through the programmer again took about 9.5 s.
- No mailbox command was sent: no erase, program or finalize.
- Before loading, the flash differed from the October 8 dump in 12,479 bytes in
  11 sectors of the vendor's runtime-data region. Code through `0x362000` and the
  protected tail matched, or the tool would not have loaded.

Not measured or not established, as after run 4: the flash status registers
(`hal_SpiFlashOpen` ran), and flash writing. The charge current is set in the
configuration; the current actually drawn was not measured.

Recovery, 10:39:02 UTC: the user pressed RST and ran `rda_flash_readback.py`
against the pre-start read. Evidence:
`firmware/live/2026-10-09-programmer-clean-1-recovery/`. Vendor `RDA Usb` was
back, reset fields `0x00200000` (force bit cleared), two reads identical (SHA-256
`c3ab5c44…bc2a`), code and protected tail unchanged. The only difference is 528
bytes in sector `0x398000`: one 512-byte record appended at `0xc00` into blank
flash and its 16-byte index change, numbered `0x75` to `0x76`, bits only going 1
to 0. Byte for byte it has the shape of the change after run 4 (there `0x73` to
`0x74`, record at `0x600`), so it is again the vendor firmware's per-boot record
and the whole change across the run and one boot. Full application, radio and
GPS operation were not exercised.

What this opens: re-pinning the writer (`rda_flash.py`) to build `c238911d…6c65`
and its addresses. That is a writer change with its own review; the writer's
gates and its original-unit block are untouched so far.

### Writer re-pinned to the clean build

Prepared October 9 for review, offline: no device request, nothing committed.

`tools/rda_flash.py` now loads build `c238911d…6c65` and refuses the unmodified
one. The values that changed, each read from the clean ELF's symbols:

| Constant | Unmodified build | Clean build | Symbol |
| --- | --- | --- | --- |
| `LOD_SHA` | `8a3ea625…9dd1` | `c238911d…6c65` | |
| `MAP` | `0xa1c0bb68` | `0xa1c0b9e8` | `g_flashProgDescr` |
| `GEOMETRY_ADDRESS`, and the pointer inside `LAYOUT` | `0xa1c095c4` | `0xa1c0944c` | `g_memdFlashBankLayout` |
| `LAYOUT_ADDRESS` | `0xa1c095e0` | `0xa1c09468` | `g_memdFlashLayout` |
| `FLASH_CONTEXT` | `0xa1c076f0` | `0xa1c075b0` | `gSpiFlashCtx` |
| `IMAGE_END`, the end of the RAM-write allowlist | `0xa1c0bd20` | `0xa1c0bba0` | `_sys_sram_end` |

- One gate is new: `read_lod` refuses an image whose load range does not end at
  `IMAGE_END`, so a stale bound cannot leave the allowlist wider than the image.
- Nothing else in the writer changed: the qualification gate, the block on the
  original unit, the wire protocol and the restore sequence are as they were. A
  qualification naming the unmodified build is now rejected.
- `tools/rda_programmer_start.py` without a flag now starts this build, read
  through the writer's own `read_lod` and checked at the writer's addresses.
  `--clean` is gone; `--markers` is unchanged.

Checked again for this binary:

- **Compiled objects.** The 126 objects, archives and linker scripts of the two
  build trees were compared. Apart from the archives that contain them, six
  objects differ: four version maps by the build-date byte; `target_config.o` by
  the charge-current byte and a build-time string that is not linked into the
  image; and `flash_programmer.o`.
- **`flash_programmer.o`.** Of its nine functions only `main` differs. It still
  makes the same calls: its 113 call and jump targets are the unmodified build's
  114 without `hal_SwRequestClk`, and its 18 calls into the ROM are the same, in
  the same order.
- **USB service.** In the clean ELF `main` calls `boot_HostUsbOpen` at
  `0x81c021d8`, `boot_HostUsbRecv` at `0x81c02230` and `boot_HostUsbSend` at
  `0x81c02238`.
- **Structure.** `rda_lod_audit.py`: load ranges `[0x01c000a0,0x01c000b8)` and
  `[0x01c00280,0x01c0bba0)`, entry `0x81c00280` with command word 0, one protocol
  map at `0x01c0b9e8`. Saved as `clean/artifacts/audit.json`.
- **On 417**, clean run 1: READY, then the fresh mailbox, bank table, layout and
  JEDEC `c8 60 16` read at exactly these four addresses, and 8 MiB of memory reads
  answered afterwards.
- **Tests.** All 64 `test_rda*.py` tests pass, seven of them new. Each was seen to
  fail before the change: the real image holds the tables where the writer reads
  them; the whole image loads and starts through the writer's own monitor; the
  allowlist ends exactly at the image; a stale end is refused; the unmodified
  build is refused; a qualification for it is rejected; the start tool's default
  is the writer's build.

Not established:

- **`main` is not the audited listing minus one call.** `main` holds the command
  loop, and removing the call made the compiler assign registers differently
  through the whole function: 747 instructions became 745 (the call's five gone,
  three delay-slot `nop`s added), with many of the rest using other registers. It
  is the same source lines and the same compiler, but the October 8 audit read
  the other listing.
- **No mailbox command has run on a tracker**, in any build: not PING, not
  GET_FINALIZE_INFO, not ERASE, PROGRAM or END. Start-up and memory reads are all
  that hardware has confirmed.
- The flash status registers, and whether start-up changed QE.
- No qualification exists, and the original unit stays blocked.

The four disassemblies behind this are in
`firmware/live/usb-programmer-build/clean/review/`.

### Review of the re-pin, and what the two query commands do in this binary

Done October 9 in a separate session, offline, at the user's request: "review
and go ahead if you think everything is safe to execute on the device".

Checked again, independently of the section above:

- The LOD hashes to `c238911d…6c65`, and the five pinned values equal the clean
  ELF's symbols and linker map. The 417 journal of clean run 1 shows the mailbox,
  bank table, layout pointer `0x81c0944c` and JEDEC at those addresses.
- All 126 objects, archives and linker scripts of the two build trees, archives
  member by member: the six objects named above differ and nothing else does.
  Only `main` differs inside `flash_programmer.o`; its 18 ROM calls are the same.
- `clean-elf.dis` is the pinned LOD: each of the 745 instruction words of `main`
  equals the LOD's word at that address.

`main`'s dispatch, read from that listing, since the October 8 audit read the
other one:

| Command | Branch | What it does |
| --- | --- | --- |
| 9, PING | `0x81c02254` to `0x81c02afc` | stores DONE in the slot, sends `0xf0` + slot, switches slot |
| 6, GET_FINALIZE_INFO | `0x81c022a4` to `0x81c02330`, `0x81c02504` | writes `0`, `0xd9ef0045` to the slot's RAM address, size 1, DONE, `0xf0` + slot, switches slot |

Neither path calls anything but the ROM's `boot_HostUsbEvent`. Flash erase and
write are reached only from the arms for 1, 2, 4, 10, 11, 13 and 15, and restart
and shutdown only from 7 and 16. An unknown value stores ERROR and sends
`0xd0` + slot.

Findings from the code review, none seen on 417 and none blocking: the start
tool accepts READY after error words other than `0xce`, where the writer stops
on any; the writer stops on a `0xc0` memory-power retry that the start tool
tolerates; and a failed force-bit read-back leaves the bit set until RST.

### Query run 1: the first mailbox commands answer, and the flash reads back unchanged

`tools/rda_programmer_start.py --query` runs the start as before and then the
writer's own start-up check, `Programmer.initialize`, unchanged: PING on slot 0,
PING on slot 1, GET_FINALIZE_INFO on slot 0.

- The wire allowlist passes six more exact packets after execute, in order:
  parameters (offset 0, buffer `0xa2000000`, size 0) and command word for each of
  the three. Any other write is still refused, including every other command.
- Nothing is sent unless start-up was exactly the ROM acknowledgement and READY.
- Afterwards the mailbox must hold DONE in both slots, count 1 in slot 0 and
  nothing else changed, and two more full reads must equal the pre-start read.
- `--query` is refused with `--markers`, whose mailbox is at another address.

All 87 tests in `tools/` pass, seven of them new, and the whole of `main()` was
dry-run against a simulated tracker with the real image, with and without
`--query` and with three injected faults.

```sh
.venv/bin/python tools/rda_programmer_start.py --execute --query --unit 1403167417 \
  --journal firmware/live/2026-10-09-programmer-query-1
```

11:09:29 UTC, October 9 (12:09:29 Lisbon), run by the assistant on the user's
go-ahead, build `c238911d…6c65`. Evidence:
`firmware/live/2026-10-09-programmer-query-1/`, with `operations.jsonl` and six
4 MiB dumps.

| Elapsed | Result |
| --- | --- |
| 1.42 s | `Coolsand Usb`; ROM handshake |
| 32.5 / 63.6 s | Two ROM reads identical, SHA-256 `c3ab5c44ba41ea797cf3ad76ed947376541bf01abd2c2b220e2d074e1cbfbc2a` |
| 63.812 s | Image read back byte-for-byte; execute sent once; ROM acknowledgement |
| 64.353 s | **READY (`0xf0`)**, 0.54 s after execute, with no other event |
| 73.8 / 83.2 s | Two reads through the programmer, identical to the pre-start read |
| 83.365 s | PING, slot 0: event `0xf0`, DONE within 1 ms |
| 83.367 s | PING, slot 1: event `0xf1`, DONE within 1 ms |
| 83.368 s | GET_FINALIZE_INFO, slot 0: event `0xf0`, DONE; count 1, buffer holds `0`, `0xd9ef0045` |
| 83.370 s | Mailbox as expected: DONE in both slots, count 1 in slot 0, buffers unchanged |
| 92.8 / 102.2 s | Two more reads through the programmer, identical to the pre-start read: 0 bytes differ |

- The mailbox works on hardware: RAM writes through the running programmer land,
  both slots answer, the slots alternate as the writer expects, and each answer
  comes with the event the writer expects.
- The pre-start read is identical to the recovery read after clean run 1, so the
  flash did not change in the half hour between the two runs either.
- Three mailbox commands were sent. No erase, program or finalize.

Recovery, 11:22:51 UTC: the user pressed RST and ran `rda_flash_readback.py`
against the pre-start read. Evidence:
`firmware/live/2026-10-09-programmer-query-1-recovery/`. Vendor `RDA Usb` was
back, reset fields `0x00200000` (force bit cleared), two reads identical (SHA-256
`47affe8b…3105`), code and protected tail unchanged. The only difference is 528
bytes in sector `0x398000`: one 512-byte record appended at `0xe00` into blank
flash and its 16-byte index change, bits only going 1 to 0. It is the record
after the one clean run 1 left at `0xc00`, with the index entry 16 bytes further
on, so it is again the vendor firmware's per-boot record and the whole change
across the run and one boot. Full application, radio and GPS operation were not
exercised.

Not measured or not established: flash writing (ERASE, PROGRAM and END have
still never been sent), and the flash status registers.

### Write test: the build

The user decided on October 9 to make the first flash write on 417, on blank
flash, and not on a spare: 417 has two full backups and today's dumps, is open,
and is the unit ROM entry and the programmer start are proven on. No device
request was sent in building this; the run is in the next section.

`tools/rda_programmer_start.py --write-test` runs the start and the query as
above, then three flash commands through the writer's own `Programmer.command`:

| Command | Where | Then |
| --- | --- | --- |
| PROGRAM, 4 KiB | `0x3e0000`, the sector's first 4 KiB | one full read must equal the pre-start image plus this chunk |
| PROGRAM, 4 KiB | `0x3ef000`, its last 4 KiB | one full read must equal the pre-start image plus both chunks |
| ERASE | `0x3e0000` | two full reads must equal the pre-start image |

- **The sector.** `0x3e0000` is 64 KiB, blank in every dump of 417 since October 3,
  and a whole erase block: nothing else is inside the reach of its erase. The
  ten blank 4 KiB sectors at `0x3f0000` share their 64 KiB block with calibration
  (`0x3fa000`) and factory data (`0x3fe000`), so they are not used. The test
  refuses to send anything if the sector is not blank in the pre-start read.
- **The order.** The programs come first: one landing in the wrong place costs
  4 KiB and shows in the read-back before any erase is sent, and the erase takes
  its address from the same mailbox field. The erase comes last, so a host that
  stops waiting during it still leaves the sector as it found it.
- **The data.** Each chunk is 4 KiB of SHA-256 output over its own offset, so the
  two differ and neither can be mistaken for anything the firmware writes.
- **The allowlist** passes these fourteen packets and nothing else: four buffer
  packets, the parameters and the command word for each program, and the
  parameters and command word for the erase. An erase or program at any other
  offset, any other data, and END are refused before they reach USB.
- **On any mismatch** the tool stops: no retry, no repair, no clean-up erase.
  Every read is saved, so the journal shows what the flash held.

What these commands do in the pinned binary, read from `clean-elf.dis` and the
SDK source:

- `main`, command 1 with checksum word 0, calls
  `hal_SpiFlashWrite(offset, 0xa2000000, 4096)`: sixteen page programs of 256
  bytes, opcode `0x02`. A program at offset 0 would arm END; these do not.
- `main`, command 2, calls `memd_FlashGetSectorLimits`, which returns
  `0x3e0000` to `0x3f0000` for this offset, then `hal_SpiFlashErase(0x3e0000,
  0x10000)`. Traced with these values, the compiled function makes exactly one
  call, `hal_SpiFlashBlockErase(0x3e0000)`, opcode `0xd8`. That is the opcode
  an install would use for every sector below `0x3f0000`.
- Each write-enable first re-reads the JEDEC id and executes `break 1` if it is
  not the id cached at start-up.
- No lock or unlock callback is installed, and nothing in these paths writes a
  status register. If the chip's block-protect bits covered this sector, the
  commands would report DONE and the read-back would show no change.
- Each operation runs with interrupts off, so USB is not served during it. The
  host waits up to 1 s to send a status poll and 5 s for its answer; a block
  erase slower than that would stop the tool while the erase still completes.

All 94 tests in `tools/` pass, seven of them new, each seen to fail first, and
five deliberately broken versions of the allowlist and the verification were
each caught. The whole of `main()` was dry-run against a simulated tracker that
programs and erases as the SDK driver does: the full sequence, the two older
modes, and a corrupted program, a program at the wrong address, a short erase, a
silent erase and a start-up retry, each of which stopped the run.

Not covered by any of this: the compiled `hal_SpiFlashWrite`, the SPI command
layer and the flash controller were read as source, not traced or exercised.
Whether they address this chip correctly is what the run tests. If the erase
landed on another block and the vendor firmware no longer booted, getting back
into the ROM monitor is unproven, because every entry so far went through the
vendor firmware.

```sh
.venv/bin/python tools/rda_programmer_start.py --execute --write-test --unit 1403167417 \
  --journal firmware/live/2026-10-09-programmer-write-test-1
```

About 140 s. Recovery as before: physical RST, then the read-back against
`before-startup.bin`.

### Write test run 1: program and erase work, and the flash ends as it started

11:50:43 UTC, October 9 (12:50:43 Lisbon), run by the assistant after the user's
"yes, run it", build `c238911d…6c65`. Evidence:
`firmware/live/2026-10-09-programmer-write-test-1/`, with `operations.jsonl` and
ten 4 MiB dumps.

| Elapsed | Result |
| --- | --- |
| 1.22 s | `Coolsand Usb`; ROM handshake |
| 32.7 / 64.4 s | Two ROM reads identical, SHA-256 `47affe8bad088320fad795cd572bf658388f8058b92b4b7ea49ded1484223105` |
| 65.190 s | **READY (`0xf0`)**, 0.54 s after execute, with no other event |
| 74.9 / 84.5 s | Two reads through the programmer, identical to the pre-start read |
| 84.676 s | PING, PING, GET_FINALIZE_INFO: all DONE, mailbox as expected |
| 94.2 / 103.6 s | Two reads, identical to the pre-start read |
| 103.641 s | **PROGRAM `0x3e0000`, 4 KiB:** DONE after 9 ms, event `0xf1` |
| 113.098 s | Full read: the pre-start image plus the chunk, nothing else |
| 113.113 s | **PROGRAM `0x3ef000`, 4 KiB:** DONE after 8 ms, event `0xf0` |
| 122.528 s | Full read: the pre-start image plus both chunks, nothing else |
| 122.530 s | **ERASE `0x3e0000`:** DONE after 133 ms, event `0xf1` |
| 132.2 / 141.7 s | Two reads, identical to the pre-start read: 0 bytes differ |

Checked again from the saved dumps, apart from the tool:

- After the first program the image differs from the pre-start read only inside
  `0x3e0000`-`0x3e0fff`, which holds the first pattern; the other 60 KiB of the
  sector are blank. After the second, `0x3ef000`-`0x3effff` holds the second
  pattern, the 56 KiB between are blank, and everything outside the sector is
  unchanged.
- Both reads after the erase hash to the pre-start read's `47affe8b…3105`.
- The pre-start read is identical to the recovery read after the query run.

What this establishes on 417:

- Page program and 64 KiB block erase work through this programmer and the
  writer's `Programmer.command`, at the addresses asked for and nowhere else.
- The block erase covers the whole 64 KiB sector and stops at its ends.
- No block-protect bit covers `0x3e0000`.
- The host's waits are long enough: the erase took 133 ms.

Not established: writes below `0x3e0000` or in the 4 KiB sectors (the chip's
protection bits, if any are set, could cover other ranges), the 4 KiB sector
erase, END and the boot-magic write, a program across a whole sector, and the
writer's restore sequence as a whole. The flash status registers are still
unmeasured, and the writer's gates are unchanged.

Recovery, 11:54:01 UTC: the user pressed RST and the assistant ran
`rda_flash_readback.py` against the pre-start read. Evidence:
`firmware/live/2026-10-09-programmer-write-test-1-recovery/`. Vendor `RDA Usb`
was back, reset fields `0x00200000` (force bit cleared), two reads identical
(SHA-256 `5d158836…fc2d`), code and protected tail unchanged, and the test sector
blank. This time 4296 bytes differ, in three sectors of the vendor's store, and
they are the store moving to its next sector:

- `0x398000`, the sector the per-boot records were going into, was full: the
  record the previous boot put at `0xe00` took its seventh and last 512-byte
  slot. Two header bytes changed, bits only 1 to 0 (`00 b0` became `00 00`).
- `0x3a8000` was blank apart from the marker `0xcafebee0` and a counter. It now
  has the header `0xbabeface`, `00 b0`, and one record at `0x200` whose first 16
  bytes equal those of the record at `0x398e00`: this boot's record, in a new
  sector. Nothing in it needed an erase.
- `0x390000` held seven older records of another kind and was erased; its
  counter went `0x23` to `0x24`. The marker was not yet written when it was read.

The last read through the programmer, before RST, was identical to the pre-start
read, so all of this was written after RST by the vendor firmware. My reading is
that it would have happened at this boot with or without the test, since the
firmware booted from the same flash contents; that is an inference from the
sector being full, not a control. Full application, radio and GPS operation were
not exercised.
