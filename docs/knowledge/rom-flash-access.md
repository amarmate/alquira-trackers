# RDA ROM monitor, RAM programmer and flash access: what is known

Reference, reconciled 26-10-11 from the restore specification, the writer guide, the SPI
initialization comparison and the live runs through 2026-10-10 18:48 UTC. The dated notes
it replaces are in [done/](../done); each carries a banner pointing here. Run history and
open steps: [the working summary](../in-process/26-10-10-agents-summary.md).

Labels: **read** = from source or binary, **measured** = observed live on a unit.
Units: 417 (`1403167417`) is the original reference; 412 (`1403167412`) is the spare used
for destructive trials. Five spares exist.

## 1. What works today (measured)

| Capability | Entry point |
| --- | --- |
| Read the vendor firmware over the magnetic cable | `tools/rda_dump.py`; [firmware-analysis.md](firmware-analysis.md) |
| Enter the ROM monitor without opening the tracker | vendor debug force bit + reset (`tools/rda_rom_recovery.py`, or the first step of `rda_programmer_start.py`); physical RST when the boot word is blank |
| Load a USB RAM programmer that reaches READY | `tools/rda_programmer_start.py`; READY ~0.54 s after execute |
| Query, erase and program flash | mailbox slots, 4 KiB program chunks, 64 KiB and 4 KiB erases; full-image install and restore have passed |
| Restore after a trial | `rda_programmer_start.py --finish INSTALL_JOURNAL` |
| Read and narrowly clear flash block protection | `--read-status`, `--clear-protection` |
| Run a returning helper from the ROM monitor | `tools/rda_spi_probe.py` via the `0xfc` handler (§6) |
| Read the flash security registers | passed 18:47:12 UTC through the `0xfc` helper |

**Not established:** recovery after complete battery loss or an interrupted hardware write
(only simulated), and a production boot path. The blank boot word is a deliberate recovery
mechanism for trials; do not call RST recovery "unbrickability".

## 2. USB identities and entering the ROM

Distinguish modes by interface, not VID:PID alone.

| Identity | Meaning |
| --- | --- |
| `1e04:0900`, interface **RDA Usb** | Vendor debug firmware; libusb memory reads while it runs |
| `1e04:0900`, interface **Coolsand Usb** | ROM monitor, or the running RAM programmer; handshake and pinned metadata tell them apart |
| `1782:3d00` | Running vendor app; interface 1 OUT `0x02` / IN `0x82` carries `AT:` commands and logs. Interface 0 is not the command channel |
| `1782:4d11` | LogicROM CDC modem, `/dev/cu.usbmodem*` |

- **Forcing ROM entry:** write the force-monitor bit (17) of the reset register at physical
  `0x01a000a0` and reset. Common reading `0x00200000`; forced `0x00220000`. These fields
  alone do not identify every reset cause. Result: handshake `0xff000001`, pinned 24 KiB ROM
  hash `3946ea195270620f0907997f96f32fbaa1e2ab405146235fef2afb5f3c4680d7`, two identical
  full-flash reads (ROM reads take ~31 s; the programmer ~9.5 s).
- **With the boot word blank** (`0xffffffff` instead of `0xd9ef0045`), a physical RST lands
  in ROM and the monitor stays up beyond its usual idle timeout. This is the independent
  recovery path.
- **Do not infer "USB absent means ROM failed."** A plain reset also drops USB while the
  vendor app continues. Power button + RST does not assert the ROM strap. A Mac USB port
  reset was needed once before ROM appeared.
- **Reading `Reset_Cause`:** `tools/rda_boot_mode.py --read --output <new log>` (one attempt,
  exactly one `1e04:0900` interface, no writes). Frame `ad 00 07 ff 02 a0 00 a0 01 03 ff`,
  reply `ad 00 06 ff 03 <4 bytes LE> <xor>`, 10 bytes. `BOOT_MODE = (Reset_Cause >> 16) &
  0x3f`; `USB_MONITOR_DISABLE` is bit 19. 417 read `0x00200000` on 2026-10-03, so that bit
  was clear. Do not use `rda_dump.read_block` for a register (it always reads 1,024 bytes),
  and do not add `0x88000000` to a register address.
- **Do not send vendor-form MMIO writes through the ROM monitor.** An early `Reset_Cause`
  write became `0x00350000`. Use the reviewed tool paths.
