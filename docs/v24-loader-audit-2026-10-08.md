# V24 RAM programmer audit — 2026-10-08

Update, 01:04 Lisbon on 2026-10-09: the cause of the missing READY below is found
and a diagnostic build starts on 417. The stock programmer calls
`hal_SwRequestClk` without the clock framework ever being initialised, so the
pinned LOD cannot reach READY as built. With that one call removed the
programmer reached READY, reported JEDEC `c8 60 16`, and two full flash reads
through it matched the pre-start read. The entry point is `boot_Sector`, not the
loader, so the start-up section further down is incomplete. Details, evidence
and what is still open are in
[the run report](v24-programmer-start-2026-10-09.md). Flash writing is still
not qualified. The paragraph below predates this.

Latest result, 2026-10-09 Lisbon: the user-authorized start-only experiment on
417 verified the full RAM load and received ROM execution acknowledgement, but
no programmer READY within 30 seconds. No mailbox/erase/program/finalize command
was sent. Physical RST restored vendor USB; two matching recovery dumps confirm
unchanged code and calibration/factory bytes, with 533 changed runtime-data bytes
after reboot. See [start-only run and recovery](v24-programmer-start-2026-10-09.md).
No successful programmer startup or flash-write qualification is established.
Earlier status statements below are chronological.

