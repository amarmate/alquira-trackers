> **Archived 26-10-11.** The current, reconciled account is [logicrom-core.md](../knowledge/logicrom-core.md). This note is kept as the dated record of the work; statements here may be superseded there.

# LogicROM offline trace and next diagnostic image — 2026-10-10

Prepared offline. **No tracker was opened, reset, programmed or started in this work.**
412's last recorded state remains restored vendor firmware. The working SIM and
exclusion of Waybyte support remain settled decisions.

The exact 0.5.1 binary contains a **10-second enumeration timeout that closes USB**.
This is a strong candidate for the measured 9.9-second disappearance, not a measured
explanation yet. Separately, console transmission depends on CDC line state and the
network state machine has several distinct reset branches.

## Inputs and evidence

The pinned [core LOD](../../firmware/live/usb-programmer-build/logicrom/core_v0.5.1.lod)
has SHA-256 `0499c0e051f166e899daf13503c8d2b07ba65c884de047f17bb8f8cd38d31df7`.
It was reconstructed with `read_core()` and only the reviewed NVM format-size fix
was applied. Addresses below are virtual code addresses; subtract `0x88000000`
for flash offsets. MIPS16 function pointers have bit 0 set. Byte strings are in
ascending flash order, little endian, including call delay slots where shown.

The [address map](../../firmware/live/2026-10-10-logicrom-offline/address-map.json)
contains exact bytes for the trace points. Focused disassembly is saved beside it:
[USB enumeration](../../firmware/live/2026-10-10-logicrom-offline/usb-enumeration.txt),
[controller power](../../firmware/live/2026-10-10-logicrom-offline/usb-power.txt),
[suspend/boot power](../../firmware/live/2026-10-10-logicrom-offline/usb-sleep.txt),
[console](../../firmware/live/2026-10-10-logicrom-offline/console.txt),
[CDC events](../../firmware/live/2026-10-10-logicrom-offline/usb-logicrom-events.txt),
[network](../../firmware/live/2026-10-10-logicrom-offline/network.txt),
[reset](../../firmware/live/2026-10-10-logicrom-offline/reset.txt),
[other reset paths](../../firmware/live/2026-10-10-logicrom-offline/reset-other.txt),
[timer units](../../firmware/live/2026-10-10-logicrom-offline/timer.txt), and
[application selection](../../firmware/live/2026-10-10-logicrom-offline/app-selection.txt).
Additional evidence covers the [generic timer](../../firmware/live/2026-10-10-logicrom-offline/generic-timer.txt)
and [logout response](../../firmware/live/2026-10-10-logicrom-offline/console-command.txt).

## USB: timeout, mode switch and power are separate paths

| Address | Exact instruction / meaning |
| --- | --- |
| `0x880fcd6c` | Charger-status routine. Input 0 opens USB; input 1 closes it. Direct calls at `0x8808b002`, `0x8808b056`, `0x8823ca30`. |
| `0x880fcd94` | Starts a function timer with period `0x28000`, callback `0x880fcce9`. Period literal at `0x880fce08`: `00800200`, or 163,840 ticks. |
| `0x880fccec` | Timeout callback calls `hal_UsbClose`: `30180ece0065` = `jal 0x88073839; nop`. |
| `0x880fcd44` | Descriptor callback cancels that timer after USB status advances from 3 to 4. First speed-enumeration callback advances status 2 to 3. |
| `0x880fcdbe` | Disconnected-mode call to `hal_UsbClose`, same six bytes. Cancels timer at `0x880fcdec`. |
| `0x88073872` | Controller close calls power routine `0x82014ffd` with `(6,0)`, after clearing controller registers `0xa1a80008/0c`; then releases USB clocks. |
| `0x88073a1a` | Controller open calls the same power routine with `(6,1)`, initializes controller and installs descriptor callback `0x880fccf9`. |
| `0x88074324` | USB interrupt path also calls power `(6,0)`: accumulated early-suspend/suspend/reset flags equal `0x1c00`, charging flag clear, detect flag 1. It bypasses the close routine. |
| `0x8802fef8`, `0x8802ff38` | Boot microphone-download path enables USB power; default boot path then sets power from board configuration. This is not evidence of a runtime sleep transition. |

