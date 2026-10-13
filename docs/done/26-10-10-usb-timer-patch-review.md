> **Archived 26-10-11.** The current, reconciled account is [logicrom-core.md](../knowledge/logicrom-core.md). This note is kept as the dated record of the work; statements here may be superseded there.

# USB 10 s timer patch review — offline, 2026-10-10

**Offline only. No device was accessed.** This reviews the unreviewed
"cancel the timer on the 2→3 transition" candidate from
[26-10-10-ghidra-core-read.md](26-10-10-ghidra-core-read.md),
against the pinned NVM-only core
(`firmware/live/2026-10-10-logicrom-offline/core-nvmfix.bin`,
SHA-256 `aae11341…c643a`).
Disassembly is Homebrew `gobjdump -m mips:16 -EL --adjust-vma=0x88000000`.
Addresses are core virtual addresses; subtract `0x88000000` for file offsets.
Bytes are little-endian, ascending flash order.

The 9.9 s USB loss **remains a strong hypothesis, not a proved mechanism**.
Nobody has captured the state byte `0x820a0ff4` reaching 3, the timeout body
executing, or the second descriptor event failing to arrive on 412. Timing
alone infers it. This review corrects that overstatement, evaluates three
one-change candidates, and recommends one diagnostic patch that tests timing
causality without changing state logic.

## 1. What the code does (confirmed)

### 1.1 Mode switch `0x880fcd6c` arms the timer

Mode 0 (open CDC): stores state 2 at `0x820a0ff4`, arms
`FUN_8200cd54(0x28000, 0x880fcce9, 0, 2, 0)` — 163,840 HAL ticks at
16,384 Hz = 10 s — and installs descriptor callback `0x880fccf9`.
The period literal at file `0x0fce08` is `00 80 02 00` (`0x00028000`).
The only in-function loader is at `0x880fcd8c` (`lw a0,0x880fce08`).
The literal sits in this function's private pool (`0x0fce00–0x0fce22`),
bounded by code; no other function loads from it.

Mode 1 (charger): calls `hal_UsbClose`, posts to queue `0x820a0ffd`,
stores state 1, and **cancels** via `FUN_8200c4a8(0x880fcce9, 0)`.
At startup the USB Calib task calls mode 1 before any arm, so **cancel
without a prior arm is safe** (no-op). Double-cancel is therefore safe.

### 1.2 Descriptor callback `0x880fccf8` (full decode)

```
state = *0x820a0ff4 (literal at 0x0fcd58: f4 0f 0a 82)
if state == 2:
    if (event & 0xff) == 0: return          # 0x880fcd14: beqz v0,exit
    *0x820a0ff4 = 3                          # 0x880fcd18: sw
    return                                   # 0x880fcd1a: b exit (NO cancel)
elif state == 3:                             # event NOT checked here
    if *0x820a0ffd != 0xff: post msg (payload s1=0) to that queue
    *0x820a0ff4 = 4
    FUN_8200c4a8(0x880fcce9, 0)              # cancel
    return
else: return
```

Bytes at the 2→3 exit (`0x880fcd1a`, file `0x0fcd1a`): `17 10`
(`b 0x880fcd4b`, imm `0x17`, target even `0x880fcd4a`).
Bytes at the 3→4 cancel (`0x880fcd44`, file `0x0fcd44`):
`04 18 2a 31 00 6d` (`jal 0x8200c4a9; li a1,0`).

The second path does **not** check the event. Any second invocation with
state 3 advances to 4 and cancels, regardless of event value.

### 1.3 Timeout body `0x880fcce8` calls close directly

```
0x880fcce8: addiu sp,-24; sw ra,20(sp)
0x880fccec: jal 0x88073839 (= hal_UsbClose); nop   # bytes 30 18 0e ce 00 65
0x880fccf2: lw a3,20(sp); jr a3; addiu sp,24
```

This callback is private to the 10 s timer: referenced only by the arm
(`0x880fcd8e` loads `0x880fcce9` from `0x0fce0c`) and the two cancels
(`0x880fcd42` from `0x0fcd64`, `0x880fcdea` from `0x0fce0c`).
`hal_UsbClose` itself is shared (also called from mode-1 path at
`0x880fcdbe`), so patching one call site leaves the other intact.

### 1.4 State consumers (all checked)