Previous status: host writer implemented and audited offline; see
[host writer audit](#host-writer-audit) and [operator guide](v24-flash-writer.md).
Later [cached-ID and startup review](v24-cached-flash-id-review.md) verifies a
single vendor-RAM read location and matching vendor/programmer SPI settings
(`9`, `0x291`). After two USB preflight aborts with no request sent, the authorized
single read succeeded at 17:29:58 UTC: cached JEDEC `c8 60 16`, GigaDevice, 4 MiB,
writer ID `0x1660c8`. Exact part variant and current QE/status remain unverified.
The review also qualifies the ROM timeout and UART-diagnosis claims. No reset was
performed in that review or the cached-ID read.
No hardware qualification or live flash write has occurred. Earlier status
statements below are chronological, including “no writer implemented”.

Initial status: offline investigation. Subsequent user-requested, individually
approved read-only diagnostics on original `1403167417` are recorded below.
No RAM loads, resets, or flash operations were performed. Both original backup
files still pass `SHA256SUMS`.

## Candidate obtained

An actual programmer is available from the
[A9G SDK fork at commit 4f36e75a4187bbfa5a2c7bc86a4cc8199020819a](https://github.com/Yakir-Ben-Hillel/A9G/blob/4f36e75a4187bbfa5a2c7bc86a4cc8199020819a/platform/ramrun/flsh_spi32m/host_8955_flsh_spi32m_ramrun.lod).

- File: `host_8955_flsh_spi32m_ramrun.lod`, 15,267 bytes.
- SHA-256: `862106a7cb02b4707ef09b5ac059541f1bcff61282ac8e9a9b2c91dbd7523503`.
- Its 1,692 little-endian words total 6,768 payload bytes.
- Sum of those words modulo 2^32 is `0x6e5f57ec`, matching its checksum footer.
- Load intervals: `[0x01c000a0,0x01c000b8)` and
  `[0x01c0027c,0x01c01cd4)`. These are in the SDK's internal SRAM window;
  they are not flash destinations. Loading them into a running system is still
  unsafe without establishing ownership of that RAM.
- The first interval supplies the monitor execution context: first word `0xff`,
  followed by candidate PC `0x81c00280`, then four zero words. Stack/context
  semantics must be validated before execution.

Evidence is retained locally under `firmware/live/2026-10-08-loader-audit/`,
including the LOD, disassembly, SDK sources, ROM map, and repository tree indices.
The directory is gitignored. The artifact was not loaded or executed.

## What the binary establishes

The entry point is MIPS32 and calls MIPS16 code at `0x81c00501`. Disassemble the
entry as `-m mips:isa32` and the compact code as `-m mips:16`, little endian.
Do not interpret the entire file as MIPS32 or treat literal pools as instructions.

The initialization beginning at `0x81c00500` clears 60 bytes at `0xa1c0e020`,
writes halfwords `0xfa01` and `0xfb05` there, and initializes buffer fields at
offsets 44, 48, 52, and 56. The last field is `0x10000`. Its mailbox starts at
`0xa1c0e024` and uses a 20-byte descriptor stride. These are observations of this
binary, not merely assumptions from the newer SDK source. Buffer allocation and
the full startup call graph have not been audited.

**USB support is a new compatibility concern.** The idle path reads the mailbox
at `0x81c0057a` and branches directly back to that read for command zero at
`0x81c00596`; it does not poll USB on that path. The compact-code direct-call scan
also found no calls to the SDK ROM's `boot_HostUsbRecv`, `boot_HostUsbSend`, or
`boot_HostUsbOpen`. Events call the ROM address mapped as `mon_Event`.
This suggests a host-port programmer build, unsuitable for assuming continued
USB mailbox access. It is not a complete proof that every indirect/interrupt path
lacks USB support. Treat this candidate as unapproved for USB use.

By contrast, the inspected SDK
[flash_programmer.c](https://github.com/cherryding1/RDA8955_W17.44_IDH/blob/b2b6287e8fa9a9f49b679a357b49beb1c31d821c/soft/toolpool/flash_programmer/flash_programmer.c)
explicitly gates both USB initialization and polling on `FASTPF_USE_USB`.
A filename containing `host_8955` does not resolve that build-time distinction.
That source also initializes PMD, clocks, watchdog, and SPI flash, and may reset
memory power. RAM-only load addresses do not prove harmless startup effects.
Its `FPC_END` can write flash magic. The candidate is not established as a build
of that source; retain the distinction during further auditing.

## Alternative entry path, still unproven

The SDK
[HAL monitor callback](https://github.com/cherryding1/RDA8955_W17.44_IDH/blob/b2b6287e8fa9a9f49b679a357b49beb1c31d821c/soft/platform/chip/hal/src/hal_usb_monitor.c)
handles execution-context commands as well as monitor restart. This suggests
investigating a direct RAM execution path while the vendor firmware still runs.
It could avoid the observed restart/enumeration failure, but requires confirming
the vendor implementation, safe RAM, stack, interrupts, power and USB ownership.
It does not establish cold recovery from corrupted boot flash, and does not
replace the restore specification's recovery gate. No execution frame was sent.

## Next work

1. Connect only the powered-off spare and record its printed ID. Make two matching
   dumps and bind its identity to a checksum manifest before hardware experiments.
2. Locate or build a programmer with demonstrated USB service, then audit its
   startup, supported flash IDs, erase geometry and runtime RAM footprints.
3. Establish ROM entry and sustained power on the spare. Do not repeat the failed
   original-unit restart automatically.
4. Complete the existing writer-spec review before implementation; retain separate
   approval for the destructive scratch-sector and boot-fallback experiments.

No writer has been implemented, and actual flash writing remains unproven.

## Subsequent build audit and live diagnostics

The SDK's [Makefile](https://github.com/cherryding1/RDA8955_W17.44_IDH/blob/b2b6287e8fa9a9f49b679a357b49beb1c31d821c/soft/toolpool/flash_programmer/Makefile)
explicitly selects `LOCAL_BATCH_NAME = usb` when `FASTPF_USE_USB=1`, otherwise
`host`. Its `install.sh` includes both builds for target `8955_ramrun` with flash
model `flsh_spi32m`. The expected USB artifact is therefore
`usb_8955_flsh_spi32m_ramrun.lod` (possibly with a ROM-version suffix), not the
host candidate already downloaded. This is a source-supported build route;
the build has not been attempted on this Mac.

A second candidate was retrieved from
[pulkin/csdtk42-linux, commit 0501320d7c77646c35b4ca61718a39168c25443f](https://github.com/pulkin/csdtk42-linux/blob/0501320d7c77646c35b4ca61718a39168c25443f/cooltools/chipgen/Modem2G/toolpool/plugins/fastpf/flash_programmers/host_8955_flsh_spi32m_ramrun.lod).
It is 53,995 bytes, SHA-256
`3092fb5d01203f865b15f6b8063b276d48ac4003ce5a460fb88585a9891049ba`.
Its word-sum checksum matches `0xb7de5517`; load records occupy
`[0x01c000a0,0x01c000b8)`, `[0x01c0027c,0x01c05f00)` and
`[0x01c05f30,0x01c0603c)`. It initializes the protocol map at `0xa1c05f30`
and mailbox at `0xa1c05f34`. This different ABI address demonstrates why the
host must discover the loaded map instead of copying addresses from another
programmer. Its idle branch at `0x81c006c2` also returns directly to its mailbox
read at `0x81c006a2`, without USB polling; no direct calls to the SDK ROM USB
open/send/receive functions were found. It was not executed.

The archive's `fastpf.rb` calls `ramrunXfer`, whose executor session first enters
the monitor. The [8809-family executor](https://github.com/pulkin/csdtk42-linux/blob/0501320d7c77646c35b4ca61718a39168c25443f/cooltools/chipgen/Modem2G/toolpool/scripts/8809/target_executor.rb)
uses the same `0xee` request on USB, waits for reconnection, then sends the monitor
start command and waits for its event. A missing post-reconnect handshake does
not explain the earlier absence of enumeration. The archive has a separate
8909 power-register workaround; do not copy it to 8955 without chip-specific
evidence. Neither the generic loader nor its verify-only UI is read-only: both
enter the monitor and execute a programmer.

Actual tests on original `1403167417`, following the user's continuation request
and execution approvals:

| Test | Result |
| --- | --- |
| USB enumeration outside sandbox | `1e04:0900`, interface `RDA Usb`, endpoints `81,01`; stable for 3 seconds |
| One 1 KiB read at `0x88000000` | Valid reply; byte-identical to the original backup; magic `0xd9ef0045` |
| Word read at ROM physical `0x01e00ffc` | `0x81c001c0`, the USB-monitor variable pointer |
| Word read at ROM physical `0x01e05ff8` | `0x51612152`, matching the SDK default/v1.1 ROM definition; u01 definition differs (`0x51608222`) |

Both ROM replies passed length, header, and XOR validation. A matching version
word is not a full ROM byte comparison, nor does it validate either programmer's
startup effects or flash-chip support. `Reset_Cause` was not reread.

Logs: `firmware/live/2026-10-08-usb-descriptors.jsonl`,
`firmware/live/2026-10-08-original-flash-read-check.json`, and
`firmware/live/2026-10-08-original-rom-identity.jsonl`.

New diagnostic tools:

- `tools/rda_usb_watch.py`: bounded enumeration/descriptor observer, no tracker
  protocol requests. Run with `--seconds 1..60 --output <new firmware/live path>`.
- `tools/rda_rom_identity.py`: defaults to printing requests; `--read` reads only
  the two fixed ROM words, once each, with validated replies and no retries.

The sandbox can return **zero USB devices despite the tracker being connected**.
The outside-sandbox checks above confirmed this. Do not classify a future
disconnect using a sandbox-limited observer. This does not by itself invalidate
the October 3 probe, which observed the tracker before the request on the same
connection and then observed its departure.

Next hardware experiment remains a reset/ROM-entry experiment on the backed-up
spare, or a specifically authorized original-unit reset experiment. It must run
the descriptor observer outside the sandbox, record baseline and transition,
use a single audited entry request, and stop if no ROM port appears. Do not load
a programmer merely because the VID/PID returns: validate the ROM interface and
handshake first. Repeating the same failed request without a new power/entry
hypothesis is not a useful next test. Flash writing remains a later gate.


## Further offline continuation: build feasibility and startup side effects

No device requests were sent during this continuation. No programmer was built
or executed. The USB build and sustained ROM entry remain unresolved.

### Prebuilt search and compiler constraint

Complete GitHub tree indexes for `dezamora98/CSDTK42`
(`426da8e315e526c0049edb73f43e1e90e7bf4732`), `darkatrium/CSDTK4.2`
(`96c420e7bd231247d81935a6f57180a7c9b4b604`) and `kezenwere/CSDTK-4.2`
(`e842723c81740a931e48d395f007c42626b21cca`), and `niwantha33/CSDTK42`
(`a4fef8cde557da2374da6d7c86d061aae461a130`) contain host 8955 programmers,
but no USB-named 8955 LOD. The latter contains a Gallite USB programmer,
which is not an established 8955-compatible substitute. This is a bounded search, not proof none exists elsewhere.

The pinned SDK's `8955_ramrun/target.config` selects `gcc4_xcpu`.
`compilerules.mk` requires the custom `-march=xcpu -mtune=xcpu` toolchain,
MIPS16 interworking and a reduced-register ABI; it explicitly warns that changing
that ABI is incompatible. Its alternate `gcc7_xcpu2` is also a custom target.
A generic MIPS compiler must not be substituted by simply removing these flags.
The retrieved `pulkin/csdtk42-linux` `bin/mips-elf-gcc` is an Intel 80386 Linux
ELF executable requiring `/lib/ld-linux.so.2`, not a macOS executable.
No `ctmake`, either compiler, Docker, Podman or QEMU user emulator was found on PATH.
The SDK environment script chooses its Windows tools on any non-Linux host.
Consequently the build is blocked on a compatible build environment; compilation
has not been attempted. A Linux environment able to run the supplied 32-bit x86
toolchain is the concrete next build prerequisite (or a validated native port).

Once that environment and the pinned SDK are available, the source-supported
build invocation from `soft/toolpool/flash_programmer` is:

```sh
ctmake CT_TARGET=8955_ramrun CT_RELEASE=release CT_OPT=dbg_size CT_USER=ADMIN FLSHPROG_CT_ASIC=8955 FLSH_MODEL=flsh_spi32m FASTPF_USE_USB=1 lod
```

This is a build recipe, not a tested command on this Mac. Preserve the ELF, map,
LOD and effective configuration; establish the selected ROM revision and inspect
USB calls, runtime buffers, entry context and flash ID handling before execution.

### Startup can write a flash status register

Newly inspected pinned SDK source:
[hal_spi_flash.c](https://github.com/cherryding1/RDA8955_W17.44_IDH/blob/b2b6287e8fa9a9f49b679a357b49beb1c31d821c/soft/platform/chip/hal/src/hal_spi_flash.c).
`main()` calls `hal_SpiFlashOpen()` before opening its USB context or entering the
mailbox loop. That function resets the flash, initializes its context, and reads
status register 2. If QE is clear, it issues write-enable, writes status registers
with QE set, waits for completion and disables writes. Persistence and exact
semantics depend on the actual flash chip, which is not yet established.
This is not a sector erase/program, but it is a flash-device register write.
Therefore launching this SDK programmer cannot be classified as read-only even
if no mailbox write command follows. This source observation is not proof of the
same path in either previously downloaded host binary.

The programmer also initializes PMD and requests 104 MHz. Its three data buffers
are in `.ramucbss`; a failed buffer check triggers memory-power cycling and RAM
initialization. Internal-SRAM LOD records alone do not describe its runtime
footprint or prove compatibility with the tracker's board configuration.

### ROM entry: confirmed path, additional lead

The pinned SDK callback stores a boot-sector monitor command and calls
`hal_SysRestart()`, which resets USB before a soft reset. The boot sector consumes
that one-shot command; 8955 `boot_SectorEnterBootMonitor()` sets FORCE_MONITOR and
calls the ROM monitor. The 8955 `boot_SectorFixRom()` implementation is empty.
These facts do not distinguish loss of power from failed USB startup on 417 and
do not justify another identical reset attempt.

[boot_key.c](https://github.com/cherryding1/RDA8955_W17.44_IDH/blob/b2b6287e8fa9a9f49b679a357b49beb1c31d821c/soft/platform/chip/boot/src/boot_key.c)
contains a second lead: a USB-download key check gated by the PMU AC_ON indication.
The generic target lists KP_OK for USB download, but this is a phone keypad
configuration, not a verified mapping for the tracker's buttons. Do not instruct
button combinations based on that target. Locate the corresponding key-check
path and key table in the vendor backup before designing a cold-entry experiment.
That path also depends on intact boot-sector code and does not itself prove
recovery after corrupting sector zero.

Source evidence was saved under the existing gitignored loader-audit directory:
`compilevars.mk`, `compilerules.mk`, `set_env.sh`, `ctmake`, `target.config`,
`target.def`, `tgt_board_cfg.h`, `pmd.c`, `hal_spi_flash.c`, `hal_sys.c`,
`boot_sector.c`, `boot_sector_chip.c`, and `boot_key.c`.


## USB build completed and original-unit ROM experiment

User explicitly requested the USB programmer ready and ROM recovery checked,
then confirmed original 417 powered off on the cable. This continuation supersedes
the earlier build-environment blocker. It does not authorize flash erasure.

### Built artifact

Installed Colima/Docker CLI/QEMU and created profile `rda-build` (ARM64 VZ VM,
4 CPUs, 4 GiB RAM, x86 binfmt emulation). Its sole explicit host share is the
public-source directory `firmware/live/usb-programmer-build`. No tracker USB or
backup directory was passed to the build container. The actual SDK compilation
ran with network disabled in an Ubuntu 22.04 amd64 container, using the pinned
CSDTK compiler's 32-bit executable and bundled libraries.

SDK script/ELF execute bits were missing in the archive and restored, recorded in
`executable-fixes.txt`. `LD_LIBRARY_PATH=/work/csdtk/lib` supplies the compiler's
bundled cloog/PPL libraries. No SDK C or assembly source was edited. The successful
build log is `build-03.log`; it contains 149 legacy SDK warnings, so this is not a
warning-free build. Link and LOD generation completed successfully.

Artifact directory: `firmware/live/usb-programmer-build/artifacts/`.

- `usb_8955_flsh_spi32m_ramrun.lod`: 107,589 bytes, 47,800 payload bytes.
- SHA-256: `8a3ea6257de0c4d584d9f04d8e19db73ee54d8eee0a47fc3ddcaebb2f8af9dd1`.
- Word checksum `0x969b40e2`, verified.
- SRAM intervals `[0x01c000a0,0x01c000b8)` and `[0x01c00280,0x01c0bd20)`.
- Entry PC `0x81c00280`; execution-context command starts at zero. The SDK executor
  prepares an execution command separately; do not blindly send/execute the LOD.
- Protocol map `0xa1c0bb68`, marker `FA01/FB05`, three 64 KiB buffers at
  `0xa2000000`, `0xa2010000`, `0xa2020000` (external RAM runtime requirements).
- Actual machine code calls ROM USB open at `0x81c021e8`, USB receive at
  `0x81c02240`, and USB send at `0x81c02248`. The no-command branch loops through
  those receive/send calls. This resolves the host-only compatibility issue.
- ELF, linker map, checksums, structural audit, build scripts and manifest retained.
  `tools/rda_lod_audit.py` validates the LOD offline without any USB access.

**Built and structurally audited, not loaded or device-qualified.** PMD/GPIO and
external RAM compatibility and flash JEDEC identity remain unverified. The known
conditional QE status-register write remains in this stock SDK build. No host
flash writer has been implemented and no programmer was loaded onto 417.

### Actual ROM comparison

`tools/rda_recovery_snapshot.py` made bounded read-only checks on 417. Its boot
1 KiB matched the backup and saved ROM boot mode was `0x20`. All 24,576 ROM bytes
at physical `[0x01e00000,0x01e06000)` match BOTH the default and v1_1 SDK LODs
byte-for-byte. ROM SHA-256:
`3946ea195270620f0907997f96f32fbaa1e2ab405146235fef2afb5f3c4680d7`.
The u01 image differs in 20,721 bytes. Evidence:
`firmware/live/2026-10-08-recovery-snapshot/`.

Vendor flash disassembly also identifies the USB boot-download list at
`0x880010c0` as key code `0x4d`, mapping to keypad matrix index 27 via the table
at `0x8800107c`. Its getter is at `0x88001010`; the AC_ON-gated check begins at
`0x88000eec`. This is not a verified physical button mapping.

### Bounded forced-ROM test

New hypothesis: use the volatile FORCE_MONITOR bit so reset enters ROM before the
vendor boot sector, instead of relying on the boot-sector command used by `0xEE`.
`tools/rda_rom_recovery.py` verifies the ROM hash/boot bytes, reads and preserves
boot fields, writes only those volatile fields, and refuses reset unless readback
confirms the force bit. It has no programmer-load or flash-write path.

First preflight used physical register address `0x01a000a0` for its write. The HAL
write decoder ORs `0x80000000`, potentially selecting the cached alias. Readback
did not confirm the force bit; original fields were written back and **no reset
was sent**. Corrected MMIO writes explicitly use uncached `0xa1a000a0`.

Second attempt:

- Initial `Reset_Cause=0x00200000`.
- Write frame `ad 00 0a ff 82 a0 00 a0 a1 00 00 22 00 fe`.
- Readback confirmed `0x00220000` (FORCE_MONITOR enabled, USB-disable clear).
- Sent exactly one internal debug reset:
  `ad 00 07 ff 84 00 00 00 00 01 7a`.
- USB disappeared. The initial observer encountered PyUSB's transient "no langid"
  ValueError during disconnect; observer handling was corrected to record that
  descriptor error. Separate outside-sandbox 3 s and 30 s observations found no
  USB devices. No ROM handshake or programmer load was attempted.
- This is a failed forced-ROM enumeration test, not proof of successful recovery.
  Power loss, ROM USB initialization failure and an earlier execution hang are
  still not distinguished. Do not repeat the reset automatically.

Logs: `2026-10-08-force-rom-recovery.jsonl` (preflight abort),
`2026-10-08-force-rom-uncached.jsonl` (one reset),
`2026-10-08-after-forced-reset.jsonl`, `2026-10-08-forced-rom-observe.jsonl`.
All are under `firmware/live/`. The user reconnected the cable afterwards;
physical recovery verification is recorded separately below when complete.


### Recovery after the failed test

The user reported cable reconnection, then RST pin press and reconnection with an
LED but no beep. USB briefly returned during the intervening descriptor watch;
we cannot attribute that first return uniquely to cable cycling versus RST.
After the user's RST confirmation, the bounded read-only snapshot succeeded:

- Interface `RDA Usb`.
- `Reset_Cause=0x00200000`, saved boot mode `0x20`: force bit cleared.
- First 1 KiB of live boot flash matches the original backup.
- All 24 KiB ROM bytes retain the baseline SHA-256.

Evidence: `firmware/live/2026-10-08-after-rst-snapshot/`. Both local backup files
also passed their SHA-256 manifest again. This does not assert a new full-flash
comparison or full runtime functionality. No flash-write command or programmer
execution occurred. The programmer is built; ROM USB recovery remains unproven
and the forced-entry attempt failed. No further reset was sent.

## Host writer audit

User-requested implementation/audit continuation, entirely offline. Reviewed
`tools/rda_flash.py` against SDK commit
`b2b6287e8fa9a9f49b679a357b49beb1c31d821c`, the local
`firmware/live/usb-programmer-build/sdk/` source and matching artifacts.
The LOD remains SHA-256
`8a3ea6257de0c4d584d9f04d8e19db73ee54d8eee0a47fc3ddcaebb2f8af9dd1`;
this continuation did not rebuild or change it.

Note, 2026-10-09: this build never reaches READY, and the writer is now pinned to
the clean build `c238911d…6c65`. The addresses in this section are the unmodified
build's; the
[re-pin review](v24-programmer-start-2026-10-09.md#writer-re-pinned-to-the-clean-build)
gives the new ones and what was checked again.

### Protocol and binary findings

| Item | Source/binary basis and host behavior |
| --- | --- |
| USB request lengths | `boot/8955/src/boot_usb_monitor.c:183,212,249,413,485`: big-endian header size counts bytes after flow ID, including CRC. Block read includes command, LE32 address, nonzero RID, two BE size bytes and a separate XOR byte. RAM write consumes exactly `DataSize - 1` data bytes after removing command/address. A 1024-byte write is 1034 wire bytes, below the 2048-byte OUT buffer. |
| Read replies/events | Same source at lines 602–623 and 852–878: `AD`, BE16(data size + 2), `FF`, RID, data, XOR. Event RID is zero and contains one LE32 value. Reads are capped at 1024 bytes by the host (1030 wire bytes, within the 1032-byte IN buffer). Fragmentation and coalesced events are handled; malformed length, XOR, flow or RID aborts. |
| Legacy dump frame | `rda_dump.read_block` omits a separate CRC and uses the last byte as the low block-count byte. The new ROM writer sends both count bytes plus CRC according to the decoder. The vendor-read compatibility quirk was not changed and is not evidence of a live ROM-writer test. |
| Execution | ROM `boot_HstMonitorX` retains SP when context SP is zero and invalidates instruction cache before jumping. The LOD has command zero, PC `0x81c00280`; host verifies all loaded bytes, changes only context command to `0xff`, verifies it, then sends internal `0xff`. Require execution event `0xff000004`, then startup `0xf0`; reject returned/unsupported execution and memory-failure events. Stack/USB-context ownership still needs board qualification. |
| ABI and slots | `flash_prog_map.h` and `flash_programmer.c:390–620`: map `0xa1c0bb68`, marker `0xfb05fa01`, descriptors at +4/+24 with 20-byte stride, buffers at +44/+48/+52, size at +56. Startup selects slot zero; `DONE=0xffffff9c` toggles slot. Errors `9d/9e/9f` do not toggle. Host pings both slots, serializes publication after parameter readback and treats `f0/f1` events as notifications; mailbox status is authoritative because device events can time out. |
| Configured geometry | ELF/link map `g_memdFlashBankLayout=0x81c095c4`: one bank, 63 × 64 KiB then 16 × 4 KiB. `g_memdFlashLayout=0x81c095e0`: six words `1, 0x81c095c4, 0x400000, 0x3f6000, 0x4000, 512`. Host now checks both structures in the LOD and at runtime. `memd_FlashGetSectorLimits` also returns 4 KiB for non-64-KiB-aligned offsets; host deliberately accepts only the table's full-sector boundaries. |
| HAL flash identity | ELF `gSpiFlashCtx=0x81c076f0`; disassembly of `hal_SpiFlashOpen` at `0x81c04518` stores raw JEDEC at +4 and manufacturer/type/capacity at +8/+9/+10. Host reads the uncached alias and compares against reviewed evidence, requiring capacity byte 22. This is a post-startup check and cannot substitute for identifying the chip before execution. |
| Finalization | `flash_programmer.c:407–410,548–555,602–623,716–762`: one special sector, offset zero/magic `0xd9ef0045`. Successful PROGRAM at zero sets `sectorWrite`; END writes that one word then clears the flag. Host validates GET_FINALIZE_INFO, withholds boot magic, checks the whole flash before END and again afterwards. END also changes LCD/keypad power levels in this USB build; it does not reboot. |

The ABI header's 16-bit program-size warning is conservative for this pinned
source: `FPC_PROGRAM` passes the 32-bit size directly to `hal_SpiFlashWrite`, which
splits it into page operations. The host retains the smaller 4 KiB limit; no
65536-byte program request is generated.

### Additional startup effects confirmed in the built binary

`fp_CheckDataBuffer` is MIPS32 at `0x81c01ec4`, while HAL routines such as
`hal_SpiFlashOpen` are MIPS16. Use the correct disassembler mode per function.
The buffer checker writes four patterns to the first/last word of all three
64 KiB buffers. Its compiled high-address path at `0x81c01f7c–0x81c02088` also
writes 256-byte spans at PSRAM-base + `0x3c0000` and + `0x3fff00`.
`NO_PSRAM_HIGH_ADDR_CHECK` was not selected. Thus compatibility requires more than
the first 192 KiB of external RAM; mirroring or a smaller chip remains a concern.
Failures begin with USB events `0xebc0eee2` (buffer) or `0xebc0eee1` (high RAM),
followed by diagnostic values, then the memory-reset/error path. The host now
stops on the initial failure event, but cannot undo startup's device-side effects.

`hal_SpiFlashOpen` disassembly confirms reset opcodes `0x66/0x99`, JEDEC read
`0x9f`, status-2 read `0x35`, and conditional write-enable/status-write to set QE.
The JEDEC debug event goes through `mon_Event`, not the USB event function; the
host does not assume it will receive the ID as a USB packet. The runtime context
check was added for that reason. No physical flash ID was obtained in this audit.

### Corrections and validation

The draft checked only the bank table, ignored early RAM-failure and ROM-return
events, accepted any hashed file as qualification, allowed journals outside the
ignored directory and did not poison a session after sector readback failure.
Those gaps are corrected. Qualification is bound to a spare, baseline, exact
target, ROM, programmer and reviewed chip identity, with named passing reports.
It remains an operator assertion: software cannot authenticate the report or
turn failed ROM access into a hardware pass.

Added whole-flash verification before boot magic, retained after-finalization
readback, copied reviewed evidence into the durable run journal, and required
the ROM execution/startup event sequence. `tools/test_rda_flash.py` now passes
26 offline tests, including literal wire vectors, SRAM write lengths, startup
failures, layout/identity faults, both mailbox slots, finalization-footprint
mismatch, disconnect/timeouts and corruption before/after finalization.
The actual pinned LOD passes the host's interval and geometry checks. Both
original backup files pass their existing SHA-256 manifest. No USB discovery,
ROM-entry attempt, RAM load or flash operation was performed here.

Remaining hardware gates and evidence-generation instructions are in
[the operator guide](v24-flash-writer.md#qualification-evidence-still-needed).
The original remains unqualified and blocked; offline tests do not establish a
safe live write or cold recovery.

## Control for the forced-ROM test: a plain reset also goes dark

The forced-ROM test above was judged by USB not returning. It had no control.
`tools/rda_rom_recovery.py --plain-reset` now sends the same debug reset after the
same checks, without writing the force bit.

Run A, 22:32 UTC on 2026-10-08, unit `1403167417` off on the cable, `1e04:0900`:
`Reset_Cause=0x00200000`, one reset frame `ad 00 07 ff 84 00 00 00 00 01 7a`, USB
gone 0.11 s later and no USB device for the full 120 s. A descriptor check at
22:34:54 UTC still found none. The user reports not touching the cable and not
watching the LEDs during the window.
Logs, under `firmware/live/`: `2026-10-08T223231Z-run-a-plain-reset.jsonl`,
`2026-10-08T223215Z-control-test-usb-state.jsonl` (before) and
`2026-10-08T223454Z-after-run-a-usb-state.jsonl` (after).

Afterwards the user saw both LEDs blinking in step, then unplugged and replugged
the cable without pressing RST. At 22:38:28 UTC the unit was on USB as `1782:3d00`
(`2026-10-08T223828Z-after-replug-usb-state.jsonl`). `AT:ts#` answered with
`ID:1403167417` and `pwon_count:80`; the count was 79 after the 18:04 reset
(`2026-10-08T223900Z-status-after-run-a.raw`).

What this shows:

- The plain reset restarted the vendor firmware into the running application: the
  LEDs blink, the count rose by one, and the unit that was off on the cable is now on.
- USB stayed off until the cable was replugged, and the replug did not restart
  the unit: the count did not rise again. My reading is that the application
  starts USB only on a cable plug event.
- So "no USB after the forced reset" does not show that ROM entry failed: the
  control gives the same observation. Whether the ROM monitor ran is open again.

A reading of the 17:00 forced test in this light, not a result: after that reset
the replug brought back `1e04:0900`, the off-on-the-cable mode, not `1782:3d00`.
So the application was not running when the cable came out. That fits a ROM
monitor waiting without USB and losing power on the unplug, because nothing had
told the PMU to hold power. It fits a hang equally. The RST press in the same
minutes means the record cannot separate them.

## Run B: forced ROM entry works on `1403167417`

22:45 UTC on 2026-10-08, unit off on the cable in `1e04:0900`; a pad read a minute
earlier showed the application not running (`KEYIN_2` `0x0`, accelerometer type 0,
`2026-10-08T224343Z-pin-state-before-run-b.jsonl`). Same tool, force bit set, 120 s
window. Log: `firmware/live/2026-10-08T224504Z-run-b-forced-reset.jsonl`.

| Time after the reset | Observation |
| --- | --- |
| before | `Reset_Cause=0x00200000`; force write read back as `0x00220000` |
| 0.11 s | vendor device going away (descriptor error) |
| 0.32 s | no USB device |
| 0.73 s | `1e04:0900` with interface `Coolsand Usb` |
| 0.74 s | monitor start sent; ROM answered `ad 00 06 ff 00 01 00 00 ff 01` (`0xff000001`) |
| 0.74 s | boot fields written back as `0x00200000`; read back `0x00350000`; tool stopped |
| about 29 s | still `Coolsand Usb` (`2026-10-08T224534Z-after-run-b-usb-watch.jsonl`) |
| about 30 s | device gone; no USB device for the following 59 s |

So the ROM monitor enumerates within a second of a forced warm reset and answers
the handshake. It left USB about 30 s after the reset, which matches
`BOOT_IDLE_TIMEOUT`; `boot_HostUsbDecode` returns `CONTINUE` for every packet it
parses, and the loop restarts the timer on `CONTINUE`, so a host that keeps
sending commands should hold it. That has not been tried.

Not explained: the boot-field readback. The write of `0x00200000` used the same
frame form that worked in the vendor firmware, and the ROM's decoder maps reads
to KSEG0 and writes to KSEG1 as the HAL does, yet the masked readback was
`0x00350000` (mode `0x35`, force bit clear). The tool logged only the masked
value, and no read was taken before the write, so it is not known whether the
write took effect or what the register held on entry. Not known either: whether
the force bit is still set, and what the unit did after leaving the monitor.

About the 17:00 test: that run's tool stopped on a descriptor error at the moment
of disconnect, the same transient seen here at 0.11 s, so nothing was watching in
the first seconds. My reading is that the ROM came up then too. One thing does
not fit: a 3 s check about 17 s after that reset found no USB device, inside the
30 s in which the monitor should have been present.

## Read-only ROM session on `1403167417`: ROM hash and two full flash reads

22:56 UTC on 2026-10-08, unit off on the cable. `tools/rda_rom_recovery.py` now
writes no register in ROM mode and, after the handshake, uses the writer's own
`Monitor.read`. Log: `firmware/live/2026-10-08T225652Z-rom-session.jsonl`.
A first start at 22:54 stopped in its preflight on `Reset_Cause=0x00350000`
before sending any write or reset (`2026-10-08T225432Z-rom-session.jsonl`).

| Step | Result |
| --- | --- |
| Preflight, vendor firmware | `Reset_Cause=0x00350000`; wrote `0x00220000`, read back `0x00220000` |
| Reset | `Coolsand Usb` 0.73 s later; handshake `0xff000001` |
| `Reset_Cause` read in ROM mode, nothing written | `0x00220000` |
| ROM `0xa1e00000`, 24 KiB | SHA-256 matches `3946ea19…80d7` |
| Flash `0xa8000000`, 4 MiB, twice | 31.0 s and 30.9 s; the two reads are identical |
| `Reset_Cause` at the end | `0x00220000` |
| Monitor exit `ad 00 07 ff 84 05 00 00 00 fe 80` | device gone 0.9 s later; no USB in the next 19 s |

The flash image is saved as `2026-10-08T225652Z-rom-session.flash.bin`, SHA-256
`148c0d4240b3fb49160afe0c030628f774e2cebec060cf1d1ae3e64c4bb32f62`. Against
`firmware/backup/v24_1403167417_2026-10-03_flash.bin`: the first 1 KiB matches,
`[0x3fa000,0x400000)` matches, and 68,453 bytes differ in 40 sectors of 4 KiB, all
between `0x37a000` and `0x3d9fff`. That range is outside the code; what the
firmware keeps there has not been checked.

What this settles:

- The monitor stayed up for 62 s while requests kept coming, past the 30 s idle
  limit.
- The writer's read frames, handshake and ROM check work against the real ROM.
  These are the steps `rda_flash.py` runs before it loads anything.
- Run B's `0x00350000` came from that run's write in ROM mode, not from the ROM:
  with no write, the register read `0x00220000` on entry and at the end. The
  SDK's ROM source copies a non-internal USB write with `memcpy`
  (`boot/8955/src/boot_usb_monitor.c:415` and `:424`), where the HAL has separate
  8, 16 and 32-bit write states. How that produces `0x35` is not worked out. Do
  not write registers in ROM mode with this frame.
- The value survived the user's power-key off and the restart into the
  off-on-the-cable state, so that transition does not reset this register.

Left as it is: the force bit is still set. Until RST, a power loss or a write of
`0x00200000` through the vendor firmware, each warm reset waits 30 s in the
monitor before it boots. Not tested: loading or starting the programmer, any RAM
write in ROM mode, any flash command.

The user saw both LEDs dark for a long stretch during this session, which fits
the minute spent in the monitor with no firmware running.

## What the programmer's start-up touches on this board (offline)

Read from the pinned SDK, the built ELF's map and `programmer-disassembly.txt`.
No device request was sent. This narrows the `board_ram_power` question; it does
not replace a live start.

- **No board pin setup runs.** `flash_programmer/Makefile:38` exports
  `BOOT_MONITOR_NO_HAL_OPEN`, and the built `boot_Loader` calls `main` at
  `0x81c01320`, before `tgt_GetHalConfig` and `hal_Open` at `0x81c013f8` and
  `0x81c01400`. `main` does not return, so `hal_Open`, and `hal_BoardSetup` under
  it, are linked but not reached. The `TGT_HAL_GPIO_*` table of the `8955_ramrun`
  target is therefore not applied; pads stay as the ROM left them.
- **No supply is switched by a GPIO.** Every `power[]` and `level[]` entry of that
  target's `TGT_PMD_CONFIG` is a PMU regulator or `NONE`
  (`target/8955_ramrun/include/tgt_board_cfg.h`, from line 481).
- **Switchable regulators start off, USB stays on.** All `powerOnState` values are
  `FALSE`: microphone, camera, audio, SD/MMC, LCD, I2C. On the V24 those feed the
  WiFi chip and the sensors. USB is the exception: the built
  `pmd_UsbDownloadByMicDetect` at `0x81c067f0` is only `pmd_EnablePower(6, 1)`.
- **Battery limits equal the vendor's**: 4200 mV end of charge, 4150 mV recharge,
  3400 mV power-on, gauge on GPADC channel 7.
- `main` (`flash_programmer.c:416-425`) then sets idle power mode, requests
  104 MHz, closes the watchdog and opens the SPI flash, as already audited.

Not checked: the fixed PMU register writes inside `pmd_Open` against the vendor's
own; the charge current (`PMD_CHARGER_400MA` here, vendor value not decoded); and
whether PSRAM answers on the first buffer check when started from the ROM monitor.
If it does not, `main` cuts memory power for 2 s, re-opens RAM and flash and checks
again (`flash_programmer.c:427-447`). `rda_flash.py` stops at the first failure
event, so a start-only run should record every event instead of stopping there.

## Two more entry leads from the vendor code

Read from the decompile and the pinned SDK only. No device request was sent.

### The vendor build has the SDK's mic-detect USB download check

Vendor `FUN_82012aac` (`firmware/decompiled/82010000.c:1627`) matches the SDK's
`pmd_UsbDownloadByMicDetect` (`soft/platform/edrv/pmd/pmu_8955/src/pmd.c:4353`)
step for step, including the event `0x0DE00000 | mv`. It runs when the PMU driver
starts and restarts into the ROM monitor when all of these hold:

| Condition | SDK | Vendor |
| --- | --- | --- |
| Normal power-on | `hal_SysGetResetCause() == HAL_SYS_RESET_CAUSE_NORMAL` | `FUN_82004054() == 0`; matched by position, not traced |
| Feature built in | `tgt_GetUsbDownloadByMicDet` under `USB_DOWNLOAD_BY_MIC_DET` | `FUN_88001020` returns 1 with `lo = 0x400`, `hi = 0xffffffff` |
| Charger present | `RDA_PMU_CHR_AC_ON`, bit 7 of the charger status | PMU register `0x14`, bit 7 |
| Earpiece GPADC reading | `mv >= lo && mv <= hi` | value from the channel at config offset `0x14c`, 1024 or more |

It then switches USB power on, stores boot-sector command `0x4e6a821c` (the same
command the `0xEE` path stores), flushes the data cache and soft-resets through
`FUN_82000e84`. It does not go through `FUN_82000ebc`, the restart that holds a
USB reset for 8000 ticks first.

So the board has a built-in way into download mode: power on with the cable in
while that GPADC input is held at 1.024 V or more. The channel is 1
(`HAL_ANA_GPADC_CHAN_1`): the PMD config is at `0x8823b49c` (`tgt_GetPmdConfig`),
and the word at offset `0x14c`, file offset `0x23b5e8`, is `1` in both backups of
`1403167417`. In the same table the earpiece and USB power-on states (offsets
`0x4e` and `0x36`) are both 0. Not known: which pad or connector pin carries
channel 1, and whether this entry enumerates where the two warm restarts did not. Its destination is the same ROM monitor. What
differs is that it runs at power-on, before the application has changed clocks
and power; that this matters is my reading, not a result.

### Starting the programmer from the running firmware

The SDK's USB decoder runs an execute command without a restart
(`hal_usb_monitor.c:339`; the comment at line 308 names fastpf). In the vendor
decompile the only caller of ROM `boot_HstCmdBasicHandler` (`0x81e01628`) is
`FUN_82002718` (`82000000.c:2733`), which reads `0xa1a3f010` and acts on `0xee`
and `0xff`. My reading is that `0xa1a3f010` is the host UART port's status
register, so this is the UART path. The vendor's USB decoder branch for the same
command has not been found, and no caller of `boot_HstMonitorX` appears in the
decompile. Whether an execute command sent over USB reaches the executor is open.

## ROM entry without the vendor firmware (offline, 2026-10-09)

Every entry so far was asked for through the vendor firmware. Once that firmware
is replaced, its `0xEE` request, its mic-detect check and its USB decoder are
gone. This section is what the chip offers with nothing from flash. It is all
reading: nothing was sent to a tracker.

Sources, saved in `firmware/live/2026-10-09-rom-entry-audit/` with hashes: from
the SDK at commit `b2b6287`, `boot_rom.S`, `bootp_mode.h`, `boot_host.c`,
`boot_sector.h`, `sys_ctrl.h`, `debug_host_internals.h`, `hal_abb_config.c`,
`halp_abb_regs.h` and `hal_usb.c`; and `8955_hard.xml`, RDA's register map for the chip, from
`pulkin/csdtk42-linux` at commit `0501320`. `boot_monitor.c` was already in the
loader-audit directory.

### What the ROM does before any flash code runs

Each row was checked in 417's own ROM dump (`2026-10-08-after-rst-snapshot/rom.bin`,
SHA-256 `3946ea19…80d7`), not only in the source.

| Step | Source | In 417's ROM |
| --- | --- | --- |
| Raises the wake-up line, which keeps the power on | `boot_rom.S:104-108` | `0x81e00034`: writes 1 to `0xa1a000a4` |
| Takes the boot mode from `Reset_Cause >> 16` | `boot_rom.S:172-176` | `0x81e00084`: shift by 16, stored at `0x81c001a8` |
| Enters the monitor if FORCE_MONITOR is set or flash word 0 is not `0xd9ef0045` | `boot_monitor.c:131-139` | literals `0x88000000`, `0xd9ef0045`, `0x81c001a8` and the tests against masks 2, 4 and 8, all in `0x81e00400`-`0x81e0054f` |
| Opens USB unless USB_MONITOR_DISABLE is set; opens the UART monitor only with UART_MONITOR_ENABLE | `boot_monitor.c:152-173` | calls to `boot_HostUsbClockEnable`, `boot_UsbOpen`, `boot_HostUsbOpen`, `boot_UartMonitorOpen` |
| Leaves on the 30 s idle limit only while word 0 is valid; with a bad word it stays | `boot_monitor.c:229-240` | literal `0x00078000`; the branch was read in the source, not decoded from the dump |
| On leaving, jumps to flash `0x88000010` whatever word 0 holds | `boot_monitor.c:89-93` | literal `0x88000010` in `boot_Monitor` |

### Three ways in that need nothing from flash

**1. A strap: `KEYIN_1` high at reset.** The register map's keypad entry says:
"The Key In pins 0 to 5 are muxed with the boot mode pins, latched during Reset.
Key_In 0: BOOT_MODE_NO_AUTO_PU. Key_In 1: BOOT_MODE_FORCE_MONITOR. Key_In 2:
BOOT_MODE_UART_MONITOR_ENABLE. Key_In 3: BOOT_MODE_USB_MONITOR_DISABLE." Its
`Reset_Cause` entry says the field holds "the state of boot mode pins latched
during Reset" and "is not reseted by a software or host reset". The bit is the
one `rda_rom_recovery.py` sets by a register write, so the monitor it leads to is
the one Run B reached.

On this board: 417 has read boot mode `0x20` after each RST so far, so `KEYIN_0` to
`KEYIN_3` are low at reset. `KEYIN_2` and `KEYIN_3` are the red LED and white
light lines ([pin map](v24-pin-map.md)); their being low is what leaves the USB
monitor on. `KEYIN_1` is GPIO 26, in the board's keypad mask, with no tracker
code found for it. Where it goes on the PCB is not known, nor whether the
tracker's button is on it.

**2. The host UART pads.** The debug host is hardware, not code. Its internal
register `CTRL_SET` has `Debug_Reset` and `XCPU_Force_Reset` ("Hold XCPU in reset
state until this bit is cleared"), its own clock divider defaults to 921,600
baud, and `boot_Monitor` forces it on at every boot (`boot_monitor.c:76`).
Coolwatcher's `enterHostMonitor` (`8809-target_executor.rb:54-100`) reads
`Boot_Mode`, sets bit 1, restarts the target and then unfreezes the CPU, with the
comment "for example, when the code loaded into a phone crashes early after the
boot". Those are the two commands `rda_rom_recovery.py` sends over USB; over the
UART Coolwatcher also sets bit 3, which turns the USB monitor off, and we would
not. My reading is that the same two commands over these pads work whatever is
in flash, and that the ROM then comes up on USB for the existing tools. Not
tested. It needs the pads found (`HST_RXD`, `HST_TXD`, ground), a USB-serial
adapter, and a serial sender, which the repo does not have; the UART's byte
framing has not been compared with the USB one.

**3. A bad word 0.** With anything but `0xd9ef0045` at flash offset 0 the ROM
enters the monitor by itself at every start and does not time out. This is the
state an interrupted install leaves, since the writer programs that word last.
It also allows a trial install: write a new firmware without the word, start it
with the monitor's exit command (the ROM then jumps to `0x88000010`), and program
the word only once the firmware is seen to run. The SDK's boot sector source
does not read the word; whether Logicrom's core does was not checked.

### What is still not proven

All three end in the ROM's USB monitor, and all runs of it so far came after the
vendor firmware had run in the same power session. The ROM does not set up power
itself: the only ROM call to any `boot_Ispi*` function is `boot_IspiOpen` from
`boot_Monitor` (found by listing every MIPS16 `jal` in the dump against the map's
symbols; calls through pointers are not covered), so it never writes the PMU or
the analog block, and `boot_HostUsbClockEnable` only starts the PLL. Whether USB
enumerates then depends on the power-on defaults of the USB regulator and of the
PHY power-down bit (`ABB_PD_USB`, analog register 4 bit 0). The register map
gives the PHY bit a reset value of 0, powered, with `usb_ctrl` resetting to the
value the SDK writes when it enables the PHY (`abb`, `usb_control_04H`). It gives
no reset values for the PMU, so the regulator's default (`pd_vusb_pon`, register
`0x0d`) is not documented. `pmd.c:372` says the regulator "should be always on"
because memory power derives from it, which is a hint, not a measurement.

No test without a flash write shows the ROM's USB after a hardware reset. RST
clears the force bit, and it also clears the software boot-mode bits, which hold
the flag that makes the boot sector trust a saved "enter monitor" command
(`BOOT_SECTOR_STRUCT_VALID_BOOT_MODE`, `boot_sector.h:57-62`). So writing that
command to RAM and pressing RST would do nothing.

So the open question is narrower than before: does `Coolsand Usb` appear when the
ROM is the first thing to run after power is applied? Route 1 can answer it with
no flash write: hold `KEYIN_1` high, apply power, watch USB.

### Tests this suggests (none run)

1. Hold the tracker's button, press RST with the cable in, and watch USB with
   `rda_usb_watch.py`; afterwards read `Reset_Cause` with `rda_boot_mode.py`.
   `0x0022…` and a `Coolsand Usb` port mean the button is the strap. It costs
   nothing and may well show nothing.
2. Find `KEYIN_1` among the test pads, then repeat with the pad held high through
   a resistor: first with RST, then from fully off by plugging the cable in.
3. Only with 2 passed, or with the host UART pads working: erase word 0 on a
   backed-up unit and confirm the monitor returns by itself.

On 2026-10-09 the user said the unit will not be opened again, which rules out
test 2 and the host UART pads.

### Button test on 417: the power button is not the strap

Test 1, 12:20-12:48 UTC on 2026-10-09, unit `1403167417` on the cable. Evidence:
`firmware/live/2026-10-09-button-rst/`.

| Time (UTC) | Observation |
| --- | --- |
| 12:20:53 | `1e04:0900`, `RDA Usb`; `Reset_Cause=0x00200000`, boot mode `0x20` |
| 12:22:03 | The user held the power button and pressed RST. Vendor device gone |
| to 12:26:05 | No USB device from the tracker: no `Coolsand Usb`, no vendor port (`rda_usb_watch.py`, five 60 s logs) |
| to 12:41:18 | Still none (a poll with the same `snapshot`, not logged to a file) |
| 12:46:44 | `1782:3d00` after the user unplugged and replugged the cable. The user reports the LEDs were blinking, and went dark 5 s after the cable came out |
| 12:48:46 | `1e04:0900`, `RDA Usb`, after the user switched the unit off with the power button, cable in. No `Coolsand Usb` between |
| 12:48:48 | `Reset_Cause=0x00200000`, boot mode `0x20` |

The force bit did not latch, so the power button does not pull `KEYIN_1` high at
reset. The restart with the button held went into the running application, which
stayed off USB until the replug, as in Run A. Two things rest on earlier
observations rather than this run: that the register keeps its value through a
power-button off (seen on 2026-10-08 with the bit set), and that the unit did not
lose power on the unplug (it came back in running mode, not off-on-the-cable).

The test says nothing about the ROM's USB after RST: the monitor was not entered.

### Next step without opening: a reset from inside the programmer session (prepared, not run)

With the pads ruled out, what is left is the bad-word route, and its first risk is
the restart: after block 0 is rewritten without the boot word, the chip has to be
reset from inside the programmer session and the ROM's USB has to come back. No
run so far has reset from that state; every entry reset was sent to the vendor
firmware. The stock programmer's own RESTART command goes through
`hal_SysRestart` (`flash_programmer.c:842-853`), the kind of restart the `0xEE`
request used when no ROM port appeared on 2026-10-03. Why that one failed is not
known, so the reset to use is the debug reset, which in a ROM session the ROM's
own decoder handles (`boot_usb_monitor.c:294-304`).

`rda_programmer_start.py --reset-test` tries that reset while the boot word is
still valid: start, query, one debug reset, then the ROM port, its handshake and
one full flash read equal to the pre-start read. It sends no flash command. If the
ROM came back without USB it would leave its monitor after 30 s and boot the vendor
firmware. The tool now takes `--unit 1403167412`, pinned to that unit's backup.
Nine tests cover the new path; all 103 pass.

```sh
.venv/bin/python tools/rda_programmer_start.py --execute --reset-test --unit 1403167412 \
  --journal firmware/live/2026-10-09-reset-test-412
```

Spare `1403167412`, read on 2026-10-09 before any of this: cached flash ID
`c8 60 16`, `Reset_Cause=0x00200000`
(`firmware/live/2026-10-09-spare-412/`).

### Reset test run 1 on 412: the programmer starts; the ROM port does not return by itself

13:07:43 UTC, 2026-10-09, run by the assistant after the user's "yes go". Journal
and six 4 MiB reads: `firmware/live/2026-10-09-reset-test-412/`.

| Elapsed | Result |
| --- | --- |
| 2.0 s | `Reset_Cause` `0x200000`, force bit written, debug reset sent to the vendor firmware |
| 2.76 s | `Coolsand Usb` 0.72 s after the reset; handshake `0xff000001` |
| 63.9 s | Two ROM reads, both SHA-256 `b0250296…a2c4`, the backup's |
| 64.7 s | Programmer loaded and verified; READY 0.54 s after execute; JEDEC `c8 60 16` |
| 82.8 s | Two reads through the programmer, identical |
| 101.1 s | PING on both slots and GET_FINALIZE_INFO answered; two more reads identical |
| 101.1 s | Debug reset `ad 00 07 ff 84 00 00 00 00 01 7a` sent inside the session; the transfer completed |
| to 131.3 s | The tracker stayed listed as `1e04:0900` with no answer to string requests for the whole 30 s. No `Coolsand Usb`. Tool stopped |

A watch 49 s after the reset found no USB device at all. The user pressed RST; at
13:14:28 the unit was back as `RDA Usb` with `Reset_Cause=0x00200000`. A two-pass
dump (`2026-10-09-spare-412/after-reset-test.flash.bin`) has the code and the
calibration and factory blocks identical to the backup; 7057 bytes differ in five
4 KiB sectors of the vendor's store (`0x382000`, `0x3a3000`, `0x3a7000`,
`0x3ac000`, `0x3d4000`).

What it establishes: the start-only and query steps work on a second unit, and a
debug reset from inside the programmer session does not bring the ROM port back
unaided. Had the boot word been blank, the unit would have been stuck there.

My reading, not a result: the chip did reset and the ROM waited in its monitor,
but nothing dropped off the bus, so the Mac kept the old device entry and never
re-enumerated; the entry vanished when the ROM left at its 30 s idle limit and
booted the vendor firmware. The ROM decoder resets immediately
(`boot_UsbReset()` then the soft reset), where the vendor firmware's restart
powers the USB PHY off and on first. The tool now waits one second, looks for
the port, and otherwise asks the Mac for a port reset before looking again, all
within 23 s of the reset.

### Reset test run 2 on 412: the ROM port returns after a port reset from the Mac

13:20:14 UTC, same day, same unit and build, with the change above. Journal and
seven 4 MiB reads: `firmware/live/2026-10-09-reset-test-412-2/`.

| Elapsed | Result |
| --- | --- |
| 1.95 s | `Coolsand Usb` 0.73 s after the entry reset |
| 63.1 s | Two ROM reads identical, SHA-256 `d09af2e8…694c`, the dump taken after run 1 |
| 63.9 s | Programmer READY 0.54 s after execute; JEDEC `c8 60 16` |
| 100.2 s | Query answered; four more reads identical to the pre-start read |
| 100.2 s | Debug reset sent inside the session |
| 101.2 s to 103.2 s | Tracker listed as `1e04:0900`, no answer to string requests, as in run 1 |
| 103.24 s | Port reset asked of the Mac (`usb.core.Device.reset`) |
| 103.31 s | `Coolsand Usb`, 3.14 s after the debug reset and 0.08 s after the port reset |
| 133.9 s | Handshake answered; full flash read through the ROM identical to the pre-start read |

So the reading above holds: the reset from inside the programmer session does
restart the chip into a working ROM monitor, and what was missing in run 1 was
the Mac re-enumerating the port. The monitor served a 30 s read after it. No
flash command was sent in either run.

Not covered: a reset with the boot word blank, and RST. After RST the same port
reset, or a replug, may be needed before the Mac sees the ROM; whether the ROM's
USB works at all after RST is still the open question.

After the user's RST at 13:23:40 the unit was back as `RDA Usb` with
`Reset_Cause=0x00200000`.

### Blank-word test, part one (prepared, not run)

`rda_programmer_start.py --blank-word-test`, refused for the original unit. It is
the first write to code on any tracker. After the usual start and query:

1. ERASE block 0, check it reads blank, PROGRAM it back in sixteen 4 KiB chunks
   with the boot word withheld, and require the whole flash to be the pre-start
   image with that one word blank. No END.
2. One debug reset, with the port reset from run 2, and the ROM handshake.
3. 40 s with no USB traffic, then a full read. With a valid word the ROM leaves an
   idle monitor at 30 s, so an answer here shows the blank word holds it.
4. A fresh programmer and the writer's own `restore()`: ERASE, sixteen PROGRAMs,
   full check, END, full check. The reset loses the programmer's "block 0 was
   programmed" flag, and END writes the word only when it is set
   (`flash_programmer.c:549-555,716-728`), so END alone would not do.
5. The whole flash must equal the pre-start read.

Every mailbox packet is fixed in advance from the pre-start image, and the
monitor refuses any other. `--finish JOURNAL` restores block 0 from a stopped
run's `before-startup.bin`, starting at the ROM port: port reset, debug reset,
handshake, two reads, then step 4. It refuses if anything outside block 0 differs.

From step 1 to END the unit has no boot word. What can go wrong, and what then:

| Where it stops | State | Way back |
| --- | --- | --- |
| Erase, program or a check in step 1; anything in step 4 | In a programmer session, USB up | `--finish` |
| Step 2: no ROM port even after the port reset | ROM monitor, held by the blank word, the Mac not seeing it | Replug the cable, then `--finish`. If the port never appears, the unit is stuck |
| Step 3: no answer after the silence | The ROM left despite the blank word and the vendor code is running | The vendor firmware's own way into the ROM, as in every run so far; no tool mode for it yet |

`--finish` and the composition of steps 1 to 5 have run only against the
simulated chip in the tests (112 pass). Step 2 with a valid word is run 2 above.

```sh
.venv/bin/python tools/rda_programmer_start.py --execute --blank-word-test --unit 1403167412 \
  --journal firmware/live/2026-10-09-blank-word-412
```

### Blank-word test, part one, run on 412: passed

13:37:11 UTC, 2026-10-09, run by the assistant after the user's "lets run this".
Journal and fourteen reads: `firmware/live/2026-10-09-blank-word-412/`.

Before the run, a read of `run()` found that it could not have finished as
prepared. `query()` saved its two reads as `after-query.bin` and
`after-query-second.bin`, the restore step calls `query()` a second time, and the
journal never overwrites a file. The run would have stopped with `FileExistsError`
in step 4, after the fresh programmer's query and before the restore, with the
boot word blank. The tests did not show it because they give the pieces a mock
journal and a patched `read_flash`. Driving the real `run()` against the simulated
chip with a journal on disk reproduced it. The second query now saves as
`before-restore.bin`, and two tests run the whole of `--blank-word-test` and
`--finish` that way; the first fails against the tool as it was. 114 pass. Nothing
sent to the tracker changed.

| Elapsed | Result |
| --- | --- |
| 1.9 s | `Reset_Cause` `0x200000`, force bit written; `Coolsand Usb` 0.72 s after the entry reset |
| 63.0 s | Two ROM reads identical, SHA-256 `6c53d5e4…91bf`; code and protected tail as the backup, 5806 bytes differ in the same five sectors of the vendor's store |
| 63.8 s | Programmer READY 0.54 s after execute; JEDEC `c8 60 16` |
| 100.1 s | Query answered; four more reads identical to the pre-start read |
| 100.1 s | ERASE of block 0 done in 0.28 s; the block read back blank |
| 100.6 s to 101.0 s | Sixteen PROGRAMs, 12 to 24 ms each |
| 110.1 s | Full read `bb58b7fb…eaa0`: the pre-start image with bytes 0 to 3 `ff ff ff ff`, nothing else changed |
| 110.1 s | Debug reset sent inside the session |
| 111.1 s to 113.1 s | Listed as `1e04:0900`, no answer to string requests, as in both reset tests |
| 113.19 s | `Coolsand Usb` 3.1 s after the debug reset and 0.08 s after the Mac's port reset; handshake `0xff000001` |
| 113.2 s to 153.2 s | No USB traffic for 40 s |
| 155.1 s | First 256 KiB of the read answered |
| 183.7 s | Full read through the ROM identical to the blank-word image |
| 184.4 s | Second programmer READY 0.54 s after execute; query answered; three reads identical to the blank-word image |
| 211.7 s | Restore: ERASE of block 0 in 0.29 s, sixteen PROGRAMs, block and whole flash checked |
| 221.8 s | END done; it wrote the boot word |
| 239.8 s | Two full reads `6c53d5e4…91bf`, the pre-start read |

The unit had no boot word from 13:38:51 to 13:40:53 UTC, 122 s.

What it establishes on a real unit:

- Erasing and programming a code block works: block 0, twice.
- END writes the boot word when block 0 was programmed in the same session.
- The writer's own `restore()` puts block 0 back, from a programmer started on a
  ROM that had no boot word to find.
- With the word blank the ROM monitor answered after 40 s of silence. With it
  valid the monitor leaves at 30 s (Run B, and reset test run 1).
- The reset from inside the programmer session brings the ROM back with the word
  blank, given the Mac's port reset, as it did with the word valid.

Not covered: `--finish` has still only run against the simulated chip, and RST
with the word blank is part two. After this run the unit sat in the second
programmer session, listed as `Coolsand Usb`, with a valid boot word; RST returns
it to the vendor firmware, as after both reset tests.

After the user's RST the unit was back as `RDA Usb`, and at 13:44:03 UTC it read
`Reset_Cause=0x00200000`. A two-pass dump through the vendor firmware
(`2026-10-09-spare-412/after-blank-word-test.flash.bin`) has block 0, all the code
and the calibration and factory blocks identical to the backup. Against the
pre-start read of this run, 528 bytes differ, all in one 4 KiB sector of the
vendor's store (`0x3a3000`), one of the five that already differed from the backup.

### Blank-word test, step A: separate stop and finish (prepared, not run)

Prepared on 2026-10-09 from `handoff-2026-10-09-blank-word-part-two.md`.
The new `--blank-word-stop` mode runs the existing start and query checks, calls
`blank_boot_word()`, and returns after the full flash read proves only bytes 0-3
changed to `ff ff ff ff`. It sends no debug reset or END after blanking. It leaves
the chip in the programmer with USB connected. The original unit 417 remains
refused; this plan uses spare 412, whose identity is checked before writing.

The new test drives the real `run()` with journals on disk through blank-and-stop,
checks the exact command list and absence of a reset, then drives `--finish` using
the first run's actual journal and requires the entire original image. Before the
implementation the test failed because the word was still valid. After the change
it passes. CLI checks also reject combining this mode with another test, `--finish`,
or the marker build. All 116 tests pass. No dependency was added.

Read-only preflight: no `rda_` process was found. The descriptor watch recorded
`RDA Usb` in `firmware/live/2026-10-09-part-two-preflight-usb.jsonl`. At 13:58:52 UTC,
`Reset_Cause=0x00200000`; evidence is
`firmware/live/2026-10-09-part-two-preflight-reset-cause-unsandboxed.log`.
The earlier sandboxed register-read attempt could not enumerate the tracker and
sent no request. USB descriptors alone do not identify the unit.

Two separate flash-writing runs are needed. Obtain a go for each run. Throughout
step A: no RST, unplug or power button. Run 2 restores the valid boot word before
any physical-reset experiment is considered.

| Where it stops | State | Next action |
| --- | --- | --- |
| Before the first erase | Boot word remains valid | Inspect the journal before any retry |
| During erase/program/verification in run 1 | Block 0 incomplete or word blank, programmer still running if USB is healthy | Keep connected; restore with `--finish` after its own go |
| Successful run 1 | Whole flash matches pre-start except word 0, programmer running | Run 2 after its own go; no physical reset |
| Run 2 before END | Word may still be blank | Keep connected; inspect the journal, fix the cause and obtain a go for another recovery run |
| USB becomes unreachable while the word is blank | No valid boot word; external recovery unproven | The unit could be lost without opening it, which the user has ruled out |

Commands, output to regular files and new journal directories (allow ten minutes
per command). Recheck for competing tracker processes immediately before each run.

```sh
.venv/bin/python tools/rda_programmer_start.py --execute --blank-word-stop \
  --unit 1403167412 --journal firmware/live/2026-10-09-finish-check-412-blank \
  > firmware/live/2026-10-09-finish-check-412-blank.log 2>&1

.venv/bin/python tools/rda_programmer_start.py --execute \
  --finish firmware/live/2026-10-09-finish-check-412-blank \
  --unit 1403167412 --journal firmware/live/2026-10-09-finish-check-412-restore \
  > firmware/live/2026-10-09-finish-check-412-restore.log 2>&1
```

Offline validation of the blank-and-stop command passed against the pinned spare
412 backup and programmer. Neither command above has run. `--finish` is still
unproven on hardware; RST with a blank word is still unproven. Step B requires a
separate blanking run and the user's physical RST after step A succeeds.

### Step A, run 1 on 412: blank-and-stop passed; restoration pending

14:00:59-14:02:51 UTC on 2026-10-09, after the user's "yes, go. I wont touch the
usb" authorizing the first blank-and-stop run. No competing `rda_` process was
found immediately before execution. Command and paths are as prepared above;
journal `firmware/live/2026-10-09-finish-check-412-blank/`. Process exit code 0.

| Elapsed | Result |
| --- | --- |
| 3.0 s | Vendor boot, unit identity and ROM checks passed; normal reset fields; force bit set and entry reset sent |
| 3.7 s | `Coolsand Usb`, 0.72 s after the entry reset; ROM handshake answered |
| 65.0 s | Two full ROM reads identical, SHA-256 `47f9966f…4c47`; code and protected tail match spare 412's backup |
| 65.8 s | Pinned programmer READY, JEDEC `c8 60 16` |
| 102.3 s | Startup and query checks passed; four more full reads identical to pre-start |
| 102.3-102.6 s | Block 0 ERASE completed; blank block readback passed before programming |
| 102.8-103.2 s | Sixteen 4 KiB PROGRAMs completed, word 0 withheld |
| 112.2 s | Full read verified; `boot_word_blank` and `blank_word_stopped`; no subsequent reset or END |

Independent comparison of the saved 4 MiB images confirmed that exactly offsets
0, 1, 2 and 3 changed. Pre-start SHA-256:
`47f9966f4e2e753e6cbf1432062f7fdcb7c43c846b4401a1fc780b517b674c47`.
Blank-word image SHA-256:
`5ef028552bf891f33811e55b27aefd3c33042bad44eb5d40c7a5610e413f7f93`.
The pre-start image differs from the backup only in the same five vendor-store
sectors already observed, by 6334 bytes.

Current state: boot word blank since the erase at 14:02:41 UTC, left in the
programmer session. No RST, unplug or power button. The separately authorized
`--finish` run is next, using this run's `before-startup.bin`. It has not run;
hardware recovery through `--finish` and the physical-reset experiment remain
unproven.

### Step A, run 2 on 412: separate `--finish` passed

14:04:24-14:06:25 UTC on 2026-10-09, after the user's separate "yes, go ahead"
for restoration. No competing `rda_` process was found. The saved recovery target
hash and the blank image were checked before starting. Journal:
`firmware/live/2026-10-09-finish-check-412-restore/`; command as prepared above.
Process exit code 0.

| Elapsed | Result |
| --- | --- |
| 0.0 s | Tracker listed as `Coolsand Usb` in the stopped programmer session |
| 1.1 s | Initial Mac port reset completed; debug reset sent |
| 4.2 s | After another Mac port reset, ROM returned 3.12 s after debug reset; handshake answered |
| 65.4 s | Two full ROM reads match the saved blank image, SHA-256 `5ef02855…7f93`; exactly four bytes differ from target |
| 66.2 s | Fresh pinned programmer READY |
| 84.3 s | Query checks passed; both full reads still match the blank image |
| 93.3 s | Writer's own pre-write read matches the blank image; plan contains block 0 only |
| 93.7-94.4 s | ERASE and sixteen PROGRAMs completed; block 0 verified |
| 103.5 s | Whole-flash check with word withheld passed; END completed, writing the boot word |
| 112.5 s | Writer's full post-END read matches the target |
| 121.5 s | Additional full read matches the target; `boot_block_restored`, word `0xd9ef0045` |

Independent comparison of `after-flash.bin` and `after-restore.bin` against run 1's
`before-startup.bin` confirmed exact equality across all 4,194,304 bytes. All three
have SHA-256
`47f9966f4e2e753e6cbf1432062f7fdcb7c43c846b4401a1fc780b517b674c47`.
The boot word was blank from approximately 14:02:41 to 14:06:07 UTC, 206 seconds.

What this establishes: `--finish` can recover this spare from a separately stopped
blank-and-stop run, using its actual on-disk journal. It can reset the stopped
programmer, regain the ROM through Mac port resets, start a new programmer and
restore the exact pre-start image. It does not establish USB recovery after RST
with a blank word or after power loss. The unit is left in the programmer with a
valid boot word; the user's RST can now return it to the vendor firmware.

After the user reported RST, a descriptor-only watch found `RDA Usb`
(`firmware/live/2026-10-09-after-finish-rst-usb.jsonl`). At 14:08:40 UTC the
single register read returned `Reset_Cause=0x00200000`, boot mode `0x20`,
software boot mode zero and `USB_MONITOR_DISABLE=0`
(`firmware/live/2026-10-09-after-finish-rst-reset-cause.log`). No competing tracker
process was found. Vendor firmware has returned with normal boot fields. No
post-RST flash dump was taken; the full-image equality above was verified before
RST, and vendor firmware can change its settings store when it runs.

### Step B on 412: RST with a blank boot word (prepared, not run)

First return to vendor firmware with the user's RST while the boot word is valid,
then verify `RDA Usb` and normal reset fields. Obtain a new go for blank-and-stop.
Use the same pinned unit and mode as step A; no code change is needed.

```sh
.venv/bin/python tools/rda_programmer_start.py --execute --blank-word-stop \
  --unit 1403167412 --journal firmware/live/2026-10-09-rst-blank-412 \
  > firmware/live/2026-10-09-rst-blank-412.log 2>&1
```

After the full read verifies only the word changed, start a descriptor-only USB
watch and ask the user to press RST once. This is the experiment's risk: the ROM's
USB power after hardware reset is unknown. If USB never returns, the unit may be
lost under the user's no-opening constraint. Step A does not remove this risk.

| Observation after RST | Next action |
| --- | --- |
| `Coolsand Usb` returns | Record enumeration; obtain the separate go for `--finish` below |
| `1e04:0900` remains listed but silent | Record it; `--finish` begins with its own Mac port reset; obtain its separate go |
| No tracker listed | Ask for a cable replug, observe again, and restore if a usable port returns |
| Still no tracker after replug | Do not claim recovery; power-button handling or battery depletion are unproven external options |
| Vendor interface unexpectedly returns | Record the contradiction, inspect read-only state and do not force the prepared ROM-only recovery path |

```sh
.venv/bin/python tools/rda_programmer_start.py --execute \
  --finish firmware/live/2026-10-09-rst-blank-412 \
  --unit 1403167412 --journal firmware/live/2026-10-09-rst-blank-412-restore \
  > firmware/live/2026-10-09-rst-blank-412-restore.log 2>&1
```

Each writing run needs its own go, fresh journal, output file and process check.
Require exact equality to step B's own pre-start image after restoration. Success
would establish recovery after the tested RST with the cable connected; fully
discharged power-on and compatibility with Logicrom's core would remain untested.

### Step B, blank-and-stop on 412: passed; physical reset pending

14:09:45-14:11:37 UTC on 2026-10-09, after the user's "yes, go for step B".
No competing `rda_` process was found. Command as prepared above; journal
`firmware/live/2026-10-09-rst-blank-412/`. Process exit code 0.

| Elapsed | Result |
| --- | --- |
| 4.4 s | Unit and ROM checks passed; force bit set, entry reset, ROM handshake |
| 65.6 s | Two identical full ROM reads, SHA-256 `a09f61a9…1f75`; code and protected tail match the backup |
| 66.4 s | Pinned programmer READY |
| 102.7 s | Startup and query reads unchanged; blanking begins |
| 112.6 s | Full flash read verifies only bytes 0-3 changed; no subsequent reset or END |

Independent comparison of saved images confirmed exact equality outside the four
boot-word bytes. Pre-start SHA-256:
`a09f61a9c67b4f1c4830173432d6682bc33dc9a556d2c24d23e9fafff6f51f75`.
Blank-word SHA-256:
`67ea2cd01ad3667467bb1312e9f11b69d3a6f686f38dda2b61856576337de493`.
The pre-start image differs from the backup by 6862 bytes in the same five
vendor-store sectors as earlier runs.

The boot word is blank from 14:11:28 UTC. A 60 s descriptor-only watch was started
at 14:11:42 UTC (watch-file creation time), initially showing `Coolsand Usb`, and the user was
instructed to press RST once with the cable connected. Evidence:
`firmware/live/2026-10-09-rst-blank-412-watch-01.jsonl`.
The post-RST result and restoration remain pending. `--finish` must use this
step B journal, not step A's earlier image, and needs its own go.

### Step B, physical RST on 412: ROM USB reachable with the boot word blank

The user reported RST after blanking. Neither 60 s descriptor watch captured a
transition; both logged `Coolsand Usb` throughout. Therefore these watches do not
establish the exact reset time or enumeration delay. A fresh three-second watch
after the user's report also found `Coolsand Usb`:
`firmware/live/2026-10-09-rst-blank-412-after-rst-usb.jsonl`.

At 14:15:40 UTC a bounded check used the existing `StartMonitor` with no load
segments, no armed reset and no allowed mailbox packets. It sent the ROM
handshake, read the reset register and boot word, and read the whole flash. It
sent no Mac port reset, debug reset, RAM load, MMIO write or flash command.
Journal: `firmware/live/2026-10-09-rst-blank-412-rom-check/`; output:
`firmware/live/2026-10-09-rst-blank-412-rom-check.log`. Process exit code 0.

| Elapsed | Result |
| --- | --- |
| 0.014 s | ROM handshake answered `0xff000001` |
| 0.015 s | `Reset_Cause=0x00200000`, force-monitor bit clear; flash word 0 `0xffffffff` |
| 30.607 s | Full 4 MiB read exactly matches the saved blank-word image, SHA-256 `67ea2cd0…e493` |

The normal reset fields distinguish this state from the forced monitor used to
enter the programmer: before RST the force bit was set. Together with the user's
RST report, the blank word and successful ROM read establish that USB remains
reachable after hardware reset with the boot word withheld on this unit, with
the cable connected. No port reset or replug was needed after the user's RST.

Not established: enumeration timing, startup from a depleted battery or complete
power loss, behavior across other units, or Logicrom's handling of a blank word.
No new firmware was installed. The unit is currently in the ROM monitor with a
blank boot word. The prepared step B `--finish` command is next, after its own go;
restoration has not yet run.

### Step B, restoration on 412: passed; valid boot word restored

14:17:43-14:19:45 UTC on 2026-10-09, after the user's separate "yes, go" for
restoration. No competing `rda_` process was found. Before starting, the pre-start
target hash and equality of the post-RST read to the saved blank image were
verified. Command as prepared above; journal
`firmware/live/2026-10-09-rst-blank-412-restore/`. Process exit code 0.

| Elapsed | Result |
| --- | --- |
| 0.0 s | `Coolsand Usb` present |
| 1.1-4.2 s | `--finish` performed its initial port reset and debug reset; a further Mac port reset recovered the ROM, 3.12 s after debug reset |
| 65.5 s | Two full ROM reads agree; only four bytes differ from the valid target |
| 66.2 s | Fresh pinned programmer READY |
| 84.2 s | Query and its two full-read checks passed |
| 93.6-94.3 s | Block 0 ERASE and sixteen PROGRAMs completed, followed by block verification |
| 103.4 s | Full flash checked with word withheld; END completed, restoring the boot word |
| 112.4 s | Writer's full post-END read matches the target |
| 121.5 s | Additional full read matches; `boot_block_restored`, word `0xd9ef0045` |

Independent comparison confirmed that both `after-flash.bin` and
`after-restore.bin` exactly match all 4,194,304 bytes of step B's
`before-startup.bin`, SHA-256
`a09f61a9c67b4f1c4830173432d6682bc33dc9a556d2c24d23e9fafff6f51f75`.
The boot word was withheld from about 14:11:28 to 14:19:27 UTC, 479 seconds.

The physical-reset experiment and subsequent restoration are complete. On this
unit, with USB connected, a blank boot word allowed a working ROM monitor after
the user's RST, and `--finish` subsequently restored the exact pre-start image.
The Mac port resets in this restoration belong to the tool's additional debug
reset sequence; they were not needed for the earlier post-RST ROM read.

Current state: valid boot word, left in the programmer session. The user's next
RST can return it to vendor firmware; that post-restoration reboot has not yet
been checked. This establishes the tested hardware-reset recovery path only,
not recovery after full power loss or any Logicrom firmware behavior. Original
unit 417 was not touched. Nothing was committed.

After the user's final RST, the descriptor check found vendor `RDA Usb`
(`firmware/live/2026-10-09-rst-blank-412-final-usb.jsonl`). At 14:20:47 UTC the
single register read returned `Reset_Cause=0x00200000`, boot mode `0x20`, software
boot mode zero and `USB_MONITOR_DISABLE=0`
(`firmware/live/2026-10-09-rst-blank-412-final-reset-cause.log`). No competing
tracker process was found. Final state: vendor firmware running normally on USB,
normal reset fields, restoration verified before RST. No post-RST full flash dump
was taken; vendor firmware may update its settings store. Steps A and B are complete.