The archived SDK's `uctls_fnc.c` and `hal_usb.c` corroborate the timeout,
descriptor-state cancellation and suspend power handling. Actual core instructions
determine these addresses. HAL ticks are 16,384 Hz: `163840 / 16384 = 10 s`.
The failed patch at `0x8823c9d0` does not intercept the timeout or interrupt power path.
No timeout cancellation, power policy or sleep behavior has been changed.

## Console: pre-application path and CDC transmission gate

Builtin console init `0x8823b344` registers USB RX callback `0x8823b3fd` through
`0x8823c94d` at **`0x8823b3d4`**. USB event handler `0x8823ca88` reads RX DMA and
calls the registered callback at `0x8823caf8` with buffer and length. That callback
copies input and queues a type-2 message.

Console task `0x8823b118` echoes type-2 input at `0x8823b146`, accumulates characters,
and submits a line on **CR (13)** at `0x8823b150–192`. LF (10) is ignored at
`0x8823b19e`. A type-1 message calls parser `0x8823aa81` at `0x8823b12e`;
its initial comparison at `0x8823aa8e` matches `devinfo`.
There is no login check before that comparison in this path. The `Username:`
string at `0x882440a0` is emitted for `logout`, via `0x8823ad9c–ae`; its existence
does not establish a login gate. The linked application CLI is a separate path.

Output `0x8823b0cc` writes UARTs and queues USB bytes through `0x8823c8f5` at
`0x8823b0fc`, then flushes at `0x8823b104`. TX completion drains the ring into
DMA memory and starts transmission at `0x8823cb3e`.
CDC request `0x22` handling compares `wValue=3` at `0x8823cb70`, enabling
`0x82300ef8`; value 2 clears it at `0x8823cb8a–96`. The gate checks exact values,
not DTR alone. This makes explicit **DTR on + RTS on** a useful host setting to
measure. It does not explain the previous zero bytes by itself.

Module selection calls a license-parameter check at `0x8823036e`, with fallback
selection after a nonzero result, then further identity checks. The selected
module's init runs at `0x882303f2`. Loading a valid APP1 and seeing the builtin
console are insufficient proof that our `main()` runs or activation succeeds.

## Reset: caller and units, without fitting the observed duration

| Call site | Reason supplied to `0x88232e09` |
| --- | --- |
| `0x882319e2` | 3 — data/network URC path |
| `0x88232474` | 1 — no-SIM retry threshold, delay slot `li a0,1` |
| `0x88232780` | 2 from registration threshold at `0x88232626–28`, or 3 from data-failure joins including `0x8823277e` |
| `0x88233650` | 5 — parameter reset |
| `0x8823bebc`, `0x88240aa0` | 4 — FOTA paths |

These are the six direct MIPS16 calls found and inspected. An indirect API export
also exists; this is not an exhaustive map of all watchdog, exception or base-modem
reset mechanisms. SDK reason 6 (system format) has no identified direct caller here.

`sys_reset()` at `0x88232de8` supplies reason 0. Its four direct callers are
`0x88233932`, `0x8823aa62`, `0x8823ad1c`, `0x8823b2ae`.
The callback dispatcher `0x88232dcc` reads `0x823009b8`, returns 1 when unset,
and otherwise calls it with the reason. Calls at `0x88232dec` and `0x88232e0c`
are `101973cb`, with delay slots `006c` and `0065` respectively. The returned value
controls whether reset proceeds through vtable offset 28 to `0x88184afd`.
A base-modem path at `0x88192d8a` calls that reset target directly, bypassing this callback.

Network timer callback `0x88232968` rearms at `0x88232992` with delay-slot
`li a1,100` (`40ea646d`). Through `0x88185c8c → 0x88093148 → 0x88092e2c`,
milliseconds become `(ms << 4) + high32(ms * 0x624dd2f1)` HAL ticks.
Thus 100 ms becomes 1,638 ticks, about 99.976 ms. The state machine uses changing
poll periods and interleaved states; the roughly five-minute reset cannot identify
the caller from timing alone.

The separate generic timer stores `period_ms / 100` at `0x8823737a–8e`.
Its tick routine `0x882373bc` increments that count; initialization
`0x8823768e–a4` configures a repeating timer for 100 ms using the same underlying
millisecond conversion. The serial-validity check registered by the system task
with 600,000 units is therefore nominally **600 seconds**, not 300. Its callback
`0x882301fc` frees the timer when valid and enters the task-control path
`0x8823307c` when invalid. This does not measure actual runtime cadence or identify
the earlier reset. Neither validity checking nor its timer has been altered.

