# V24: plan to reach 30 days on battery (2026-10-11)

Three routes, tried in this order: **stock firmware**, then the **Ai-Thinker SDK**, then
the **RDA vendor SDK**. Each route ends in a gate. We only open the next route when the
gate says the current one cannot reach the target. Nothing here has been run yet; where
a number is an estimate it says so.

Logicrom is parked: no app can run on it without activation, and Waybyte is not to be
involved. The tracker app skeleton (`firmware/logicrom/tracker/`) is parked with it and
gets ported if route 2 or 3 opens.

## 1. The target

**From a full charge, with the solar panel covered and the cable off, a unit keeps
reporting for 30 days.**

What "reporting" means, from the 2026-10-10 skeleton policy. The user confirmed this
duty and the 20 % reserve on 2026-10-11:

- one position every 30 minutes (it may be skipped while the animal is at rest);
- battery level and activity with every record;
- the data reaches our server at least twice a day.

Pass and fail, in the unit the trackers already report (battery percent):

| | Drain | Meaning |
|---|---|---|
| Pass | **2.7 %/day or less** | 30 days use 80 % of the battery. The 20 % reserve is for cold, battery age and weak-signal sites |
| Marginal | 2.7 to 3.3 %/day | 30 days on paper, no reserve. Your call |
| Fail | above 3.3 %/day | flat before day 30 |

## 2. The budget

The battery is 4000 mAh by the vendor's figure (not measured).

- 30 days = 720 hours, so the limit is **5.6 mA on average**, or 4.4 mA with the reserve.
- 1 %/day = 40 mAh/day = 1.7 mA on average.

Where the energy probably goes, at the assumed duty. These are typical figures for
parts of this class, from general knowledge. **None is measured on a V24**; they show
which term matters, not the answer.

| Consumer | Estimate | Per day |
|---|---|---|
| 48 GPS fixes | about 50 mA for 30 to 60 s each | 20 to 40 mAh (0.5 to 1.0 %) |
| 2 uploads | about 100 mA for 60 to 90 s each | 4 to 5 mAh (0.1 %) |
| Left for everything in between | | 60 to 80 mAh, which is 2.5 to 3.4 mA |

So the result is decided by what the unit draws **between** fixes and uploads: whether
the radio is off or registered, and how often it wakes. By the vendor's protocol
document, stock keeps a TCP link and exchanges a keepalive every 5 minutes, which is
288 radio wake-ups a day. Whether that fits the budget is what route 1 measures.

## 3. How we measure (every route)

- **Battery percent over the air**, logged by our own server with the server's clock.
  Stock sends it in every keepalive (`LK`) and every position (`UD`). The cable charges
  the unit, so nothing is measured over USB.
- **Drain is read from a full charge downward**, over at least 7 days. The gauge works
  from battery voltage (PMU ADC), so percent may not be linear in charge.
- **Gauge check, once:** under a steady load, percent should fall in a straight line
  from 100 % to shutdown. If it does not, we correct the short runs with that curve.
  With one SIM this comes from route 2's logger (gate 2.8), which records millivolts
  and percent to flash. If route 2 stalls, a stock unit on `upload,60` gives it instead.
- **Optional check in mAh:** recharge a unit through an inline USB power meter after a
  run and note the mAh put back. This needs a meter, nothing else.
- **Conditions:** panel covered with opaque tape, outdoors with sky view, on a 2G
  signal like the farm's.
- **One change per run.**
- **A 7-day run projects; only a 30-day run proves.**
- **There is one usable SIM (2026-10-11).** Route 1 therefore runs on one unit, one run
  after another, and its results carry no check of unit-to-unit spread. Route 2 runs at
  the same time on a second unit with no SIM, which logs its own battery to flash. Each
  further SIM would let one more route 1 run go in parallel.

## 4. Route 1: stock firmware

Keep the vendor firmware untouched. We add a server of ours and change settings.

**What we expect to reach**

- Every measurement the experiment needs, already on the wire: battery percent, step
  count (SC7A20 pedometer), at-rest bit, GSM signal and cell ids, position, and stored
  positions re-sent after an outage (`UD2`).
- Control through settings. `upload,<s>` is acknowledged live; the firmware carries a
  message refusing values under 60. Present in the parser, effect not yet read or tested: work modes (`sgdh_UploadStart.workmode`,
  `m8support`), `worktime`, `sleeptime`, `linktime`/`lt`, `spof`, `gprsgps`,
  `gpson`/`gpsoff`, `wifisleep`, `autoreset`.
- **Not reachable:** logic of our own on the device, such as holding an upload until
  coverage is good, GPS conditional on steps, or per-slot acceleration statistics.
- **Battery: unknown.** Stock may pass as it is.

**Steps**