- Address spaces: vendor flash `0x88000000`; ROM/programmer uncached flash `0xa8000000`. Do
  not reuse vendor RAM symbol addresses in a programmer or LogicROM session.

## 3. The RAM programmer

- **Pinned build:** the SDK's `usb_8955_flsh_spi32m_ramrun` without its 104 MHz clock
  request and with 200 mA charging, SHA-256
  `c238911dc478363b1dffdebbffcc407e6e1b1b51ef5c53c9d90ca2fe8bff6c65`
  (`firmware/live/usb-programmer-build/clean/artifacts/…_noclk_200ma.lod`). Audit it with
  `tools/rda_lod_audit.py`.
- **Why the stock build fails:** `hal_SwRequestClk(104M)` runs without the clock framework
  initialised (this build skips `hal_Open`; `BOOT_MONITOR_NO_HAL_OPEN`), so READY is never
  reached. The unmodified build `8a3ea625…8af9dd1` is refused by the writer. The entry
  point is `boot_Sector`, not the loader.
- **What startup touches:** it applies no board pin setup and switches no supply by GPIO;
  switchable regulators start off, USB stays on. It tests PSRAM, resets the flash chip
  (`66`/`99`), reads JEDEC `9f` and SR2 `35`, and may set the QE bit. So the programmer is
  not a strictly read-only reader, and matching array data does not show unchanged status
  registers.
- **Flash startup order** (read): `boot_MemInit` sets 26 MHz and `boot_SysSetupPLL`
  (`0x81c01640`: lock PLL, enable fast output, write **zero to `Sel_Clock`** `0xa1a00048`, so
  fast sources including SPI flash are selected), then `memd_FlashOpen` → `hal_SpiFlashOpen`
  runs **before `main()`**: writes `9` to `Cfg_Clk_SpiFlash` (`0xa1a000ac`; nominal 156 MHz
  source, divider 2 → 78 MHz) and `0x291` to `spi_config` (`0xa7fff014`), then flash reset,
  JEDEC, SR2, conditional QE. `main()` opens it again at `0x81c02118`.
- **Mailbox ABI:** protocol `FA01/FB05`; two 20-byte command descriptors, three buffer
  pointers; commands alternate between the two slots only after `DONE`, each slot checked by
  a serialized ping. Commands: `FPC_PROGRAM` 1, `FPC_ERASE_SECTOR` 2, `FPC_END` 4 (may set
  boot magic: treat as a flash write), `FPC_CHECK_FCS` 5 (extra verification only). The
  SDK header warns of 16-bit size truncation; keep the conservative 4 KiB program limit.
  Check the loaded ABI rather than guessing addresses.
- **Geometry:** erase 64 KiB below offset `0x3f0000`, 4 KiB above, stopping at `0x3fa000`.
  Use the pinned geometry, not the LOD metadata's sector map.
- **Flash chip:** JEDEC `c8 60 16` (GigaDevice, 4 MiB, writer ID `0x1660c8`), from the vendor's
  cached bytes at `0x81c01f51..53` and then measured through a live SPI transaction at
  18:24:15 UTC. Exact part revision and QE/status semantics are not established.

## 4. Writing and restoring

### 4.1 Tools

- `tools/rda_programmer_start.py` is the hardware-exercised orchestration path. Offline
  validation by default; `--execute` performs live work. Modes: `--query`, `--write-test`,
  `--reset-test`, `--blank-word-test`/`--blank-word-stop`, `--trial`, `--finish`,
  `--repair-tail`, `--read-status` (with `--from-rom`), `--clear-protection`. After execute,
  the host sends only memory reads unless a mode adds mailbox commands.
- `tools/rda_flash.py` is the underlying writer: offline plan by default, `--execute`
  needed for USB, pinned to the clean programmer, with a separate qualification gate.
- `tools/rda_logicrom_image.py` builds the unit-bound Logicrom trial image offline.

### 4.2 Rules the code enforces

- Default to a local plan: target identity, source hash, changed sectors, erase footprints,
  program chunks, verify steps. Execution is explicit. A plan with no changed sector writes
  nothing and proves nothing about the writer.
- **Hard-deny any erase/program/finalization footprint intersecting `[0x3fa000, 0x400000)`**
  (RF calibration and factory data). A 64 KiB erase at `0x3f0000` crosses it and is
  forbidden. No chip erase, no factory write, no generic memory-write CLI, no force override.
