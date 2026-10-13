# Reviewed return path: the 0xfc extended-handler arm — 2026-10-10

**Validated live: return control at 18:15:52 UTC, JEDEC at 18:24:15 UTC,
and security read at 18:47:12 UTC. The two security passes are entirely `ff`;
final unchanged-flash verification completed at 18:48:14 UTC.** The review below was offline: nothing was sent to a
device in that work. The only live input was the already-recorded read-only
snapshot of 18:07:40 UTC
([journal](../../firmware/live/2026-10-10-logicrom-412-cache-control-1/operations.jsonl)),
which measured `Cache_Control` `0xa1a2b444` = `0x00000000` (`Dcache_Inhibit`
clear). That measurement promotes the write-back data cache from model
assumption to device fact, and confirms the `0xff` executor return path stays
disabled ([return audit](26-10-10-rom-jedec-probe.md)).

This note reviews the second arm of the same USB execute command — the named
extended command `0xfc` — as the candidate return path for helpers, per the
gate in the return audit. It covers the source semantics, the byte-pinned ROM
dispatch, the exact wire format of a first live control, the hazards, and the
staged (still disabled) tool mode.

## Source semantics (SDK `boot/8955`, pinned as audit inputs)

`include/boot_host.h`:

- `BOOT_HST_MONITOR_X_EXT_CMD = 0xfc`; `BOOT_HST_MONITOR_X_CMD = 0xff`.
- `BOOT_HST_MONITOR_X_CTX_T` is five words: `cmdType` (+0), `pc` (+4),
  `sp` (+8), `param` (+0xc), `returnedValue` (+0x10).
- `BOOT_HST_EXECUTOR_T` places `hstMonitorExtendedHandler` immediately after
  `hstMonitorXCtx`. Both live in section `.sram_hst_monitor_ctx`, so with the
  context at `0xa1c000a0` the `ExtendedCmdHandler` pointer is the word at
  **`0xa1c000b4`** — matching the literal the ROM dispatch loads.

`src/boot_usb_monitor.c` (H2P_STATUS write, packet byte `0xff`):

```c
case BOOT_HST_MONITOR_X_CMD:
    boot_HostUsbEvent(BOOT_HST_START_CMD_TREATMENT);        // ff000004
    switch(boot_HstMonitorXCtx.cmdType)
    {
        case BOOT_HST_MONITOR_X_CMD:
            boot_HstMonitorX();                             // 0xff: executor
            break;
        default:
            if (boot_HstMonitorExtendedHandler.ExtendedCmdHandler != 0)
                ((VOID(*)(VOID*))boot_HstMonitorExtendedHandler.
                 ExtendedCmdHandler)((VOID*)&boot_HstMonitorXCtx);
    }
    boot_HostUsbEvent(BOOT_HST_END_CMD_TREATMENT);          // ff000005
```

- The command is read from the **context block** (`cmdType`, word 0), not from
  the packet. The packet's trailing byte stays `0xff` to enter this case.
- Any `cmdType != 0xff` with a non-zero handler word takes the extended arm.
  `0xfc` is the named value; the dispatch does not compare against it.
- The handler is called with **`a0 = &boot_HstMonitorXCtx` (`0xa1c000a0`)**;
  its register return value is discarded (no `returnedValue` store).
- The end event is sent unconditionally after the switch, even with a null
  handler. The start event always precedes it — the exact `ff000004`-only
  shape of the 17:26:19 UTC timeout cannot occur here unless the handler
  itself never returns.
- **No cache operation appears anywhere in this arm.** The flush-then-execute
  ordering exists only in the debug-IRQ path (`boot_HstCmdBasicHandler` in
  `src/boot_host.c`), which is not the USB path.

## ROM dispatch, byte-pinned and disassembled

From the pinned ROM snapshot (SHA-256 in the audit inputs), Homebrew binutils
`objdump -m mips:16 -EL`:

```
81e03434: b476       lw   a0,0x81e0360c      ; a0 = 0xff000004
81e03436: 1b03 0c5a  jal  0x81e03169         ; START event
81e0343c: b475       lw   a0,0x81e03610      ; a0 = 0xa1c000a0 (&ctx)
81e0343e: 9ca0       lw   a1,0(a0)           ; a1 = cmdType
81e03440: 75ff       cmpi a1,255
81e03442: 6104       btnez 0x81e0344c        ; cmdType != 0xff -> extended arm
81e03444: 1f03 00b4  jalx 0x81e002d0         ; 0xff -> executor (cache hazard)
81e0344a: 1006       b    0x81e03458
81e0344c: b272       lw   v0,0x81e03614      ; v0 = 0xa1c000b4 (&handler word)
81e0344e: 9a60       lw   v1,0(v0)           ; null check
81e03450: 2303       beqz v1,0x81e03458      ; null handler -> end event
81e03452: 9a20       lw   s1,0(v0)           ; s1 = handler
81e03454: e940       jalr s1                 ; a0 still = &ctx; ra = 0x81e03459 (MIPS16)
81e03458: b470       lw   a0,0x81e03618      ; a0 = 0xff000005
81e0345a: 1001       b    0x81e0345e
81e0345e: 1b03 0c5a  jal  0x81e03169         ; END event
```

Literal pool at `0x81e0360c`: `0xff000004`, `0xa1c000a0`, `0xa1c000b4`,
`0xff000005` (pinned in the audit). The parser epilogue at `0x81e035d0`
restores `s0`/`s1`/`ra` from its own frame and returns — on the cached KSEG0
stack, which is correct under write-back **because nothing on this arm
invalidates**. `a0` is not reloaded in the extended arm, so the handler
receives the context pointer left over from the `cmdType` load — the same
argument the source passes.

The MIPS16 `jalr s1` enters the helper in the ISA selected by bit 0 of the
pointer: even address `0xa1c01000` → MIPS32. The helper's `jr ra` returns to
`0x81e03459` (MIPS16). The executor (`0x81e002d0`) is never entered.

## Hazards evaluated

| Hazard | Verdict |
| --- | --- |
| Cache invalidate/writeback on this arm | None — no `cache` instruction in the arm, the dispatch, or the event call path it uses. Write-back without invalidate is architecturally correct. |
| MIPS16→MIPS32 entry / return | Byte-pinned `jalr s1` with even target; helper returns to `0x81e03459` MIPS16. Modeled with delay slots in the audit. |
| Callee-saved registers | Handler pointer arrives in `s1`; the parser epilogue restores `s1` regardless. The 40-byte control touches no callee-saved register (pinned by `audit_rda_rom_probe.py`). |
| Stack | The ROM does **not** switch `sp` on this arm; the helper inherits the parser's KSEG0 stack. The 40-byte control performs no stack access. **Any future helper with a frame (the JEDEC stage) must switch to the private KSEG1 stack `0xa1c04000` itself at entry and restore `sp` before return.** That change does not exist yet. |
| `returnedValue` (context word 4) | Not stored by this arm; the host must read the SRAM result block instead. The staged tool expects exactly that. |
| Null/other handler values | `0` skips the call and still ends the command; other `cmdType` values take the same arm. The staged control uses the named `0xfc`. |

## Staged live control (implemented, disabled pending the user's go)

`tools/rda_spi_probe.py --return-control-fc` reuses the pinned 40-byte control
(SHA-256 `90813fa7…44916c5`) and the full probe guard set (baseline validation,
ROM hash, allocation separation, two before and two after flash reads,
controller/clock equality). It differs from the failed 17:26 control in
**two context words only**:

| Word | Address | 0xff control (failed) | 0xfc control (staged) |
| --- | --- | --- | --- |
| 0 `cmdType` | `0xa1c000a0` | `0x000000ff` | `0x000000fc` |
| 5 handler | `0xa1c000b4` | `0x00000000` | `0xa1c01000` |

The execute packet is unchanged: `ff 84 05000000 ff`. Expected device
behavior, from the source and the byte-pinned dispatch:

