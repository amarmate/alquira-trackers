# 412 ROM snapshot and staged JEDEC probe — 2026-10-10

## Read-only snapshot completed

At 17:20:27 UTC, the ROM handshake and pinned ROM hash passed. The controller
and clock/context snapshot was identical before and after two complete flash
reads. Both reads equal the prior recovery image, SHA-256
`b1dc8ccc2bb6ea1a26ee5bb353f7fff0627b65af34131a50a5d72b71be71b47d`.
Completion was recorded at **17:21:28 UTC**. Core/application and 412's protected
tail are intact; the boot word is still blank. No code, MMIO write, reset or exit
was sent in this snapshot.

| Register | Measured value | Meaning supported by the pinned definitions |
| --- | --- | --- |
| `Pll_Ctrl`, `0xa1a00044` | `0x1011` | PLL enabled and fast output enabled |
| `Sel_Clock`, `0xa1a00048` | `0x5f16` | PLL lock set; SPI slow-select bit 10 set |
| `Cfg_Clk_SpiFlash`, `0xa1a000ac` | `2` | Fast-source selector is 52 MHz, presently bypassed by SPI slow selection |
| `Clk_Other_Enable`, `0xa1a0003c` | `0x1fffff` | Both SPI clocks enabled, bits 19/20 |
| `Clk_Other_Mode`, `0xa1a00038` | `0x1fffff` | Raw readback retained; mode fields above bit 9 are not defined by this header |
| `Sys_Rst_Set`, `0xa1a00004` | `0x7fffffff` | SPI bit 23 is **out of reset** |
| SPI block/config/status | `0x100` / `0x8a0` / `0x40a` | Original baseline; controller idle |
| ROM USB context at `0xa1c001d8` | `0xa1c0eeb4` | Physical range `0x01c0eeb4–0x01c0ffc8`, length `0x1114` |

Reset readback has the opposite polarity from its write-one-to-set operation:
the pinned 8955 hardware XML explicitly says **read 0 = in reset, read 1 = out
of reset**. The first snapshot JSON's generated `spi_reset: true` label was
incorrect; the raw value is intact and the decoder has been corrected to
`spi_out_of_reset`. Do not diagnose an asserted SPI reset from that label.

The live ROM buffers are clear of the old reader's result and stack. This rules
out an overlap with that measured context, not every possible earlier execution
fault. The failed reader's stopping PC remains unknown.

[Snapshot journal](../../firmware/live/2026-10-10-logicrom-412-spi-snapshot-1/operations.jsonl)
and [raw/decoded snapshot](../../firmware/live/2026-10-10-logicrom-412-spi-snapshot-1/snapshot-before.json).

## New staged artifacts, independently of disabled readers

[rda_spi_probe.py](../../tools/rda_spi_probe.py) has three separate stages. It leaves
the failed security readers disabled and sends no flash mailbox command. Each
live probe verifies the ROM, controller/context ownership and two baseline flash
reads before an exact SRAM load, then requires checkpoints/return, restoration
and two unchanged post-probe flash reads. Requests are consumed before transfer;
no uncertain operation is replayed.

All new probe code executes from **uncached** `0xa1c01000`. The result is
`0xa1c02000`, 64 bytes; private stack top is `0xa1c04000`. These allocations are
below and separate from the measured ROM USB context and active stack near the
top of internal SRAM. The ROM execution context remains `0xa1c000a0`.

- [rom_return_probe.S](../../firmware/logicrom/rom_return_probe.S): exactly 40 bytes,
  ten MIPS32 instructions, no stack access, calls or MMIO. It writes only two
  SRAM words (`RTN1` and the argument `0x13579bdf`), returns `0x42505242`, and
  leaves callee-saved registers untouched. Binary SHA-256
  `90813fa73099e76bb82032c6b031e4269a0ae93e3bb6374c1fb69167344916c5`.
- [rom_jedec_probe.c](../../firmware/logicrom/rom_jedec_probe.c): 1,072 bytes,
  SHA-256 `d58e59d6312d888c1dff2da2708db89460e14fcf0246852e5f296bcfca23ed10`.
  It requires the measured baseline, changes **only SPI's source-select bit 10**
  from slow to fast, selects 156 MHz with frequency value 9, and establishes
  HAL config `0x291`. JEDEC mode uses block `0x300`, config `0x60291`, FIFO clear 3
  and exactly one command `0x19f00`. All controller/clock accesses are aligned
  word MMIO. There is no flash reset, write-enable, status write, security access,
  program/erase, PMD startup or system-clock request.