| # | Step | Done when |
|---|---|---|
| 1.1 | Protocol server: one Python file, standard library only. It answers `CONFIG`, `ICCID`, `LK` and `AL` and appends every frame with a timestamp to a log | **Written 2026-10-11** (`tools/tracker_server.py`, 20 tests pass, checked as a running process on the Mac). **Not deployed.** Done when a unit on battery shows up in the log |
| 1.2 | Read the setting handlers in the existing decompile: `sms_worktime_handle`, `sms_sleeptime_handle`, `sms_spof_handle`, `link_check`, `sgdh_UploadStart`, `gprsgps`, `wifisleep` | each has its syntax, its effect, and whether the radio stays registered, written down |
| 1.3 | Baseline: factory settings (`upload,600`, `lt,240`), 7 days | %/day, and counts of keepalives, positions and valid fixes per day |
| 1.4 | Setting runs, one change each, 7 days each: the sleep or work-mode setting that 1.2 identifies first, then `upload,1800`, then WiFi scans off if a setting exists | %/day per setting |
| 1.5 | Best setting: 30-day proof | day 30 reached |

With one SIM these run in sequence: baseline, the most promising setting, then the
proof. That is about six weeks at the least, and each further setting adds a week. Step
1.2 is offline and runs during the baseline, so the first setting is chosen by reading
the code and not by trial.

The server has no command channel. Settings are changed over USB while the unit is on
the cable to recharge between runs, so nothing on an open port can reconfigure a unit.
The server answers only the device ids it is started with.

A setting that switches data off cannot be undone remotely, because these SIMs have no
SMS. Any such setting is tried on the bench over USB first, with the way back known.

**Server host.** The Oracle instance that serves alquira.pt (`80.225.187.151`, Ubuntu,
Nginx, `ufw`), on a TCP port of its own, as a separate systemd service under an
unprivileged user. The website is not touched. The port has to be opened in three
places: the Oracle security list, `ufw` on the instance, and the Vodafone IoT portal if
it restricts destinations. The tracker is pointed at the IP, not a host name, so it
needs no DNS. While a unit points at our server it no longer appears in the vendor's
app; `ip,47.106.163.223,8888` sends it back.

**Gates**

| Gate | Condition | Then |
|---|---|---|
| 1-start | the server logs a unit on battery, and the unit reconnects by itself after a reboot | field runs begin |
| **1-pass** | a 7-day run at 2.7 %/day or less, with the duty of section 1 met | start the 30-day proof. Routes 2 and 3 stay closed |
| 1-marginal | best setting between 2.7 and 3.3 %/day | you decide: accept, or open route 2 |
| **1-fail** | best setting above 3.3 %/day, **and** step 1.2 or the log names a cause no setting changes (radio stays registered, keepalive fixed, GPS stays powered) | open route 2 |
| 1-function | battery passes, but you decide a device-side function from the "not reachable" list is required | open route 2 for that function |
| 1-timeout | two rounds of 7-day runs give neither a pass nor a named cause | open route 2 anyway |

If the miss comes down to one constant or one behaviour, a small patch to the stock
image is weighed before route 2. The decompile and the write and restore path exist.

## 5. Route 2: Ai-Thinker SDK

Our own application on Ai-Thinker's prebuilt core for the A9G module (same RDA8955
chip). Checked on 2026-10-11 in the fork
[Yakir-Ben-Hillel/A9G](https://github.com/Yakir-Ben-Hillel/A9G) (MIT licence; the
official repository returned 404):

- No licence or activation step found in the tree.
- Its declared flash map matches the V24 tail: 4 MiB, calibration at `0x3FA000`,
  factory block at `0x3FE000`, user data `0x361000` to `0x3FA000`, app from `0x240000`.
- The API has what the policy needs: flight mode, attach and detach, sockets, GPIO 0 to
  34, UART1 and UART2, I2C, file system, and a low-power demo.
- **Probably no console with the case closed.** Its trace goes out the host UART, which
  on the V24 is only on test pads, and the API has no USB functions. Whether the core
  brings up USB at all is not known. Signs of life we can count on are the LEDs, a log
  file in flash read back through the ROM, and the server connection.