1. `ff000004` (start), then the helper runs from uncached SRAM, then
   `ff000005` (end) within the existing 5 s window.
2. Result block: `52544e31` at `0xa1c02000`, `a1c000a0` at `0xa1c02004`
   (the control echoes its `a0`), remaining 56 bytes `0xcc`.
3. Context unchanged after return; all clock/controller words unchanged; both
   post-run flash reads equal `b1dc8ccc…71b47d`.

The mode raises `RuntimeError` until the user's go for this run; enabling it
is deleting that guard and running with a fresh journal. Outcomes:

- **Events and result as expected** → a returning helper path exists. Next:
  adapt the JEDEC helper for the self-switched stack above, re-audit, then
  run it through this arm (its own go), followed by the security read for the
  license bytes.
- **`ff000004` without `ff000005`** → the model is wrong in a new way; stop,
  keep the unit in ROM, analyze offline. No automatic retry exists.
- Any checkpoint mismatch stops the run before further requests, as before.

## Audit status

`tools/audit_rda_rom_execution.py` now pins the measured snapshot
(`cache_control == 0`), the `boot_host.h` field layout and the `0xfc`
constant, the source arm's shape and its freedom from cache operations, zero
cache operations in every modeled direct/extended case, and the
context-pointer argument. All nine cases pass; report:
[audit.json](../../firmware/live/2026-10-10-rom-execution-audit-2/audit.json).
`live_requests_sent` is 0. The `0xff` executor path, the original readers and
the JEDEC stage remain disabled; the JEDEC stage additionally needs the
stack-switch change described above before it can use this arm.

## Live validation — PASSED at 18:15:52 UTC

Authorized by the user's go for this run. The disabled guard was removed and
the staged control ran with a fresh journal:
[operations.jsonl](../../firmware/live/2026-10-10-logicrom-412-return-fc-1/operations.jsonl).
Every expectation from the review was met:

- Both events arrived: `ff000004` then `ff000005`, within the same second.
- Result block: marker `0x52544e31` (`RTN1`) at `0xa1c02000`, echoed argument
  `0xa1c000a0` at `0xa1c02004` — confirming the handler was called with the
  context pointer, as the source said. Remaining 56 bytes `0xcc` untouched.
- Context after return byte-identical to the load (`cmdType 0xfc`, handler
  word `0xa1c01000`); this arm stored no `returnedValue`, as reviewed.
- Before/after snapshots identical (including `cache_control == 0`), all four
  full flash reads equal `b1dc8ccc…71b47d`, controller/clock words unchanged,
  unit remains in ROM with the boot word blank.

**A returning helper path now exists on 412.** The audit's
`extended-command-0xfc` case matched the device on every modeled point. Next
on this thread, each with its own go: add the self-switched private stack to
the JEDEC helper and re-audit, run JEDEC through this arm, then the security
read for the license bytes. The `0xff` executor path and the original readers
stay disabled.

## Stack-switched JEDEC helper — built and audited, staged disabled

The prerequisite recorded in the hazard table (the `0xfc` arm does not switch
`sp`) is now resolved. [rom_jedec_entry.S](../../firmware/logicrom/rom_jedec_entry.S)
is an 18-instruction entry stub: it saves the incoming `sp`/`s0`/`ra` on the
private KSEG1 stack, switches `sp` to `0xa1c04000`, fetches the argument from
`boot_HstMonitorXCtx.param` (`0xa1c000ac`) — keeping the arm-agnostic C body
unchanged — runs the body, then restores the incoming state exactly. Built in
the pinned compiler image: `jedec-fc.bin` is 1,144 bytes, SHA-256
`1fc6b2edf93f9b04f3b69753d636ad137bc880466e55882fa074e914179acdaa`. The
executor-arm artifacts reproduce byte-identically (`return.bin`
`90813fa7…4916c5`, `jedec.bin` `d58e59d6…23ed10`), so the
macro-parameterized source did not alter the reviewed binaries.

