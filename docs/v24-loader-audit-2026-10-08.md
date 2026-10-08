# V24 RAM programmer audit — 2026-10-08

Latest status: host writer implemented and audited offline; see
[host writer audit](#host-writer-audit) and [operator guide](v24-flash-writer.md).
Later [cached-ID and startup review](v24-cached-flash-id-review.md) verifies a
single vendor-RAM read location and matching vendor/programmer SPI settings
(`9`, `0x291`); the read itself awaits approval. It also qualifies the ROM
timeout and UART-diagnosis claims. No reset was performed in that review.
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
