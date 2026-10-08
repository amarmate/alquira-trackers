# ReachFar V24: pin map (first pass)

Which RDA8955 pin does what on the V24 board, read from the 2026-10-03 flash backup of unit
`1403167417`. This is the input a replacement firmware needs.

**Status, 2026-10-08:** the map comes from the firmware image and five photos of the opened
unit. One read of the pad and GPIO registers on the live unit, taken while it was off on the
cable, agrees with every line that the boot code sets up (section 7). The lines that only the
tracker application sets up, and which physical part hangs on each pin, are not confirmed:
no pin has been toggled yet. Function addresses refer to the decompile described in
[the firmware analysis](v24-firmware-analysis.md), section 11.

## 1. How the pins were found

1. **The board table.** `boot_LoaderEnter` passes `tgt_GetHalConfig()` (`0x8803968c`) to
   `hal_Open`. The table it returns, at `0x8823b300`, has the layout of the public SDK's
   `HAL_CFG_CONFIG_T`, and `hal_BoardSetupGeneral` (`0x8200202c`) uses it exactly as the
   SDK's `hal_config.c` does. Its build target is named `5827_watch_128_tp_gps_wifi`: a
   kids-watch target, so the table also lists watch parts the V24 does not have.
2. **The GPIO driver.** `hal_GpioOpen/Set/Clr/Get/SetOut/SetIn` were identified from their
   register writes at `0x01a03000` and their assert strings. A pin id is `0x20000 | n` for
   GPIO n. Every call with a constant pin was traced to what calls it.
3. **The pad multiplexer.** Every write to the pad registers at `0x01a2a000` was listed. The
   pad order and function numbers are those of the SDK's `regs/8955/include/iomux.h`.
4. **The tracker's own code.** Its log strings name the purpose: `open_GPS_power_TD`,
   `gps_uart_open`, `rfhz_led_status`, `sms_lsn_handle`, `hon_alarm_stop`.

## 2. Pins

"Pad" is the SoC's name for the pin. "GPIO" is the number the SDK, and Logicrom, use for it.

| Pad | GPIO | Use on the V24 | Mode | Evidence |
|---|---|---|---|---|
| `GPIO_0` | 0 | UART1 RXD, from the GPS | function 1 while the GPS is on, GPIO input when off | `gps_uart_open` `0x8804b658`, `gps_uart_close` `0x8804b5e0` |
| `GPIO_1` | 1 | UART1 TXD, to the GPS | same | same |
| `GPIO_2` | 2 | interrupt of the removal (proximity) sensor | input, interrupt | `hal_GpioOpen(0x20002)` in the LS98xx driver `0x8823111c` and the EM30719 driver `0x88237448` |
| `GPIO_4` | 4 | blue LED (GPS) | output, high = on | `led_gps_set` `0x8819c3ec`; `rfhz_led_status` case -2 turns it off and is logged as `GK9501_Gps_Off` |
| `GPIO_6` | 6 | I2C3 SCL: accelerometer | function 2, or bit-banged | sensor table `0x8823b6b0` = bus 2; bit-bang table `0x8823b6b8` names GPIO 6 and 7 |
| `GPIO_7` | 7 | I2C3 SDA: accelerometer | same | same |
| `CAM_PWDN` | 19 | I2C2 SCL: removal sensor | function 2 | board table `i2c2Used`, `i2c2UseCamPins`; `light_hal_i2c_send` uses bus 1 (byte at `0x8201d308`) |
| `CAM_RSTB` | 20 | I2C2 SDA: removal sensor | function 2 | same |
| `KEYIN_2` | 27 | red LED (network) | output, high = on | `led_net_set` `0x8819c4e0`; pad set to GPIO with pull-up by `0x82001ea4` |
| `KEYIN_3` | 28 | white LED | output, high = on | `sms_lsn_handle` `0x881b035c` ("LED light keeps on" writes 1); pad set to GPIO with pull-up by `0x82001eb8` |
| `KEYIN_4` | 29 | interrupt line of the WiFi chip (SDIO) | input, interrupt | `0x8804e30c` opens it before sending SDIO commands; id `0x2001d` at RAM `0x82017320` |
| `KEYOUT_1` | 31 | not known | input, pull-up | set to input whenever the GPS UART closes; pad set to GPIO with pull-up by `0x82001edc`, the same setting as the two LED pads |
| `KEYOUT_2` | 32 | GPS power enable | output, high = on | `open_GPS_power_TD` `0x8822faf4`, `close_GPS_power_TD` `0x8822fa84`; platform start-up `0x8803de3c` drives it high before the tracker application runs |
| `KEYOUT_3` | 33 | 32 kHz clock output, on request | function 5 | `0x82001e60`; requested by the GPS pin setup at start-up (`0x8804b2d0`) and by `wifi_init`. Which chip takes the clock is not traced |
| `KEYOUT_4` | 34 | accelerometer interrupt | input, interrupt | sensor table `0x8823b6b0` = `0x20022`; pad set to GPIO by `0x82001f40` |
| `SDMMC_*` | 8-13 | SDIO to the WiFi chip | function 0 | inferred: pads are never remuxed, and SDIO commands follow `pmd_EnablePower(SDMMC)` in `0x880d96b8` |
| `HST_RXD`, `HST_TXD` | 35, 36 | host UART, the ROM's download port | function 0 | never remuxed |