The JEDEC helper calls the pinned ROM USB event function `0x81e03169` at four
checkpoints: entered (`53500001`), immediately before command (`53500002`),
readback completed (`53500003`), restoration finished (`53500004`). Result fields
retain error and stage. A responding controller that remains busy has a finite
instruction guard; a stuck MMIO bus access can still prevent return.

Before exit, the helper restores block/config, SPI frequency and source selection,
sysCtrl protection lock and saved critical-section state. Exact controller/clock
readbacks and two full flash comparisons are required by the host. The simulator
does not establish flash electrical timing; these requirements distinguish a
successful measurement from a modeled transaction.

Build uses the existing pinned local compiler image
`99dd818d…ee0a939`, networking disabled, toolchain mounted read-only, and only the
new staging directory writable. The custom reduced-register flags and explicit
little-endian MIPS32 target are present. No old payload was overwritten.

[audit_rda_rom_probe.py](../../tools/audit_rda_rom_probe.py) executes the actual compiled
instructions with delay slots, rejects unknown instructions/stores/opcodes, checks
callee-saved state and reserved registers, and models the ROM event call with
caller-saved registers clobbered. Seven scenarios pass: SRAM return, successful
JEDEC, wrong chip, wrong argument, temporary busy, busy before the command, and
busy after the command that clears for restoration. Maximum modeled stack depth,
including ROM event/copy frames, is 152 bytes; 512 bytes are reserved.

[Build/audit report](../../firmware/live/usb-programmer-build/rom-probe-2026-10-10/build/audit.json).
This audit proves modeled CPU behavior, not electrical hardware behavior.

## Live stage outcomes

At **17:26:19 UTC**, the SRAM-only return control's code, result prefill and
execution context readbacks all passed. ROM acknowledged execution with
`ff000004`. No return event arrived in five seconds; the runner stopped at
17:26:24 UTC. The 40-byte control contains **no SPI or other MMIO access**.
Therefore the previous failures cannot be assigned solely to SPI initialization.
Whether the control reached its first instruction, wrote its marker, or stalled
inside ROM's executor/return path remains unmeasured.

The separate memory-only peek at 17:26:55 UTC could not obtain USB string
descriptors (`device has no langid`). No code, context or marker was recovered
before RST. The user pressed RST once after being asked. A fresh read-only
recovery completed at **17:28:53 UTC**: pinned ROM passed, both full 4 MiB reads
equal the pre-probe baseline `b1dc8ccc…71b47d`, and all measured clock/controller
and ROM-context settings are restored and stable. Core/application and 412's
factory/calibration tail are intact; boot word remains blank; 412 is waiting in ROM.

The single-JEDEC probe was **built and audited, but never loaded or executed**.
Its successful-return prerequisite was not met. Both new execution entry points
are now disabled, as are the original readers. The read-only snapshot entry
remains available. No security register, flash reset, status write, firmware flash,
activation service or Waybyte contact occurred.

[Return-control journal](../../firmware/live/2026-10-10-logicrom-412-return-control-1/operations.jsonl)
and [failed memory-only peek](../../firmware/live/2026-10-10-logicrom-412-return-peek-1/operations.jsonl).

[Post-RST recovery journal](../../firmware/live/2026-10-10-logicrom-412-return-recovery-1/operations.jsonl)
and [recovered snapshot](../../firmware/live/2026-10-10-logicrom-412-return-recovery-1/snapshot-after.json).

The successful programmer replaces ROM's execution environment. It does not
show that a helper can return through the original monitor. Another SPI
experiment is not justified by this control result. License presence and
acceptance are still unknown.

## Offline return audit

No device access in this step. The return-control and JEDEC entry points stay
disabled. The check is [audit_rda_rom_execution.py](../../tools/audit_rda_rom_execution.py);
its report is [audit.json](../../firmware/live/2026-10-10-rom-execution-audit/audit.json).
Nine modeled cases pass. `live_requests_sent` is 0.

The 40-byte control is launched with context command `0xff`, the same command
that starts the working programmer at `0x81c00280`. That command sends
`ff000004`, then calls `boot_HstMonitorX` at `0x81e002d0`, then sends
`ff000005`. The USB source does not flush the data cache on this path. The
debug-IRQ handler does: `boot_FlushDCache(TRUE)` runs before the same function.

`boot_HstMonitorX` stores `ra` and `s0` on the current stack, then executes
`cache 2,0`. That word is `0xbc000002`, identical to `boot_InvalidDCache`. It
is not the writeback operation `0xbc000003` used by `boot_FlushDCache`. The
invalidate is the eleventh instruction after that store. The instructions
between them do not call anything. Their only memory operations are loads from
the uncached context, so the 16-byte line is still dirty when it is discarded.

