# LogicROM 0.5.1 core on the V24: what is known

Reference, reconciled 26-10-11 from the four offline reads of the core and the live
runs through 2026-10-10 19:55 UTC. The dated notes it replaces are kept in
[done/](../done) as the evidence trail; each carries a banner pointing here. For the run
history and the open next steps see
[the working summary](../in-process/26-10-10-agents-summary.md).

Every claim below carries one of three labels:

- **read**: taken from the core's bytes or its decompile. Supports a mechanism, not what
  the device did.
- **measured**: observed live on spare 412.
- **hypothesis**: fits the evidence, not shown.

## 1. Where things stand

| Question | Answer | Label |
| --- | --- | --- |
| Why does USB leave after 9.9 s? | A 10 s timer armed when CDC opens calls `hal_UsbClose`. The 1 h build kept CDC for the full 660 s window, three boots running. | measured |
| Why did the ROM return after ~5 min on trial 4? | It followed the USB loss. With the timer extended there was no reset in 12+ min. Trial 4 ran the patched charger-branch core; the NVM-only core never returned in 11 min. | measured |
| Why does the app never run? | The license record is blank, so the validator returns nonzero and startup drops the app descriptor for the built-in one. Two filmed boots showed no entry marker (the marker code itself is not hardware-proven). | blank record measured; validator return **read**, not captured |
| Does the console answer? | No. `help`, `devinfo`, `secr` and `apn=` are echoed and produce no reply and no effect. | measured, cause open |
| Does the network work? | `SIM card ready`, `GSM - Registered`, `GPRS - Registered`, then `APN Not Found`. The APN cannot be set because the parser does nothing. | measured |
| What else is open? | CDC data stops ~11 min after boot while enumeration persists; a constant ~868 B/s NUL stream on the port. | measured, cause open |
| What blocks the project? | Activation. The stock path (`getlic`) goes through the vendor's server, which the user has ruled out. A user decision, not an engineering step. | |

## 2. Conventions and pinned inputs

- **Core:** `core-nvmfix.bin`, the first `0x250000` bytes of the NVM-fixed trial image,
  SHA-256 `aae113419a716f04defd2375e8ece913af67bf02c6159e7d682a72b7199c643a`, at
  `firmware/live/2026-10-10-logicrom-offline/`. Upstream LOD 0.5.1:
  `0499c0e051f166e899daf13503c8d2b07ba65c884de047f17bb8f8cd38d31df7`.
- **Addresses** are core virtual addresses: `0x88000000` plus the flash offset. A MIPS16
  function pointer has bit 0 set (`0x880fcce9` is the function at `0x880fcce8`).
- **Disassembly:** Homebrew `gobjdump -m mips:16 -EL --adjust-vma=0x88000000`. Bytes are
  little-endian, in ascending flash order.
- **Decompile:** the Ghidra export has 8,124 functions, none failed. Only flash and blank
  RAM are mapped, so calls into `0x81xxxxxx`/`0x82xxxxxx` have no body. Rebuild recipe in
  [the core-trace handoff](../done/26-10-10-handoff-core-trace.md).
- **Time:** HAL ticks run at 16,384 Hz. Milliseconds convert as
  `(ms << 4) + high32(ms * 0x624dd2f1)`, so 100 ms is 1,638 ticks.
- The core's SDK exports resolve by hash (358 of 367 named). Our probe's 87 SDK imports
  all resolve against that table.

## 3. Application handoff and the license gate

### 3.1 App loader (read)

Loader `0x88238d44` checks magic `0x41505031` at `0x88250000`, the size, and a CRC32
(`invalid appimg crc/0x%x calc/0x%x`), then walks a section table (copy, zero-fill,
symbol patch). Symbols resolve by hash against a sorted 367-entry table at file offset
`0x241a40` (lookup `0x88230038`). A stub's hash is `((w0 & 0xffff) << 16) | (w1 & 0xffff)`
of its first two words. The image builder already checks magic, size and CRC, so a bad
header, CRC or unresolved symbol is not why the probe prints nothing.

### 3.2 Descriptor selection in the system task `0x882302f0` (read)

1. With an app present: prints `app:`/`main:`/`magic:` and compares `_DAT_88250080`
   against `LROM_SDK_APPCODE` (16 bytes). **A mismatch, or `_DAT_88250090 == 0`, selects the
   built-in descriptor `0x88244434`; otherwise `0x82300000 = 0x88250080` (the app).** The
   installed image passes both checks.