Pins the board table lists, with no tracker code found for them:

| Pad | GPIO | What the table says | Note |
|---|---|---|---|
| `GPIO_3` | 3 | not connected: driven low at boot | a touch-screen function (`0x881127b0`) also toggles it, so probably a watch part |
| `GPIO_5` | 5 | used as GPIO | no caller found |
| `SDMMC_DATA_0` | 10 | used as GPIO | conflicts with the SDIO reading above; unresolved |
| `LCD_RSTB` | 14 | LCD reset | the V24 has no LCD |
| `KEYIN_0`, `KEYIN_1`, `KEYOUT_0` | 25, 26, 30 | keypad matrix (`keyInMask 0x17`, `keyOutMask 0x1d`) | which line the V24's button uses is not traced |

## 3. Parts and how they connect

| Part | Connection | Evidence |
|---|---|---|
| GPS (Goke or AT6558) | UART1 at 9600 baud, power switched by GPIO 32 | settings block `0x88247c64` starts with 9600; section 2 |
| Accelerometer: SC7A20 | I2C3, interrupt on GPIO 34. Four drivers are tried in order: MC3413, MC3416, SC7A20, QMA6100P | driver table `0x8201d29c`; all four read `0x8823b6b0`. A trace from the running unit prints `SC7A20_eint_clear.` and `Gs:3` with changing x, y, z values (`firmware/live/reconnected-host-read.raw`); type 3 is the SC7A20 |
| Removal sensor | optical proximity sensor LS98xx or EM30719 on I2C2, interrupt on GPIO 2 | strings `ls98xx remove!!!!`, `light em30719 found!` |
| WiFi (RDA5990 or 5991, for scans) | SDIO, interrupt on GPIO 29, supply from the PMU's SD-card regulator | `pmd_EnablePower(7, …)` around the SDIO start in `0x8804e30c` |
| Sounder | the PMU's vibrator output | `hon_alarm_stop` (`0x881ada64`) switches level id 8, which the PMU table maps to the vibrator regulator; the board has wired pads marked `+MOTO` (section 4) |
| LEDs | GPIO 27 red, GPIO 4 blue, GPIO 28 white, all high = on | section 2 |
| Battery gauge | PMU ADC channel 7; charge ends at 4200 mV, restarts at 4150 mV; power-on needs 3400 mV | PMU table `0x8823b49c` |
| USB | the SoC's own USB, on the magnetic cable | in use today |

The red-or-blue assignment rests on one link: the log line `GK9501_Gps_Off` is printed with
case -2, and case -2 switches off GPIO 4. Case -1 switches off GPIO 27.

## 4. Seen in the photos (`pictures/`)

- Main board with shield cans stamped `R36S0028 / JN 250108 / R36S#16` and a nano SIM holder.
- Silkscreen next to the board edge, readable in `pic3.jpeg` and `pic4.jpeg`:
  - `WIFI`: a solder pad carrying the single wire antenna.
  - `GPS`: a small coaxial antenna socket. A ceramic patch antenna sits on its own small board.
  - `+MOTO`: two solder pads. Two red/black wire pairs are soldered to them. One appears to run
    to the round sounder; the other was not followed.
- A row of about eight unlabelled gold test pads below the SIM holder, and a shorter row near
  the flex connector. Not probed. The host UART is likely among them.
- A flex board marked `R36S-KCUSB_V0.2 RFHZ-V24` with an 8-pin chip, the battery wires and the
  wires from the lid. It probably carries charging, the button and USB.
- A small board with a white LED.

## 5. PMU regulators the firmware switches

| Power id | Regulator | Likely load |
|---|---|---|
| SD card (7) | MMC, 2.8 V | WiFi chip |
| I2C (13) | LCD and camera regulators together | sensors and I2C pull-ups (inferred) |
| Vibrator level (8) | vibrator | sounder |
| PA (5) | RF | radio |
| USB (6) | USB | USB |