The 8955 SDK builds with `XCPU_CACHE_MODE_WRITE_BACK=1`. The data cache is
16-byte lines, 64 indexes, 4 ways. `Cache_Control` can inhibit it, but this
ROM image never mentions `0xa1a2b444`, and the hardware XML does not give
`Dcache_Inhibit` a reset value (`rst="no"`). That bit was not read on 412.

The ROM stack top constant is `0x81c0fffc`, in cached KSEG0. The context block
`0xa1c000a0` and the helper at `0xa1c01000` are KSEG1, so their accesses bypass
the data cache. Giving the helper the live private stack `0xa1c04000`, or a
zero stack that means "keep the current pointer," does not move the saved
return address. The function saves it before the stack switch, keeps the old
pointer in `s0`, and reloads `ra` from the cached frame afterward.

Under the write-back assumption the helper still writes `RTN1` and its
argument, and it returns to `0x81e00310`. The executor then jumps to the stale
word that was in SRAM. The model seeds that word so the loss is visible; it is
not a PC measured on 412. The end event is not reached. Only `ff000004` is
sent. That is the same shape as the 17:26:19 UTC timeout. A flush before the
invalidate, or a caller stack already in KSEG1, lets the model reach
`ff000005`.

The programmer survives this sequence because `boot_Sector` does not return to
`boot_HstMonitorX`. The discarded monitor address is never reloaded.

There is a second arm in the same USB command. If the context command is not
`0xff` and `boot_HstMonitorExtendedHandler` at `0xa1c000b4` is non-zero, the
monitor calls that pointer with `jalr` and then sends the end event. The named
value is `0xfc`. The model runs the 40-byte control through that MIPS16-to-MIPS32
call and back, and it reaches `ff000005`. A null handler also reaches the end
event without entering the helper. This path was not sent. The bodies of the
USB event functions are not CPU-emulated, and the inhibit bit is still unknown.

The deciding read, before any returning helper, is `Cache_Control` at
`0xa1a2b444`. Bit 0 set means data accesses are uncached and this hazard does
not apply. Bit 0 clear leaves the write-back explanation standing. Do not load
the JEDEC probe, and do not send the extended handler, until that read or a
reviewed return path exists. **Measured 18:07:40 UTC: bit 0 is clear — see
below.**

## Cache_Control measured — 2026-10-10 18:07 UTC

[Journal](../../firmware/live/2026-10-10-logicrom-412-cache-control-1/operations.jsonl)
and [snapshot](../../firmware/live/2026-10-10-logicrom-412-cache-control-1/snapshot-before.json).
The read-only snapshot path (`rda_spi_probe.py --read`) was extended with one
word, `cache_control` at `0xa1a2b444`, inside its existing fixed scope. No
load, execution, MMIO write, SPI command, reset or exit was sent.

| Register | Value | Decode |
| --- | --- | --- |
| `Cache_Control`, `0xa1a2b444` | `0x00000000` | `Dcache_Inhibit` **clear**, `Icache_Inhibit` clear, `Cache Hit Disable` clear |

Bit 0 clear means data accesses are cached. Under the 8955's write-back
configuration the hazard stands: `boot_HstMonitorX`'s `cache 2,0` discards the
dirty KSEG0 stack line holding `ra`, and the `0xff` context command cannot
return from a helper. The 17:26:19 UTC timeout is now explained by a measured
register, not only a model assumption. Every other snapshot word matched the
17:20:27 UTC baseline, the before/after snapshots were identical, and both
flash reads equal `b1dc8ccc…71b47d`. The unit remains in ROM, boot word blank.

Consequence: the `0xff` return path stays disabled. The next candidate is the
extended `0xfc` handler path (`0xa1c000b4`), which skips the invalidate in the
model and reaches the end event. It has not been sent. It first needs an
offline review of its wire format and the MIPS16-to-MIPS32 entry, and its
first live use is the 40-byte SRAM control, not JEDEC. **Review completed
later on 2026-10-10: [26-10-10-rom-extended-handler.md](26-10-10-rom-extended-handler.md).
Validated live at 18:15:52 UTC — the `--return-control-fc` control returned
both events with the expected markers and unchanged flash. **The
stack-switched JEDEC variant then passed live at 18:24:15 UTC** (`--jedec-fc`,
[journal](../../firmware/live/2026-10-10-logicrom-412-jedec-fc-1/operations.jsonl)):
error 0, JEDEC `0x1660c8` through a live transaction, one command, full
restoration, flash unchanged. The original executor-arm JEDEC stage remains
disabled.**