`audit_rda_rom_probe.py` now models the extended arm: entry with
`a0` = context pointer on the parser stack `0x81c0ee4c`, return to
`0x81e03459`, the context block readable, stores confined to the result block
and the private stack. All **13 cases** pass (7 previous + 6 `fc-`): maximum
modeled stack is 168 bytes of the 512 reserved, no store ever reaches the
parser stack, and `sp`/callee-saved state return exactly.
[audit.json](../../firmware/live/usb-programmer-build/rom-probe-fc-2026-10-10/build/audit.json).

`rda_spi_probe.py --jedec-fc` is fully staged: the same guard set as the
control, plus the JEDEC baseline register check and the validated
`return-fc` journal as a hard prerequisite. It stays disabled until the
user's go. Expected events: `ff000004`, `53500001–4`, `ff000005`; the result
block is checked by the existing single-JEDEC condition.

## JEDEC through this arm — PASSED at 18:24:15 UTC

Authorized by the user's go. [operations.jsonl](../../firmware/live/2026-10-10-logicrom-412-jedec-fc-1/operations.jsonl).
Every checkpoint fired in order — `ff000004`, `53500001` (entered),
`53500002` (pre-command), `53500003` (readback), `53500004` (restored),
`ff000005` — and the result block reports **error 0**:

- **JEDEC ID `0x1660c8` measured through a live SPI transaction** with the
  helper's own clock switch (slow→fast 156 MHz source-select change) and HAL
  config `0x291`/`0x60291`. This agrees with the cached vendor ID
  (`c8 60 16`, GigaDevice) and replaces it as the stronger evidence.
- Exactly one command (`commands = 1`); stage reached 4 (restoration done).
- Before/after block `0x100`, config `0x8a0`, clock `0x5f16`, frequency 2 —
  identical; all clock/reset/context words identical; persistent controller
  fields identical. The only after-snapshot differences are the volatile
  transaction leftovers: `command = 0x19f00`, `readback = 0x1660c800`.
- Context byte-identical to the load; all four full flash reads equal
  `b1dc8ccc…71b47d`; unit remains in ROM, boot word blank.

The SPI initialization sequence is now hardware-validated with a returning
helper. The remaining stage on this thread is the security read (opcode
`0x48`, security address `0x1000`) for the license bytes — a new helper
variant with its own audit and staging, now built and staged disabled (below).

## Security read through this arm — built and audited, staged disabled

Offline only; no device access in this step. [rom_security_entry.S](../../firmware/logicrom/rom_security_entry.S)
is byte-identical to the JEDEC entry stub except its call target (`jal
security_body`): same private-stack switch, same argument fetch from
`boot_HstMonitorXCtx.param`, same exact restore. [rom_security_probe.c](../../firmware/logicrom/rom_security_probe.c)
reuses the validated SPI init (slow→fast source-select change, frequency 9 for
nominal 156 MHz, HAL config `0x291`), then JEDEC + SR1/SR2 checks and two
complete 256-byte security passes (`0x48`, `0x1000–0x10fc`, 4 bytes per
transaction, dummy byte), then exact restoration. Result is 592 bytes at
`0xa1c02000` (20-word header + two 256-byte passes); magic `0x53454352`,
version 2. Error codes: 1 arg/baseline, 2 pre-clock idle, 3 JEDEC read, 4 wrong
JEDEC, 5 status read, 6 WIP/WEL, 7 security read, 8 post status read, 9 status
mismatch, 10 restore idle, 11 restore mismatch. Success is error 0, 133
commands, two equal passes. Built in the pinned compiler image:
`security-fc.bin` is 1,872 bytes, SHA-256
`3c89fc6197af76e9cf2fb8f44a029f4d3e6baf19fef6d4df5223cfdeeb685dbb`.
The three earlier artifacts reproduce byte-identically, so the build-script
addition did not alter the reviewed binaries.