2. Reads record 1 at boot (`0x88232a84(1, 0x823002f8, 0x100)`).
3. Calls the license validator (`0x88233bcc`, startup call at `0x8823036e`). **Nonzero:**
   registers the 600,000-unit generic timer (callback `0x882301fc`), selects the built-in
   descriptor (`0x8823038e`) and posts `0x1607`. **Zero:** runs the module check
   (slot `0xc` against `0x88233a64`/`0x88233a70`), falling back to built-in on mismatch.
4. Descriptor slots then drive the system: `[3]` init, `[4]` second init, `[5]` event
   callback (SYS Task2 forwards `0x160e` cable events), `[7]` print, `[10]` SYS Task1 hook.
   The selected init is called at `0x882303f2`.

**Consequence:** an absent or invalid license means the app descriptor is dropped before
slot 3, so our `main()` never runs and no entry marker can appear. Loading a valid APP1
and seeing the built-in console proves core execution only.

### 3.3 Where the license lives (read)

`0x88233bcc` asks `0x88232a84` for 96 bytes of record index 0. That reader maps index 0 to
address `0x1000` and calls the core vtable slot at offset `0x5ac`; the vtable at
`0x88204468` holds `0x820011ed` there. The boot copy maps flash `0x8801b7e0–0x8801caf0` to
RAM `0x82000b00–0x82001e10`, and its routine at `0x820011ec` sends SPI opcode `0x48`, three
address bytes and one dummy byte, up to four bytes per transaction. That is
`hal_SpiFlashSecurityRead` / `OPCODE_SECURITY_READ`. Security program/erase use `0x42`/`0x44`.

**The address is in the flash chip's security registers, not main-array offset `0x1000`
and not `/nvm`.** No saved 4 MiB image contains it, so ordinary dumps cannot tell an absent
license from a present, rejected one.

### 3.4 The validator (read, reconstructed)

The validator is reconstructed from the init block copied from `0x882454a0` to
`0x82300000`. The caller hex-decodes the 96-byte record to 48 bytes, transforms the stored
key and IV, then AES-CBC decrypts `0x1b0` bytes at `0x82300110`. The entry at `0x82300144`
decrypts the record, compares its identity field with a value derived from the device UUID
and IMEI, and Luhn-checks the serial (`0x88233a9c`).

| Return | Condition |
| --- | --- |
| 14 | Decoded input is not 48 bytes (all-`ff` input gives length zero) |
| 13 | Decryption routine reports an error |
| 5 | Device identity retrieval fails |
| 6 | Identity comparison fails |
| 1 | Serial check fails |
| 0 | Checks succeed |

These are reconstructed paths. The decoded validator SHA-256 is
`8287d3697273da63965d680c07f1ff67730e26161f1756e09bf3aceb88a6bc27`; reproduce with
`python3 firmware/live/2026-10-10-logicrom-offline/extract-license-trace.py` (needs OpenSSL
and GNU objdump, asserts both hashes, performs no device I/O).

### 3.5 Measured state of 412