Useful snapshots: `0x82300828/+1/+2/+3` hold last SIM/CS/PS/state bytes;
`0x82300814` no-SIM/retry counter, `0x82300810` registration counter,
`0x82300834` registration limit, `0x82300818` polling count,
`0x82300820` polling period. The binary recognizes SIM value 1 and registration
values 1/5. Preserve raw values as well as those interpretations.

Future core hooks should identify both close callers, interrupt power-off, and
the two reason-dispatch calls, preserving arguments, return values and delay slots.
Capture these state bytes before reset. Placement, ABI and a bounded LED reason
code still need review; **no core hook is implemented or applied to this image**.

## Prepared application image and next comparison

[Application source](../../firmware/logicrom/main.c) now gives a blue entry pulse before
SDK init and red pulse after it returns. Each has a nominal 250 ms lit interval
between two 80 ms dark gaps, so an already-lit LED still shows a marker; every wait
has a finite guard if the hardware timer stops. [Marker code](../../firmware/logicrom/v24_diag.h) restores
pad configuration, direction and sampled level, touches only GPIO4/27, and opens
no UART. Pulse duration and visibility still require hardware verification.
The probe uses direct `write()` for every diagnostic, calls `cli_init(NULL)`,
registers the reboot callback, reports API return codes and always permits reset.
It does not bypass activation or add diagnostic flash writes.

[Prepared 412 image](../../firmware/live/2026-10-10-logicrom-offline/v24-412-diag-entry-v2.bin):
SHA-256 `90ae7ffa47824eee169fcc9ea9a06268a8184ad4fdf7f5d49256efd7b861c079`.
[Manifest](../../firmware/live/2026-10-10-logicrom-offline/v24-412-diag-entry-v2.json) and
[build provenance](../../firmware/live/2026-10-10-logicrom-offline/build-provenance.json)
record pinned inputs, source hashes and artifacts. APP1 is 128 KiB; CRC, unused
partition, exact NVM-only core and 412's calibration/factory tail were checked.
All [87 SDK imports resolve](../../firmware/live/2026-10-10-logicrom-offline/app-imports.json)
against the core's export table. The [compiled main/markers](../../firmware/live/2026-10-10-logicrom-offline/app-main-v2.txt)
were inspected for ordering and MMIO addresses; this is not runtime execution proof.
The trial installer preserves the live tail and withholds boot magic, using its
own pre-start snapshot for recovery. Hardware-tested remains **false**.
The earlier `diag-entry.bin` was an offline intermediate without the dark gaps;
use the v2 image above. Neither image has been installed.

The Mac [logger](../../tools/logicrom_console.py) records requested/effective settings,
post-open/pre-configuration state, actual transmitted bytes, and UTC/elapsed time.
It uses immediate raw 8N1 without flushing RX, handles partial writes, closes owned
descriptors on interruption, supports CR/LF/CRLF and explicit existing `--port`.
`keep` means no extra control ioctl; opening may already change DTR/RTS.
Unavailable line readback is reported explicitly. PTY tests cover these behaviors.
Validation: **14 logger tests and 23 image/recovery tests passed**, and the installer
accepted the prepared image in its offline validation mode. The
[verification record](../../firmware/live/2026-10-10-logicrom-offline/verification.json)
binds those checks to the final artifacts.

After a separate go for one installation, start the passive logger **before**
startup and film the LEDs through the reset. Use 660 seconds to cover both the
observed delayed reset and the nominal ten-minute validity timer. Then, with the
same installation, save two equal ROM reads, verify unchanged
core/application and intact tail, and restart using the existing
[read-and-exit script](../../firmware/live/2026-10-09-logicrom-412-trial-3-restart.py)
with that fresh read as its expected image. No identical reinstall is needed.
Start the active logger before this second startup:

```sh
.venv/bin/python tools/logicrom_console.py --output firmware/live/diag-passive.jsonl --seconds 660 --no-open
.venv/bin/python tools/logicrom_console.py --output firmware/live/diag-active.jsonl --seconds 660 --baud 115200 --dtr on --rts on --send devinfo --send-after 1 --ending cr
```

Compare enumeration lifetime and LED markers first. If no entry marker appears,
the next image needs the reviewed core hooks above. If it appears, use readable
app diagnostics and callback results before changing radio or reset behavior.
No activation, network/data, GPS, or server report has been demonstrated by this
offline preparation.
