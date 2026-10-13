> **Archived 26-10-11.** The current, reconciled account is [rom-flash-access.md](../knowledge/rom-flash-access.md). This note is kept as the dated record of the work; statements here may be superseded there.

# V24 flash restore: implementation contract and evidence gates

2026-10-09 Lisbon update: forced ROM access is now proven with double full-flash
reads. A separately authorized start-only run on original 417 verified the RAM
load and received ROM execution acknowledgement, but no programmer READY.
RST restored vendor USB, and matching double recovery dumps preserve all code
and protected bytes (533 runtime-data bytes changed across the run/reboot).
See [run report](26-10-09-programmer-start.md). No flash command was sent;
writer qualification gates below remain unchanged. Earlier status is historical.

2026-10-08 latest: the user explicitly requested implementation and qualification
of the host writer, superseding the earlier approval-before-coding requirement.
`tools/rda_flash.py` now implements the offline planner and a guarded spare writer;
see [operator instructions](26-10-08-flash-writer.md) and the
[source/binary audit](26-10-08-loader-audit.md#host-writer-audit).
26 offline tests pass. This is software validation, not hardware qualification.

The USB programmer is built and the original's ROM matches the SDK, but forced
ROM enumeration failed. Original `1403167417` recovered its vendor interface
after RST/reconnection and remains blocked from writer execution. The user
reported on 2026-10-08 that five spare units are on hand; none has been connected,
identified or dumped yet. There were no USB actions during writer implementation/audit.
The off-laptop backup requirement remains waived; spare-backed destructive
experiments and cold-recovery evidence remain pending. A good dump or locally
hashed qualification JSON does not prove recovery.

## Read-only boot-mode diagnostic

`tools/rda_boot_mode.py` prints its frame by default; `--read --output <new log>` makes
one attempt on exactly one vendor `1e04:0900` / `RDA Usb` interface. It refuses the
normal `1782:3d00` interface, does not change USB configuration, and does not retry.
Logs are exclusively created under `firmware/live/` and remain gitignored.

- Physical address: `0x01a000a0` (`sysCtrl + 0xa0`). The HAL decoder ORs the read
  address with `0x80000000`; the response generator uses its uncached alias,
  `0xa1a000a0`. Do not add the flash base `0x88000000` to a register address.
- Word-read command `0x02`: read bit clear, internal bit clear, access width 4 bytes.
  Frame: `ad 00 07 ff 02 a0 00 a0 01 03 ff`. Length counts bytes after flow ID,
  including the CRC. Word access has no block-size field.
- Expected response: `ad 00 06 ff 03 <4 bytes LE> <xor>`, exactly 10 bytes.
  Validate length, flow, request ID and checksum before interpreting the value.
- `BOOT_MODE = (Reset_Cause >> 16) & 0x3f`; `USB_MONITOR_DISABLE` is its bit 3
  (absolute bit 19). Report software boot bits 22–27 separately.
- A set disable bit supports the disabled-ROM-USB explanation. A clear bit only
  removes that explanation for this sampled boot; it does not prove ROM entry,
  board power continuity, or recovery after a failed flash.

The existing `rda_dump.read_block` always reads 1024 bytes. Never use it for this
hardware register. The read script has no register-write or reset command.

Live result on original `1403167417`, 2026-10-03 14:19 UTC: reply
`ad 00 06 ff 03 00 00 20 00 dc`, valid checksum. `Reset_Cause=0x00200000`,
`BOOT_MODE=0x20`, `SW_BOOT_MODE=0x00`, `USB_MONITOR_DISABLE=0`.
The single permitted register read is complete; do not repeat it on the original.

## Preconditions for live execution

1. Identify the spare physically and bind its identity to two identical 4 MiB reads
   and a SHA-256 manifest. Refuse the original's dump for the spare. USB VID/PID and
   the generic USB serial string are not unit identity.
2. Establish repeatable ROM-monitor access and continued board power on the spare.
   A vendor debug connection is insufficient. Do not automatically repeat the
   unsuccessful original-unit restart probe.
3. Obtain and inspect the compatible USB `usb_8955_flsh_spi32m_ramrun.lod`, record its
   provenance and hash, and validate all load addresses as RAM. Confirm its flash
   chip support, erase geometry, entry point, exported map and protocol version.
   The pinned build's RAM load, entry, ABI and configured geometry have now been
   checked offline. Physical chip support and board compatibility remain unresolved.
4. Review startup and finalization code for implicit flash writes before loading
   the programmer. Refuse any programmer whose effects cannot be bounded.

## Required behavior

- Default to a local plan showing target identity, source hash, changed sectors,
  erase footprints, program chunks and verify steps. Execution must be explicit.
- Hard-deny every erase/program/finalization footprint intersecting
  `[0x3fa000, 0x400000)` (RF calibration and factory data). Reject overflowing,
  aliased, unaligned or out-of-range addresses before transmission. The programmer's
  actual erase geometry determines the footprint, not just the requested offset.
  A 64 KiB erase at `0x3f0000` is forbidden because it crosses the protected range.
- No chip erase, factory write, generic memory-write CLI, or force override.
  RAM writes are limited internally to the validated loader, buffers and mailbox.
- Read and compare protected data against the unit's backup before proceeding;
  abort on a mismatch. Leave matching protected bytes in place during restore.
- Use `FPC_ERASE_SECTOR` (2), `FPC_PROGRAM` (1), completion/error polling and full
  byte readback. Validate the effective erase layout first. `FPC_CHECK_FCS` (5) is
  additional verification only after confirming its algorithm for this programmer.
- The SDK has 64 KiB buffers. Its ABI header warns of 16-bit size truncation,
  although the pinned C implementation passes an unsigned size to the HAL. Retain
  the conservative 4 KiB program limit. Commands alternate between two mailboxes
  only after `DONE`, with both slots checked by serialized pings.
- Check the loaded ABI rather than guessing addresses: SDK map has two 20-byte
  command descriptors, three buffer pointers, and protocol `FA01/FB05`. Write
  validated parameters before publishing a command. Bound waits; stop on timeout,
  disconnect or verification failure without blindly reissuing an erase/write.
- Preserve original bytes and an append-only operation journal locally before each
  destructive step. Recovery after an uncertain command starts with fresh readback.
- Program changed non-boot sectors first and the boot sector last. SDK `FPC_END` (4)
  may set boot magic: treat it as a flash write, audit its destinations and perform
  full readback before and after it. A plan with no changed sectors does no writes and does
  not qualify as proof of a functioning writer.
- Check the runtime layout descriptor (bank count, pointer and total capacity)
  as well as the bank table. Compare the HAL's post-startup JEDEC identity with
  independently reviewed chip evidence. Neither check makes unknown startup safe.
- Bind qualification to the exact unit, baseline, target, ROM and programmer;
  require reviewed evidence for ROM access, RAM/power, flash startup and the
  specific experiment. Keep journals and dumps in gitignored local storage.

## Proposed experiments, each requiring approval

1. On the backed-up spare, confirm `[0x3e0000, 0x3f0000)` is erased in its own image
   and establish that it is safe scratch space. Being blank in the original's dump
   is insufficient. Select the smallest independently erasable sector in that range.
2. Program a deterministic pattern, read back every byte, restore the exact original
   sector bytes, and verify again. Check protected data remains identical.
3. Restore the spare's own image with the protected tail excluded from all writes;
   verify the whole image before boot and normal behavior afterwards. Explain which
   sectors actually changed and were exercised; do not claim a skipped boot sector
   was tested. Runtime settings can change after boot, so compare them accordingly.
4. A blank-sector-0 fallback experiment is a separate destructive decision. Even a
   successful scratch-sector write does not prove cold recovery after boot corruption.
   Foreign firmware remains blocked until the recovery outcome is established.

## Source basis

Historical diagnostic source paths (the latest writer audit uses pinned commit
`b2b6287e8fa9a9f49b679a357b49beb1c31d821c` in the local build tree):

- [HAL USB decoder and response generator](https://github.com/cherryding1/RDA8955_W17.44_IDH/blob/master/soft/platform/chip/hal/src/hal_usb_monitor.c)
- [USB access command bits](https://github.com/cherryding1/RDA8955_W17.44_IDH/blob/master/soft/platform/chip/hal/src/halp_usb_monitor.h)
- [RDA8955 system registers](https://github.com/cherryding1/RDA8955_W17.44_IDH/blob/master/soft/platform/chip/regs/8955/include/sys_ctrl.h)
- [Boot mode bits](https://github.com/cherryding1/RDA8955_W17.44_IDH/blob/master/soft/platform/chip/boot/8955/src/bootp_mode.h)
- [Programmer ABI](https://github.com/cherryding1/RDA8955_W17.44_IDH/blob/master/soft/toolpool/flash_programmer/flash_prog_map.h)

These sources guide the protocol; the actual board and flash chip still require
validation. The latest continuation audited local pinned SDK sources and the
matching LOD/ELF without network or device access.
