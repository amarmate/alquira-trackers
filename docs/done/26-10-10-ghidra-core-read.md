> **Archived 26-10-11.** The current, reconciled account is [logicrom-core.md](../knowledge/logicrom-core.md). This note is kept as the dated record of the work; statements here may be superseded there.

# Ghidra core read: USB timeout, console, descriptor and license — 2026-10-10

**Offline only. No device was accessed.** This reads the existing Ghidra export
of the corrected 0.5.1 core (8,124 functions, from
`v24-412-trial-nvmfix.bin` [0, 0x250000)); rebuild recipe in
[26-10-10-handoff-core-trace.md](26-10-10-handoff-core-trace.md), whose
"next steps" item 1 this completes. Addresses are core addresses
(`0x88000000` + flash offset); a MIPS16 target has bit 0 set. Decompiled bodies
support mechanism claims; live-state claims remain unmeasured.

## 1. The 9.9 s USB loss: the timer chain, with bodies

`FUN_880fcd6c(mode)` (`0x880fcd6c`, 148 B) is the USB mode switch. Stored mode
at `0x820a1000`; link state at `0x820a0ff4`.

- **mode 0 (open CDC):** sets state 2, **arms
  `FUN_8200cd54(0x28000, 0x880fcce9, 0, 2, 0)`** — 163,840 HAL ticks at
  16,384 Hz = 10 s, oneshot — and installs descriptor callback
  `FUN_880739cc(0x880fccf9)`.
- **mode 1 (charger):** sets the `USB Controller 1.0` strings, calls
  `FUN_88073838` (= `hal_UsbClose`), posts `0x15e988ac` to queue
  `0x820a0ffd`, sets state 1, and **cancels** the timer via
  `FUN_8200c4a8(0x880fcce9, 0)`.

`FUN_880fcce8` (`0x880fcce9`, the timeout callback) calls `FUN_88073838`
directly. `FUN_880fccf8` (`0x880fccf9`, the descriptor callback):

- state 2 and event nonzero → state **3**. Timer still armed.
- state 3 → posts `0x15e988ac`, state **4**, **timer canceled**.

So the 10-second close is canceled only by the **second** descriptor-callback
event. The earlier disassembly trace placed the 3→4 transition on suspend. If
that second event does not occur — and every 412 run, passive or DTR+RTS,
loses USB at ~9.9 s — the timer fires and `hal_UsbClose` runs. This is now a
body-level candidate, still not a live measurement: the state byte
`0x820a0ff4` reaching 3 but never 4 is the capture that would settle it.

The interrupt power-off path (`0x88074324`) remains a secondary suspect for
what happens after the close, but is no longer needed to explain the timing.

**Patch candidate for later review (not applied, not decided):** also cancel
the timer on the 2→3 transition inside `FUN_880fccf8`. One change per image,
own review pass, own go.

## 2. The `USB Calib` task — resolved

`FUN_8808b010` (`0x8808b010`, 188 B, contains the `USB Calib` string at
`0x8808b048` and the close caller at `0x8808b056`) is a persistent task:

1. `FUN_880fcb34(0)` — select default USB configuration. (`FUN_880fcb34(2)`
   is what presents `1782:4d11`; it also re-enumerates the controller when
   the link state is 2/3/4.)
2. `FUN_880fcd6c(1)` — switch to charger mode at startup.
3. `uVar1 = FUN_88075124()` — read charger state from `0x820173e8`;
   `FUN_8808aff4(uVar1)` — wrapper: `!= 0` → `FUN_880fcd6c(state == 1)`,
   i.e. charger state 1 keeps mode 1, state 2 opens CDC (mode 0, arming the
   10 s timer).
4. `FUN_88075ae8(0x8808aff5)` — registers the wrapper as the charger-change
   callback (`0x820173f0`).
5. Loop: 500 ms message wait on queue `0x8203d1bb`; messages dispatched by
   `FUN_8808b0dc` (message IDs `0x20009`, `0x30008`, `0x110001/2` —
   calibration command handling, not USB-close related).