- The core is closed and built for another board. The open points are the same as in
  [the Logicrom fit](../knowledge/pin-map.md#8-fit-with-logicrom): PA driver variant, pad and PMU
  setup, and a GPS helper that may assume the A9G's wiring.

**What we expect to reach:** the full policy under our control: radio off between
uploads, batched uploads, motion gate, steps from the SC7A20, upload held for good
coverage. In return we take on a closed core that has never run on a V24.

**Decided 2026-10-11: route 2 starts now, alongside route 1, on 412 with no SIM.** Its
first goal is a logger: the app takes GPS fixes and writes them, with battery and
motion, to flash. The Mac reads that log back through the ROM over the cable. The radio
is tested last, when the SIM is free or a second one exists. With no SIM the app must
hold the radio in flight mode, or the core keeps searching for a network and the floor
figure means nothing.

**Gates, in order. Each is a stop point.**

| Gate | Condition | Where |
|---|---|---|
| 2.1 Build | a demo from the fork builds to a `.lod` in the existing Docker toolchain on the Mac | offline |
| 2.2 Flash map | every region the core writes at run time is read from the core image itself, and none overlaps `0x3FA000`–`0x3FFFFF`. The Logicrom core's header also looked right, and its code still wrote there | offline |
| 2.3 Board fit | PA driver, GPIO, UART and I2C numbering compared with [the pin map](../knowledge/pin-map.md); a list of what the app must do itself (GPS power on GPIO 32, NMEA on UART1 at 9600, accelerometer bus on GPIO 6 and 7) | offline |
| 2.4 App runs | on 412: an LED pattern produced by app code on first boot, and the flash tail unchanged on readback | bench |
| 2.5 Flash log | the app writes records to flash, and the Mac reads and decodes them through the ROM | bench |
| 2.6 Parts | a GPS fix, the SC7A20 answering on I2C, and a battery reading in mV and percent, all in the log | bench |
| **2.7 Sleep floor** | flight mode, GPS off, deep sleep, battery logged hourly, 7 days off the cable: **1.5 %/day or less**, and no worse than the best floor stock showed | field, no SIM |
| 2.8 GPS duty | 48 fixes a day logged to flash, radio still off, 7 days: floor plus fixes at 2.5 %/day or less. The log also gives the gauge curve of section 3 | field, no SIM |
| 2.9 Radio | registers on GSM, attaches with `sme.vodafone.iot`, opens TCP to our server | bench, needs the SIM |
| 2.10 Full duty | tracker app ported, two uploads a day; a 7-day run at 2.7 %/day or less, then the 30-day proof | field, needs the SIM |

Gate 2.4 is the step Logicrom never passed. Gates 2.7 and 2.8 come before the radio
because, on paper, the floor and the fixes are nearly all of the budget and the two
uploads are about 0.1 %/day.

**Status, 2026-10-11. No unit was touched.**

- **Gate 2.1 passed.** The fork's `gpio` demo builds offline in the existing Docker
  image with the existing `csdtk42-linux` toolchain. Both outputs, the app-only
  `gpio_flash_debug.lod` and the full `gpio_B2130_debug.lod`, are byte-identical to the
  files the fork ships. The SDK is at
  `firmware/live/usb-programmer-build/ai-thinker-sdk/A9G` (commit `4f36e75a`), inside
  the one folder the build VM mounts. Two fixes were needed: five helper scripts lacked
  the executable bit (`elfCombine.pl`, `lodtool.py`, `lodCombine.pl`, `genlib.sh`,
  `win32/cygenv.sh`), and the image has `python3` but the build calls `python`.

  ```sh
  B="$PWD/firmware/live/usb-programmer-build"
  docker --context colima-rda-build run --rm --network none --platform linux/amd64 \
    -v "$B/ai-thinker-sdk/A9G:/work/A9G" -v "$B/csdtk:/work/csdtk:ro" \
    -e LD_LIBRARY_PATH=/work/csdtk/lib rda-usb-builder:local \
    bash -c 'ln -s /usr/bin/python3 /usr/local/bin/python && cd /work/A9G && bash ./build.sh demo gpio'
  ```

- **Gate 2.2, first half only.** The full image covers flash `0x000000`–`0x250000`
  (core to `0x240000`, then the app) and nothing at or above `0x3FA000`. An app gets
  1 MiB of flash and 1 MiB of RAM. What the core writes at run time has not been read
  yet; that is the half that caught the Logicrom core.
- **The core ships with its symbols** (`platform/csdk/debug/SW_V2130_csdk.elf`, 20,636
  names), which the Logicrom core did not. Read from it so far:
  - `_calib_start` is `0x883fa000` and `_factory_start` is `0x883fe000`, as on the V24.
  - `_user_data_start` is `0x883f6000` with size 0, which disagrees with the
    `0x361000` in `memd.def`. Where the file system really sits must come from the
    code. The names to read for the second half of 2.2 are `FS_Format`,
    `FS_HasFormatted`, `DSM_DevInit`, `VDS_GetFlashInfo`, `FACTORY_WriteField` and
    `FACTORY_Writeback`.
  - It was built from the same SDK line as route 3 (`…GPRS_C_SDK_SRC-dev17.44`), with
    `xcv_8955`, `pmu_8955`, `flsh_spi32m` and PA driver `pasw_rda6625`. Stock names
    `pasw_rda6625e`. Logicrom's core has the same difference and registered on GSM on
    412.
  - The only USB code is the boot monitor's (`boot_Usb*`). A running app has no USB
    port. Whether the Mac can still read RAM through that monitor while the app runs is
    worth one test at gate 2.4; it would stand in for a console.
  - Deep sleep, battery voltage and GPS power calls are present (`hal_LpsDeepSleep`,
    `PM_SleepMode`, `PM_Voltage`, `GPS_Open`).
- Gate 2.3 and onward: not started.

**To route 3 when** a gate fails for a reason inside the closed core, after one bounded
attempt to fix it: the app never starts, the core writes the tail and cannot be stopped,
pads, PMU or PA are set wrongly for this board, or the floor is too high with everything
of ours switched off. A bug in our own app is not a reason to change route.

## 6. Route 3: RDA vendor SDK

Build the whole firmware from the chip vendor's tree
([cherryding1/RDA8955_W17.44_IDH](https://github.com/cherryding1/RDA8955_W17.44_IDH)).
Stock reports the same SDK line (W17.40). Checked on 2026-10-11:

- Source for boot, hardware layer, low-power code, USB, and board targets
  (`8955_modem` and three others). The GSM stack is four prebuilt libraries.
- Matches stock: `xcv_8955`, `pmu_8955`, `flsh_spi32m`.
- Missing: the PA driver stock names (`pasw_rda6625e`; the tree has `pasw_rda6625`), an
  SC7A20 driver, and a driver for our GPS chip. We write the last two; the PA needs a
  radio test.
- No compiler in the tree; it needs the same MIPS toolchain as route 2. A copy of this
  tree is already at `firmware/live/usb-programmer-build/sdk`, and the existing Docker
  recipe builds its flash programmer (`8955_ramrun` target) from it. A full
  `8955_modem` build has not been tried.
- **The repository has no licence.** It is a vendor SDK that someone uploaded.

**What we expect to reach:** anything stock does at the hardware level, since stock is
built from this line, plus our own policy, plus a USB console (the stock `AT:` path
comes from this code). The cost is the largest of the three: we write the board
definition and own charging, the power key, the watchdog and the flash layout.

| Gate | Condition | Where |
|---|---|---|
| **3.0 Licence** | you decide whether unlicensed vendor code is acceptable, for the bench and for a product | before any work |
| 3.1 Build | `8955_modem` builds unmodified in Docker on the Mac | offline |
| 3.2 Board target | a V24 target whose pad, PMU and I2C tables equal the tables read from the stock image | offline |
| 3.3 Flash layout | calibration and factory block at stock's addresses; the image and its first boot leave the tail alone | offline |
| 3.4 Boot | on 412: boots, LED marker, USB console answers | bench |
| 3.5 Radio and parts | GSM and GPRS with the unit's own calibration; GPS; SC7A20; battery reading | bench |
| 3.6 Sleep floor | no worse than stock's best floor, and 1.5 %/day or less | field |
| 3.7 Full duty | 7-day run at 2.7 %/day or less, then the 30-day proof | field |

**If route 3 also misses**, the limit is the hardware. What remains is a lighter duty
(fewer fixes a day), relying on the solar panel, or a different tracker.

## 7. Units

- **Route 1** runs on one sealed spare with stock firmware and the one SIM. It gets the
  Vodafone APN and our server address over USB (`tools/rda_config.py`). 417 would also
  do, but it has been opened and written to, so a sealed spare is the cleaner reference.
- **412 is the development unit for routes 2 and 3, with no SIM.** It currently runs a
  Logicrom trial image with the boot word blank. Before gate 2.4 it is restored with
  `rda_programmer_start.py --finish firmware/live/2026-10-10-logicrom-412-timeout-1hr`,
  on its own go. The SIM last registered in 412 on 2026-10-10; if it is still there, it
  moves to the route 1 unit.

## 8. Rules that hold on every route

- Mac only. Cable, button and RST hole only.
- Each live erase or program run needs your go for that run.
- Before any new image goes on a unit: the image is checked offline against the flash
  tail, the boot word is withheld, and the restore journal for that unit exists.
- Never restore one unit's dump or calibration onto another.

## 9. Needed from you

1. Your go to install the server on the Oracle instance, and the port opened in the
   Oracle security list (console only) and, if it restricts destinations, in the
   Vodafone IoT portal.
2. More SIMs, if you want route 1 faster than one run at a time. Any SIM with 2G data
   works; one with SMS also gives the SMS command channel.
3. Your go for each live write on 412, starting with its restore before gate 2.4.
4. Optional: an inline USB power meter.
5. Only if route 3 opens: the licence decision (gate 3.0).