| Reader | File | Behavior for 2/3/4 |
| --- | --- | --- |
| `0x880fcca2` in `FUN_880fcb34` (USB open) | `0x0fcce4` literal | 2, 3, 4 **identical**: re-enumerate controller (`0x88073279(1)`, sleep 8000, `0x88073279(0)`) |
| `0x880fce2c` in USB init | `0x0fcec4` literal | Any nonzero skips init; 2/3/4 identical |
| `0x880fce68` in USB init | `0x0fcec4` literal | Zero check only; 2/3/4 identical |

No consumer distinguishes 3 from 4. Skipping the transient 3 is safe for
every reader found (4 literal refs to `0x820a0ff4`, all decoded above).

Queue `0x820a0ffd` (3 refs): holds a dynamically set queue ID (written at
`0x880fce64`). Message payload at offset 8 is 0 (normal 3→4), 1 (mode-1
path), and would be 2 under a naive fallthrough patch (state value leaks).
The consumer is unidentified; **avoid changing this payload**.

## 2. Three one-change candidates

### Candidate A — NOP the timeout's close (robust neutralizer)

- **Site:** file `0x0fccec`, 4 bytes: `30 18 0e ce` → `00 65 00 65`.
- **Effect:** timeout fires, does nothing, returns. State stays 2 or 3.
  USB never closes via this timer, regardless of whether 2→3 occurred.
- **Side effects:** timer lifecycle unchanged (oneshot fires, done). No
  state, post, or cancel logic touched. Mode-1 close path intact.
- **Strength:** does not assume the first event occurs. Works even if
  state never leaves 2 (unmeasured in the passive run).
- **Weakness:** timeout still fires (resource held 10 s); no delayed-close
  signal to observe. If USB persists, causality is supported but the
  counterfactual timing shift is not demonstrated.

### Candidate B2 — Retarget the 2→3 exit to store-4 + cancel (corrected cancel)

The original "cancel on 2→3" proposal did not name bytes. A naive
fallthrough (`17 10` → `00 65`, NOP) would execute the 3→4 path with
`s1=2`, posting a message with payload 2 instead of 0 to an unidentified
consumer — **rejected** for that payload change.

- **Site:** file `0x0fcd1a`, 1 byte: `17 10` → `11 10`.
  (`b` imm `0x17`→`0x11`: target `0x880fcd4a`→`0x880fcd3c`,
  skipping the conditional post, landing on `li a3,4; sw; cancel`.)
- **Effect:** first event with state 2 stores 3, then immediately stores
  4 and cancels, without posting. State 3 never observable. Second event
  (state already 4) exits via `0x880fcd12`, no double-cancel issue
  (and double-cancel is safe anyway per §1.1).
- **Side effects:** state skips 3 (safe per §1.4). No spurious post.
  Timer canceled, USB stays open. Requires the first event to occur;
  if state never leaves 2, the timer still fires and closes.
- **Weakness:** depends on the unmeasured assumption that 2→3 occurs in
  both passive and active runs. Enumeration without open likely triggers
  the first (speed-enumeration) callback, but this is inferred, not captured.

### Candidate C — Extend the period literal (recommended diagnostic)

- **Site:** file `0x0fce08`, 4 bytes: `00 80 02 00` (`0x00028000`, 10 s)
  → `00 00 84 03` (`0x03840000`, 58,982,400 ticks = 3,600 s = 1 hr).
- **Effect:** timer arms for 1 hr instead of 10 s. All state, post, and
  cancel logic **unchanged**. If the second event occurs (e.g., suspend
  after minutes), the timer still cancels normally and USB persists
  indefinitely. If it never occurs, USB closes at ~3,600 s instead of 9.9 s.
- **Side effects:** none on code flow, state values, message payloads, or
  other timers. The literal is private to this arm (§1.1). Timer still
  occupies its slot for longer; no resource concern for a diagnostic run.
- **Strength:** minimal (one word, no branch/jal touched), reversible,
  preserves mechanism. Directly tests timing causality: if loss moves from
  9.9 s to beyond the 660 s observation window, the timer is confirmed; if
  loss stays at 9.9 s, the timer is refuted (pointing to the interrupt
  power-off path at `0x88074324` or another closer). Works whether or not
  2→3 occurs.
- **Weakness:** USB still closes eventually (at 1 hr) if the second event
  never arrives — acceptable for a diagnostic; the final fix can then be
  A or B2 with measurement behind it.

An intermediate 600 s value (`00 00 96 00`, `0x00960000`) would show a
delayed close inside the 660 s window. The 3,600 s value is preferred to
maximize console time for `devinfo`/`secr`/`devmem` in the same run.

