> **Archived 26-10-11.** The current, reconciled account is [logicrom-core.md](../knowledge/logicrom-core.md). This note is kept as the dated record of the work; statements here may be superseded there.

# Console reply trace: why echo works but devinfo/secr do not — offline, 2026-10-10

**Offline only. No device was accessed.** This re-traces the built-in console
reply path against the pinned NVM-only core (`core-nvmfix.bin`,
`aae11341…c643a`), correcting the "print pointer replacement" suspect from
[26-10-10-ghidra-core-read.md](26-10-10-ghidra-core-read.md).
Bytes below are verified with `gobjdump -m mips:16` and Python pool dumps.

Live input is the already-recorded `secr` capture
(`firmware/live/2026-10-10-logicrom-412-license-secr-1/console.jsonl`):
TX `secr\r` (5 B) at 3.396 s, RX `secr\r\n` (6 B) at 3.402 s, then zeros,
`NW: SIM card ready` at 6.33 s, `NW: GSM - Registered` at 10.733 s, USB loss
at 11.733 s. No security dump.

## 1. Print pointer and channel mask are both exonerated

### 1.1 SIM/GSM use the identical print call as devinfo/secr

| Message | String vaddr | Pool entry | Call site | Print func source | Channel |
| --- | --- | --- | --- | --- | --- |
| `NW: SIM card ready` | `0x88242c04` | `0x882328bc` | `0x882324e0–e4` | `s1 = *0x823002c4`, `jalr s1` | `a0=0` |
| `NW: GSM - Registered` | `0x88242c44` | `0x882328cc` | `0x8823258e–92` | `s1 = *0x823002c4`, `jalr s1` | `a0=0` |
| `devinfo` reply lines | `0x88243f34…` | `0x8823afc8…` | `0x8823aad0…` | `s0 = *0x823002c4`, `jalr s0` | `a0=0` |
| `secr` hex bytes | `0x882441f8` (`%02x `) | `0x8823b08c` | `0x8823af1e` | `v0 = *0x823002c4`, `jalr v0` | `a0=0` |

Pool proof: `0x882328ac = 0x823002c4` (network), `0x8823afd0 = 0x823002c4`
(parser). Both tasks load the print function from the same word and call it
with channel 0.

### 1.2 Consequence

`NW: SIM card ready` and `NW: GSM - Registered` **appear** in every recent
capture. Therefore:

- `*0x823002c4` (whatever descriptor installed it) successfully prints on
  channel 0. Replacing the pointer at init does not break channel-0 output.
- The slot-7 gate in `FUN_8823b1e0` (`1<<channel & *0x82300dd4`, early return
  at `0x8823b1fc` if clear) passes for channel 0 — bit 0 of `*0x82300dd4`
  is set. The mask does not explain the failure either.
- The USB TX queue behind `0x8823b0cc` delivers network-task prints. TX
  itself works.

The critique is confirmed: "Replacing the print pointer alone does not
explain the failure." The mask variant is now refuted as well, by the same
witnesses. Remaining suspects must distinguish parser-path prints (silent)
from network-path prints (audible) despite sharing function, channel, and queue.

## 2. CR is received and processed; the parser is almost certainly invoked

TX `736563720d` (`secr\r`) → RX `736563720d0a` (`secr\r\n`) in 6 ms.

- Type-2 echo (`0x8823b146`) echoes the 5 received bytes verbatim.
- The 6th byte (`\n`) can only come from the CR branch at
  `0x8823b164–6a`, which prints pool `0x8823b1d4 = 0x88244984 = "\n"`.
- That print is 6 instructions before the type-1 post at `0x8823b192`
  (`jal 0x882333e1`, queue `0x823002cc`, type 1).

So the console task reached the CR branch. Unless the queue post itself
fails (full/invalid — unmeasured, unlikely for a single line), the parser
`0x8823aa81` ran with input `secr`.

Unknown commands print nothing (`bnez` to the epilogue at `0x8823afb5`),
so a corrupted line would also be silent. But the line is exactly `secr`
(NUL-terminated at submit, `strncmp` first 4 bytes), which matches pool
`0x8823b084 = 0x882441f0 = "secr"`. Mismatch is not the explanation.

## 3. Leading hypothesis: the parser hangs in data collection, before printing

### 3.1 `secr` prints unconditionally — unless the reader never returns

`secr` branch (`0x8823aee6` on match):