- Read and compare the protected tail with the unit's own backup first; abort on mismatch.
  Never substitute another unit's tail. USB VID:PID and the generic serial string are not
  unit identity: the factory block's IMEI is (digits 5–14 are the label ID).
- All images are exactly 4 MiB; the target has boot magic `0xd9ef0045` and the backup's bytes
  in the protected tail.
- Program changed non-boot sectors first and **sector zero last**, with the first boot word
  left erased while sector zero is programmed. A full 4 MiB comparison must pass before
  `FPC_END` writes that word, and another follows. If sector zero is unchanged, `FPC_END`
  is not sent.
- Keep an append-only journal under gitignored `firmware/live/` (new directory every time,
  fsynced) with the original bytes of each changed sector before the destructive step.
  Recovery after an uncertain command starts with a fresh read. Recovery points at the
  **installation** journal, never a failed restore journal.
- Stop on any failed transfer, deadline, disconnect or verification failure. Never retry an
  erase or program blindly; stopping the host cannot stop a device already erasing.

### 4.3 Restore and flash protection

- `--finish INSTALL_JOURNAL` restores changed sectors from the installation's pre-start
  snapshot, block 0 last, then writes the boot magic. After the vendor firmware boots again
  compare code and protected tail separately: legitimate settings writes change the full
  hash (the 412 backup and the pre-start image differ for that reason).
- **Erase can silently fail.** After a Logicrom core run the flash status registers can read
  SR1/SR2 `0x1c/0x02` (all blocks protected): the erase then reports DONE in 1 ms and nothing
  is erased. Never equate DONE with an erase; verify erased contents before programming.
  `--read-status` reads both registers; `--clear-protection` accepts only `0x1c/0x02` and
  changes it to `0x00/0x02` (preserving QE). It recurred after one vendor restore and was
  cleared the same way. The cause is unproved: "RST while the core runs sets it" is a
  hypothesis (locked runs ended with RST, later natural-reset runs stayed unlocked).
- `--repair-tail` was a specifically reviewed recovery of the first bad-core trial, not a
  normal path. Do not bypass the protected-tail check.
- Keep the blank boot word while diagnosing. Permanent boot needs its own reviewed path.

### 4.4 Using `rda_flash.py` offline

```sh
.venv/bin/python tools/rda_flash.py --unit 1403167417 \
  --backup firmware/backup/v24_1403167417_2026-10-03_flash.bin \
  --image  firmware/backup/v24_1403167417_2026-10-03_flash.bin
.venv/bin/python -m unittest discover -s tools -p test_rda_flash.py -v
.venv/bin/python tools/rda_lod_audit.py \
  firmware/live/usb-programmer-build/clean/artifacts/usb_8955_flsh_spi32m_ramrun_noclk_200ma.lod
```

The first prints `OFFLINE_PLAN`, the image hashes, `sectors: []` and
`hardware_validated: false`: a no-change example that neither erases nor proves recovery.
`--current` compares another local snapshot with the target. Execution needs one device
already in `Coolsand Usb` ROM mode; the writer checks the handshake and ROM hash, makes two
matching full reads, plans from the live bytes, and the post-startup JEDEC check cannot
protect against startup QE writes. It leaves the device in the programmer; it does not
reboot it.

### 4.5 The qualification gate in `rda_flash.py`