## 3. Recommendation

**Build the next diagnostic image as NVM-only + Candidate C (period to
3,600 s).** One change, exact bytes above, no code-flow alteration.

Rationale:

1. It is the smallest possible intervention (one literal word).
2. It preserves every state transition, post, and cancel semantic.
3. It yields a decisive timing test in a single run, passive or active.
4. It gives up to an hour of USB for console measurements if the hypothesis
   holds, without promising that console replies will work (see §4).
5. Candidates A and B2 remain available as the final fix once C confirms
   the timer; B2 in its corrected `11 10` form, not the naive fallthrough.

Implementation follows the existing `fix_nvm_format_size` / `keep_usb_open`
pattern in `tools/rda_logicrom_image.py`: a new `extend_usb_timeout()`
checking for `0x00028000` at `0x0fce08`, writing `0x03840000`, with
before/after tests and installer acceptance. The old `--keep-usb-open`
(charger branch) stays out; it failed and is not carried.

## 4. What this patch does NOT promise (corrections)

- **USB persist does not imply console replies.** `secr` already echoed
  without a dump. The built-in slot-7 printer `FUN_8823b1e0` gates on a
  channel mask (`1<<channel & *mask`, early return at `0x8823b1fc` if
  clear) before reaching the same USB output as echo. Replacing the print
  pointer alone does not explain the failure; the mask value and the
  type-1 submission (`FUN_882333e0` post in `FUN_8823b118`) are the live
  suspects. Console success is measured, not assumed.
- **License gate result is unknown.** A nonzero validator drops the app
  descriptor, but a module mismatch on the success path also selects the
  built-in descriptor. The `secr`/`devmem` bytes (or the `0xfc` ROM
  security read) decide; the patch does not.
- **Reboot callback cannot promise reset answers.** It requires the app to
  execute (license-gated) and the reset to traverse the callback path
  (`0x88232dcc`; the base-modem path at `0x88192d8a` bypasses it).
  Canceling or delaying the USB timer resolves neither dependency. If the
  app never runs, reset attribution needs a core hook before `0x88232e08`
  (LED reason code) or `devmem` polling of `0x82300814/18/20/28` — separate
  reviews, not part of this patch.
- **The `0xfc` ROM path is validated, not queued.** The return-control
  passed live at 18:15:52 UTC; the stack-switched JEDEC helper is built
  and audited, staged disabled as `--jedec-fc`; the security read for the
  license bytes follows it. That thread proceeds in parallel; this console
  thread does not replace it.

## 5. Live-run capture plan (needs its own go; not authorized here)

One installation, two starts on the same image (no reinstall), each with
its own fresh two-read verification:

1. **Passive** (`--no-open`, 660 s): does CDC persist beyond 9.9 s with no
   host open? Film LEDs. Expected under the timer hypothesis: persist.
2. **Active** (115200 DTR+RTS on, `devinfo\r` at 1 s, then `secr\r`,
   `devmem` for `0x820a0ff4`/`0x820173e8` if the console answers, 660 s):
   does CDC persist with host interaction? Do replies appear? Film LEDs.

Decisions:

| Observation | Interpretation |
| --- | --- |
| Persist in both | Timer confirmed as the 9.9 s closer; proceed to console/license measurements |
| Loss still at ~9.9 s in either | Timer refuted as the (sole) closer; investigate `0x88074324` and other close callers |
| Persist but no replies | Timer confirmed, console path still faulty; pursue mask/submission trace and `0xfc` security read |
| Entry marker appears | App runs; use CLI + reboot callback (record, allow) |
| No marker | App still gated; license bytes via `secr`/`devmem` or `0xfc` decide blank vs rejected vs module mismatch |

No RST, unplug, or power button during writing; distinguish automatic reset
from operator reset; collect ROM flash/tail comparison and status registers
after each run with existing tools. Change one cause per image.

## 6. Provenance

- Core bytes read from `core-nvmfix.bin` via `gobjdump` (MIPS16) and direct
  Python dumps; branch immediates hand-verified
  (`17 10`→`0x880fcd4a`, `11 10`→`0x880fcd3c`).
- State literal `0x820a0ff4`: 4 refs, all decoded (§1.4). Queue literal
  `0x820a0ffd`: 3 refs. Timeout `0x880fcce9`: 3 refs (1 arm, 2 cancel).
  Period literal `0x0fce08`: 1 loader in-function, private pool.
- No hardware touched. No image built yet. Implementation + build are the
  next offline step after this review is accepted.
