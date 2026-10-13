# V24 / LogicROM — working summary for agents

Updated 2026-10-11; run evidence runs to 2026-10-10 19:55 UTC. This is the single
handoff: current state, the experiment ledger, traps and open questions. What is known
about the systems lives in [../knowledge/](../knowledge/), starting with
[logicrom-core.md](../knowledge/logicrom-core.md) and
[rom-flash-access.md](../knowledge/rom-flash-access.md). Since 2026-10-11 the project
direction is the [30-days-on-battery plan](26-10-11-battery-route-plan.md), which parks
Logicrom.

**Latest result.** The reviewed 10 s→3600 s timeout image kept CDC alive for a full
660 s passive window (before: 9.9 s every time), so the enumeration timeout is the 9.9 s
closer, and the ~5-min return to ROM went away with it (no reset in 3 boots).
**Console input is a dead end in this build:** `help`/`devinfo`/`secr`/`apn=` all echo
with zero replies and zero effects while network prints keep arriving. Two filmed boots
show **no app entry marker**: the app never runs. **The license record is blank**
(`0xfc` security read 18:47:12 UTC, two identical 256 B `ff` passes), the validator
returns 14 and the built-in descriptor is selected, which is the structural cause of the
missing app. Activation is the demonstrated blocker and conflicts with the no-Waybyte
constraint: a user decision. 412 is running the timeout image (boot 3), boot word blank,
last contact 19:54:59 UTC — **not in ROM; do not assume ROM state.**