The gate wants five reports (`two_matching_backups`, `repeatable_rom_access`,
`board_ram_power`, `flash_chip_and_startup`, `experiment_review`) each with
`result: "pass"` and a named reviewer, bound to the exact unit, baseline, target, ROM and
programmer hashes, in `firmware/live/<case>/qualification.json`
(`schema: 1`, `scope: "spare_writer_test"`, `flash_jedec_id` as the integer
`manufacturer | type << 8 | capacity << 16`, so `0x1660c8`). Hash checking establishes file
integrity, not truth; check offline with `--qualification … --check-qualification`.
**Whether this gate is still the intended route is not recorded**: the installs and
restores that actually ran went through `rda_programmer_start.py`, which has its own pinned
allowlists. The full report descriptions and schema live in
[the archived writer guide](../done/26-10-08-flash-writer.md#qualification-evidence-still-needed).

## 5. SPI controller and clock facts

| `spi_config` field | ROM state `0x8a0` (measured) | Programmer `0x291` (compiled) |
| --- | --- | --- |
| Quad main-array read, bit 0 | off | on |
| WP/HOLD, bits 1/2 | clear | clear |
| Sample delay, bits 4–6 | 2 | 1 |
| Bypass start command, bit 7 | on | on |
| Divider, bits 8–15 | 8 | 2 |
| Receive-size mode, bits 17–18 | 0 | 0 |

JEDEC receive uses block `0x300` and config `0x608a0` (ROM base) or `0x60291` (programmer
base), FIFO clear 3, one command `0x19f00`. SR1 is `0x10500`, SR2 `0x13500`, security read
`0x14800`.

ROM clock snapshot at 17:20:27 UTC (measured, 412 idle in ROM): `Pll_Ctrl` `0x1011`,
`Sel_Clock` `0x5f16` (SPI slow-select bit 10 **set**), `Cfg_Clk_SpiFlash` `2`,
`Clk_Other_Enable` `0x1fffff`, `Sys_Rst_Set` `0x7fffffff` (SPI bit 23 out of reset),
SPI block/config/status `0x100`/`0x8a0`/`0x40a`, ROM USB-context pointer (`0xa1c001d8`)
`0xa1c0eeb4` (`0x1114` bytes, top of internal SRAM).

- ROM's `boot_HostUsbClockEnable` powers the PLL for USB but writes neither `Sel_Clock` nor
  `Cfg_Clk_SpiFlash`, so USB working says nothing about the SPI source or divider.
- **Reset readback polarity:** read 0 = in reset, read 1 = out of reset (the first
  snapshot's `spi_reset: true` label was wrong; the decoder is fixed).
- **ROM "word writes" are byte stores.** The ROM USB decoder (`0x81e034a4`) and the
  read-reply generator (`0x81e030ba`) call `memcpy`, whose mask-ROM implementation
  (`0x81e03b10`) uses a byte loop for every size below 16 bytes. A nominal four-byte write
  of `0x19f00` becomes four `sb` to `0xa7fff000–03`, and a four-byte read four `lbu`. The HAL
  and RAM helpers use aligned `sw`/`lw`. So the direct-ROM-MMIO path is not an equivalent
  controller transaction. Whether the peripheral honours byte stores is unmeasured.
- Do not read the SC critical-section register `0xa1a01014` (the read changes interrupt
  state) and prefer controller ranges `0xa7fff000–004` and `0xa7fff00c–034` to skip the FIFO
  data port at offset 8.
- A legacy write of `0x210` to `0xa1a25014` appears in boot memory init; its alias and
  necessity are not established. Do not add it to an allowlist from the source comment.
- Copying `hal_SpiFlashOpen` wholesale would add a flash reset and possibly a nonvolatile
  QE write.
- The earlier host simulator succeeds with both `0x8a0` and `0x291`, so it cannot qualify a
  config change: it does not model clock sources, sampling, reset or stuck bus loads.

## 6. Returning helpers through the ROM monitor

A helper that returns control to the ROM (instead of replacing it like the programmer) is
how the security register was read. What the failures taught:

### 6.1 The `0xff` executor cannot return (measured + read)

The USB execute command with context `cmdType = 0xff` sends `ff000004`, calls
`boot_HstMonitorX` (`0x81e002d0`), then sends `ff000005`. `boot_HstMonitorX` stores `ra` on
the cached KSEG0 stack and executes `cache 2,0` (`0xbc000002`, `boot_InvalidDCache`, not the
write-back `0xbc000003`), so the dirty line holding `ra` is discarded and the executor
returns to a stale address. The USB path does no flush (only the debug-IRQ path does).
**`Cache_Control` (`0xa1a2b444`) measured `0` at 18:07:40 UTC: `Dcache_Inhibit` clear, data
accesses cached, so the hazard stands.** The programmer survives because `boot_Sector`
never returns. A private stack does not help: the return address is saved before the switch.
The 40-byte SRAM-only control timed out at 17:26:19 UTC with `ff000004` and no `ff000005`
for exactly this reason. The two RAM security readers used the same arm and timed out the
same way; the cache hazard is a sufficient explanation, not shown separately for them.

### 6.2 The `0xfc` extended handler returns (read + measured)

- Context block `boot_HstMonitorXCtx` at `0xa1c000a0` (five words: `cmdType` +0, `pc` +4,
  `sp` +8, `param` +0xc, `returnedValue` +0x10). The handler pointer is the word at
  `0xa1c000b4`. Set `cmdType = 0xfc` and the handler word to the helper; the packet's
  trailing byte stays `0xff`, execute packet `ff 84 05000000 ff`.
- The ROM dispatch (`0x81e03434–5e`) sends `ff000004`, loads `cmdType`, and for any value
  other than `0xff` calls the handler through `jalr s1` with `a0 = &ctx`, then sends
  `ff000005` unconditionally. No cache operation occurs on this arm, so the cached return
  address survives. The register return is discarded; read the SRAM result block instead.
- **Rules for a helper:** execute from uncached `0xa1c01000` (MIPS32, even address); result
  at `0xa1c02000`; **if it has a stack frame, switch `sp` to the private KSEG1 stack
  `0xa1c04000` on entry and restore it exactly** (the ROM does not switch it; stub
  `firmware/logicrom/rom_jedec_entry.S` / `rom_security_entry.S`, which fetches its argument
  from `ctx.param` at `0xa1c000ac`); callee-saved registers preserved; **build with the
  SDK's reduced-register flags** (`REDUCED_REGS_FLAG`: no `t3–t7`, `s2–s7`, `fp`) and
  explicit little-endian MIPS32. The first security-reader build omitted the flags and its
  hash `9b1b6b7a…40923` must never be replayed.
- **Guards the host applies** (`tools/rda_spi_probe.py`): baseline validation, pinned ROM
  hash, allocation separation, two full flash reads before and two after, controller and
  clock equality, exact SRAM load and context readback, journal prerequisite for each
  stage. Checkpoint events `53500001–53500004` (entered, pre-command, readback done,
  restored) bracket the SPI work. Offline audits
  (`tools/audit_rda_rom_probe.py`, `audit_rda_rom_execution.py`,
  `audit_rda_spi_initialization.py`) execute the compiled instructions with delay slots; they
  prove modelled CPU behaviour, not electrical behaviour.

### 6.3 Live record on 412, 2026-10-10

| Time (UTC) | Step | Result |
| --- | --- | --- |
| 16:41:49, 16:50:53 | RAM security reader, then the reduced-register-corrected build, via the `0xff` arm | Execution acknowledged, no return event; RST needed |
| 16:54:36 | Direct ROM MMIO JEDEC (`rda_security_mmio.py`) | Controller read timed out after `0x19f00`; opcode `48` never sent |
| 17:20:27 | Read-only clock/controller snapshot | Table in §5; flash unchanged |
| 17:26:19 | 40-byte SRAM control via `0xff` | `ff000004` only |
| 18:07:40 | `Cache_Control` read | `0` |
| 18:15:52 | 40-byte control via `0xfc` | both events, marker `RTN1`, flash unchanged |
| 18:24:15 | Stack-switched JEDEC via `0xfc` | error 0, `0x1660c8`, one command, all settings restored |
| 18:47:12 | Security read via `0xfc` | error 0, 133 commands, two equal 256-byte passes, **all `ff`** (SHA-256 `3d6876a0146de8576eb2395a858de1213d1b92c65b779df3a331cfd5a4584546`); SR1/SR2 still `0x1c/0x02`; flash unchanged |

Each ended with two full reads equal to `b1dc8ccc…71b47d` and the unit still in ROM with the
blank boot word. The live entry points of the failed readers (`rda_security_read.py`,
`rda_security_mmio.py`, the `0xff` arms) are disabled; `--security-fc` is disabled again.
Each future live run needs its own go. Journals are under
`firmware/live/2026-10-10-logicrom-412-*`.

## 7. Operating traps

- Reads can run beside the vendor app, but check for competing libusb clients
  (`rda_*`, `logicrom_console`, `tracker_ui` processes) before any live work. During CDC
  enumeration observe from the Mac side instead of opening competing handles.
- The single permitted `Reset_Cause` read on the original `1403167417` is done; do not repeat
  it. `rda_flash.py` and `rda_programmer_start.py` keep their block on replacing the
  original's vendor code.
- Do not run a returning helper, a programmer or an erase on a unit whose identity was not
  confirmed by the per-unit tail check: one wrong-unit install was caught that way (417 was
  on the cable instead of 412).
- No RST, unplug or power button during a writing operation. Distinguish an automatic reset
  from an operator reset on long observations.
- Firmware images and logs carry unit identifiers and private radio data: link the
  evidence, never paste or commit binary dumps into notes.
- External RAM read after a reset is not retained state (`ff 11 55 aa` pages); a capture
  method must be demonstrated first.