## 6. Not resolved

- Which proximity sensor is fitted. No saved trace names one.
- The button: which key line, or the PMU power key.
- GPIO 31 and the 32 kHz clock's consumer. GPIO 31 is an input with a pull-up, which would
  suit a button or a charger status line; nothing that reads it has been traced.
- Charging and solar input: handled on the flex board; how the SoC sees "charging" is not traced.
- Whether the WiFi SDIO really uses the `SDMMC_*` pads.
- The test pads on the main board.
- The boot sector's USB-download key, which the [loader audit](v24-loader-audit-2026-10-08.md)
  found as key code `0x4d`, matrix index 27. With eight lines per row that is `KEYIN_3` with
  `KEYOUT_3`. On this board those two pads are the white LED line and the 32 kHz clock line, so
  my reading is that no button presents that key. Not verified.

## 7. Live check, 2026-10-08

`tools/rda_pin_state.py` read the 37 pad registers, the GPIO direction and level registers
and RAM `0x82239eb8` from unit `1403167417`: one pass, read-only, no flash access beyond the
1 KiB that identifies the unit. The unit was off on the cable (USB `1e04:0900`), which is the
only state that has a read path. Log: `firmware/live/2026-10-08-pin-state.jsonl` (not in git).

| Pad | Register | Reads as | Against section 2 |
|---|---|---|---|
| `CAM_PWDN`, `CAM_RSTB` | `0x2` | I2C2 SCL and SDA | agrees |
| `GPIO_6`, `GPIO_7` | `0x2` | I2C3 SCL and SDA | agrees; the hardware I2C function, not bit-banging |
| `GPIO_0`, `GPIO_1` | `0x0` | GPIO inputs, levels 0 and 1 | agrees: the GPS UART is closed |
| `GPIO_2` | `0x0` | GPIO input, level 0 | agrees |
| `GPIO_3` | `0x0` | GPIO output, low | agrees |
| `GPIO_4` | `0x0` | GPIO output, low | agrees: LED off |
| `GPIO_5` | `0x0` | GPIO input, level 0 | still no known use |
| `KEYIN_3` | `0x10201` | GPIO 28 with pull-up, output, low | agrees: LED off |
| `KEYOUT_2` | `0x1` | GPIO 32, output, high | agrees as an output; see below for the level |
| `KEYOUT_3` | `0x5` | clock output | agrees: the 32 kHz clock is on |
| `KEYIN_0`, `KEYIN_1`, `KEYOUT_0` | `0x0` | key matrix | agrees |
| `SDMMC_*`, `HST_RXD`, `HST_TXD` | `0x0` | their own function | agrees |
| `KEYIN_2` | `0x0` | key input, not GPIO 27 | not set up in this state |
| `KEYIN_4`, `KEYOUT_1`, `KEYOUT_4` | `0x0` | key lines, not GPIO 29, 31, 34 | not set up in this state |
| LCD and camera pads | `0x0` | their own function | unused, as expected |

**What this state is.** The registers are exactly what the platform start-up (`0x8803de3c`)
leaves behind. It switches `KEYOUT_2` to GPIO 32 and drives it high, makes GPIO 0, 1 and 31
inputs, turns the 32 kHz clock on, and switches `KEYIN_3` to GPIO 28 driven low. A pin
set-up routine at `0x881ab498`, started from a timer, is the only code found that switches
`KEYIN_2` and `KEYOUT_1` to GPIO; it also switches `KEYIN_4` and `KEYOUT_4`. All four pads
still hold their reset value, and RAM `0x82239eb8` read 0, the value before any
accelerometer driver has matched. My reading is that "off on the cable" means the platform
is up and the tracker application has not set up its pins.

Two consequences:

- The GPS power pin is high in this state. If high = on is right, the GPS is powered
  whenever the unit sits off on the cable.
- A register read cannot confirm the application's pins (red LED, GPIO 31, the WiFi and
  accelerometer interrupts): when the unit is switched on, USB changes to `1782:3d00`,
  which has no read path.

Direction bits, for the record: GPIO 3, 6, 7, 8 and 35 are outputs because the board table's
not-connected mask (`0x1c8`, table offset `0x68`) is written to both halves of the direction
register; 28 and 32 come from the platform start-up. GPIO 4, 14 and 27 are also outputs; what
set them in this state is not traced. The LED pads are written with `0xd0201` and read back
`0x10201`: the two drive-strength bits do not read back.

