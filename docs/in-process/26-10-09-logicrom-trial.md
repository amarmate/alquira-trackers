# Logicrom preparation for spare 412 — 2026-10-09

**Prepared and tested offline. No tracker USB access, reset, erase, program or
firmware start was performed during this preparation.** Hardware multi-block
recovery and Logicrom compatibility remain untested. Each writing run below
requires its own explicit go. Original unit `1403167417` remains blocked.

**Update, 14:53 UTC:** Runs A and B below have since been run on spare 412 and both
passed; see [Hardware rehearsal results](#hardware-rehearsal-results--2026-10-09).
Multi-block installation and recovery are now hardware-tested.

**Update, 15:48 UTC:** the core was then started once on 412. It enumerated on USB,
reset after about 13 s, and in that time wrote into flash up to its end, zeroing the
first 32 bytes of all six calibration/factory sectors. 412 has been restored exactly,
tail included. **Do not start this image again as it is.** See
[Live core trial and recovery](#live-core-trial-and-recovery--2026-10-09).

**Update, 16:17 UTC:** the cause is found, offline. The core's layout is V24's; the
damage is one wrong size in its first-boot `/nvm` format (`0x60000` for `0x6000`).
The image builder now corrects that word and the installer refuses the old image.
The corrected image has **not** been run on hardware. See
[Root cause of the tail damage](#root-cause-of-the-tail-damage--2026-10-09).

**Update, 16:45 UTC:** the corrected image was installed and started once on 412. The
read afterwards has the calibration/factory tail equal to 412's backup, byte for byte,
and every change inside `0x2f0000–0x3fa000`. The core still leaves USB about 10 s
after it appears, and why is not known. 412 is in the ROM with the core installed and
the boot word blank; it has **not** been restored yet. See
[Trial 3](#trial-3-corrected-core-first-boot--2026-10-09).

**Update, 17:20 UTC: 412 cannot be restored with the present tools.** After a second
start of the core, the restore stopped at its first erase: the flash chip reported the
erase done in 1 ms and nothing changed. Nothing was written; flash content, tail
included, is as it was before the attempt. 412 is in the ROM with the core installed
and the boot word blank. **Do not start the core on any other unit until this is
understood.** See
[The restore stopped](#the-restore-stopped-the-flash-ignores-erase--2026-10-09).

**Update, 19:11 UTC:** the refused erase was block protection (BP2–BP0) left by the
core's runs. One status write cleared it and 412 was restored; it booted its vendor
firmware at 18:45. Trial 4, the core with the charger-disconnected report ignored, was
then installed and started on 412: **the port still left after 9.9 s**, and the ROM
came back by itself five minutes later, as it had in trial 2. The tail is intact and
the status registers read `0x00`/`0x02`. 412 is in the programmer on USB with that core
installed and the boot word blank; it has not been restored. See
[Trial 4](#trial-4-the-port-still-leaves-at-99-s--2026-10-09).

**Update, 2026-10-10 10:46 UTC:** a second start of that install did the same: port
gone after 9.9 s, the ROM back by itself five minutes later, registers still
`0x00`/`0x02`. 412 has no SIM, and the core has a no-SIM reset; that is the candidate
for the five minutes, to be tested with a SIM. 412 is unchanged otherwise and not
restored. See
[Second start of the trial-4 install](#second-start-of-the-trial-4-install-the-timer-again-no-lock--2026-10-10).

**Update, 2026-10-10 11:05 UTC:** a third start with a SIM in the unit: the port left
after 9.9 s and the ROM still came back by itself, after 308 s. The SIM did not stop
the reset. 412 is in the programmer on USB with the SIM inside, registers
`0x00`/`0x02`, not restored. See
[Third start, with a SIM](#third-start-with-a-sim-the-reset-still-comes--2026-10-10).

**Update, 2026-10-10 14:04 UTC:** 412 is restored. All 4 MiB equal its vendor image
again (`af47612a…78b3`) and the boot word is written. After RST at 14:07 UTC it came
back on USB as the vendor firmware (`RDA Usb`, bcdDevice `0x3410`). See
[Restore of 412 after the SIM start](#restore-of-412-after-the-sim-start-passed--2026-10-10).

## Prepared image

Local artifacts are in `firmware/live/usb-programmer-build/logicrom/` (gitignored,
because the combined image contains 412's identifiers and calibration).

| Artifact | SHA-256 |
| --- | --- |
| `core_v0.5.1.lod` | `0499c0e051f166e899daf13503c8d2b07ba65c884de047f17bb8f8cd38d31df7` |
| `build/probe.raw.bin` | `d34ca6ec199063b13c63413cf3d10e71ece2462788d306d529da5110346fb668` |
| `v24-412-trial.bin` | `7b229494cfb3d1e0a4c9e8d9d2406328407a0577e635a7d16be80dc89b398135` |
| 412 backup used for preparation | `b0250296dda7f0e6fd6eed44a561de740dbf52b158008d2ad416d7541d34a2c4` |

The core was independently downloaded again from [Waybyte's published
v0.5.1 LOD](https://github.com/waybyte/logicrom_core/blob/master/2G_RDA8955/Logicrom_rda8955_core_v0.5.1.lod)
and compared byte for byte with the earlier archived copy. The LOD checksum is
`0x764da370`; its records cover exactly `0x000000–0x250000`, with no gaps or
overlaps. The first word is the programmer's blank placeholder. The image builder
replaces that placeholder with `0xd9ef0045` in the **disk target only**; the trial
installer deliberately never writes it to the tracker.

Ranges below are half-open (end excluded):

| Flash offsets | Preparation and installation behavior |
| --- | --- |
| `0x000000–0x250000` | Logicrom core |
| `0x250000–0x270000` | Probe application, padded to 128 KiB |
| `0x270000–0x2e0000` | Unused application partition, filled with `0xff` |
| `0x2e0000–0x3fa000` | Preserve existing bytes; the installer uses the fresh pre-start snapshot |
| `0x3fa000–0x400000` | Calibration/factory tail; exact match to 412's backup required; no write commands allowed |

The SDK linker script gives the app 576 KiB at `0x88250000` and RAM at
`0x82302000`. The compiled ELF's entry is `0x88250151` (MIPS16); raw load data ends
at `0x88268338`. The image builder uses Waybyte's packaging convention: 64 KiB
padding, APP1 header length, CRC32 with the CRC field initially zero. It rejects
bad headers, CRCs, lengths and changes outside the core/app partitions.

The LOD's `FACT_SETTINGS_BASE=0x3f4000` conflicts with the factory address used by
its code, `0x3fe000`; see the prior binary review in
[the pin map](../knowledge/pin-map.md#8-fit-with-logicrom). Neither address is overwritten
by installation. Do not interpret header metadata as permission to relocate or
erase factory data. The LOD sector map also differs from the actual programmer's
erase geometry; the installer uses the pinned, checked runtime geometry:
64 KiB below `0x3f0000`, 4 KiB above it.

Preserving these bytes during installation does not prove the closed core will
preserve them while running. If its execution changes the protected tail, the
recovery tool stops rather than overwrite identity/calibration. That case needs
investigation and a separately reviewed recovery procedure.

## Probe and reproducible build

Source: `firmware/logicrom/main.c`, build script: `firmware/logicrom/build.sh`.
The app calls `logicrom_init("/dev/ttyUSB0", ...)`, prints `V24-PROBE 1 ready`,
reports SIM/network/system/voltage events, and emits a heartbeat every ten
seconds. It does not configure board GPIOs, either UART, GPS, Wi-Fi, sensors,
sounder, reporting or FOTA. The linked SDK and closed core still initialize their
own services and may write settings. Application execution requires activation;
absence of the probe banner before activation does not alone mean core boot failed.

Inputs:

- [SDK](https://github.com/waybyte/logicromsdk/tree/72f60a27f45c292bc3b75994775f61949fc03da2), commit `72f60a27f45c292bc3b75994775f61949fc03da2`.
- [Official build/packaging code](https://github.com/waybyte/platform-logicrom/tree/44bad61ff8af68e79c3683d227da0774ef199f92/builder/framework/rda8955), platform commit `44bad61ff8af68e79c3683d227da0774ef199f92`.
- Existing Coolsand GCC 4.4.2 Linux compiler and local `rda-usb-builder:local` image.
- Waybyte `toolchain-gccmipselfrda8955` 4.4.2 archive, SHA-256
  `382f120180a5fc2d4f2d19247feec0cf60c2de13376b870dd69e78970730ac95`.
  Its registry package is labelled Windows; only the platform-independent MIPS
  `libc.a`, `libm.a` and `libgcc.a` archives were extracted. No Windows executable
  was run. The Linux compiler otherwise lacked the matching C library.

`build-provenance.json` records source/library/ELF hashes. The SDK include and
RDA8955 library directories, runtime archives, upstream packaging scripts and
download archive are retained beside the build. Compile on this Mac:

```sh
cp firmware/logicrom/main.c firmware/logicrom/build.sh firmware/live/usb-programmer-build/logicrom/
colima start rda-build
docker --context colima-rda-build run --rm --network none --platform linux/amd64 \
  -v "$PWD/firmware/live/usb-programmer-build/logicrom:/work/logicrom" \
  -v "$PWD/firmware/live/usb-programmer-build/csdtk:/work/csdtk:ro" \
  rda-usb-builder:local bash /work/logicrom/build.sh
.venv/bin/python tools/rda_logicrom_image.py \
  --core firmware/live/usb-programmer-build/logicrom/core_v0.5.1.lod \
  --app-raw firmware/live/usb-programmer-build/logicrom/build/probe.raw.bin \
  --output firmware/live/usb-programmer-build/logicrom/v24-412-trial-rebuilt.bin
```

Output paths must be new. The container has neither network nor USB access.

## Installer and full recovery

`tools/rda_programmer_start.py --trial IMAGE --trial-sha256 HASH`:

1. Validate the image hash, app format, unit backup and pinned programmer before
   USB access. Confirm live vendor boot, ROM and calibration/factory identity.
2. Enter ROM and save two equal full flash reads. The durable `before-startup.bin`
   and its journal hash are the recovery target, including current vendor settings.
3. Load/query the programmer and verify unchanged flash. Save the live trial target.
4. Erase/reprogram block 0 with its boot word blank, then check all flash. This
   happens **before any other code block changes**, so a partial installation
   cannot auto-boot a mixture of old and new code through a valid word.
5. Install the 46 changed 64 KiB blocks. Verify erase results, each programmed
   block and two full image reads. All mailbox packets are exactly allowlisted.
   No END command is allowed. Block 0 is written twice overall: once to establish
   the blank-word recovery state, then again with the new core.
6. Unless `--trial-stop` was specified, reset to a fresh ROM session, verify the
   entire blank-word image twice, then send monitor exit `0xfe` exactly once.
   The ROM source's exit path goes to flash entry `0x88000010`; this is not the
   programmer's END/finalize command. Sending exit does not prove firmware boot.

`--finish INSTALL_JOURNAL` now restores **every changed unprotected sector**.
It validates the saved target's full hash, journal unit, original vendor code and
protected tail before USB access. It enters a fresh ROM session, checks the ROM
hash and two equal full reads, and binds the live unit by its protected tail.
Multi-block recovery requires a blank boot word. The original block-0-only path
remains available for old blank-word journals. Already-restored images need no
write or programmer load.

After fresh programmer startup/query, recovery plans from actual flash, restores
64 KiB and/or 4 KiB sectors, restores block 0 last, checks all 4 MiB with the word
still blank, and only then sends END. Two complete post-restore reads must equal
the original pre-start image. No protected byte is rewritten. A failed recovery
can be retried only as a fresh separately approved run with a new journal, always
pointing `--finish` at the **original installation journal**, not a failed recovery.
There is no automatic retry or repair.

## Offline verification

129 unit tests passed (`cd tools && ../.venv/bin/python -m unittest`). Coverage
includes interrupted install and interrupted recovery, early erase/program loss,
wrong-unit protected data, damaged recovery images, a truncated final journal
event, valid-word refusal for multi-block recovery, corruption before start/END,
mixed 64 KiB/4 KiB geometry, original-unit refusal and exact ROM-exit authorization.

The exact prepared 4 MiB image was also installed and recovered through the real
`run()` function and real on-disk journals against the USB/flash simulator.
`simulation-result.json`, `simulation-install/` and `simulation-restore/` contain
that evidence. Those directories are **simulation evidence, not hardware results**.
The prepared offline CLI and `git diff --check` passed as well.

## Hardware rehearsal — prepared, not run

First prove multi-block recovery without executing the new core. Run A writes
the actual image and stops with its word blank. Run B, requiring a separate go,
restores the full vendor image. Only after both pass should a third separately
approved installation attempt start Logicrom.

Before each hardware run: check `pgrep -fl rda_`, confirm spare 412 on the cable,
and use new journal/log paths. Keep USB attached; do not press RST, unplug or use
the power button during a writing run. Journals must be on local disk.

Run A (approval requested separately; remove `--execute` for offline validation):

```sh
.venv/bin/python tools/rda_programmer_start.py --execute --unit 1403167412 \
  --trial firmware/live/usb-programmer-build/logicrom/v24-412-trial.bin \
  --trial-sha256 7b229494cfb3d1e0a4c9e8d9d2406328407a0577e635a7d16be80dc89b398135 \
  --trial-stop --journal firmware/live/2026-10-09-logicrom-412-rehearsal \
  > firmware/live/2026-10-09-logicrom-412-rehearsal.log 2>&1
```

Run B (separate go after reviewing A's actual result):

```sh
.venv/bin/python tools/rda_programmer_start.py --execute --unit 1403167412 \
  --finish firmware/live/2026-10-09-logicrom-412-rehearsal \
  --journal firmware/live/2026-10-09-logicrom-412-rehearsal-restore \
  > firmware/live/2026-10-09-logicrom-412-rehearsal-restore.log 2>&1
```

| Result/failure | Next action |
| --- | --- |
| Validation or ROM read fails before flash commands | Stop and inspect journal; no automatic write |
| A stops after erase/program | Keep USB attached; inspect durable pre-start image and journal; obtain separate go for B |
| A passes | New core is installed but not started; obtain separate go for B |
| B stops mid-write | Keep USB attached; inspect; fresh recovery run with new journal and separate go |
| Protected tail mismatch | Stop; do not override the identity/calibration check |
| B passes | User presses RST; confirm vendor `RDA Usb`, then read back code and protected tail |
| Later live core trial has no usable console | RST to blank-word ROM, inspect, then separately approved full recovery |

RST blank-word recovery has been demonstrated on 412 after the vendor/programmer
power setup. Recovery after total battery loss, and after Logicrom changes PMU
state, remains unproved. If neither RST nor cable replug restores ROM USB after a
core trial, recovery without opening the case is not established; the spare may
be lost under the no-opening constraint. A is deliberately stopped before the
Logicrom execution that introduces that additional uncertainty.

## Hardware rehearsal results — 2026-10-09

Both runs were executed on spare 412, each after its own explicit go, from a different
session than the one that prepared them. The commands were the two above, unchanged
except for a `caffeinate -i` prefix that keeps the Mac from idle sleep.

| Run | Journal | Finished (UTC) | Elapsed | Mailbox commands | Result |
| --- | --- | --- | --- | --- | --- |
| A, install and stop | `firmware/live/2026-10-09-logicrom-412-rehearsal/` | 14:48:37 | 198.7 s | 802: 3 query, 47 erase, 752 program, no END | Exit 0 |
| B, full restore | `firmware/live/2026-10-09-logicrom-412-rehearsal-restore/` | 14:53:10 | 177.8 s | 786: 3 query, 46 erase, 736 program, 1 END | Exit 0 |

Run A: 46 sectors verified, block 0 last. Both final full reads equal the live trial
target with word 0 blank, SHA-256
`58430bcfc4dbc0a564853509e21ece17402831833152bb49bf2a19d8bda5ed98`. Checked separately
from the saved reads: `0x000004–0x2e0000` equals the prepared image,
`0x2e0000–0x400000` equals this run's pre-start read, and the protected tail equals
412's backup. Pre-start image SHA-256
`5c71c411929bdc4c793efb27bcf5e8e0d31a0afdfe34fa3e3f849f2ae534ab9e`.

Run B: started from the programmer session that A left. The ROM port returned 9.3 s
after the debug reset, following the host port reset; earlier runs recorded 3–4 s.
46 sectors verified, block 0 last, END only after the full blank-word check. Both
post-restore full reads equal A's pre-start image exactly (`5c71c411…ab9e`), and word 0
is `0xd9ef0045` again.

Establishes: the installer writes the whole core/app image from the Mac with the boot
word withheld, and `--finish` restores all 46 changed sectors on hardware.

Does not establish: anything about Logicrom running (it was never started), recovery
from an interrupted run on hardware (simulated only), or recovery after power loss.

After the user's RST (reported shortly before 15:03 UTC): `RDA Usb` returned, and one
read at 15:03:12 UTC gave `Reset_Cause=0x00200000`. A two-pass dump through the vendor
firmware, `firmware/live/2026-10-09-logicrom-412-rehearsal-after-rst.flash.bin`
(SHA-256 `b4fb41c3e223d493741484749c3f2d0e5f490e1e1ce038d57f4168f14f0d5314`), has word 0
`0xd9ef0045`, and its code `0x000000–0x362000` and protected tail are identical to
412's backup. Against A's pre-start read, two 4 KiB sectors of the vendor's settings
store differ: `0x3ac000` and `0x3d9000`. The vendor firmware rewrites its store when it
runs; `0x3d9000` is not in the handoff's list of sectors seen changing so far.

## Live core trial and recovery — 2026-10-09

Run on spare 412 after the user's go. The session's own launch of the start was
refused by the permission classifier, so the user ran the prepared commands from
Terminal: `firmware/live/2026-10-09-logicrom-412-trial.run.sh` and
`firmware/live/2026-10-09-logicrom-412-recover.run.sh`. Times are UTC.

### Attempt 1: wrong unit on the cable, nothing sent

Journal `firmware/live/2026-10-09-logicrom-412-trial/`. Stopped at 0.58 s with
`Unit calibration/factory identity mismatch`, before the force bit, any reset or any
write. A read-only check then found the connected unit's tail equal to 417's backup:
the cable had been moved to 417 after 15:07. Neither unit was changed.

### Attempt 2: installed and started

Journal `firmware/live/2026-10-09-logicrom-412-trial-2/`, exit 0, 269.9 s. Pre-start
image SHA-256 `f77c52f9c9859a63042fc82a1d217fede3780a944f611afa8ae94963c803325f`.
46 sectors verified, 802 mailbox commands, none failed. The ROM port returned 3.1 s
after the debug reset; two full ROM reads equalled the blank-word target; the monitor
exit was sent once at 15:26:38.

What the Mac's kernel log (`IOUSBHostFamily`) recorded afterwards:

| UTC | Event |
| --- | --- |
| 15:26:39.56 | ROM device `1e04:0900` gone |
| 15:26:41.67 | New device `1782:4d11`, bcdDevice `3410`, name "Coolsand", 12 Mbps |
| 15:26:41.67 | "device functionality blocked by transport restrictions"; not registered for matching |
| 15:26:51.61 | That device gone, "hardware connection lost" |
| 15:31:54.65 | `1e04:0900` enumerates again (the user had replugged the cable) |
| 15:33:20.99 | `1e04:0900` gone, "hardware port disabled", during a ROM read |
| 15:33:27.27 | `1e04:0900` enumerates again, with nothing sent or touched |

The block is macOS's approval for a USB accessory it has not seen before. A blocked
device is hidden from libusb, so the read-only watcher
(`2026-10-09-logicrom-412-trial-2-after-start-usb.jsonl`) recorded zero devices for
its 120 s. The user reported no LEDs.

### State found in the ROM

Read-only checks, journals `…-412-trial-2-rom-check/` and `…-rom-check-2/`: ROM
handshake and ROM hash as expected; `Reset_Cause=0x00220000`, the installer's force
bit still set. Three full reads agree, SHA-256
`1c9fe7732063983e4efec340bbf0d83de2c44957c63ec402cbc0260d997a29aa`. The first check's
second pass ended in a USB I/O error at 15:33:20 (the "port disabled" row above); it
did not recur in the next 15 minutes.

Against the installed image:

- Word 0 still blank; core and app `0x000004–0x2e0000` unchanged.
- 149 4 KiB sectors changed, from `0x2f0000` to `0x3ff000`. `0x2f0000` onward holds
  a file system with the names `params`, `cfw_nv.bin` and `sms_dm_nv.bin`.
- Sectors up to the end of flash carry a 32-byte zeroed head, including all six
  protected sectors `0x3fa000–0x3ff000`. In the tail 157 bytes differ from 412's
  backup, all inside those heads; every other tail byte is intact.

Reading, not a result: the generic 0.5.1 core takes `0x2f0000–0x400000` for its file
system on this 4 MiB flash and does not keep V24's calibration (`0x3fa000`) and
factory (`0x3fe000`) sectors. The force bit still being set suggests the chip left
the core by a soft reset, not RST or a power-on.

**Disproved the same day:** the file system ends at `0x3f0000` and the core keeps
calibration and factory where V24 has them. See
[Root cause of the tail damage](#root-cause-of-the-tail-damage--2026-10-09).

Not established: why the core stopped after about 13 s (10 s after its USB
enumerated); whether the blocked, unconfigured USB device played a part; whether it
would have erased the marked sectors had it run on; whether RST alone would have
returned the ROM's USB (a cable replug did).

### Recovery

`--finish` refuses a tail that differs from the unit backup, as designed. A bounded
repair was added: `--finish JOURNAL --repair-tail`.

- `tail_repair_sectors()` accepts a protected sector only if each byte equals the
  unit backup, or is erased, or is zero inside the first 32 bytes. Anything else
  stops before the programmer is loaded. The live core/app must also equal the
  journal's `trial-target.bin`.
- `repair_tail()` erases and programs those sectors from the unit backup first, each
  verified, then requires a full read equal to the pre-repair image with the backup
  tail. The writer's protected limit is lifted only inside that step
  (`Programmer.limit`). The ordinary full restore and END follow in the same session.
- Three tests were written first and seen to fail: the repair end to end, its
  refusals (no flag, other damage, another unit), and resuming after an interrupted
  erase. 132 tests pass. The real `run()` on the simulated chip, loaded with the
  damaged image read from 412, returned the pre-start image exactly.

Hardware run, journal `firmware/live/2026-10-09-logicrom-412-recover/`, exit 0,
15:44:52–15:48:20, 208.0 s. ROM port back 3.1 s after the reset. 78 erases, 1008
programs, 1 END, none failed. Sixteen of the erases were 4 KiB sectors, the first on
hardware. The six tail sectors were restored first; the read after that step has the
backup tail and nothing else changed. 72 further sectors verified, END last. Both
final full reads equal the pre-start image (`f77c52f9…325f`); code
`0x000000–0x362000` and the protected tail equal 412's backup.

After RST (seen on USB at 15:49:25–15:49:32): `RDA Usb` returned, and one read at
15:49:41 gave `Reset_Cause=0x00200000`, the force bit cleared. A two-pass dump through
the vendor firmware, `firmware/live/2026-10-09-logicrom-412-recover-after-rst.flash.bin`
(SHA-256 `2bcf53ff054ee238a47051fde9e7fb4da972b391f8ff05d41db0835bcf21d28c`), has word 0
`0xd9ef0045`, and its code `0x000000–0x362000` and protected tail are identical to
412's backup. One 4 KiB sector differs from the pre-start read, `0x3ac000`, in the
vendor firmware's own settings store.

### What this means for a next attempt

- The core boots on this board far enough to bring up USB as `1782:4d11`.
- As shipped it is not safe here: it writes over the calibration and factory sectors.
  A next start needs a core or configuration that keeps `0x3fa000–0x400000`, or a
  confirmed answer from Waybyte on the flash layout it expects. The corrected image in
  [Root cause of the tail damage](#root-cause-of-the-tail-damage--2026-10-09) is that
  candidate; it is untested on hardware.
- Allow the accessory on the Mac before any start (System Settings → Privacy &
  Security → Allow accessories to connect), or its console cannot be opened.
- Take a tail backup check into every recovery: `--repair-tail` covers only this
  known damage.

## Boot, SIM/radio and activation checks after the rehearsal

**Superseded for now:** the start described here was done once and damaged the
calibration tail; see the section above before repeating any of it.

For the later trial, use the same image/hash with a new journal and **omit**
`--trial-stop`. This still requires its own go. Observe USB enumeration and find
the console before sending commands. Check core `devinfo`, SIM state, GSM/GPRS
registration and signal through available documented console commands. Record
actual outputs; the matching SoC, calibration tags and PA IDs do not prove radio
or power compatibility. Do not use reboot as a substitute for explicit trial
start: with the word blank, a reboot returns to ROM.

[Waybyte's activation instructions](https://docs.logicrom.com/en/stable/book/quick_start.html#activate-logicrom-core)
require an account, IMEI/module registration and a working data SIM; personal
licences are free. The documented commands are `apn=<name>`, `getlic`, and
`devinfo`; successful acquisition gives `+SER`, and after a restart the UID must
match. A post-activation restart in this trial needs another explicit blank-word
start procedure; permanent boot-word activation has **not** been added.

The [official supported-module list](https://docs.logicrom.com/en/stable/index.html#supported-modules)
names A9/A9G, M590 and MC65 for RDA8955, not ReachFar V24. **Module selection is
unresolved. Do not register V24 as A9G simply because the chip matches.** A question
ready for Waybyte (not sent): “Which free-device module type should be used for a
custom ReachFar V24 RDA8955 board with 4 MiB flash, RDA6625-family RF hardware and
external Goke/AT6558 GNSS, using your generic RDA8955 0.5.1 core? Is there a generic
RDA8955/custom-board registration option?”

GPS, sensor and server reporting development remains dependent on a working,
activated core; the existing pin map is the starting point for that stage.

## Resolution plan — offline review after recovery

**Step 2 below has since found the cause.** The overrun hypothesis was right; see
[Root cause of the tail damage](#root-cause-of-the-tail-damage--2026-10-09). Steps 4
and 5 still stand for the corrected image.

The immediate blocker is the core's runtime flash handling. The installer preserved
the tail and verified it before execution; changing the application's linker script
or the installer's protected limit cannot constrain writes made by the running core.

One distinction matters: the read-back proves writes reached `0x400000`, not that
the intended filesystem partition ends there. A sector discovery, invalidation or
formatting loop could have crossed an otherwise correct partition boundary. The
32-byte zeroed heads make that a useful hypothesis to investigate. Do not patch a
guessed end-address constant without tracing the code that actually writes them.

The local SDK headers expose filesystem operations and a higher-level storage
library, but no physical internal-flash boundary setting was found in this review.
`storagecfg_t.noformat_onfail` belongs to `storage_init()`; it is not evidence of a
way to stop the core's early flash initialization. The app linker script only maps
the application's flash and RAM. Editing LOD comment metadata likewise does not
by itself change the core's executable code.

Two additional clues, neither a diagnosis:

- Waybyte's [filesystem documentation](https://docs.logicrom.com/en/latest/book/api/storage/filesystem.html)
  lists 952 KB of internal filesystem space for RDA8955, but provides no physical
  boundaries there. This is not enough to derive its raw allocation or erase range.
- The pinned SDK's `include/lib.h` defines `RESET_REASON_SYSFORMAT` (reboot due to
  system memory format), alongside no-SIM and network-related reboot reasons.
  Formatting is therefore another candidate for the observed reset. Neither that
  enum nor the retained force bit establishes which reason occurred in this run.

Recommended sequence:

1. Request the exact runtime map and a supported configuration or rebuilt core
   from Waybyte. All filesystem discovery, formatting, allocation, garbage
   collection and erase/program operations must exclude `[0x3fa000, 0x400000)`.
   Confirm any additional core-reserved sectors below that range as well.
2. Continue offline analysis of the existing image: trace the VDS/DSM initialization
   and sector-status writers, their flash geometry and their upper bounds. Printable
   strings in this exact core include `vds_InitEntry` and `vds_SetSectStatus`; these
   give investigation leads, not callable addresses or a validated patch.
3. Review a candidate's actual executable behavior, not just its LOD header. If
   Waybyte cannot provide a supported fix, a binary patch remains an engineering
   project requiring control-flow and write-range validation before a hardware trial.
4. For a later approved trial, arrange host USB access and boot-log capture before
   starting. Retain the blank boot word and known recovery procedure. Verify the
   full protected tail after first boot, then after controlled restart and filesystem
   write/format/space-pressure exercises within the confirmed map. A quiet first
   boot alone does not establish that later garbage collection is bounded.
5. Establish stable core operation and unchanged calibration/factory bytes before
   proceeding with activation, radio qualification and the tracker application.

### Expanded question for Waybyte — draft, not sent

**Superseded** by the report at the end of
[Root cause of the tail damage](#root-cause-of-the-tail-damage--2026-10-09): the
layout questions here are answered by the core's own tables.

> We tested the published RDA8955 core v0.5.1 (LOD SHA-256
> `0499c0e051f166e899daf13503c8d2b07ba65c884de047f17bb8f8cd38d31df7`)
> on a ReachFar V24 with 4 MiB flash. Verified pre-execution reads preserved the
> original calibration/factory tail at `[0x3fa000, 0x400000)`. After one execution,
> 149 4 KiB sectors had changed, between `0x2f0000` and `0x3ff000`, with filesystem
> names including `params`, `cfw_nv.bin` and `sms_dm_nv.bin`. The first 32 bytes of
> each of the six calibration/factory sectors had been zeroed; the rest of the tail
> was unchanged. Core/app bytes were unchanged. The original firmware and tail
> have now been restored and verified.
>
> What are the intended runtime filesystem, VDS/DSM, NVRAM, calibration and factory
> ranges for this core? Can first-boot discovery or formatting scan/write beyond
> the filesystem's allocated range? Is there a supported pre-initialization setting,
> corrected release or custom build that excludes the entire tail from all such
> writes? Please also clarify `FACT_SETTINGS_BASE=0x3f4000` in the LOD metadata
> versus the `0x3fe000` factory address referenced in the executable, and the required
> erase geometry for this build.
>
> USB enumerated as `1782:4d11` about 3 s after start and disappeared about 10 s
> later; macOS blocked this newly seen accessory, so no console log was captured.
> A software reset is suspected but its cause is unconfirmed. Is a reboot expected
> after initial formatting, and how can we capture its reason before activation?
> The trial deliberately retained a blank boot word and the ROM force bit for
> recovery, and started through ROM monitor exit. Are there any initialization
> assumptions affected by that entry path?
>
> Finally, which registration/module type should a custom V24 board use, and is
> this board's RDA6625-family RF configuration supported?

## Root cause of the tail damage — 2026-10-09

**Found offline; no tracker was touched.** Inputs: the read taken after the core ran
(`firmware/live/2026-10-09-logicrom-412-trial-2-rom-check-2/rom-read.bin`), the image
as installed (`…-trial-2/trial-before-exit.bin`), and a disassembly of that image's
first `0x250000` bytes (Homebrew binutils,
`objdump -D -b binary -m mips:16 -EL --adjust-vma=0x88000000`). Addresses starting
`0x88` are flash offsets plus `0x88000000`.

### What the core wrote

The sectors the core took carry its own block-device headers, and each header states
the device's range. Words 3–5 of the 32-byte head are base, size and erase-block size:

| Device | Base | Size | Erase block | Range | Holds |
| --- | --- | --- | --- | --- | --- |
| A | `0x2f0000` | `0x100000` | `0x2000` | `0x2f0000–0x3f0000` | file system: `params`, `cfw_nv.bin`, `sms_dm_nv.bin` |
| B | `0x3f0000` | `0x6000` | `0x1000` | `0x3f0000–0x3f6000` | `/nvm` |

Above B, `0x3f7000–0x3fa000` hold a `VDS0`/FAT12 store. The core's flash table at
file offset `0x1c6400` gives user data `0x3f6000` + `0x4000`, calibration `0x3fa000`
+ `0x4000` and factory `0x3fe000` + `0x2000`, and its code reads `0x883fa000` and
`0x883fe000`. **That is V24's layout.** The file system does not run to the end of
flash; it ends at `0x3f0000`. The LOD's `FACT_SETTINGS_BASE=0x3F4000` is not what the
code uses.

A format marks every erase block of its device by zeroing the 32-byte head and leaves
the erase for later. That accounts for every zeroed head in the read:

- A has 128 blocks of 8 KiB. Five were since erased and are in use; the other 123
  have a zeroed head, at `0x2fa000`, `0x2fc000` … `0x3ee000`. All inside A.
- From `0x3f2000` to `0x3ff000` there are 14 at a 4 KiB step: sixteen blocks counted
  from `0x3f0000`, less the two B has since erased and used. B owns six.

### The defect

The `/nvm` set-up at `0x88232ccc`:

| Address | Call | Arguments (base, size, erase block, block) |
| --- | --- | --- |
| `0x88232ce6` | mount (`0x880ee194`) | `0x3f0000`, `0x6000`, `0x1000`, `0x200` |
| `0x88232cfa` | format (`0x880edc64`), only if the mount failed | `0x3f0000`, **`0x60000`**, `0x1000`, `0x200` |
| `0x88232d20` | mount again | `0x3f0000`, `0x6000`, `0x1000`, `0x200` |

The two mounts load the size as an immediate. The format loads it from the literal at
`0x88232d88`, which holds `0x00060000`. The format builds its own device record from
its arguments: block count = size / erase block = 96 (`0x880edb46`), and the range
check on each write (`0x880edbec`) uses that same size, so nothing stops it. Sixteen
of the 96 heads lie inside the 4 MiB flash, up to its last sector. The other 80 are
addressed past the end; the read-back shows no trace of them.

The format runs only when no valid `/nvm` is found, so on a first boot. The device
mounted afterwards is the six-block one, so the core would not have gone on to erase
the calibration sectors. Nothing in this path is specific to V24.

0.5.1 is still the newest RDA8955 core in
[Waybyte's repository](https://github.com/waybyte/logicrom_core/tree/master/2G_RDA8955)
(checked 2026-10-09; published 2025-02-11).

### Correction

- The word at file offset `0x232d88` becomes `0x00006000`: bytes `0x232d89` and
  `0x232d8a`. Only the format call loads it: one pc-relative load in the whole image,
  and no pointer to it.
- `tools/rda_logicrom_image.py`: `fix_nvm_format_size()` is applied to every build and
  refuses a core without the reviewed word. `validate_trial()` refuses an image that
  still has it, so the installer stops on the image started on 412 before any USB
  access.
- Four tests, written before the code; 136 pass.

| Artifact | SHA-256 |
| --- | --- |
| `v24-412-trial-nvmfix.bin` | `e7ee068aa9fd04230703ae7e2b124a27b62995a8b3e2adbd070db0ec3c55bb9e` |

It differs from `v24-412-trial.bin` in those two bytes only. The installer's offline
validation (no `--execute`) accepts it and stops on the old image. The install and
recovery simulation was not repeated for it.

### Not established

- **Nothing here has run on hardware.** If the core checks its own code, the changed
  word may stop it booting; with the boot word blank that ends in the ROM as before.
- Why the core reset after about 13 s. It has no "formatted, rebooting" message. Its
  reboot messages are for registration failure, GPRS time-outs, a parameter reset, a
  changed STK setting and a saved licence. The first boot's console is needed.
- Whether later operation writes the tail by design: licence storage is unknown and
  the core contains `factory_EraseFlash`. Keep the tail check after every run.
- Whether a first boot on Waybyte's supported modules loses the same 32 bytes.

### Next trial — needs its own go

As attempt 2, with the corrected image and its hash, a new journal, the USB accessory
allowed on the Mac beforehand, and a console capture ready. Expected in the read
afterwards: zeroed heads only inside `0x2f0000–0x3f6000`, and the tail
`0x3fa000–0x400000` equal to 412's backup, so `--finish` needs no `--repair-tail`.
Anything else in the tail means the correction is not the whole story.

**Prepared after the user's go at about 16:20 UTC; not yet run.** The core's USB is
RDA's CDC modem service (`UAT`, interface "Coolsand  modem", class 2/2/1 set up at
`0x88084cb4`), so macOS should give it a `/dev/cu.usbmodem*` node once the accessory
is allowed.

- `tools/logicrom_console.py` logs every new `/dev/cu.usbmodem*` node to JSON lines,
  can send one line, and records USB arrivals from the IORegistry. It uses no libusb,
  so nothing competes with macOS while it configures the device. Four tests against
  pseudo-terminals; 140 pass.
- `firmware/live/2026-10-09-logicrom-412-trial-3.run.sh`: asks for the accessory
  setting, installs and starts the corrected image (journal `…-412-trial-3`), logs the
  console for 3 minutes and sends `devinfo` once, 3 s after the port opens, then saves
  the kernel's USB log and says what to do next.
- `…-412-trial-3-rom-check.run.sh`: read-only ROM read, twice, with a verdict.
  Its comparison was checked on saved reads: trial 2's read gives FAIL with the ten
  zeroed heads, the untouched image gives INCONCLUSIVE, and trial 2's read with the
  tail and `0x3f6000` put back gives PASS.
- `…-412-trial-3-recover.run.sh`: `--finish` without `--repair-tail`. A writing run
  with its own go, after the check has been read.

### Trial 3: corrected core, first boot — 2026-10-09

Run by the user from Terminal with `…-412-trial-3.run.sh`. Times are UTC.

- **Install and start.** Journal `firmware/live/2026-10-09-logicrom-412-trial-3/`,
  exit 0, 272.3 s. Monitor exit sent at 16:37:13.
- **USB.** `1782:4d11` enumerated at 16:37:16.71 and was not blocked. macOS bound it
  as a CDC device: interface 0 "Coolsand  modem" (class 2/2/1), interface 1 CDC data,
  serial node `/dev/cu.usbmodem101`.
- **Console** (`…-412-trial-3-console.jsonl`). The port opened 3.06 s after the
  logger started. Nine bursts of 868 zero bytes followed, one a second. `devinfo`,
  sent at 6.09 s, came back at once as `devinfo\r\n\n`; no reply followed. Of 7823
  bytes received, those ten are the only non-zero ones.
- **It left the bus at 16:37:26.65**, 9.9 s after enumerating, after a transaction
  error on endpoint `0x82`. Trial 2 was also 9.9 s (15:26:41.67 to 15:26:51.61), so
  the blocked accessory then was not the cause.
- **Afterwards.** Nothing on the port. The user saw no LED. A cable replug shortly
  after 16:40:14 brought no device in four minutes, and five ROM checks found none.
  The user then pressed RST and `1e04:0900` enumerated at 16:44:50.95: RST alone
  returns the ROM after a core run.
- **Flash** (ROM check 6, `…-412-trial-3-rom-check-6/`, 16:45:03). ROM hash as
  expected; `Reset_Cause=0x00200000`, as after any RST. Two reads agree, SHA-256
  `290231e7f8b135aff37993533d03220f5f419f37cd386b5c03528fb1a726249d`. Word 0 blank;
  core and app unchanged; 143 sectors changed, all inside `0x2f0000–0x3fa000`; `/nvm`'s
  six sectors among them; no zeroed head from `0x3f6000` up; **the tail equals 412's
  backup, 0 bytes differing.**
- **Against trial 2's read.** The file system and `/nvm` are byte-identical. The only
  differences are `0x3ac000`, a vendor leftover that already differed before the
  start, and the first 32 bytes of `0x3f6000–0x3f9000`. Those now hold the core's own
  sector headers (`cefabeba…`); in trial 2 the faulty format had zeroed them too.

**The correction holds on a first boot.** The core wrote exactly what it wrote in
trial 2, less the damage.

Not established:

- Why the core leaves USB after 10 s, and whether it is still running afterwards.
  Both runs made the same writes with the same timing, so a first-boot restart by
  design is one candidate; a fault or a power-down are others. In trial 2 the ROM was
  back after a replug with the installer's force bit still set; this time a replug
  did nothing.
- What the zero bytes are, and why `devinfo` is echoed but not answered.
- Anything about a second boot, activation, SIM or radio.

Prepared, not run: `…-412-trial-3-restart.run.sh` starts the installed core once more
without installing anything. It sends the ROM handshake, two full reads that must
equal check 6's read, and one monitor exit, then logs the console as before. It
differs from the first start in three ways: the file system and `/nvm` already exist,
the ROM was entered by RST and not by the installer's debug reset, and the force bit
is clear.

### Second start of the same install — 2026-10-09

Run by the user with that script; journal `…-412-trial-3-restart-1/`. Nothing was
written by the host. Times are UTC.

- `Reset_Cause=0x00200000` before the start; two reads equal to check 6; exit sent.
- `1782:4d11` enumerated at 16:54:38.04 and left at 16:54:47.98: **9.9 s again**. So
  this is not something a first boot does. Three starts, three times 9.9 s.
- Console as before: ten one-second bursts of zero bytes (868 each, a little more or
  less at the ends), `devinfo` echoed and not answered.
- After RST, ROM check 7 (`…-412-trial-3-rom-check-7/`): two reads agree, SHA-256
  `40c2709e21a0c8433f62c2c30b09fab31b53551ffcab21fc68b35fe45434a5b2`. The tail still
  equals 412's backup. Fourteen 4 KiB sectors changed since check 6, all in
  `0x2f0000–0x300000`: the file system rewrote `cfw_nv.bin` and `sms_dm_nv.bin` and
  moved blocks. `/nvm` and user data did not change. **The correction also holds on
  a second boot, with ordinary file-system activity.**

### Why the port leaves: the core closes it — read from the code, not yet proven

- `EV_PM_BC_IND` (event 121, the modem layer's battery and charger report) is handled
  at `0x88184a78`, which logs `nBatteryChargeState`, `nBatteryChargeLevel`,
  `nBatteryState` and `nBatteryVoltage` and passes them on as event 44.
- Logicrom's system task (`0x882302f0`) handles event 44 by calling `0x8823c9c8` with
  the charge state. State 1 prints `USB: Charger connected` and opens USB
  (`0x880fcb34` with mode 2, which sets `1782:4d11`). State 0 prints
  `USB: Charger Disconnected` and closes it (`0x880fcd6c`). Other states do nothing.

So the port's life is the time between a "connected" and a "disconnected" report, and
the core would go on running without USB. That fits the fixed 9.9 s, the missing
restart and the unchanged flash. It does not explain why the board reports no charger
with the cable in; how V24 presents charging to the SoC is untraced
([pin map](../knowledge/pin-map.md)). Not shown: that the core is alive after the port
closes, and what the zero bytes are.

### Trial 4, prepared, not run: ignore the disconnected report

- `tools/rda_logicrom_image.py --keep-usb-open` changes one more byte: the handler's
  `beqz a0` at file offset `0x23c9d0` (`0x241a`) is pointed at the function's return
  (`0x2432`), so state 0 is ignored. An experiment, not a correction. Three tests;
  143 pass.
- Image `v24-412-trial-usbkeep.bin`, SHA-256
  `9802981441d3d165130718263ef74141cdf98d986678d110d14b2186f1b4556f`; it differs from
  `v24-412-trial-nvmfix.bin` in that byte only, and the installer's offline validation
  accepts it.
- Scripts `firmware/live/2026-10-09-logicrom-412-trial-4.run.sh`, `-rom-check.run.sh`
  and `-recover.run.sh`. The installer starts from the vendor firmware, so trial 3 has
  to be restored first (`…-412-trial-3-recover.run.sh`).
- Reading the outcome: a port that stays up confirms the mechanism and gives a
  console to work with. A port that still leaves at 9.9 s means something else takes
  it down, a power-down included.
- **On hold:** trial 4 cannot be installed while the flash ignores erase; see below.
- **Run at 18:56 UTC**, after the lock was cleared and 412 restored; see
  [Trial 4](#trial-4-the-port-still-leaves-at-99-s--2026-10-09).

### The restore stopped: the flash ignores erase — 2026-10-09

Times are UTC.

- **Restore attempt.** `…-412-trial-3-recover.run.sh`, journal
  `firmware/live/2026-10-09-logicrom-412-trial-3-recover/`, exit 1. Everything up to
  the plan passed: ROM port, two equal reads (`40c2709e…a5b2`, check 7's image),
  programmer loaded and queried, JEDEC id `0x1660c8` as before. The first erase, the
  64 KiB block at `0x010000`, was reported done after **0.001 s**; a 64 KiB erase on
  this chip takes 0.27 to 0.30 s (47 of them in the trial-3 install). The read-back
  was not erased and the tool stopped, with no retry and before any program command.
- **Afterwards.** The user pressed RST and ran the trial-4 script; its installer
  stopped at the first check, `Expected RDA Usb`, having sent nothing. ROM check 8
  (`…-412-trial-3-rom-check-8/`, 17:15, run from the session): two reads agree and
  equal check 7's image; the tail equals 412's backup. So the attempt and the RST
  changed nothing.
- **What it looks like.** The programmer audit of 2026-10-09 described this exact
  signature for block protection: "If the chip's block-protect bits covered this
  sector, the commands would report DONE and the read-back would show no change"
  ([programmer start](../done/26-10-09-programmer-start.md)). The chip answers its id,
  so it is taking commands. The programmer resets the chip at start-up
  (`hal_SpiFlashOpen`: `0x66`, `0x99`), which clears a suspended erase and volatile
  settings, and the erase is still ignored.
- **Not established.** That it is block protection: no tool here can read the chip's
  status registers. Which range is covered: only `0x010000` was tried. What set it:
  the restore after trial 2 erased both the tail and the low blocks, after one core
  run and no RST. Since then the core ran twice more and was stopped by RST both
  times. Whether the setting can be cleared: a status-register write normally clears
  it, unless the register itself has been locked.

What the present tools cannot do: read or write the flash status registers. The
pinned programmer writes them only at start-up, only when QE is clear, and writes
status 1 back unchanged. The next step is a read of status registers 1, 2 and 3, which
changes nothing; a clearing write is decided only on what that read shows. A wrong
value in those registers can lock a chip for good, so the write needs its own review.

State of 412: ROM on USB (`1e04:0900`), `Reset_Cause=0x00200000`, boot word blank,
core 0.5.1 with the `/nvm` correction installed, file system from two boots, tail
intact. The recovery target is `…-412-trial-3/before-startup.bin`. Unplugging it or
leaving it connected changes nothing in flash.

### Status reader: the build and the tool — 2026-10-09

The user approved a read-only reader on October 9, with a control run on 417 before
412. No device request was sent in building it. Each live run needs its own go.

**The chip's registers.** The GD25LQ32D datasheet
([PDF](https://cdn.components.ru/media/PDF/8115612.pdf)) gives `C8 60 16` for `9FH`,
the id both units report. The JEDEC id does not tell the C, D and E revisions apart,
so the revision on the board is not established. In that datasheet:

| Register | Opcode | Bits, high to low |
| --- | --- | --- |
| 2 (S15–S8) | `35H` | SUS1, CMP, LB3, LB2, LB1, SUS2, QE, SRP1 |
| 1 (S7–S0) | `05H` | SRP0, BP4, BP3, BP2, BP1, BP0, WEL, WIP |

There is no third register: `15H` is a QPI-only read of S1–S0, so the reader leaves
it out. BP0–BP4 with CMP choose the protected area. SRP1/SRP0 decide whether the
register itself can be written: `0,0` after a write-enable, `0,1` only while WP# is
high, `1,0` not until the next power cycle, `1,1` never again. A `01H` write with one
data byte clears CMP and QE.

**The build.** `firmware/live/usb-programmer-build/status/`, LOD
`artifacts/usb_8955_flsh_spi32m_ramrun_noclk_200ma_status.lod`, SHA-256
`b4231c54…000f`. It is the clean build's tree with one mailbox command added,
`FPC_READ_STATUS = 0x11` (the `.patch` beside the LOD is the whole difference). The
arm calls the SDK's `hal_SpiFlashReadStatusRegister()` and returns the result in the
command's size field, the two registers in the low half and their complement in the
high half. The host sends size 0, so a field that is not value-under-complement is
not this arm's answer. Built with the clean build's recipe plus `--network none`.

What the audit found, against the clean build:

- Of the 347 files in the two build trees, `flash_programmer.o` differs, and
  `target_config.o` by five bytes of its build-time string. Every archive member is
  otherwise identical.
- One symbol is new, `hal_SpiFlashReadStatusRegister` at `0x81c0350c`, with one
  caller, the new arm. No status-write function is linked in; the only status write
  is still the QE check inside `hal_SpiFlashOpen`.
- The compiler laid `main` out again, so its arms are not byte-identical. Its
  start-up, the 84 instructions from entry to the top of the command loop, is
  identical with its relocations; the first difference is at `main+0x16c`.
- Read from `review/status-elf.dis`: command 9 reaches `0x81c02b08` and 6 reaches
  `0x81c02350`, and both call only the ROM's `boot_HostUsbEvent`. Command `0x11`
  reaches `0x81c02bfc`: one call to `hal_SpiFlashReadStatusRegister`, a store to
  the size field, then the PING arm's DONE tail. That function calls the shared
  read routine with opcodes `0x05` and `0x35`, one byte each, inside a critical
  section. Across the image that routine is only ever given `0x9f`, `0x05` and `0x35`.

Not established: the other arms (program, erase, END) were not traced in this build.
The reader's allowlist never passes their packets, and the writer keeps the clean
build.

**The tool.** `tools/rda_programmer_start.py --read-status` loads this build with
its own table addresses (mailbox `0xa1c0ba78`), runs the query, sends the status
command twice, and requires equal readings, WIP and WEL clear, and two full flash
reads equal to the pre-start image. `--from-rom` starts on the ROM port for a unit
without a boot word and binds it by its calibration/factory tail alone. The
allowlist passes the query's six packets and the status command's four. 157 tests
pass, 14 of them new, including both entries through the real `run()` with a
journal on disk.

"Read-only" covers the new command, not the start-up: `hal_SpiFlashOpen` resets the
chip (`0x66`, `0x99`) and, if QE reads clear, writes status 1 back as read with QE
set. So QE clear in a reading means that write was refused.

Control on 417, from the vendor firmware, about 3 minutes:

```sh
.venv/bin/python tools/rda_programmer_start.py --execute --unit 1403167417 \
  --read-status --journal firmware/live/2026-10-09-status-417 \
  > firmware/live/2026-10-09-status-417.log 2>&1
```

Then 412, from the ROM port (it ends in the programmer, still without a boot word):

```sh
.venv/bin/python tools/rda_programmer_start.py --execute --unit 1403167412 \
  --read-status --from-rom --journal firmware/live/2026-10-09-status-412 \
  > firmware/live/2026-10-09-status-412.log 2>&1
```

Before each: `pgrep -fl rda_`, the right unit on the cable, no RST or unplug during
the run. 417 leaves the programmer by RST, back to the vendor firmware.

### Status control on 417: registers `0x00` and `0x02` — 2026-10-09

18:14:25 to 18:16:23 UTC, run from the session on the user's go, exit 0. Journal
`firmware/live/2026-10-09-status-417/`, log beside it.

| Elapsed | Result |
| --- | --- |
| 2.3 s | `Coolsand Usb` after the forced reset; ROM hash and two equal reads |
| 64.2 s | status build `b4231c54…000f` loaded, verified and started: `0xff000004`, `0xf0` |
| 82.4 s | tables at the build's own addresses, JEDEC `c8 60 16`; flash unchanged by the start |
| 100.4 s | query passed; both status commands DONE, each returning `0xfdff0200` |
| 118.5 s | two more full reads equal the pre-start image (`97d2dcf2…dcdc`) |

Register 1 is `0x00` and register 2 is `0x02`: QE set and nothing else. No
block-protect bit, CMP clear, SRP1/SRP0 `0,0`, no lock bit. That is what a V24 that
erases normally holds after a programmer start, and it is the first run of the
status command on hardware: both mailbox slots answered with value-under-complement.

The unit was left in the programmer session; RST returns it to the vendor firmware.

### Status read on 412: every block protected, register not locked — 2026-10-09

18:17:39 to 18:19:22 UTC, run from the session on the user's go, `--from-rom`,
exit 0. Journal `firmware/live/2026-10-09-status-412/`, log beside it.

| Elapsed | Result |
| --- | --- |
| 4.2 s | debug reset, port reset from the Mac, ROM port back; ROM hash and two equal reads |
| 66.2 s | tail equals 412's backup; status build loaded, verified and started |
| 84.4 s | query passed; both status commands DONE, each returning `0xfde3021c` |
| 102.6 s | two more full reads equal the pre-start image |

Register 1 is `0x1c` and register 2 is `0x02`: BP2, BP1, BP0 and QE. Against 417's
`0x00`, `0x02`, the difference is those three block-protect bits and nothing else.

- **What they protect.** The datasheet's Table 1 (CMP=0) gives BP2, BP1, BP0 =
  `1 1 1`, with BP4 and BP3 at any value, as blocks 0 to 63, `000000H–3FFFFFH`, all
  4 MiB. So the refused erase at `0x010000` is block protection, and every other
  block is covered too. This is now measured, not a reading of the symptom.
- **Whether it can be cleared.** SRP1/SRP0 are `0,0`, the default: the register
  takes a write after a write-enable. No lock bit is set and CMP is clear. QE is
  set, so WP# is a data pin and cannot hold the register.
- **Non-volatile.** The programmer resets the chip (`0x66`, `0x99`) before this
  read, which returns volatile settings to the stored ones, and the bits are still
  there.
- **Start-up wrote nothing.** QE read set, so `hal_SpiFlashOpen` skipped its
  status write. This run says nothing yet about whether the chip accepts one.

The flash is `40c2709e…a5b2` before and after, the image of ROM check 8, with the
tail equal to 412's backup. 412 was left in the programmer session, still without a
boot word.

Not established: what in the core sets the bits, and when. The restore after trial
2 erased normally after one core run; this state followed two more runs, each
stopped by RST. Clearing them needs a status-register write, `01H 00H 02H` after a
write-enable, which nothing here can send yet and which needs the user's go on the
exact value.

### Clearing write: the unlock build and the tool — 2026-10-09

The user approved the value on October 9: register 1 = `0x00`, register 2 = `0x02`,
what 417 holds. No device request was sent in building this. The run needs its own go.

**What the chip is sent.** `06H`; `01H 00H 02H`; status polls (`05H`) until WIP
clears, 5 ms typical and 35 ms at most; `04H`. The write is the non-volatile one:
the volatile form would leave the stored bits to return at the next power-up. Both
data bytes are sent, because a one-byte `01H` clears QE and CMP on this chip.

**The build.** `firmware/live/usb-programmer-build/unlock/`, LOD
`artifacts/usb_8955_flsh_spi32m_ramrun_noclk_200ma_unlock.lod`, SHA-256
`ca324886…944f`. It is the status build's tree with one more command,
`FPC_CLEAR_PROTECTION = 0x12`. The arm reads the registers; unless they are exactly
`0x021c` it stores ERROR, sends `0xe0` + slot and writes nothing; otherwise it calls
`hal_SpiFlashWriteStatusRegister(0x0200, 0xffff)` and answers like the status
command, with the registers as read back. The mask is the whole register, so the
value written does not depend on the second read inside that function.

What the audit found, against the status build that ran on both units:

- Of the 347 build files, `flash_programmer.o` differs, and `target_config.o` by its
  build-time string. Every archive member is otherwise identical.
- Two symbols are new: `hal_SpiFlashWriteStatusRegister` (`0x81c035e8`, one caller,
  the new arm at `0x81c02bb8`) and `hal_SpiFlashWaitWipDoneLocked` (`0x81c0350c`,
  one caller, that function).
- The arm at `0x81c02b80`, read from `review/unlock-elf.dis`: the status read; a
  compare with `0x021c`; on a mismatch ERROR and the event; on a match
  `a0 = 0x0200`, `a1 = 0xffff` and the call, then it falls into the status command's
  arm for the read-back and DONE.
- `hal_SpiFlashWriteStatusRegister`: both callbacks are null and skipped; write-enable
  (`0x9f` id check, then `0x06`); `hal_SpiSendCmdNoRx(0x01, {low, high}, 2)`; the WIP
  wait; `0x04`. Opcode with data bytes through this routine is how every erase so
  far was sent.
- `main` is laid out again, and this time its start-up is not instruction-identical:
  a stack offset, the order in which two table addresses are loaded, and the slot
  index kept in a register. Its 26 calls, their order and their constants are the
  same. The dispatch was traced by executing its compare chain from the encodings:
  6, 9, `0x11` and `0x12` reach their own arms, and `0x13` the default.

Not run on any unit before: `hal_SpiFlashWriteStatusRegister` and its WIP wait. On
both units QE was already set, so the start-up's own status write never ran either.
The wait executes `break 1` if two consecutive status reads disagree, as the erase
path's wait does; the programmer would then stop answering and the tool time out.

**The tool.** `--clear-protection`, refused for 417, always from the ROM port with
the unit bound by its tail. After the query: the registers twice, which must be
`0x1c`/`0x02`, or no write; the command once; the registers twice, which must be
`0x00`/`0x02`; two full flash reads equal to the pre-start image. The command is
never sent twice. 166 tests pass, 9 of them for this mode.

```sh
.venv/bin/python tools/rda_programmer_start.py --execute --unit 1403167412 \
  --clear-protection --journal firmware/live/2026-10-09-unlock-412 \
  > firmware/live/2026-10-09-unlock-412.log 2>&1
```

| Result | Next action |
| --- | --- |
| Stops before the command (registers not `0x1c`/`0x02`, tail mismatch, start-up) | Nothing was written; read the journal |
| Registers `0x00`/`0x02`, flash unchanged | Separate go for the restore below |
| Command times out or errors | No retry. RST, then `--read-status --from-rom` shows what the registers hold |
| Registers anything else afterwards | Stop. The reading is in the journal; decide from it |

The restore afterwards, a writing run with its own go, with the clean build as before:

```sh
caffeinate -i .venv/bin/python tools/rda_programmer_start.py --execute --unit 1403167412 \
  --finish firmware/live/2026-10-09-logicrom-412-trial-3 \
  --journal firmware/live/2026-10-09-logicrom-412-trial-3-recover-2 \
  > firmware/live/2026-10-09-logicrom-412-trial-3-recover-2.log 2>&1
```

### Clearing write on 412: registers now `0x00` and `0x02` — 2026-10-09

18:37:24 to 18:39:07 UTC, run from the session on the user's go, exit 0. Journal
`firmware/live/2026-10-09-unlock-412/`, log beside it.

| Elapsed | Result |
| --- | --- |
| 4.2 s | ROM port back after the reset; ROM hash, two equal reads, tail equals 412's backup |
| 66.3 s | unlock build `ca324886…944f` loaded, verified and started; tables and JEDEC as pinned |
| 84.5 s | query passed; registers read twice: `0xfde3021c`, `0xfde3021c` |
| 84.499 s | clear command DONE 3 ms after it was sent; the arm's read-back `0xfdff0200` |
| 84.502 s | registers read twice more: `0xfdff0200`, `0xfdff0200` |
| 102.7 s | two full reads equal the pre-start image, `40c2709e…a5b2` |

One status write was sent and the chip took it: register 1 went from `0x1c` to
`0x00`, register 2 stayed `0x02`. That is 417's reading. It is also the first run
of the SDK's status-write path on a V24, and its WIP wait returned normally.

Not established: that the cleared bits are the stored ones. All four readings after
the write are from the same session, with no chip reset or power cycle in between.
The next programmer start resets the chip before anything else, so the restore's
first erase decides it: a block erase that takes its 0.28 s and reads back blank.

412 was left in the unlock programmer's session, still without a boot word, with the
Logicrom core installed.

### Restore of 412 after the clearing write: passed — 2026-10-09

18:40:26 to 18:43:36 UTC, run from the session on the user's go, exit 0. Journal
`firmware/live/2026-10-09-logicrom-412-trial-3-recover-2/`, log and `.exit` beside it.
The command is the one that stopped at its first erase at 17:10, with a new journal.

| Elapsed | Result |
| --- | --- |
| 4.2 s | ROM port back after the reset; ROM hash and two equal reads |
| 65.8 s | clean build `c238911d…6c65` loaded, verified and started; query passed |
| 93.6 s | plan: 72 sectors, boot word last |
| 94.0 s | first erase, the 64 KiB block at `0x010000`: 0.282 s, read back blank |
| 172.2 s | 72 sectors erased, programmed and verified (1002 program commands); END |
| 190.3 s | two full reads equal the recovery target, `2bcf53ff…d28c` |

The 62 block erases took 0.08 to 0.29 s and the ten 4 KiB erases 0.05 to 0.15 s;
the refused one at 17:10 had returned in 0.001 s. The clean build resets the chip at
start-up, so the bits cleared at 18:38 are the stored ones. 412 holds its pre-trial vendor image
again, boot word included, with the tail equal to its backup.

**After RST.** The user pressed RST at about 18:44 UTC. At 18:45:09 the unit was on
USB as `RDA Usb` with `Reset_Cause=0x00200000`: the vendor firmware booted. A
read-only readback through it (`…-recover-2-after-rst/`, 18:45:21 to 18:51:08, exit
0) took two full reads that agree with each other. Code below `0x362000` and the
calibration/factory tail equal the recovery target. One 4 KiB sector differs,
`0x3ac000`, by 528 bytes: the vendor firmware's own storage, written after boot, as
after earlier restores. That it could write there is the vendor firmware itself
confirming the protection is gone.

412 is a working V24 on its vendor firmware again.

What this settles and what it does not:

- The refused erase was block protection (BP2–BP0), set by something in the Logicrom
  core's runs and stored in the chip. One two-byte status write clears it.
- A unit that has run the core should have its registers read before a restore:
  `--read-status --from-rom`, then `--clear-protection` if they read `0x1c`/`0x02`.
  The clear command refuses any other value, so a different lock state needs a
  look before anything is written.
- Still not established: what in the core sets the bits and when. The restore
  after trial 2 needed no clearing.

### Trial 4: the port still leaves at 9.9 s — 2026-10-09

Run from the session on the user's go, with `…-412-trial-4.run.sh`. Its journal is
`…-412-trial-4-2`: the name without `-2` was taken by the attempt of 17:12 UTC, which
stopped at `Expected RDA Usb` before sending anything. The three trial-4 scripts were
changed to that name. Times are UTC.

- **Install and start.** Journal `firmware/live/2026-10-09-logicrom-412-trial-4-2/`,
  exit 0, 18:56:40 to 19:01:02, 261.5 s. Pre-start image SHA-256
  `af47612a1ccd73b8c5190adfb45f83a3256423f9d943e6da0324b6341e0978b3`; against trial 3's
  pre-start image only `0x3ac000` differs. 46 sectors verified, 802 mailbox commands,
  none failed. Both ROM reads before the exit equal the blank-word target, SHA-256
  `42cc03d37a0d2671de14defef2452f84f41669efc8c8193ec5fc645ec57d0a12`, and carry both
  changes: `0x00006000` at `0x232d88` and `0x2432` at `0x23c9d0`. Monitor exit sent
  at 19:01:02.
- **USB.** `1782:4d11` enumerated at 19:01:05.45, not blocked, bound as CDC, serial
  node `/dev/cu.usbmodem1101`. It left at 19:01:15.38 after a transaction error on
  endpoint `0x82`: **9.9 s, as in the three starts before.**
- **Console** (`…-412-trial-4-2-console.jsonl`). The port opened 3.33 s after the
  logger started. Nine one-second bursts of zero bytes followed, about 893 each (868 in
  trial 3). `devinfo`, sent at 6.55 s, came back as `devinfo\r\n\n` and was not
  answered. Of 8048 bytes received, those ten are the only non-zero ones.
- **Afterwards.** At 19:04:10 there was no tracker on USB and no serial node. At
  19:06:17.25 the ROM (`1e04:0900`) enumerated again, before the session had asked
  for RST.
- **ROM check 1** (`…-412-trial-4-2-rom-check-1/`, read-only). ROM hash as expected;
  `Reset_Cause=0x00220000`, the installer's force bit still set, so the return was
  not an RST. Two reads agree, SHA-256
  `901e73860ea03019186a0565cd8940336128055f2a00d2c41ddceb50e6734122`. Word 0 blank;
  core and app unchanged; 143 sectors changed, all inside `0x2f0000–0x3fa000`; no
  zeroed head from `0x3f6000` up; the tail equals 412's backup, 0 bytes differing.
- **Status registers** (`firmware/live/2026-10-09-status-412-2/`,
  `--read-status --from-rom`, 19:08:52 to 19:10:35, exit 0). Both status commands
  DONE: register 1 is `0x00` and register 2 is `0x02`, QE only. **No block protection
  after this run.** The flash is `901e7386…4122` before and after.

**Ignoring the disconnected report did not keep the port.** The handler at
`0x8823c9c8` is therefore not what takes it down, or not the only thing that does.

**The ROM came back on a timer, as in trial 2.**

| Run | Core on USB | Port gone | ROM back | After the port left | `Reset_Cause` |
| --- | --- | --- | --- | --- | --- |
| Trial 2 | 15:26:41.67 | 15:26:51.61 | 15:31:54.65 | 303.0 s | `0x00220000` |
| Trial 4 | 19:01:05.45 | 19:01:15.38 | 19:06:17.25 | 301.9 s | `0x00220000` |

Trial 2's return was put down to a cable replug. Two returns 1.2 s apart in their
timing, both with the force bit still set, point at the core instead: it goes on
running after it leaves USB and resets itself about five minutes later, and with no
boot word that reset ends in the ROM. So the port leaving at 9.9 s is not a
power-down. Trial 3 does not test this: its cable was replugged about three minutes after the
start, and no device came in the four minutes after that.

On the lock: the registers were `0x00`/`0x02` before this run and are after it. A
first boot that ends in the core's own reset does not set the protection. The lock
found at 17:10 followed a first boot and a second boot, each ended by RST.

The user confirmed afterwards that nothing was touched before 19:06:17, and that 412
has no SIM.

**A candidate for the five-minute reset, read from the code, not proven.** The core's
network state machine is at `0x882323d0`, run from a timer callback at `0x88232968`
that re-arms itself with the argument 100. Its state 1 (`0x88232444`) counts its
passes in `0x82300814`; at 60 it prints `NW: No SIM, reset` (string at `0x88242bf0`)
and calls the reset function at `0x88232e08`. In that state a pass comes every 20
timer calls. Not worked out: the timer's unit, so whether those 60 passes are the
five minutes seen, and when the state is entered. A SIM in the unit would test it.

On the port: the USB close at `0x880fcd6c` has three direct callers in a MIPS16
decode of the core, the handler trial 4 patched and two in a boot-time routine at
`0x8808aff4–0x8808b070`, and no pointer to it. Calls from 32-bit code would not show
in that decode. The function compares its argument with a stored mode before doing
anything, so it may be a mode switch rather than a plain close.

Not established: what ends the port at 9.9 s; that the five-minute reset is the
no-SIM one; what sets the block protection.

State of 412: on USB in the status programmer's session, core 0.5.1 with both changes
installed, boot word blank, registers `0x00`/`0x02`, not restored. RST returns it to
the ROM. The recovery target is `…-412-trial-4-2/before-startup.bin`; the restore is
`…-412-trial-4-recover.run.sh`, a writing run with its own go.

Prepared on the user's go: `…-412-trial-4-restart.run.sh` waits for RST, reads the
flash twice against ROM check 1's read, starts the installed core once more and logs
USB for seven minutes; a status read follows. It asks whether the ROM returns on the
timer after a second boot too, and whether a second boot sets the protection. It
waited from 19:14 to 20:25 UTC, no RST came, and nothing was sent.

### Second start of the trial-4 install: the timer again, no lock — 2026-10-10

Run from the session with that script (`--in-rom`), after the user's RST at 10:33:11
UTC on 2026-10-10. Journal `firmware/live/2026-10-09-logicrom-412-trial-4-2-restart-1/`;
the names keep the trial's date. Nothing was written by the host. Times are UTC.

- **Start.** `Reset_Cause=0x00200000`; two reads equal ROM check 1's
  (`901e7386…4122`); exit sent at 10:35:06.
- **USB.** `1782:4d11` enumerated at 10:35:08.77 and left at 10:35:18.71: 9.9 s, the
  fifth time. Console as before: zero bytes, `devinfo` echoed and not answered.
- **The ROM came back by itself at 10:40:15.36**, 296.7 s after the port left, with
  no RST asked for or reported. After the two first boots it took 303.0 and 301.9 s.
- **ROM check 2** (`…-412-trial-4-2-rom-check-2/`). `Reset_Cause=0x00200000`; the
  force bit was already clear, so here it does not tell the core's reset from an RST.
  Two reads agree, SHA-256
  `b738ea1a51a7f06cf4d31d0bcac22ccb84723ec2a23a0d4ebce29901b412a5e0`. Fourteen 4 KiB
  sectors changed since check 1, all in `0x2f0000–0x300000`, as in trial 3's second
  boot. The tail equals 412's backup.
- **Status registers** (`firmware/live/2026-10-10-status-412/`, 10:43:34 to 10:45:17,
  exit 0): `0x00` and `0x02`. **No block protection after a second boot either.**

What this settles: the five-minute reset does not depend on a first boot or on the
force bit. And two runs that ended in the core's own reset left the registers clear,
while the lock of 2026-10-09 followed two starts that were each ended by RST. An RST
while the core runs is the candidate left for what leaves the bits set; untested.

State of 412: on USB in the status programmer's session, flash `b738ea1a…a5e0`, core
installed, boot word blank, registers `0x00`/`0x02`, not restored.

Next, needing its own go: the same start with a SIM in the unit (no PIN), left for
seven minutes. No return of the ROM would confirm the no-SIM reset; the RST that then
ends the run, followed by a status read, tests the lock candidate.

### Third start, with a SIM: the reset still comes — 2026-10-10

The user put a SIM into 412 and pressed RST at 10:49:01 UTC; that was the go. Same
script, now logging for ten minutes; journal `…-412-trial-4-2-restart-2/`. Nothing was
written by the host. Times are UTC.

- **Start.** `Reset_Cause=0x00200000`; two reads equal ROM check 2's
  (`b738ea1a…a5e0`); exit sent at 10:50:08.
- **USB.** `1782:4d11` enumerated at 10:50:09.66 and left at 10:50:19.56: 9.9 s, the
  sixth time. Console as before.
- **The ROM came back by itself at 10:55:27.59**, 308.0 s after the port left.
- **RAM** (`firmware/live/2026-10-10-logicrom-412-ram-peek.py`, journal
  `…-412-ram-peek-1/`, read-only, before anything else ran). The pages at
  `0x82300000` and `0x820a4000` read `ff 11 55 aa` repeated. The core's variables
  cannot be read from the ROM after its reset.
- **ROM check 3** (`…-412-trial-4-2-rom-check-3/`). Two reads agree, SHA-256
  `2d7d9f49ba0249565bfa02581d08aa85f68bf96b3d76d707e6357e0c27d6f773`. Three sectors
  changed since check 2 (`0x2fc000`, `0x2fe000`, `0x2ff000`), 2857 bytes, with no new
  text and nothing shaped like an IMSI. The tail equals 412's backup.
- **Status registers** (`firmware/live/2026-10-10-status-412-2/`, exit 0, 11:04:27):
  `0x00` and `0x02`.

| Start | SIM | ROM back after the port left |
| --- | --- | --- |
| Trial 2, first boot | no | 303.0 s |
| Trial 4, first boot | no | 301.9 s |
| Trial 4 install, second boot | no | 296.7 s |
| Trial 4 install, third boot | yes | 308.0 s |

**A SIM in the unit did not stop the reset.** Two readings are open: the core does
not see the SIM on this board, or the reset is not the no-SIM one (the core also has
`NW: Reg. fail, rebooting`). The 308 s is outside the 297 to 303 s of the three runs
without a SIM, but one run is not enough to say the path changed. Not checked: that
the SIM works elsewhere, and that it registers on 2G.

State of 412: on USB in the status programmer's session, SIM inside, flash
`2d7d9f49…f773`, core installed, boot word blank, registers `0x00`/`0x02`, not
restored. The lock candidate (an RST during a run) was not tested: no run needed one.

### Restore of 412 after the SIM start: passed — 2026-10-10

The user gave the go for the restore on 2026-10-10 and stated that the SIM works and
has 2G service. That is the user's statement, not something measured here. It weakens
the reading "the SIM is at fault" for the third start; it does not decide between
"the core does not see the SIM on this board" and "the reset is another one".

Before the run:

- The registers read `0x00`/`0x02` at 11:04 UTC
  (`firmware/live/2026-10-10-status-412-2`).
- The kernel's USB log shows no arrival or departure of the tracker between that
  read's last reopen (11:02:48 UTC) and the restore, so nothing ran on 412 in between.
- The restore target `…-412-trial-4-2/before-startup.bin` hashed `af47612a…78b3`.

Run: `firmware/live/2026-10-09-logicrom-412-trial-4-recover.run.sh`, journal
`firmware/live/2026-10-09-logicrom-412-trial-4-2-recover`, 14:00 to 14:04 UTC
(192 s), exit 0. It carried no `--repair-tail`.

- 72 changed sectors were erased, written and verified one by one.
- The full read afterwards hashed `af47612a…78b3`: every byte equals what trial 4 read
  before its start, which is 412's vendor image. The journal says
  `full_image_restored`, `flash_identical_to_pre_start: true`.
- The boot word was written (`boot_word_withheld: false`).

Boot check, read from the Mac only (kernel USB log and IORegistry, nothing sent to
the tracker): the user pressed RST. The programmer's entry (`1e04:0900`, bcdDevice
`0x948c`) left at 14:07:23 UTC and the unit enumerated again at 14:07:30 UTC as
`1e04:0900` with bcdDevice `0x3410` and interface `RDA Usb`, which is the vendor
firmware. So 412 boots its vendor firmware again. The SIM was inside for this boot.
Not checked: whether the vendor firmware registered on the network with it, and the
flash was not read back after the boot.

### Report for Waybyte — draft, not sent

> RDA8955 core v0.5.1 (LOD SHA-256
> `0499c0e051f166e899daf13503c8d2b07ba65c884de047f17bb8f8cd38d31df7`): on a first
> boot the `/nvm` block device is formatted with size `0x60000` but mounted with
> `0x6000`. In the function at `0x88232ccc` the mount at `0x88232ce6` uses
> `(0x3f0000, 0x6000, 0x1000, 0x200)`; when it fails, the format at `0x88232cfa` uses
> `(0x3f0000, 0x60000, 0x1000, 0x200)`, the size coming from the literal at
> `0x88232d88`. The format zeroes the 32-byte head of 96 erase blocks, not 6. On a
> 4 MiB flash that is every 4 KiB sector from `0x3f0000` to the end, including user
> data at `0x3f6000` and the calibration and factory sectors at `0x3fa000–0x400000`.
>
> Seen on a ReachFar V24 (RDA8955, 4 MiB flash) after one first boot: the first 32
> bytes of all six sectors `0x3fa000–0x3ff000` were zero, the rest of each unchanged.
> With that literal set to `0x6000`, the same first boot left all six sectors intact.
>
> 1. Can you confirm this and publish a corrected core?
> 2. Does a first boot on A9/A9G zero the same calibration bytes?
> 3. In both runs the core enumerated as `1782:4d11` (CDC modem) and left USB 9.9 s
>    later. In the run we could read, the port sent only zero bytes, 868 a second,
>    and echoed `devinfo` without answering it. Is that expected on a first boot or
>    without a licence, and what makes the core leave USB?
> 4. Does the core write calibration or factory sectors in normal use or on
>    activation?
> 5. Which registration/module type should a custom RDA8955 board use, and is an
>    RDA6625-family RF front end supported?