The reviewed `0xfc` ROM helper read the security register at 18:47:12 UTC: error 0, JEDEC
`0x1660c8`, 133 commands, two identical 256-byte passes **entirely `ff`**. The reader then
supplies length zero and the validator returns 14. The runtime return code itself was not
captured. Run record:
[rom-flash-access.md §6](rom-flash-access.md#6-returning-helpers-through-the-rom-monitor).

### 3.6 Activation and the other license code (read)

- `getlic` → `0x8823aa2c` → `0x88233b50`: a server round-trip (`0x88233c90`), Luhn check on
  the returned serial, no-op if the stored record matches, otherwise copy the serial to
  `0x82300014`, save the 96-byte record (`0x88233b14` → `0x88232adc(0, …)`), print `+SER:`
  and `sys_reset`. This is the stock self-service activation and it uses the vendor's
  service.
- `setlic=` takes exactly `0x60` hex characters.
- `system_serialvalid` (`0x88233afc`) Luhn-checks the RAM serial at `0x82300014`.
- The 600,000-unit generic timer stores `period_ms / 100` (`0x8823737a–8e`), so its nominal
  period is **600 s**. Its callback re-runs the serial check: valid frees the timer, invalid
  enters the task-control path `0x8823307c`. This timer is not the ~5 min reset and not the
  ~11 min data death (data lived 58 s past 600 s).

Whether `getlic` is acceptable under the no-Waybyte constraint is the user's decision. No
bypass is assumed or proposed.

## 4. USB

### 4.1 Mode switch and the 10 s timer chain (read, body level)

`0x880fcd6c(mode)` (148 B) is the USB mode switch. It does nothing if `mode` equals the
stored mode at `0x820a1000`. Link state is the byte at `0x820a0ff4`.

| Mode | Effect |
| --- | --- |
| 0 (open CDC) | State 2. **Arms `0x8200cd54(0x28000, 0x880fcce9, 0, 2, 0)`**: 163,840 ticks = 10 s, oneshot. Installs descriptor callback `0x880739cc(0x880fccf9)`. |
| 1 (charger) | Sets the `USB Controller 1.0` strings, calls `hal_UsbClose` (`0x88073838`), posts `0x15e988ac` to queue `0x820a0ffd`, state 1, **cancels** the timer (`0x8200c4a8(0x880fcce9, 0)`). |

- **Timeout body** `0x880fcce8` calls `hal_UsbClose` directly (`30 18 0e ce 00 65` =
  `jal 0x88073839; nop`, at file `0x0fccec`). It is referenced only by the arm and the two
  cancels, so patching it touches no other path. `hal_UsbClose` itself is shared (also
  called at `0x880fcdbe` in mode 1).
- **Descriptor callback** `0x880fccf8` (`0x880fccf9`):
  - state 2 and event nonzero → state **3**, timer still armed (the exit at `0x880fcd1a`
    is `17 10`);
  - state 3 → posts to queue `0x820a0ffd` if its ID is not `0xff`, state **4**, **timer
    canceled** (`0x880fcd44`: `04 18 2a 31 00 6d`). This second path does **not** check the
    event value.
  So the 10 s close is canceled only by a **second** descriptor-callback event. Whether that
  event is suspend or something else on this host is not established.
- **Period literal** `00 80 02 00` (`0x00028000`) at file `0x0fce08`, in the function's
  private pool (`0x0fce00–0x0fce22`); no other function loads it. Cancel without a prior
  arm is a no-op, so double-cancel is safe.
- **State consumers** (4 references to `0x820a0ff4`, all decoded): `FUN_880fcb34` (USB
  open) treats 2, 3 and 4 identically (re-enumerates the controller); USB init at
  `0x880fce2c`/`0x880fce68` only tests nonzero. Nothing distinguishes 3 from 4. Queue
  `0x820a0ffd` holds a dynamically set queue ID; its consumer is unidentified, so do not
  change the payload (0 on the normal 3→4 path, 1 from mode 1).
- **Secondary path:** the USB interrupt handler `0x88074324` also powers the controller off
  (`(6,0)`) when early-suspend/suspend/reset flags equal `0x1c00` with the charging flag
  clear. It bypasses `hal_UsbClose`. It is no longer needed to explain the 9.9 s timing.
- The SDK's `uctls_fnc.c` and `hal_usb.c` corroborate the timeout, the state cancel and
  the suspend handling; the core's own bytes set the addresses.

### 4.2 The `USB Calib` task `0x8808b010` (read)

A persistent task: selects the default USB configuration (`0x880fcb34(0)`; `(2)` presents
`1782:4d11`), switches to charger mode at startup (`0x880fcd6c(1)`), reads the charger state
byte at `0x820173e8` and calls the wrapper `0x8808aff4` (`!= 0` → `0x880fcd6c(state == 1)`:
state 1 keeps mode 1, state 2 opens CDC and arms the timer), registers the wrapper as the
charger-change callback (`0x820173f0`), then loops on a 500 ms wait for calibration
messages unrelated to USB close. The charger byte at boot therefore decides whether CDC
ever opens; its value on this board has not been captured.

### 4.3 Cable events and the TX gate (read)

The USB event handler `0x8823ca8c` only logs and gates; none of its branches closes USB.

| Event | Action |
| --- | --- |
| 0 | RX DMA drain; TX completion restarts DMA; calls callback `0x82300f00` |
| 1 | RX into `0xa2074000`, NUL-terminate, call `0x82300efc` (console input) |
| 10 (`0xa`) | CDC request `0x22`: **`wValue == 3` sets the TX gate `0x82300ef8` ("USB: Port open"); `wValue == 2` clears it ("USB: Port close")**; 0/1 ignored |
| 14 (`0xe`) | "USB: cable connected", set `0x82300ef9`, rearm RX |
| 15 (`0xf`) | "USB: cable disconnected", clear TX gate |

The gate is exact: **DTR and RTS both on** opens it, RTS alone closes it, both off is a
no-op. Host-side, opening a node may already change DTR/RTS; set them explicitly.

### 4.4 Measured outcomes

- Every 412 run lost USB at ~9.9 s, with or without a host open, with the SIM in or out.
- The charger-disconnected patch (halfword `0x241a → 0x2432` at `0x23c9d0`, `--keep-usb-open`)
  did **not** help; it does not intercept the timer or the interrupt path. Legacy, not
  carried.
- **3,600 s build** (`--usb-timeout-1hr`: literal `0x00028000 → 0x03840000` at `0x0fce08`,
  image `40312e47…4c551`): CDC persisted the whole 660 s passive window on boot 1 and no
  reset occurred in three boots. The timer is the 9.9 s closer.
- **CDC data death:** on boot 2 data went silent 662 s after boot (19:42:03 UTC) while the
  device stayed enumerated, 58 s after the 600 s generic timer. Boot 3 data was alive to
  307 s. Cause unknown.

### 4.5 Patch options kept for the final fix

| | Change | Effect | Caveat |
| --- | --- | --- | --- |
| **A** | file `0x0fccec`, `30 18 0e ce → 00 65 00 65` (NOP the close) | Timer fires and does nothing; works whether or not 2→3 happens | Timer still fires; no delayed-close signal |
| **B2** | file `0x0fcd1a`, `17 10 → 11 10` (retarget the 2→3 exit to store-4 + cancel, skipping the post) | USB stays open once the first event occurs; state 3 never observable | Needs the first event; a naive NOP fallthrough would post payload 2 and was rejected |
| **C** (applied) | period literal → `0x03840000` | USB closes at 1 h instead of 10 s unless the second event arrives | Delay only, no fix |

Image builder pattern: `extend_usb_timeout()` in `tools/rda_logicrom_image.py` checks the
old literal and writes the new one, with before/after tests and installer acceptance. Change
one cause per image.

## 5. Console

### 5.1 Input, parser, output (read)

- Console init `0x8823b344` registers the USB RX callback `0x8823b3fd` (at `0x8823b3d4`).
  The callback copies input and queues a **type-2** message.
- The console task `0x8823b118` handles type-2 and type-1 in one loop. Type-2 is echoed
  (`0x8823b146`: UART1+UART2 via table `0x823002e8` slot `0xc0`, then the USB queue
  `0x8823c8f4` and a flush) and accumulated at `0x82300ddc`. **CR (13) submits a type-1
  message** (post `0x882333e0`, queue `0x823002cc`, `jal` at `0x8823b192`); the CR branch
  itself prints `"\n"`. LF is ignored. Type-1 runs the parser `0x8823aa80`.
- **There is no login gate.** `Username:` is printed by `logout`, `devuser@dev #` by
  `ttysms`, the `WAYBYTE SOLUTIONS` banner by another command. (An earlier note read these
  as a login prompt; the later body read corrected it.)
- **Command set:** `devinfo`, `ifconfig`, `ping=`, `apn=`, `network=on/off`, `getlic`,
  `setlic=`, `sysproxy`, `fota=`, `reboot`, `loglevel`, `logout`, `ttysms`, `smsr=`,
  `smsd=`, `smsdel`, `at+wsecdata=1,12,"…"` (writes a security record via `0x88232adc`),
  a help list, **`secr`** (reads `0x100` bytes at the security index through vtable slot
  `0x5ac` and hex-dumps them) and **`devmem`** (hex address, optional decimal value, width
  8/16/32: a built-in peek/poke). Unknown commands print nothing.
- Replies print through the function at `*0x823002c4` with channel 0. The system task
  replaces that pointer during init (`DAT_823002c4 = descriptor[7]`).
  `FUN_8823b1e0` gates on `1 << channel & *0x82300dd4`.

### 5.2 What the live captures show (measured)

Each of `help`, `devinfo` and `secr` was sent on its own capture in the same boot of the 1 h
image (19:34:31, 19:37:20 and 19:39:31 UTC), and `apn=sme.vodafone.iot` in the next boot.
Every line came back echoed with its `\n` (the CR branch was reached) within 30 ms. No reply and no
effect followed, while `NW:` network messages kept arriving on the same port
(`SIM card ready`, `GSM - Registered`, `GPRS - Registered`,
`NETWORK: APN Not Found, Please configure!`, repeating each ~74 s).
Captures: `firmware/live/2026-10-10-logicrom-412-timeout-1hr-restart-1-{help,devinfo,secr}.jsonl`
and `…-restart-2-apn.jsonl`.

### 5.3 Hypotheses, in the order the evidence retires them

| Hypothesis | Status |
| --- | --- |
| The descriptor's slot-7 print routes channel 0 elsewhere | **Refuted.** `NW:` messages use the identical call (`s1 = *0x823002c4`, `jalr s1`, `a0 = 0`) and are audible. Pool words: `0x882328ac` (network) and `0x8823afd0` (parser) both hold `0x823002c4`. |
| The channel mask `0x82300dd4` drops the reply | **Refuted.** Bit 0 must be set, or `NW:` prints would be dropped too. |
| The parser blocks in data collection (`secr`'s reader at `0x820011ec`; `devinfo`'s four collectors `0x88230e75`, `0x8823713d`, `0x88230e15`, `0x88232e6d`) | **Not supported.** `help` collects nothing and is silent too; and the console task echoed `devinfo` and `secr` minutes after earlier commands, so one task loop was never blocked. |
| The reply is lost under the NUL stream or a TX queue overflow | **Not supported** for `help` (14 short lines) or `apn=` (no print needed, and the APN is still missing). |
| The type-1 post never lands, or its consumer never runs the parser | **Leading, unmeasured.** `apn=` having no effect says the parser's handlers did not run at all. |

### 5.4 Capture points still available

| Hypothesis | Address / state | Expected input | Capture that settles it |
| --- | --- | --- | --- |
| Type-1 post lost | `0x882333e0` in `0x8823b118`; queue `0x823002cc` | `help\r` | post return value; consumer reached or not |
| Charger path opened CDC | wrapper `0x8808aff4`; byte `0x820173e8` | any boot | wrapper input not 2 |
| Timer is the only closer | `0x820a0ff4`; cancel `0x8200c4a8` | passive | state reaches 3 and never 4 on a 10 s image |

`devmem` and `secr` are the way to read these live, but a console that does not answer
cannot be used for it. The ROM helper path
([rom-flash-access.md](rom-flash-access.md#6-returning-helpers-through-the-rom-monitor))
remains the route to flash-side values.

## 6. Reset and network paths (read)

| Call site | Reason passed to `0x88232e08` |
| --- | --- |
| `0x882319e2` | 3: data/network URC path (`NW: GPRS enable timeout, rebooting...`) |
| `0x88232474` | 1: no SIM, 60 passes of state 1 (`NW: No SIM, reset`; counter `0x82300814`) |
| `0x88232780` | 2 from the registration threshold (`0x88232626–28`, `NW: Reg. fail, rebooting`) or 3 from data-failure joins incl. `0x8823277e` (`NW: GPRS Act timeout`) |
| `0x88233650` | 5: parameter reset |
| `0x8823bebc`, `0x88240aa0` | 4: FOTA paths |

- `sys_reset()` (`0x88232de8`) supplies reason 0; its four callers are `0x88233932`,
  `0x8823aa62`, `0x8823ad1c` (the `reboot` command) and `0x8823b2ae`.
- The gate `0x88232dcc` reads the callback at `0x823009b8` (setter `0x88232dc0`), returns 1
  when unset, otherwise calls it with the reason; the result decides whether the reset runs
  through vtable offset 28 to `0x88184afd`. A base-modem path at `0x88192d8a` calls that
  target directly and bypasses the callback. These are six direct MIPS16 calls plus an
  indirect API export; it is not an exhaustive map of watchdog, exception or base-modem
  resets. Reason 6 (system format) has no identified direct caller.
- An app that registers the reboot callback sees every network-driven reset and can deny it,
  but only if the app runs, which the license gate currently prevents.
- Network timer callback `0x88232968` re-arms at `0x88232992` with 100 ms. The poll periods
  change by state, so the ~5 min trial-4 return could not be tied to a caller by timing; it
  was in the end a consequence of the USB loss (§1).
- State bytes: `0x82300828` … `+3` last SIM/CS/PS/state, `0x82300814` no-SIM counter,
  `0x82300810` registration counter, `0x82300834` registration limit, `0x82300818` polling
  count, `0x82300820` polling period, `0x8230082b` state byte, `0x820a44cc` status character.
  Recorded as candidates; capture raw values, not interpretations.
- Core exports `gpio_request` (`0x8823c670`) and `gpio_write` (`0x8823c1b0`) exist, and the
  SDK enum covers `GPIO_0`–`GPIO_36`. `cli_init` and `system_set_reboot_callback` must be
  called by the app; the older probe called neither.

## 7. Still unknown

- What the second descriptor-callback event is on this host, and so whether the unpatched
  core would ever keep USB open.
- Why the parser's handlers have no effect while echo and `NW:` output work (§5.3).
- The ~868 B/s NUL stream, and the CDC data death ~11 min after boot.
- The runtime value of the validator return, the charger byte `0x820173e8`, and the module
  check outcome once a valid license exists.
- Radio operation beyond registration: the core's PA tables (`pasw_rda6625`) differ from
  the vendor's (`pasw_rda6625e`).