`audit_rda_rom_probe.py` now models the security transactions (FIFO address
phase, per-count block/config framing, JEDEC/status/security readbacks, byte
loads/stores, `srlv`) with the same extended-arm entry/return and confinement
checks. All **21 cases** pass (13 previous + 8 `fc-security-`): blank-ff and
present records succeed with exact addresses/counts and equal passes,
temporary busy succeeds, wrong-argument/wrong-JEDEC/WEL/busy-before/busy-during
fail with the expected errors and command counts. Maximum modeled security
stack is 192 bytes of the 512 reserved; no store reaches the parser stack.
[audit.json](../../firmware/live/usb-programmer-build/rom-probe-fc-2026-10-10/build/audit.json).

`rda_spi_probe.py --security-fc` is fully staged: the same guard set as JEDEC
(two before/two after flash reads, controller/clock equality, baseline check),
plus the validated `jedec-fc` journal as a hard prerequisite
(`--jedec-journal`). It raises `RuntimeError` until the user's go for this run;
enabling it is deleting that guard. Expected events: `ff000004`,
`53500001–4`, `ff000005`; the result block is checked for error 0, JEDEC
`0x1660c8`, equal status with WIP/WEL clear, 256+256 bytes, 133 commands,
restored registers and two equal passes. The two passes are saved as
`security-1000-first/second.bin` with their SHA-256 and the
`first_96_all_ff` flag. Outcomes: all `ff` in the first 96 → the license
record is blank, activation is a demonstrated prerequisite; non-blank → a
record exists and the investigation becomes identity/validation.

## Security read through this arm — PASSED at 18:47:12 UTC

The user authorized this reviewed run after a safety check. The pinned binary,
all 21 probe cases, the ROM execution audit, all 16 SPI initialization checks,
the 14 console tests, recovery baseline and prerequisite JEDEC journal passed
before USB execution. The guard was removed for this one run and restored after
completion; additional runs still require their own go.

[operations.jsonl](../../firmware/live/2026-10-10-logicrom-412-security-fc-1/operations.jsonl).
Started at 18:46:10 UTC, helper executed once at **18:47:12 UTC**, and final
verification completed at **18:48:14 UTC**, exit 0:

- All six events arrived in order: `ff000004`, `53500001–4`, `ff000005`.
  Result magic/version/stage/error: `53454352` / 2 / 4 / **0**. Context
  byte-identical to the load; result stable across two SRAM reads.
- JEDEC **`0x1660c8`**, exactly **133 commands**, and **256+256 bytes**.
  Both passes are identical and **all 256 bytes are `ff`**, including the
  validator's first 96 bytes. SHA-256 of each pass:
  `3d6876a0146de8576eb2395a858de1213d1b92c65b779df3a331cfd5a4584546`.
  [First pass](../../firmware/live/2026-10-10-logicrom-412-security-fc-1/security-1000-first.bin),
  [second pass](../../firmware/live/2026-10-10-logicrom-412-security-fc-1/security-1000-second.bin).
- SR1/SR2 remain **`0x1c/0x02`** (`0x021c` combined); WIP/WEL both clear.
  Block/config/clock/frequency restored to `0x100/0x8a0/0x5f16/2`.
  All clock/reset/context words and persistent controller settings unchanged;
  only transaction leftovers differ (`command 0x19f00 → 0x13500`,
  `readback 0x1660c800 → 0x02020202`). No protection clear was sent.
- Two complete flash reads before and two after execution all equal
  `b1dc8ccc2bb6ea1a26ee5bb353f7fff0627b65af34131a50a5d72b71be71b47d`.
  Core/app and 412's own calibration/factory tail intact; boot word remains
  blank. Unit remains responsive in ROM. No flash/status/security write,
  reset or exit was sent.

**412's license record is blank.** The [traced reader and validator](../knowledge/logicrom-core.md#3-application-handoff-and-the-license-gate)
turn an all-`ff` first 96 bytes into length zero, then return 14; startup selects
the built-in descriptor instead of our application. This makes normal activation
a demonstrated prerequisite for this image. The runtime return code itself was
not captured in this run. USB timeout/console-output behavior remains a separate
issue, and a successful activation would not by itself prove those issues fixed.
No activation, registration or third-party contact was attempted.