**Still to do, with the unit switched on: `gpiotest`.** The vendor firmware has a command
`gpiotest,<pin>,<0|1>` (`sms_gpiotest_handle`, `0x881b030c`) in the same dispatcher as `apn`
and `lsn`. It makes a GPIO an output and drives it until reboot, for pins 0 to 32.
`tools/rda_config.py gpio-test --pin 28 --level 1` sends it as `AT:gpiotest,28,1#`, and
accepts only the three LED pins. Watching which LED lights for pins 4, 27 and 28 settles the
LED colours. It has not been sent to a unit yet, so the reply it gives is not known.

## 8. Fit with Logicrom

Checked on 2026-10-08 against `Logicrom_rda8955_core_v0.5.1.lod` (github.com/waybyte/logicrom_core),
the SDK at commit `72f60a2` (github.com/waybyte/logicromsdk) and this unit's backup. All of it
is reading files: nothing of Logicrom's has run on the board.

| | V24 vendor build | Logicrom core |
|---|---|---|
| Transceiver, PMU, flash model | `xcv_8955`, `pmu_8955`, `flsh_spi32m` | same |
| PA driver | `pasw_rda6625e` | `pasw_rda6625` |
| PA and switch ids in the calibration data | `0x02000008`, `0x0400000a` ("RDA 6625"), in the firmware and in this unit's calibration sector | same ids |
| Calibration format | RF `0xCA1B0208`, audio `0xCAAD0103`, in this unit's sector | same two tags in the code |
| Flash size | 4 MiB | 4 MiB |
| Calibration | `0x3fa000` | `CALIB_BASE=0x3FA000` |
| Factory settings (IMEI) | `0x3fe000`, tag `0xFAC00200` | the image header says `FACT_SETTINGS_BASE=0x3F4000`; the code uses `0x3fe000` and the same tag |
| Code | `0x000000`-`0x238704`, then data and packed code to `0x362000` | core `0x000000`-`0x250000`, which is all the image writes; app `0x250000`-`0x2e0000` |

What carries over:

- **GPIO.** Logicrom names GPIOs 0 to 36 by the same SoC numbers as section 2.
- **I2C.** `I2C_PORT_0` is on the pins of GPIO 19 and 20 and `I2C_PORT_1` on those of GPIO 6
  and 7 (module pin tables in `include/plat/def_i2c.h` and `def_gpio.h`). Those are this
  board's two buses: removal sensor and accelerometer.
- **GPS UART.** Logicrom's UART0 is on GPIO 0 and 1. Its GNSS helper functions are for the
  A9G only, so an app would switch GPIO 32 itself and read NMEA at 9600 baud.
- **IMEI.** The header value `0x3F4000` appears nowhere in the core's code. The code holds
  `0x883fe000` three times, as the vendor firmware does, once in the same literal pool as the
  factory tag `0xFAC00200` and once in a table after `0x883f6000` and `0x883fa000`. My reading
  is that the core reads the factory block where this unit keeps it. This replaces the
  earlier reading that the IMEI would not be found.
- **Calibration.** Same address, same format tags, same PA and switch ids, and the PA block
  has the same size (`0x122c`) in all three places. My reading is that the core will accept
  this unit's stored calibration.

What does not carry over, or is not known:

- **PA control code.** The two drivers' built-in default PA tables differ in 1285 of 4652
  bytes. Defaults only apply when the stored calibration is rejected, but the difference
  shows the drivers are not the same. Whether the `rda6625` driver keys this board's PA
  correctly can only be settled by a radio test.
- **32 kHz clock and sounder.** The SDK headers have no function for the clock output on
  `KEYOUT_3` or for the PMU's vibrator output. If the GPS or WiFi chip needs that clock, or
  to sound the alarm, an app has no documented way to do it.
- **Second UART.** Logicrom's UART1 is on GPIO 4 and 5, and GPIO 4 is an LED here. An app
  must leave that port closed.
- **Pad setup, PMU settings and radio drivers** live in the closed core, built for the A9/A9G,
  M590 and MC65 modules. An app cannot change them.
- **USB console.** The core offers a USB serial port on the M590 and A9/A9G. Whether it comes
  up on this board is not known, and the host UART is only on unlabelled test pads.

Activation: a personal licence is free. The steps in the SDK's quick start are: register at
waybyte.in, add the device by IMEI and module type, fit a SIM, power on, and the core fetches
the licence over GPRS (`getlic` retries, `apn=<name>` sets the APN, both on the console).
The V24 is not one of the module types, so which one to declare is open. Activation needs
the radio and the console to work first, so it cannot be tried before a core is flashed.

Flashing: Logicrom's instructions use Coolwatcher or Ai-Thinker's update tool, both on
Windows. This project has no proven way to write flash at all yet: see the
[handoff](handoff-2026-10-03-flash-restore.md).