The charger state byte `0x820173e8` at boot therefore decides whether the
CDC ever opens. Capturing it names the wrapper's input on this board.

## 3. Cable callbacks (`0x8823ca8c`, the USB event handler)

Switch on event type:

| Event | Action |
| --- | --- |
| 0 | RX DMA drain; TX completion restarts DMA; calls registered callback `0x82300f00` |
| 1 | RX into `0xa2074000`, NUL-terminate, call `0x82300efc` (console input) |
| 10 (0xa) | CDC request: `bRequest == 0x22` and **wValue == 3 → set TX gate `0x82300ef8`, log "USB: Port open"; wValue == 2 → clear gate, log "USB: Port close". wValue 0/1 ignored** (gate unchanged) |
| 14 (0xe) | "USB: cable connected", set `0x82300ef9`, rearm RX (`0xfff`) |
| 15 (0xf) | "USB: cable disconnected", clear TX gate |

The TX gate is exact: **DTR+RTS both on** opens it; RTS-only closes it; both
off is a no-op. These callbacks only log and gate — none closes USB.

`FUN_8823ca58` registers the handler (`0x82083af0 = 0x8823ca89`) and the
"Logicrom USB Device" strings; it runs early in the system task.

## 4. Console: no login gate, full command set, reply path named

Console task `FUN_8823b118` (`0x8823b118`): type-2 messages are echoed
(`FUN_8823b0cc` → UART1+UART2 via table `0x823002e8` slot 0xc0, then USB queue
`FUN_8823c8f4` + flush), accumulated at `0x82300ddc`; **CR submits a type-1
message** to queue `0x823002cc`; LF ignored. Type-1 runs the parser
`FUN_8823aa80` (1,344 B). There is **no login check anywhere**; `Username:` is
printed by the `logout` command, `devuser@dev #` by `ttysms`, the
`WAYBYTE SOLUTIONS` banner by another command.

Parser command set: `devinfo`, `ifconfig`, `ping=`, `apn=`, `network=on/off`,
`getlic`, `setlic=`, `sysproxy`, `fota=`, `reboot`, `loglevel`, `logout`,
`ttysms`, `smsr=`, `smsd=`, `smsdel`, `at+wsecdata=1,12,"..."` (writes a
security record via `FUN_88232adc(0, …)`), a help list, **`secr`** (reads
0x100 bytes at security index via vtable slot 0x5ac and hex-dumps), and
**`devmem`** — hex address, optional decimal value and width 8/16/32:
a built-in memory peek/poke over the console. `devmem` and `secr` become
usable diagnostics once USB persists.

Reply routing: `devinfo`/`secr` answers print through `DAT_823002c4` with
channel 0. That pointer is **replaced during init**:
`DAT_823002c4 = descriptor[7]` in the system task — the selected descriptor's
own print takes over. The live failure shape (echo works, `SIM ready`/`GSM
registered` appear, `devinfo`/`secr` produce no reply) therefore has three
named suspects: the built-in descriptor's slot-7 print routes channel 0
somewhere else, the reply is lost under the constant zero stream, or the
type-1 submission never runs. Capture point: the type-1 post
`FUN_882333e0(0x823002cc, 1, line, 0)` in the console task.

## 5. The `0x88230330` descriptor branch — resolved

Inside the system task `FUN_882302f0`:

1. With an app present (`param_1 != 0`): prints `app:`/`main:`/`magic:`,
   `memcmp(_DAT_88250080, "LROM_SDK_APPCODE", 0x10)`. **Mismatch, or
   `_DAT_88250090 == 0` → built-in descriptor `0x88244434`; otherwise
   `0x82300000 = 0x88250080` (the app).** Per the license-storage doc our
   image passes both checks.
2. `FUN_88232a84(1, &DAT_823002f8, 0x100)` — read record 1 at boot.
3. `local_18 = FUN_88233bcc()` — the license validator. **Nonzero:**
   register the 600,000 ms generic timer (callback `0x882301fc`), select the
   built-in descriptor, and post `0x1607` to the timer task. **Zero:** run
   the descriptor's slot-0xc module check against `FUN_88233a64`/
   `FUN_88233a70`, fallback to built-in on mismatch.