```
a0=0x1000, a1=sp+128, a2=256
s0 = *(*0x823002e8 + 0x5ac)          # security reader, slot 0x5ac
jalr s0                               # 0x8823aef8 — return value IGNORED
for s02 = 0..255:                     # 0x8823aefc–28, no early exit
    if s02 % 16 == 0: print("\r\n")  # pool 0x8823b088
    print("%02x ", buf[s02])         # pool 0x8823b08c
```

272 prints, no return-value check, no error path. Even a failed read would
print 256 bytes of stack garbage. **Zero bytes printed means the loop never
started** — the reader at `0x8823aef8` did not return (hang), or the parser
never reached the branch (§2 argues it did).

The reader is the core SPI security path (`0x820011ec`, opcode `0x48`).
Hang candidates: unbounded busy wait, MMIO stall (cf. the ROM helper's SPI
difficulties — different path, same flash), unsupported opcode on this chip
revision (JEDEC `c8 60 16`, exact GigaDevice revision unestablished).
Disassembly of `0x820011ec` (flash `0x8801becc` via the boot copy) for loop
guards is the next offline step, not done here.

If the parser hangs in `secr`, the console task (single message loop for
type-1 and type-2) blocks. No further echo would process — consistent, since
no further input was sent. Network-task prints (SIM/GSM) continue because
they run on a different task. USB loss follows on the 10 s timer. Every
observed byte fits.

### 3.2 `devinfo` collects before printing — same shape

`devinfo` branch calls four collectors (`0x88230e75`, `0x8823713d`,
`0x88230e15`, `0x88232e6d`) at `0x8823aa98–b4` **before** the first print at
`0x8823aaca`. A hang in any collector (IMEI/UUID/modem/NV read) yields the
same signature: echo + newline, then silence. Collectors are not traced here.

## 4. Decisive live control: `help` (no collection, same path)

`help` branch (`0x8823af36` on match, pool `0x8823b090 = 0x88244200`):
14 straight prints via `*0x823002c4`, channel 0, **no data collection**.

| Live result (once USB persists) | Interpretation |
| --- | --- |
| `help` replies, `devinfo`/`secr` silent | Parser + prints work; confirms hang-in-collection (§3). Pursue collector/reader guards and the `0xfc` security read in parallel |
| `help` also silent | Parser never runs or all type-1 prints fail; pursue type-1 post (`0x882333e0`), queue `0x823002cc`, and TX-queue overflow under the zero stream |
| All reply | Console fully works; proceed to license bytes via `secr` + `devmem` |

`help` output is ~14 short lines — far smaller than `secr`'s 272 prints —
so it also separates "large-reply TX overflow" (help works, secr partial)
from "no reply at all" (both silent).

Recommended console order on the next persisting run: `help`, then
`devinfo`, then `secr`, then `devmem` spot reads (`0x820a0ff4` state,
`0x820173e8` charger, `0x82300dd4` mask to confirm bit 0 live). One command
per capture or spaced seconds apart; the logger sends one line per run, so
plan successive runs or extend the logger (separate change, own review).

## 5. What is NOT claimed

- The security-reader hang is inferred from code shape (no return check,
  no error path) + capture shape (echo + newline, zero reply bytes). The
  stopping instruction is unmeasured. A logic-analyzer-grade proof needs
  the `0x820011ec` guard audit (offline, queued) or a persisting run with
  the `help` control (live, needs go).
- The zero stream (868 B/s NUL) remains unexplained. It does not block
  small network prints, so it is not a blanket TX break. Whether 272 rapid
  `secr` prints interact with it (queue pressure) is unmeasured; `help`
  sizes the effect.
- Type-1 post failure is not excluded, only disfavored (single line to a
  working queue). If `help` is silent, it promotes to lead suspect.

## 6. Provenance

- Pool words dumped from `core-nvmfix.bin`: network `0x23289c–8f8`,
  parser `0x23afc0–b0c8`, slot-7 `0x23b244–24c`, CR `0x23b1d4`.
- Strings resolved: `0x88242c04`, `0x88242c44`, `0x88244984` (`\n`),
  `0x882441f0` (`secr`), `0x882441f8` (`%02x `), `0x882443e8` (`\r\n`),
  `0x88244200` (`help`).
- Call sites disassembled: `0x882324d2–ee`, `0x8823258a–92`,
  `0x8823aee6–af32`, `0x8823af36–b2`, `0x8823b146–192`, `0x8823b1e0–242`.
- No hardware touched. No image built. The `help`-first console order is
  folded into the live-run plan; the `0x820011ec` guard audit is queued
  behind the image build.