Quick navigation: [current state](#1-current-state-and-user-decisions) ·
[proven capabilities](#2-what-we-can-already-do) ·
[runtime experiments](#5-experiments-already-completed--logicrom-runtime) ·
[do not repeat](#8-do-not-repeat--operational-traps) ·
[open questions](#9-open-questions-and-next-steps).

## 1. Current state and user decisions

| Item | Current knowledge |
| --- | --- |
| Goal | Run our own tracker application on the ReachFar V24 using LogicROM. |
| Spare `1403167412` (412) | **Running the 1 hr-timeout image (boot 3 of install `2026-10-10-logicrom-412-timeout-1hr`), boot word blank, last contact 19:54:59 UTC.** Timeout image (`40312e47…4c551`, NVM fix + period `0x28000`→`0x3840000`, pinned v2 app) installed 19:11:09 UTC after vendor restore (block protection recurred `0x1c/0x02`, cleared narrowly). Boot 1: CDC persisted full 660 s passive (timer CONFIRMED; no reset). Boot 2: echo/zeros/network OK, `help`/`devinfo`/`secr` silent, GPRS registered + `APN Not Found` retry ~74 s, data died 662 s post-boot. Boot 3: `apn=sme.vodafone.iot` echoed, no reply, APN still missing across 4 cycles — parser has no effects. No LED markers on filmed boots: app never runs. Last flash verify (two equal reads `47e7a705…`, core/app + tail intact, 148 storage sectors) before boot 3. CDC data dies ~11 min post-boot, enumeration persists. **License blank** (`0xfc` read 18:47:12 UTC, `ff` × 256, [journal](../../firmware/live/2026-10-10-logicrom-412-security-fc-1/operations.jsonl)); validator-14 → built-in descriptor explains the missing app. Recovery target for this install is `--finish firmware/live/2026-10-10-logicrom-412-timeout-1hr` on a separately authorized run. |
| Reference `1403167417` (417) | Vendor code was not replaced by LogicROM. Programmer, query, scratch-sector write/erase and status-reader controls ran on it. Do not describe it as never touched; retain the tool's block on replacing its code. |
| SIM | **User confirms it works with original firmware and has 2G service.** LogicROM now prints full `SIM ready → GSM Registered → GPRS Registered` cycles plus `NETWORK: APN Not Found` (first GPRS registration 19:36 UTC). PDP/data unproved: APN cannot be set (console parser takes no commands). Do not send the user back to validate the SIM. |
| Waybyte | **User does not want Waybyte involved.** No support contact or issue filing. The old draft questions are historical, not the next action. |
| Access | Prior user constraints: Apple Silicon Mac, magnetic USB cable, power button and RST only. No Windows/Coolwatcher, case opening, pads, soldering or UART adapter. Five spares already exist; do not suggest buying more. |
| Writes | Prior user instruction requires a go for each live erase/program run. This summary and diagnostic plan are not authorization to start a new device experiment. Offline review/build work can proceed. |
| Shared checkout | Other sessions edit this checkout. Preserve their changes; do not bulk-stage, clean or commit unless requested. |

Current restore evidence: [journal](../../firmware/live/2026-10-09-logicrom-412-trial-4-2-recover/operations.jsonl),
[log](../../firmware/live/2026-10-09-logicrom-412-trial-4-2-recover.log),
[exit status](../../firmware/live/2026-10-09-logicrom-412-trial-4-2-recover.exit).
Vendor boot is recorded in the final restore section of
[the trial history](26-10-09-logicrom-trial.md#restore-of-412-after-the-sim-start-passed--2026-10-10).
That boot was identified from Mac USB logs/descriptors; no post-boot flash dump or
network-registration test was made in that check. This is the last recorded state,
not a promise that the same unit is still connected now.

## 2. What we can already do

| Capability | Demonstrated result / entry point |
| --- | --- |
| Read vendor firmware and logs over magnetic USB | Complete unit-specific backups; live network, APN and server logs. [Firmware analysis](../knowledge/firmware-analysis.md) |
| Configure the original firmware locally | `AT:<command>#\r` on its data interface; APN/server persisted across reboot, GPRS and TCP worked. [Configuration evidence](../../firmware/live/after-reboot-status.raw) |
| Enter ROM without opening the tracker | Vendor debug force bit + reset; correct monitor handshake and ROM hash. [ROM session](../../firmware/live/2026-10-08T225652Z-rom-session.jsonl) |
| Load a functioning USB RAM programmer | Corrected programmer reaches READY in about 0.54 s. Reads all 4 MiB in about 9.5 s (ROM takes about 31 s). [Clean run](../../firmware/live/2026-10-09-programmer-clean-1/operations.jsonl) |
| Query, erase and program flash | Both mailbox slots work; 4 KiB program chunks, 64 KiB block erases and 4 KiB tail-region erases exercised. Full-image installations/restores passed. |
| Keep recovery independent of vendor code | Withhold boot magic during trials. Physical RST returns to ROM with a blank word; monitor remains beyond its usual idle timeout. [RST proof](../../firmware/live/2026-10-09-rst-blank-412-rom-check/operations.jsonl) |
| Install and start LogicROM | Install core/app, verify, then issue one ROM exit to flash entry. USB enumeration and runtime filesystem writes prove some core execution. This does not prove app execution. |
| Restore after a trial | `rda_programmer_start.py --finish INSTALL_JOURNAL` restores changed sectors from the original pre-start snapshot, block 0 last, then boot magic. Exact full-image readback demonstrated. |
| Read and clear the observed flash protection | Read SR1/SR2. Narrow clear operation accepts only `0x1c/0x02` and changes it to `0x00/0x02`; recovery then works. |
| Build a LogicROM application on the Mac | Existing Colima/Docker Linux MIPS compiler, SDK and runtime archives produce a packaged APP1 image. No new toolchain search needed. |
| Inspect vendor code and board wiring | Existing Ghidra export, named functions, pad register reads, confirmed LED/buzzer tests and partial peripheral map. |

Recovery after complete battery/power loss and an interrupted hardware write is
**not** established. Interrupted install/recovery was simulated, not deliberately
power-interrupted on hardware. Proven RST recovery must not be called universal
unbrickability.

## 3. Hardware, memory and USB facts

| Fact | Value / qualification |
| --- | --- |
| Device | ReachFar V24, **2G GSM/GPRS**, RDA8955, little-endian MIPS16/MIPS32. Vendor target is a watch-derived board. |
| Flash | 4 MiB; JEDEC `c8 60 16`, GigaDevice family. Exact chip revision is not established. |
| Read mappings | Vendor flash `0x88000000`; ROM/programmer uncached flash `0xa8000000`. Do not reuse vendor RAM symbol addresses in a programmer or LogicROM session. |
| Erase geometry | 64 KiB below offset `0x3f0000`; 4 KiB above. Use actual pinned geometry, not the LOD metadata's sector map. |
| Boot magic | Flash offset 0: `0xd9ef0045` valid; `0xffffffff` intentionally blank for trials. A later reset returns a blank-word trial to ROM. |
| Reset register | Physical `0x01a000a0`; force-monitor bit 17. Common reading `0x00200000`, forced reading `0x00220000`. These fields alone do not identify every reset cause. |
| Protected tail | `0x3fa000–0x400000`: calibration and factory/identity. Unit-specific. Never substitute another unit's tail. |
| LogicROM layout | Core `0–0x250000`; app `0x250000–0x2e0000`; runtime filesystem `0x2f0000–0x3f0000`; `/nvm` `0x3f0000–0x3f6000`; user data `0x3f6000–0x3fa000`. Ranges exclude their end. |
| Factory address | Core code uses `0x3fe000`, as V24 does. LOD `FACT_SETTINGS_BASE=0x3f4000` is misleading metadata; do not relocate factory data because of it. |
| Radio compatibility | Transceiver/PMU and calibration tags/PA IDs match. Vendor PA driver `pasw_rda6625e`, core `pasw_rda6625`; default PA tables differ. Actual LogicROM radio operation remains unproved. |

USB identities (`1e04:0900` RDA Usb / Coolsand Usb, `1782:3d00`, `1782:4d11`) are
distinguished by interface, not VID:PID: see
[rom-flash-access.md §2](../knowledge/rom-flash-access.md#2-usb-identities-and-entering-the-rom).
The board mapping (GPIO 4 blue GPS LED, 27 red network LED, 28 white light, GPS power
GPIO 32, buzzer on PMU level 8) is in [pin-map.md](../knowledge/pin-map.md). LogicROM UART1
overlaps GPIO 4/5, so opening it can conflict with the blue LED.

## 4. Experiments already completed — transport and recovery

These are compressed outcomes, not a command list to replay.

| Experiment | Result and lesson | Evidence |
| --- | --- | --- |
| Oct 2–3: vendor command probing | Early APN attempts lacked `AT:` framing. Correct framing solved it; no raw settings-flash edit needed. Some commands log without `AT RETURN`; `tsext` caused a reboot. | [Analysis/configuration](../knowledge/firmware-analysis.md#9-working-native-usb-configuration), [APN persistence](../../firmware/live/verify-persistence-reboot.raw) |
| Oct 3–8: ROM entry probes / early “dark USB” | Early restart attempts did not establish recovery. A plain-reset control also lost USB while the vendor app continued; forced entry was subsequently demonstrated. Do not retain “USB absent means ROM failed.” | [Loader audit](../done/26-10-08-loader-audit.md#control-for-the-forced-rom-test-a-plain-reset-also-goes-dark), [successful ROM reads](../../firmware/live/2026-10-08T225652Z-rom-session.jsonl) |
| Oct 8: cached flash ID and clock comparison | Cached JEDEC confirmed; vendor/programmer SPI configuration constants match. The programmer's separate 104 MHz system-clock request was a different issue. | [Identity/clock review](../done/26-10-08-cached-flash-id-review.md) |
| Oct 8: prebuilt programmer audit | Host-port candidate did not establish USB polling. Built a USB-enabled programmer from archived SDK instead. | [Binary/source audit](../done/26-10-08-loader-audit.md) |
| Oct 8–9: programmer starts but no READY | Stage markers localized the stop to `hal_SwRequestClk(104M)`, using an uninitialized clock object because this build skips `hal_Open`. Removing that call fixed startup; clean build also uses 200 mA charge configuration. | [Marker failure](../../firmware/live/2026-10-09-programmer-markers-2/operations.jsonl), [marker success](../../firmware/live/2026-10-09-programmer-markers-4/operations.jsonl), [clean success](../../firmware/live/2026-10-09-programmer-clean-1/operations.jsonl) |
| Oct 9: query / scratch write on 417 | Both PING slots and finalize-info respond. Two 4 KiB patterns at the ends of blank block `0x3e0000`, then block erase, leave the complete image unchanged. | [Query](../../firmware/live/2026-10-09-programmer-query-1/operations.jsonl), [write test](../../firmware/live/2026-10-09-programmer-write-test-1/operations.jsonl) |
| Oct 9: power button + RST | Does not assert the ROM strap. Do not repeat button combinations expecting forced ROM. | [Button test records](../../firmware/live/2026-10-09-button-rst) |
| Oct 9: programmer-session reset on 412 | First run did not re-enumerate unaided. A Mac USB port reset made ROM appear in the second run; flash unchanged. Existing tool includes this handling. | [First](../../firmware/live/2026-10-09-reset-test-412/operations.jsonl), [second](../../firmware/live/2026-10-09-reset-test-412-2/operations.jsonl) |
| Oct 9: blank-word tests | Soft-reset/40 s idle test passed; separate stop/finish passed; physical RST with word blank and force bit clear returned ROM; full restore passed. | [Initial](../../firmware/live/2026-10-09-blank-word-412/operations.jsonl), [separate finish](../../firmware/live/2026-10-09-finish-check-412-restore/operations.jsonl), [RST](../../firmware/live/2026-10-09-rst-blank-412-rom-check/operations.jsonl), [restore](../../firmware/live/2026-10-09-rst-blank-412-restore/operations.jsonl) |
| Oct 9: whole-image rehearsal | LogicROM installed without running it, then original image restored exactly; 46 changed sectors. Proves installation/recovery, not runtime compatibility. | [Install](../../firmware/live/2026-10-09-logicrom-412-rehearsal/operations.jsonl), [restore](../../firmware/live/2026-10-09-logicrom-412-rehearsal-restore/operations.jsonl) |

Earlier aborted runs (no device, wrong USB mode, wrong unit, diagnostic tool fault)
are recorded in the detailed histories. They are not additional firmware executions.
Notably the first LogicROM install attempt found **417 on the cable instead of 412**
and stopped before mutation: [identity refusal](../../firmware/live/2026-10-09-logicrom-412-trial/operations.jsonl).

## 5. Experiments already completed — LogicROM runtime

| Experiment | Result / interpretation | Evidence |
| --- | --- | --- |
| Trial 2: original 0.5.1, first execution | USB appeared for 9.9 s; initially blocked by Mac accessory permissions. First-boot formatting zeroed the first 32 bytes of all six calibration/factory sectors. Separate reviewed tail repair restored 412 exactly. | [Install](../../firmware/live/2026-10-09-logicrom-412-trial-2/operations.jsonl), [readback](../../firmware/live/2026-10-09-logicrom-412-trial-2-rom-check-2/operations.jsonl), [recovery account](26-10-09-logicrom-trial.md#recovery) |
| Offline root-cause analysis | `/nvm` mount size was `0x6000`, format size `0x60000`. Core layout itself agrees with V24. Corrected literal; builder/installer reject the known bad image. | [Root cause](26-10-09-logicrom-trial.md#root-cause-of-the-tail-damage--2026-10-09), [image builder](../../tools/rda_logicrom_image.py) |
| Trial 3: NVM correction, first boot | Mac accepts CDC. USB still leaves at 9.9 s; 7,823 received bytes are zeros except echoed `devinfo`. Tail intact, all changes in core storage range. | [Install](../../firmware/live/2026-10-09-logicrom-412-trial-3/operations.jsonl), [console](../../firmware/live/2026-10-09-logicrom-412-trial-3-console.jsonl), [readback](../../firmware/live/2026-10-09-logicrom-412-trial-3-rom-check-6/operations.jsonl) |
| Trial 3: second boot of same install | Same 9.9 s USB loss; normal filesystem changes, tail intact. Therefore USB loss is not only a first-format event. Both runs ended with RST. | [Restart](../../firmware/live/2026-10-09-logicrom-412-trial-3-restart-1/operations.jsonl), [readback](../../firmware/live/2026-10-09-logicrom-412-trial-3-rom-check-7/operations.jsonl) |
| Trial 3 restoration failed | Erase reported done in 1 ms but flash was not erased; tool stopped before programming. SR1/SR2 = `0x1c/0x02`, all blocks protected. Reference 417 read `0x00/0x02`. | [Status 412](../../firmware/live/2026-10-09-status-412/operations.jsonl), [control 417](../../firmware/live/2026-10-09-status-417/operations.jsonl), [failure account](26-10-09-logicrom-trial.md#the-restore-stopped-the-flash-ignores-erase--2026-10-09) |
| Unlock and trial 3 restore | One narrowly checked status write cleared BP2–BP0 while preserving QE. All 72 changed sectors restored; vendor boot and code/tail readback passed. | [Unlock](../../firmware/live/2026-10-09-unlock-412/operations.jsonl), [restore](../../firmware/live/2026-10-09-logicrom-412-trial-3-recover-2/operations.jsonl), [post-boot](../../firmware/live/2026-10-09-logicrom-412-trial-3-recover-2-after-rst/operations.jsonl) |
| Trial 4: ignore charger-disconnected handler | Installed NVM fix plus one branch change. **No improvement:** USB still leaves after 9.9 s. Device returned to ROM by itself about 302 s later; tail intact, status `0x00/0x02`. | [Install](../../firmware/live/2026-10-09-logicrom-412-trial-4-2/operations.jsonl), [console](../../firmware/live/2026-10-09-logicrom-412-trial-4-2-console.jsonl), [status](../../firmware/live/2026-10-09-status-412-2/operations.jsonl) |
| Trial 4 second start, Oct 10, no SIM | USB 9.9 s; ROM returns 296.7 s after USB loss. Force bit was clear. No block protection after two naturally ending runs. | [Restart](../../firmware/live/2026-10-09-logicrom-412-trial-4-2-restart-1/operations.jsonl), [status](../../firmware/live/2026-10-10-status-412/operations.jsonl) |
| Trial 4 third start, Oct 10, SIM inserted | USB 9.9 s again; ROM returns 308.0 s later. A SIM did not stop the reset. Tail intact; status still `0x00/0x02`. User subsequently confirmed SIM works in original firmware. | [Console](../../firmware/live/2026-10-09-logicrom-412-trial-4-2-restart-2-console.jsonl), [kernel USB timing](../../firmware/live/2026-10-09-logicrom-412-trial-4-2-restart-2-usb-kernel.log), [readback](../../firmware/live/2026-10-09-logicrom-412-trial-4-2-rom-check-3/operations.jsonl), [status](../../firmware/live/2026-10-10-status-412-2/operations.jsonl) |
| Post-reset RAM inspection | Before loading a programmer, two external-RAM pages returned repeating `ff 11 55 aa`, not useful state. Cannot recover the network state this way. Cause of unusable RAM is not established. | [RAM journal](../../firmware/live/2026-10-10-logicrom-412-ram-peek-1/operations.jsonl), [reader/address notes](../../firmware/live/2026-10-10-logicrom-412-ram-peek.py) |
| Oct 10 final restoration | 72 sectors restored, all 4 MiB equal pre-trial vendor image, valid boot word; vendor boot confirmed after RST. No tail repair was needed. | [Restore](../../firmware/live/2026-10-09-logicrom-412-trial-4-2-recover/operations.jsonl), [latest account](26-10-09-logicrom-trial.md#restore-of-412-after-the-sim-start-passed--2026-10-10) |
| Oct 10 diagnostic v2, first start, port never opened | Install exit 0. CDC 15:07:00–15:07:10 UTC: **9.9 s with no host open**, so host port handling does not cause the loss. **No return to USB in 683 s** (all trial 4 starts returned in about 300 s; trial 4 had the extra USB patch, this core is NVM-only, so the app is not the only difference). User saw no LED activity. After user RST, ROM read: core/app unchanged, tail intact, 146 storage sectors changed, boot word blank. | [Install](../../firmware/live/2026-10-10-logicrom-412-diag-1/operations.jsonl), [passive log](../../firmware/live/2026-10-10-logicrom-412-diag-1-passive.jsonl), [readback](../../firmware/live/2026-10-10-logicrom-412-diag-1-rom-check-1/operations.jsonl) |
| Oct 10 diagnostic v2, second start, 115200 DTR+RTS on, `devinfo`+CR at 1 s | **First readable core output: `NW: SIM card ready` 4.4 s after enumeration.** `devinfo` echoed in 5 ms, no reply. Otherwise zeros (7,740 bytes). No direct app message; user filmed and saw **no blue/red marker** (marker code itself is not hardware-proven). USB left after 9.8 s; no return in the next 707 s. No status-register read yet after these two starts. | [Restart](../../firmware/live/2026-10-10-logicrom-412-diag-1-restart-1/operations.jsonl), [active log](../../firmware/live/2026-10-10-logicrom-412-diag-1-active.jsonl) |
| Oct 10 diagnostic v2, third start, `secr` CR once | Two equal full ROM reads verified installed code/tail, then one existing-image start at 16:32:44 UTC. Command echoed; no security hex dump. **SIM ready and GSM registered** were readable. USB left after 9.8 s. Subsequent ROM reads showed only runtime-storage changes `0x2f2000–0x2fdfff`; core/app and tail unchanged. License state still unmeasured. | [Console attempt](../../firmware/live/2026-10-10-logicrom-412-license-secr-1/operations.jsonl), [capture](../../firmware/live/2026-10-10-logicrom-412-license-secr-1/console.jsonl) |
| Oct 10 first RAM security helper, separate from firmware start | ROM, two full flash reads, exact SRAM load verified. Execution acknowledged at 16:41:49 UTC; return event timed out. Descriptor-only read follow-up failed. First build lacked required reduced-register flags, an avoidable error and candidate cause. No license bytes recovered; **do not replay hash `9b1b6b7a…40923`**. Corrected `444591d1…12a1f` has required flags plus binary register-use/transaction/ABI/timeout audit. | [Run](../../firmware/live/2026-10-10-logicrom-412-security-read-1/operations.jsonl), [audit and recovery state](../knowledge/rom-flash-access.md#6-returning-helpers-through-the-rom-monitor) |
| Oct 10 corrected RAM helper and direct MMIO fallback | Corrected helper also timed out. Post-RST SRAM was unusable. Direct ROM MMIO stalled on JEDEC receive `0x19f00`, before security opcode `48`. **Final recovery passed at 16:57:05 UTC:** ROM verified, controller reset state restored, two full flash reads unchanged, core/app and tail intact, blank word retained, safely waiting in ROM. License still unmeasured. Live helper/MMIO entry points disabled; compare ROM command-controller initialization offline next. | [Direct experiment](../../firmware/live/2026-10-10-logicrom-412-security-mmio-1/operations.jsonl), [final recovery](../../firmware/live/2026-10-10-logicrom-412-security-recovered-1/operations.jsonl) |
| Oct 10 reviewed `0xfc` return path, JEDEC, then security read | Return control passed 18:15:52 UTC; stack-switched JEDEC passed 18:24:15 UTC. **Security read passed 18:47:12 UTC: error 0, 133 commands, two equal 256-byte passes entirely `ff`. License record blank; normal activation prerequisite under traced validator.** Final verification 18:48:14 UTC: all four flash reads unchanged, clocks/persistent controller settings restored, status `0x021c` unchanged, 412 remains in ROM with blank boot word. Guard restored; no activation or reset/exit sent. | [Review and result](../done/26-10-10-rom-extended-handler.md), [security journal](../../firmware/live/2026-10-10-logicrom-412-security-fc-1/operations.jsonl) |
| Oct 10 1 hr-timeout image, install + passive (boot 1) | Restore blocked on 1 ms erase (protection recurred `0x1c/0x02`); status read, narrow clear to `0x00/0x02`, fresh restore passed 19:05:07 UTC (`5ca2fa00`, vendor boot `0x3410`). Timeout image (`40312e47`, +3 bytes vs v2) installed, exit 19:11:09 UTC. **CDC persisted the full 660 s passive window, never opened — the 10 s timeout is CONFIRMED as the 9.9 s closer. No reset in 12+ min: the ~5-min reset was downstream of USB loss.** First-open at 13.6 min found CDC data silent (death bounded on boot 2). | [Restore-2](../../firmware/live/2026-10-10-logicrom-412-timeout-restore-2/operations.jsonl), [install](../../firmware/live/2026-10-10-logicrom-412-timeout-1hr/operations.jsonl), [passive](../../firmware/live/2026-10-10-logicrom-412-timeout-1hr-passive.jsonl) |
| Oct 10 timeout boot 2, console mapping | Fresh baseline `42952a8d` (146 storage sectors), exit 19:31:01 UTC. Echo/zeros/network all live early; **first `GPRS - Registered` plus `APN Not Found` retry loop ~74 s**. `help`, `devinfo`, `secr` all echoed, zero replies — parser/type-1 delivers nothing while sharing the proven print path. **CDC data died 662 s post-boot (19:42:03 UTC), enumeration persisted** — a second ~11-min issue, not the 600 s timer (data lived 58 s past it). Filmed: no LED markers, app never runs. | [Restart](../../firmware/live/2026-10-10-logicrom-412-timeout-1hr-restart-1/operations.jsonl), [help](../../firmware/live/2026-10-10-logicrom-412-timeout-1hr-restart-1-help.jsonl), [span600](../../firmware/live/2026-10-10-logicrom-412-timeout-1hr-restart-1-span600.jsonl) |
| Oct 10 timeout boot 3, `apn=` attempt | Fresh baseline `47e7a705` (148 sectors), exit 19:49:52 UTC. `apn=sme.vodafone.iot` (from `tools/tracker_settings.json`) echoed at +66 ms, no `APN set to` reply, `APN Not Found` persisted across 4 network cycles in 300 s. **Parser has no side effects either (4/4 commands inert): console input is a dead end in this build.** Data alive throughout (boot age ≤307 s). Core still running at last contact 19:54:59 UTC. | [Restart](../../firmware/live/2026-10-10-logicrom-412-timeout-1hr-restart-2/operations.jsonl), [apn capture](../../firmware/live/2026-10-10-logicrom-412-timeout-1hr-restart-2-apn.jsonl) |

**Interpretation:** The 9.9 s loss was the 10 s enumeration timeout (proved by the
period change), and the ~5-min return to ROM went away with it — both symptoms had
one cause. What remains: a silent console parser (all input inert, prints proven),
an unrun app (license blank → validator 14 → built-in descriptor, plus filmed
no-marker confirmation), and CDC data death ~11 min post-boot with enumeration
persisting. Do not call the parser fault, the app gate, or the 11-min death
understood beyond these measurements.

## 6. Corrections, hypotheses and misleading older statements

| Item | What to retain |
| --- | --- |
| NVM format fix | At file offset `0x232d88`, change little-endian word `0x00060000` to `0x00006000`. Hardware-tested on first and later boots. Required in the next baseline. |
| USB “keep open” experiment | At `0x23c9d0`, halfword `0x241a` → `0x2432`. Ignores one disconnected-report branch. Did not keep USB open. Do not carry it as a proven fix; prefer NVM-only baseline for new diagnostics. |
| Core storage reaches end of flash | Early interpretation was disproved: layout matches, one format-size literal caused the damage. Do not move calibration or rewrite the app linker layout to fix this. |
| Mac accessory block | Real on trial 2, resolved before trial 3. Unblocked runs have the same 9.9 s loss. It cannot explain those later runs. |
| Flash protection cause | Protection and its clearing are proved. “RST while core runs sets it” remains a hypothesis: locked runs ended with RST; later natural-reset runs stayed unlocked. |
| Flash never written / restoration impossible | Historical statements superseded by repeated complete installs/restores and unlock. |
| Blank boot word | Deliberate recovery mechanism. Explains why a subsequent reset lands in ROM; does not explain what requested that reset or why USB disappears earlier. |
| App not printing | Does not settle whether the app executes: activation and output routing are unresolved. USB enumeration proves core execution only. |
| No LED observed | Probe does not configure board LEDs, so absence is not proof of no execution. |

## 7. Tools and reusable artifacts

Use existing implementations. Do not rebuild the flashing stack or rediscover the
protocol. `rda_programmer_start.py` is the hardware-exercised orchestration path;
`rda_flash.py` provides its underlying writer and has a separate qualification gate.

| Tool / artifact | Purpose / limitation |
| --- | --- |
| [rda_programmer_start.py](../../tools/rda_programmer_start.py) | Offline by default; `--execute` performs live work. Includes query, test, trial, full restore, status and narrow unlock modes. |
| [rda_flash.py](../../tools/rda_flash.py) | Pinned programmer/ROM hashes, geometry, protocol, journal and erase/program verification. Build addresses change with every programmer rebuild. |
| [rda_logicrom_image.py](../../tools/rda_logicrom_image.py) | Offline unit-bound image, LOD/APP1 validation, mandatory NVM fix, optional failed USB experiment. |
| [logicrom_console.py](../../tools/logicrom_console.py) | CDC capture plus passive IORegistry mode; explicit baud/raw 8N1, selectable DTR/RTS, requested/effective settings, CR/LF/CRLF, existing `--port`, partial-write handling and descriptor cleanup. Opening can itself change control lines. No login negotiation. |
| [Probe main.c](../../firmware/logicrom/main.c), [build.sh](../../firmware/logicrom/build.sh) | Diagnostic app (v2): independent blue/red entry/init pulses, direct USB writes, explicit CLI init and allow-reset reason callback. Installed and started on 412 since 2026-10-10; it has never executed (the license gate drops it). Trials 2–4 used the older printf-only app. No GPS, sensors or server reporting. |
| [Offline trace and diagnostic manifest](../done/26-10-10-logicrom-diagnostics.md) | Archived record of the first offline core trace and the v2 image preparation. The reconciled core knowledge is [logicrom-core.md](../knowledge/logicrom-core.md). No core hooks applied. |
| [Build provenance](../../firmware/live/usb-programmer-build/logicrom/build-provenance.json), [SDK and build inputs](../../firmware/live/usb-programmer-build/logicrom) | SDK `72f60a2`, pinned packaging scripts, Coolsand compiler and matching runtime archives. Existing `rda-usb-builder:local` image / `colima-rda-build` context. Build recipe in trial history. |
| [Clean programmer](../../firmware/live/usb-programmer-build/clean/artifacts/usb_8955_flsh_spi32m_ramrun_noclk_200ma.lod) | Corrected clock startup + 200 mA target. SHA-256 `c238911dc478363b1dffdebbffcc407e6e1b1b51ef5c53c9d90ca2fe8bff6c65`. |
| [Status build](../../firmware/live/usb-programmer-build/status), [unlock build](../../firmware/live/usb-programmer-build/unlock) | Extra commands use their own pinned metadata. “Read status” does not mean startup has no side effects: startup resets the flash chip and may set QE. |
| [Vendor decompile](../../firmware/decompiled/index.tsv), [Ghidra recipe](../../tools/ghidra/build.sh) | Existing 16,300-function export, named hardware/command functions and unpacked RAM code. Do not repeat the full export unless inputs change. |
| [rda_config.py](../../tools/rda_config.py), [rda_log.py](../../tools/rda_log.py), [tracker_ui.py](../../tools/tracker_ui.py) | Original firmware only; do not assume vendor command framing applies to LogicROM. |

Important hashes (full original files are local and generally gitignored):

| Artifact | SHA-256 |
| --- | --- |
| [412 original backup A](../../firmware/backup/v24_1403167412_2026-10-09_a_flash.bin), identical B copy | `b0250296dda7f0e6fd6eed44a561de740dbf52b158008d2ad416d7541d34a2c4` |
| [Upstream 0.5.1 LOD](../../firmware/live/usb-programmer-build/logicrom/core_v0.5.1.lod) — unsafe uncorrected first format | `0499c0e051f166e899daf13503c8d2b07ba65c884de047f17bb8f8cd38d31df7` |
| [NVM-only trial image](../../firmware/live/usb-programmer-build/logicrom/v24-412-trial-nvmfix.bin) | `e7ee068aa9fd04230703ae7e2b124a27b62995a8b3e2adbd070db0ec3c55bb9e` |
| [NVM + USB experiment image](../../firmware/live/usb-programmer-build/logicrom/v24-412-trial-usbkeep.bin) | `9802981441d3d165130718263ef74141cdf98d986678d110d14b2186f1b4556f` |
| [Trial 4 pre-start / latest recovery target](../../firmware/live/2026-10-09-logicrom-412-trial-4-2/before-startup.bin) | `af47612a1ccd73b8c5190adfb45f83a3256423f9d943e6da0324b6341e0978b3` |
| [Last LogicROM read before restoration](../../firmware/live/2026-10-09-logicrom-412-trial-4-2-rom-check-3/rom-read.bin) | `2d7d9f49ba0249565bfa02581d08aa85f68bf96b3d76d707e6357e0c27d6f773` |
| [Entry/console/reboot diagnostic v2 (app image)](../../firmware/live/2026-10-10-logicrom-offline/v24-412-diag-entry-v2.bin) | `90ae7ffa47824eee169fcc9ea9a06268a8184ad4fdf7f5d49256efd7b861c079` |

The backup and recovery-target hashes differ because vendor settings change during
normal operation. A restore must exactly match **that install's pre-start image**.
After vendor firmware boots again, compare code and protected tail separately;
legitimate settings writes can change the full-image hash.

## 8. Do not repeat / operational traps

- Do not rerun successful scratch-sector, blank-word or whole-image rehearsals
  unless the writer/entry mechanism changes or new evidence invalidates them.
- Do not rerun the same LogicROM image just to watch the same 9.9 s/five-minute
  sequence. Each new run needs a new measurement or a single controlled change.
- Do not ask for another SIM or another original-firmware SIM validation.
- Do not reapply the failed charger-disconnect workaround as the proposed solution.
- Do not inspect the same external-RAM pages after reset expecting preserved
  runtime state. A new retention/capture method must first be demonstrated.
- Do not infer device identity from its generic USB name. One wrong-unit trial was
  already caught by the per-unit tail check.
- Do not equate command DONE with a successful erase. Verify erased contents before
  programming. Read status after a core run; use the narrow unlock only for the
  known `0x1c/0x02` state, not arbitrary register values.
- Do not bypass the protected-tail check or use `--repair-tail` routinely. That was
  a specifically reviewed recovery of the first bad-core trial, not the normal path.
- Do not finalize the trial's boot word just to see whether reset behavior changes.
  Keep ROM recovery while diagnosing; permanent boot needs its own reviewed path.
- Do not send the old vendor-form MMIO writes through the ROM monitor: an early
  Reset_Cause write unexpectedly became `0x00350000`. Use the reviewed tool paths.
- No competing USB clients while a programmer/console owns the device. Check for
  `rda_`, `logicrom_console` and `tracker_ui` processes before live work. During CDC
  enumeration, use Mac observation rather than competing libusb opens.
- New journal/output paths every time. Recovery points at the **installation**
  journal, never a failed restore journal. Saved files are exclusive and durable.
- No RST, unplug or power button during a writing operation. Long observations of a
  running core should distinguish an automatic reset from an operator reset.
- Firmware images/logs contain unit identifiers and other private radio/network
  data. Link the existing evidence; do not paste or commit binary dumps into notes.

## 9. Open questions and next steps

**Completed since the first plan:** the offline map of startup, console, USB and reset
paths ([logicrom-core.md](../knowledge/logicrom-core.md)); the improved capture tool and
diagnostic app; the returning ROM helper and the security read
([rom-flash-access.md §6](../knowledge/rom-flash-access.md#6-returning-helpers-through-the-rom-monitor));
the 1 h timeout image and its three boots. The offline tracker skeleton exists
([design](26-10-10-tracker-app-skeleton.md), `firmware/logicrom/tracker/`: 30-min GPS
slots, motion gating, activity stats, 2×/day batched uploads, versioned record/JSON
format); it compiles and packages and has never executed.

**Decisions and constraints:**

- Activation is the demonstrated blocker for any LogicROM app. The stock `getlic` goes
  through the vendor's server; the user does not want Waybyte involved. No bypass is
  assumed or proposed. A user decision.
- The user's goal is now 30 days on battery without solar, with Logicrom parked; the route
  order and gates are in [the battery plan](26-10-11-battery-route-plan.md).
- Every live write or helper run needs the user's go. Do not repeat the security read, do
  not send console commands expecting replies, and do not run the console past ~10 min
  post-boot without accounting for the ~11-min data death.

**Open questions, if Logicrom work resumes** (details in
[logicrom-core.md §7](../knowledge/logicrom-core.md#7-still-unknown)):

1. Why the console parser delivers nothing although echo and `NW:` prints work. The
   remaining suspect is the type-1 post/consumer path; neither the print pointer, the
   channel mask nor a blocked parser fits the captures.
2. What the second USB descriptor-callback event is on this host, so whether the stock
   core would ever keep CDC open without the timeout patch.
3. The CDC data death ~11 min after boot, and the ~868 B/s NUL stream.
4. Radio and PA behaviour beyond GSM/GPRS registration; PDP/data is unproved because the
   APN cannot be set.

**Milestones if activation is ever settled:** (1) readable output and an identified USB or
reset cause (done for USB); (2) SIM ready, registration, working GPRS and a controlled TCP
exchange; (3) normal activation and an independently visible app heartbeat; (4) first
tracker slice: GPIO 32 GPS power, correct UART/pads, NMEA/fix, one report to our server,
then sensors, buzzer, sleep, charging and retry behaviour; (5) repeated starts, an extended
run past the old reset window, calibration preservation and power/recovery checks. Only
then design permanent boot-word finalization; the blank-word trials are not a production
install path.

## 10. Keeping this summary useful

After each meaningful run, update the current-state table first, add the outcome
and evidence to the experiment ledger, and move disproved hypotheses out of the
next-step plan. Record whether an action was only prepared, simulated, sent to
hardware, verified by readback, or observed after reboot. Keep UTC timestamps;
some October 10 runs deliberately retain October 9 in their filenames.

Reference docs: [logicrom-core.md](../knowledge/logicrom-core.md),
[rom-flash-access.md](../knowledge/rom-flash-access.md), [pin-map.md](../knowledge/pin-map.md),
[firmware-analysis.md](../knowledge/firmware-analysis.md),
[tracker-intel.md](../knowledge/tracker-intel.md). Run histories:
[trial history](26-10-09-logicrom-trial.md),
[programmer startup](../done/26-10-09-programmer-start.md),
[loader/recovery audit](../done/26-10-08-loader-audit.md),
[blank-word handoff](../done/26-10-09-handoff-blank-word-part-two.md).
