> **Archived 26-10-11.** The current, reconciled account is [rom-flash-access.md](../knowledge/rom-flash-access.md). This note is kept as the dated record of the work; statements here may be superseded there.

# 412 license measurement — console attempt and RAM reader

**Latest result, 18:47:12 UTC: license record blank.** The reviewed `0xfc`
security helper returned successfully (error 0, 133 commands) with two identical
256-byte passes, all `ff`. Final verification at 18:48:14 UTC found all four
main-flash reads unchanged and clocks/persistent controller settings restored;
412 remains in ROM with its boot word blank. [Live result](26-10-10-rom-extended-handler.md#security-read-through-this-arm--passed-at-184712-utc),
[journal](../../firmware/live/2026-10-10-logicrom-412-security-fc-1/operations.jsonl).
Normal activation is a demonstrated prerequisite under the traced validator;
the failed attempts below are historical. No activation was attempted.

## Console run (measured)

The user authorized the license investigation and returned connected 412 to ROM.
At 16:31:42 UTC on October 10 the ROM handshake and pinned 24 KiB ROM hash passed.
Two complete 4 MiB reads were identical, SHA-256
`98db5d86b3c3bef7159b6535e7d2fae2b5dd6e445b78d5e29e08f3f7e059fc28`.
Core/application equal installed diagnostic v2; boot word is blank and the tail
matches 412's own backup. No firmware replacement, reset, or SRAM load was sent.

The capture was ready before one ROM exit at **16:32:44 UTC**. It opened CDC at
115200 8N1 with DTR and RTS both verified on, and sent exactly `secr\r` at
16:32:48 UTC. It received 7,759 bytes: 7,711 zeros and these readable bytes:

```text
secr
NW: SIM card ready
NW: GSM - Registered
```

There was no security hex dump. CDC disappeared at 16:32:56 UTC, about 9.8 seconds
after enumeration; capture ended at 16:34:44 UTC. **License presence or acceptance
is still unknown.** The GSM registration line is new measured core output; GPRS,
TCP, activation, and our application execution remain unproved.

[Evidence](../../firmware/live/2026-10-10-logicrom-412-license-secr-1/operations.jsonl)
and [raw capture](../../firmware/live/2026-10-10-logicrom-412-license-secr-1/console.jsonl).
The ordinary core start can write runtime storage; this was not an entirely
storage-immutable boot. No install/restore cycle was repeated.

## Independently audited RAM reader

The fallback is a **returning ROM helper**, not the flash programmer. It links
only [security_reader.c](../../firmware/logicrom/security_reader.c), with no SDK
startup, libraries, flash writer, UART, power, or clock setup. It does not call
`hal_SpiFlashOpen` or set QE. The four SPI commands are `9f` JEDEC, `05` SR1,
`35` SR2, and `48` security read. There is no write-enable, status write,
security program/erase, or main-array program/erase path.

The corrected payload is 1,320 bytes, SHA-256
`444591d19fafc0db085cee0f568897af7d4a1b23afa63b12b37d2a358df12a1f`.
It is explicit little-endian MIPS32 at `0x81c00280`, result at `0xa1c02000`
(564 bytes), and private stack top `0xa1c04000` (160-byte stack reserve).
The ROM execution context is at `0xa1c000a0`; its saved ROM stack is separate.
The pinned 24 KiB ROM's executor at `0x81e002d0–328` was inspected: it preserves
the caller stack in s0, selects context SP, invalidates instruction cache,
calls context PC, writes v0 at context +16, and restores its caller stack.
The corrected build uses the SDK's required reduced-register ABI, with no t3–t7,
s2–s7 or fp. It preserves used callee-saved registers and SP. The helper returns
error zero on success.

The SPI sequence follows `hal_SpiCmdWithRx` and `hal_SpiFlashSecurityRead` in the
existing SDK. Each 4-byte security read sends opcode `48`, three address bytes
and one dummy byte, for addresses `0x1000–0x10fc`. Two complete 256-byte passes
are retained separately. All busy waits have finite loop guards. JEDEC must be
`c8 60 16`, WIP/WEL clear; SR1/SR2 must remain equal before/after. Controller block
size/config and interrupt critical-section state are restored. A timeout records
an error and partial lengths; it cannot be classified as a blank record.

Build uses the existing pinned local compiler image with networking disabled,
the toolchain mounted read-only, and only the reader staging directory writable.
The initial offline build's big-endian default was caught and corrected before
any device run. Only the hash above is the reviewed payload.

[Binary audit](../../tools/audit_rda_security_reader.py) simulates the **actual
compiled instructions**, including delay slots, ABI preservation, MMIO stores,
SPI transaction framing, byte order, and restoration. Blank and present records,
temporary controller busy, wrong JEDEC, WEL set, and a busy timeout all passed
expected outcomes. The timeout simulated 14,000,107 instructions, issued no SPI
command, returned an error, and restored the caller state.
All 128 security transactions have exact addresses/counts. Unknown instructions,
memory destinations, and SPI commands are rejected by the simulator. This is an
offline model based on the SDK, not hardware proof. Disassembly, ELF, map, hashes
and `audit.json` are under
`firmware/live/usb-programmer-build/security-reader-2026-10-10/build/`.

[Host runner](../../tools/rda_security_read.py) sends only a handshake, reads, an
exact verified SRAM payload/result-prefill/context, and **one returning execute**.
It does not send reset, ROM exit, core start, or any flash mailbox command.
It first verifies ROM, two equal full flash reads, installed core/app, blank word,
and 412's unit-specific tail. It requires execution and return events, zero return
value, a complete result, two equal security passes, equal flash status, restored
controller settings, and two unchanged complete post-reader flash reads.
Host allowlist and rejection of incomplete/unequal results were checked offline.
The binary audit now additionally rejects any use of SDK-reserved registers.

### First helper attempt failed; corrected offline

At 16:41:49 UTC the first helper's SRAM readback passed and ROM acknowledged
execution. No return event arrived within five seconds; the runner stopped.
A separate memory-only follow-up could not obtain the device's ROM interface
descriptor, so no result bytes were recovered. It did not execute again.

The first build had omitted the SDK's `REDUCED_REGS_FLAG`, using s2–s7 and fp.
That violates `compilerules.mk:1524–1544` and is a candidate for its failure;
the actual stopping instruction is unmeasured. This was an avoidable build error.
Its payload hash was
`9b1b6b7a3bed4a125e690e68b68abe00c1d26a5de9b1e697fa54e57c37340923`.
The failed artifact is retained in
`firmware/live/2026-10-10-security-reader/failed-first-build/` and is rejected by
the corrected host audit requirement. Do not replay it.

The compiler flags have been corrected and the 1,320-byte payload above passes
both exact instruction simulation and the new reserved-register check. A fresh
RST and separate run are required; no firmware reinstall is involved.

Prepared separate run:

```sh
.venv/bin/python tools/rda_security_read.py --execute \
  --journal firmware/live/2026-10-10-logicrom-412-security-read-2
```

It leaves the blank-word installation in ROM. A blank first 96 bytes means the
core's reader supplies length zero and its validator returns 14; activation is
then a demonstrated prerequisite. A present record requires binding/validation
investigation. No activation service or Waybyte contact is authorized here.

## Corrected helper also timed out; direct ROM MMIO fallback

At 16:50:53 UTC the corrected helper load verified and execution was acknowledged,
but no return event arrived. After user RST, a memory-only peek verified the ROM
hash again at 16:51:47 UTC. The execution context/result had unusable bytes, not
helper magic or a complete record; no license inference is supported. Correcting
the register ABI did not resolve the stopping condition. Neither helper is
qualified for further execution; their hardware failure remains unresolved.

The next fallback uses [rda_security_mmio.py](../../tools/rda_security_mmio.py), sending
no executable payload. ROM memory writes operate the SPI controller's command,
FIFO, block-size and configuration registers. The exact write allowlist permits
only the four receive commands `19f00`, `10500`, `13500`, `14800`, FIFO clear 3,
FIFO bytes 0–255, and original/read-size controller config values. It refuses
flash addresses, status/erase/program opcodes, reset, execute and exit.

The SDK's ROM decoder converts ordinary writes to KSEG1 and memcpy stores their
four-byte data. Its read packet generator reads from the uncached address. The
host uses word-write command `82` and exact 4-byte read requests. The sequence is
the same nominal SPI framing as the audited helper, now issued stepwise by ROM.
**Subsequent compiled-ROM audit found an access-width difference:** its four-byte
`memcpy` path performs four byte accesses, whereas the helper/HAL use word MMIO.
The direct path therefore is not an equivalent controller transaction. See the
[completed offline comparison](26-10-10-spi-initialization-comparison.md).
No read of the SC interrupt-disable register is needed: ROM is idle between host
requests and no other application is running. All busy checks are bounded.

Two equal full flash reads, pinned ROM, blank boot word, core/app and 412 tail are
required before the first controller write. A JEDEC read and SR1/SR2 precede any
security read. Two 256-byte security passes must match. Original config/block
size are restored and verified after each transaction; status must match; two
complete flash reads must remain unchanged. Simulation checked blank/present
data, correct addresses/byte order, status and configuration restoration.

### Direct ROM MMIO result: stalled on JEDEC before security read

The direct MMIO run started at 16:53:35 UTC. Two equal full flash reads passed;
all main flash still equalled `b1dc8ccc…71b47d`, including after both failed RAM
attempts and their RST recovery. Controller reset state was block size `0x100`,
config `0x8a0`. At 16:54:36 the host wrote FIFO clear 3, block size `0x300`, RX
config `0x608a0`, then JEDEC receive command `0x19f00`. The following controller
read timed out. No JEDEC value was obtained, and no status read or **security
opcode `48`** was sent.
Controller restoration also timed out; the user then pressed RST.

This records a failure after nominal SPI receive submission without a RAM
payload or application startup. The subsequent access-width finding prevents
treating it as an otherwise equivalent HAL receive experiment. It does not
establish the precise hardware cause. Do not claim the register ABI correction
fixed the reader or infer a blank record from this failure.

Recovery verification started at 16:56:03 UTC with handshake and memory reads only.
The pinned ROM hash passed and controller block/config returned to `0x100/0x8a0`,
with busy clear. At **16:57:05 UTC**, both complete post-recovery flash reads
equalled the pre-MMIO snapshot, SHA-256
`b1dc8ccc2bb6ea1a26ee5bb353f7fff0627b65af34131a50a5d72b71be71b47d`.
Core/application and 412 calibration/factory tail are intact; boot word remains
blank; 412 is waiting in ROM. No further helper/controller experiment was run.
Neither the helper nor direct MMIO reader is hardware-qualified for reuse.

The initial offline comparison finds ROM controller config `0x8a0` versus the
SDK `hal_SpiFlashOpen` construction `0x291` (quad array-read bit, sample delay 1,
divider 2, bypass-start on 8955), before its chip reset and initialization. That
difference is an offline diagnostic lead, not a tested fix. Copying the entire
SDK startup would also reset the chip and may set nonvolatile QE, so it must not
be labelled a strictly read-only substitute. Resolve the command-controller
initialization and clock requirements before changing either disabled live path.

Evidence: [direct run](../../firmware/live/2026-10-10-logicrom-412-security-mmio-1/operations.jsonl),
[recovery](../../firmware/live/2026-10-10-logicrom-412-security-recovered-1/operations.jsonl).
**412's license state remains unmeasured.** No firmware flashing, activation,
Waybyte service call or support contact occurred in this investigation.

## Offline comparison completed after recovery

[SPI initialization and ROM access-width comparison](26-10-10-spi-initialization-comparison.md)
checks the actual pinned programmer LOD/ELF and measured ROM. Its 16 checks passed.
The working programmer selects the fast SPI source in `boot_SysSetupPLL`, writes
frequency selector 9 and config `0x291`, and resets the chip before JEDEC. The
readers preserved ROM config `0x8a0` without establishing that startup. Bypass
start-command is already enabled in both configs; the changed fields are divider,
sample delay and quad main-array read.

The pinned ROM's nominal four-byte controller writes and reads execute four byte
stores/loads through `memcpy`. The RAM helper and HAL use aligned word accesses.
This is a proven CPU-access difference; its peripheral bus effect remains
unmeasured. The earlier simulator accepts both configs because it does not model
clock/controller initialization or stalled bus accesses, so it cannot qualify a
correction. Bounded busy loops also cannot guarantee return if an MMIO access
itself stops completing.

No new device operation occurred in the comparison. Both failed live paths remain
disabled. The next measurement is fixed, read-only clock/reset/controller and ROM
USB-context ownership capture before preparing a one-command diagnostic. This
does not change the last verified hardware state or the unknown license state.

## Staged follow-up: SRAM-only return failed, recovered again

The [clock/context snapshot and staged probe](26-10-10-rom-jedec-probe.md)
subsequently measured PLL `0x1011`, SPI slow source (`Sel_Clock=0x5f16`), source
frequency selector 2, clocks enabled, SPI out of reset, and ROM USB context
`0xa1c0eeb4–0xa1c0ffc8`, separate from reader allocations.

At 17:26:19 UTC, an exact 40-byte uncached SRAM control containing only two SRAM
stores and a return was verified and ROM acknowledged execution. It did not
return. The single-JEDEC build was never loaded or executed. This demonstrates
that SPI access is not necessary to reproduce the returning-helper failure;
entry/executor/return behavior remains unresolved. All new execution paths were
disabled. No security bytes were read.

After one user RST, **17:28:53 UTC recovery verification** passed pinned ROM, two
full flash reads equal `b1dc8ccc…71b47d`, and stable restored clock/controller/context
settings. Core/app and 412 tail remain intact; boot word blank; 412 waits in ROM.
Next is an offline executor/interworking/cache audit, not another SPI command.