4. Descriptor slots then drive the rest: `[3]` init, `[4]` second init,
   `[5]` (`0x14`) event callback (SYS Task2 forwards `0x160e` cable events
   and others), `[7]` print, `[10]` (`0x28`) SYS Task1 hook.

**Consequence:** an absent/invalid license deterministically means the app
descriptor is dropped before slot 3 runs — our `main()` never executes and
no entry marker can appear. This is the structural explanation consistent
with every observed run, and it stays a hypothesis until the license bytes
or the validator return are captured.

## 6. License internals — function-level confirmation

- `FUN_88233bcc`: read record 0 (96 bytes, `FUN_88232a84(0, buf, 0x60)`);
  fail → −5. Hex-decode to 48 bytes; key/IV transform; AES-CBC 0x1b0 bytes
  at `0x82300110`; RAM validator `0x82300144` (return codes per
  [26-10-10-logicrom-license-storage.md](26-10-10-logicrom-license-storage.md)).
- `FUN_88233afc` (`system_serialvalid`): **Luhn check on the RAM serial at
  `0x82300014`** (`FUN_88233a9c` is the Luhn routine).
- `getlic` → `FUN_8823aa2c` → `FUN_88233b50`: server round-trip
  (`FUN_88233c90`), Luhn-check the received serial, no-op if the stored
  record already matches, else copy serial to `0x82300014`, save the 96-byte
  record (`FUN_88233b14` → `FUN_88232adc(0, …)`), print `+SER:` and
  `sys_reset` on change. This is the stock self-service activation, run
  from the device console; whether it is acceptable under the no-Waybyte
  constraint is a user decision, not made here.
- `setlic=` requires exactly 0x60 hex characters (`FUN_88233b34`).
- The 600 s timer callback `0x882301fc` re-runs `system_serialvalid`: valid
  → free the timer; invalid → task-control path `0x8823307c`. Nominal
  600 s ≠ measured ~300 s returns to ROM, so this timer still neither
  explains nor is excluded from the five-minute reset.

## 7. Capture table (hypothesis → address → expected input → capture)

| Hypothesis | Address / state | Expected input | Capture that settles it |
| --- | --- | --- | --- |
| 10 s timer causes the 9.9 s loss | `FUN_880fcd6c` arm at mode 0; state `0x820a0ff4`; cancel `FUN_8200c4a8` | charger state `0x820173e8` == 2 at boot | state reaches 3, never 4; timeout `FUN_880fcce8` runs |
| Charger path opened the CDC | wrapper `FUN_8808aff4` | `0x820173e8` value | wrapper input ≠ expected |
| `devinfo`/`secr` reply missing | type-1 post in `FUN_8823b118`; `DAT_823002c4` target after init | `secr\r` on console | parser reached but print absent → routing; parser not reached → submission |
| License gate drops the app | `FUN_88233bcc` return in `FUN_882302f0` | record 0 bytes | nonzero return → built-in descriptor; matches missing entry marker |
| Five-minute reset | six reset callers (prior trace) + 600 s timer `0x882301fc` | reset reason | reboot-callback reason once app runs, or core hook before `0x88232e08` |

## 8. What this changes in the plan

- The 9.9 s loss has a complete body-level mechanism; the reviewed patch
  candidate (cancel on 2→3) is queued behind its own review and go.
- The console is confirmed login-free and has `devmem`/`secr`; once USB
  persists, license bytes are readable **from the console**, making the ROM
  helper path (0xfc review) a fallback rather than the only route.
- App execution is gated by the license validator through the descriptor
  switch; the three-way fork (blank record → activation prerequisite;
  present-but-rejected → validation investigation; valid → module-check
  branch) is unchanged.
- Open sub-questions: what the second descriptor-callback event is on this
  host (suspend?), the 868 B/s zero stream, and the SYS Task2 message
  `0x1002/0xb` flush path.
