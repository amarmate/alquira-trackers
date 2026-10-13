# ReachFar V24 firmware: dump and analysis

Unit analysed: device ID `1403167417`, dumped 2026-10-02 over the magnetic USB cable.
Companion to [tracker-intel.md](tracker-intel.md).
Anything not read directly from the dump is marked **(unverified)**.

**USB configuration solved, 2026-10-02:** the normal `1782:3d00` data interface accepts
`AT:<command>#\r`. `AT:apn,sme.vodafone.iot,,,90128#\r` saved the APN through the
firmware's own settings handler. After reboot, `getapn` confirmed the new value,
PDP activation succeeded, and the tracker connected to the vendor server. No RAM
patch, raw flash write, staging SIM, or kernel driver was needed. See section 9.

## 1. How we talk to it

The magnetic cable carries USB data, not just charge. With the tracker powered off
and then connected to the cable, it enumerates as:

| | |
|---|---|
| USB ID | `1E04:0900`, "Coolsand Technologies / Coolsand", serial "USB Controller 1.0" |
| Interface | 0, class `ff/66/66`, name **"RDA Usb"** |
| Endpoints | bulk OUT `0x01`, bulk IN `0x81`, 64 bytes, full speed |

This is the RDA (ex-Coolsand) debug host port, the one Coolwatcher uses. It is silent until
the host sends a request. macOS has no driver for it, so `tools/rda_dump.py` uses libusb
directly. The read request comes from [hitechshell/rdatool](https://github.com/hitechshell/rdatool):

```
request: AD 00 08 FF 03 <addr LE32> 03 04 00     (last byte must be 00, an XOR there is ignored)
reply:   AD 04 02 FF 03 <1024 bytes> <xor>
```

Memory reads work while the vendor firmware keeps running. Only reads are implemented.

### Live debug log (second USB mode)

With the tracker running normally, it enumerates differently: `1782:3D00`,
still "Coolsand Technologies / Coolsand", with two vendor-class (`ff/00/00`) interfaces:

| Interface | Endpoints | What it is |
|---|---|---|
| 0 | bulk OUT `0x03`, IN `0x83` | compatibility/control interface. The matching SDK declares bulk endpoints but does not arm a receive transfer. Earlier writes failed; a reboot followed an attempted clear-halt, but causality was not established. Do not use it for commands. |
| 1 | bulk OUT `0x02`, IN `0x82` | **command input and plain-text firmware log**. Commands need `AT:` framing, e.g. `AT:ts#` followed by CR. |

The initial conclusion that USB could not set the APN was incorrect: those probes omitted
the three-character prefix that the vendor receive parser strips. The USB callback reaches
the general `sms_*` parser with source type 2. The separate `AT+uart2:` branch reaches
the narrower factory command set (`uart_*_handle`); its lack of an APN handler does not
limit the general `AT:` path. Both paths exist in the USB receive handler.

`tools/rda_log.py` prints it. It shows IMSI, PLMN, the APN in use, PDP activation results, DNS
lookups and socket targets, so it is the main tool for debugging connectivity. The device
re-enumerates on every reboot, so the stream drops then.
Confirmed 2026-10-03: debug mode (`1E04:0900`) depends on the power state, not SIM removal:
power the tracker off, then attach the magnetic cable. A check made before that switch finishes can still show the normal
`1782:3D00` port. Changing modes is unnecessary for configuration. A silent log recovered
after reconnecting the magnetic cable; reapplying the existing USB configuration alone did
not recover it.

## 2. Backup

| File | SHA-256 |
|---|---|
| `firmware/backup/v24_1403167417_flash.bin` (4 MiB, not in git) | `d8d180a38cd694a56ddebc0d73406e74d6fdec643821a41c352b726f0d7b1428` |
| `firmware/backup/v24_1403167417_2026-10-03_flash.bin` (4 MiB, not in git) | `c63a447aff0e3b457bda4cb7a049d3c2bfcb049b555f0d1398dc41b67a9982bd` |

Four full reads over ~10 minutes were byte-identical. The file contains this unit's IMEI and RF
calibration, so it is gitignored. The 2026-10-03 backup has two matching passes after
the ROM-monitor probe. Both files passed SHA-256 verification again during the handoff
continuation. Code, calibration and factory data match between backups; settings differ.
The user explicitly waived the off-laptop copy on 2026-10-03; no such copy was made.

Each dump is unit-specific: the IMEI (section 5) and the calibration at `0x3fa000` differ per
tracker. Dump every unit before reflashing it, and never restore one unit's dump onto another.

## 3. Hardware identified from the firmware

| Item | Evidence |
|---|---|
| SoC **RDA8955** (MIPS, little-endian) | `HAL for 8955_chip`, `PMD for pmu_8955`, `xcv_8955`, SDK branch `5827.W17.40` |
| PA `rda6625e` | RF driver string |
| Flash 4 MiB, mapped at `0x88000000` | reads mirror at +4 MiB; matches Logicrom's RDA8955 linker script |
| GPS: Goke or ZKW AT6558 (both drivers present) | `PGKC639`, `gk_agps_send`, `zkw_gps_init` |
| Board `R36` / `GM9_V1.1`, project `_RFHZ_V34_` | the V24, V34 and V44 share one firmware |
| App vendor 3G-elec (SeTracker family) | `agpse.3g-elec.com`, `setracker.html` |
| Build `2024-09-28 16:06:24` ("test_version"); factory stamp `2025-01-09 11:21:24` | `0x23b2b4`, `0x3fe028` |

The image also carries LCD, camera, touch and WeChat code: it is a kids-smartwatch platform with
the screen features unused on the V24.

## 4. Flash map

| Offset | Size | Contents |
|---|---|---|
| `0x000000` | 2.2 MiB | code. Boot loaders first; `0x29d0`–`0xb3a0` and `0x105b0`–`0x2da90` are the load images of sections that run from SRAM and RAM; from `0x2da90` code that runs in place, to `0x238704` |
| `0x238720` | 350 KiB | read-only data and strings, to `0x290000` |
| `0x290000` | 286 KiB | pointer table, then UI images (PNG/GIF/BMP), to `0x2d76e0`, the end of the image proper |
| `0x2d7750` | 552 KiB | **code, LZMA-compressed** in three segments, unpacked at boot to RAM `0x8201d5e0`–`0x82101e80` (section 11). Not audio |
| `0x361892` | 98 KiB | blank |
| `0x37a000` | | file system / settings store (FAT boot sector with OEM "RDA8809" at `0x37ba00`) |
| `0x3d7000` | | **NVRAM settings records** (section 5) |
| `0x3da000` | | `apn_config.txt` + `default_config.txt` (section 6) |
| `0x3e0000` | 64 KiB | erased |
| `0x3fa000` | ~13 KiB | **RF calibration, irreplaceable** |
| `0x3fe000` | 5 x 1 KiB | **factory block** (journaled copies, last one live): test flags, IMEI |

## 5. Settings as stored on this unit

Records sit on 512-byte slots: `08000000 <id LE32> 00000000 <check LE32> <payload>`. The check
value is not a plain CRC-32 of the payload. It must be worked out before we write any record.

| Record id | Offset | Value |
|---|---|---|
| `0x15e1` | `0x3d7400` | server `a.igps123.com`, port `0x22b8` = **8888** |
| `0x15e3` | `0x3d7600` | FOTA server `www.remoteupdate.net:5601` |
| `0x15e4`–`0x15e7` | `0x3ae200` | AGPS: `121.43.19.219:8089`, `121.40.88.40:21`, `agpse.3g-elec.com` |
| `0x17d5` | `0x3d8e00` | APN **`m2m.tele2.com`** (factory default) |
| `0x189d` | `0x3d9800` | passwords `123456` and **`168168168`** |
| `0x7725` | `0x3d9600` | `1234` (purpose unknown) |
| `0x1839`/`0x183a` | `0x3d9c00` | device ID `1403167417` |
| `0x170d`–`0x1718` | various | last GPS fixes as doubles, ~22.65 N 114.0 E (factory, Shenzhen) |
| factory | `0x3ff004` | IMEISV BCD `83 96 12 04 13 76 14 67 f0` -> IMEI **869214031674176** (Luhn ok), SVN 60 |

Device ID = IMEI digits 5-14 (`imei_to_id`).

Findings that matter for us:

- **At backup time, the APN from the first setup attempt (`sme.vodafone.iot`) was not stored on this unit.** Either
  the SMS never reached it, or it was a different tracker. The APN is still the factory
  `m2m.tele2.com`, which will not work on a Vodafone PT IoT SIM. Confirmed live: the boot log
  prints `gprs_state_check apn:m2m.tele2.com plmn:24007.` and every PDP activation fails
  (see the intel doc, section 7).
  This historical backup remains unchanged; the live unit was subsequently corrected over USB.
- The APN record stores an MCCMNC (`24007` at `+0x70`), but the firmware used it even though the
  SIM's PLMN is `90128`. A mismatch therefore does not stop the APN being used.
- The firmware has a built-in operator APN table (`0x287000`) that includes Vodafone PT consumer
  (`internet.vodafone.pt`, `26801`). It does not include the SME IoT APN.
- `168168168` sits next to the user password and looks like a vendor master password
  **(unverified)**. If it is accepted as `pw,168168168,...`, anyone who knows it can reconfigure
  any of these trackers by SMS.
- The firmware has a hard-coded AGPS login for the 3G-elec server (`0x267b68`).

## 6. Factory default script (`default_config.txt`, `0x3da2fd`)

Commands the device applies by default (we assume on factory reset, **unverified**):

```
apn,cmiot,,,46008#ip,a.igps123.com,8888#
lz,0,8#  von,0#  LOWBAT,1#  remove,0#  dnd,0#  hon,1#  showimei,2#  ec,0#  st,0#
agpstype,1#  upload,600#  simunbound,0#  apn,m2m.tele2.com,,,24007#  lt,240#
agpstime,1#  autoreset,1,1440#
```

So a `FACTORY` resets the timezone to UTC+8 and the APN to Tele2. Re-send our APN and server
after any factory reset.

`apn_config.txt` (`0x3da03a`) holds 27 `apn,...,<MCCMNC>#` lines for auto-APN (Morocco, France,
1NCE, NL, Chile, Tele2, CZ, ...). None are Portuguese.

## 7. Command keywords in the firmware

From the parser's string table (`0x267000`–`0x276000`). These are the same keywords the manual
documents (`pw`, `center`, `ip`, `apn`, `upload`, `verno`, `factory`, ...), plus many more. The
code has 56 `sms_*_handle` handlers. Which keywords the server channel accepts, as opposed to
SMS, is **unverified**. Test one at a time.

Undocumented and useful for us:

| Keyword | Likely use **(unverified)** |
|---|---|
| `ts`, `tsext`, `querynet`, `where`, `dw` | status, extended status, network info, position by SMS |
| `showimei`, `imsi`, `iccid`, `spn` | SIM / device identity |
| `getapn`, `configapn` | read back / configure the APN |
| `linktime`, `lt`, `autoreset` | server link timing; daily auto-reboot (default every 1440 min) |
| `netdebug`, `debug`, `debugclose` | debug output |
| `url`, `ipdurl`, `upgrade`, `recovery` | FOTA / update endpoints |
| `flashread`, `cleanfnv`, `delfile`, `setverno` | flash and file maintenance: **do not send blind** |
| `gprsgps`, `gpson`, `gpsoff`, `agpstype`, `agpstime`, `agpsupdate` | GPS power and assist |
| `mqtt` | an MQTT client is linked in; server address unknown |
| `simunbound` | SIM lock to first SIM inserted (off by default) |

Device-to-server frames found: `LK`, `UD`, `UD2`, `AL`, `CONFIG` (`TY:`, `VR:`), `ICCID`,
`TKQ`/`TKQ2`, `IMG`/`img`, `RE`, `TK`, `WT`, `WG`. A status/config SMS template is at `0x269bfc`:
`*ver:%s;id:%s;imei:%s;ip_url:%s;port:%d;mm:%s;apn:%s;...#`.

## 8. Options for modifying it

From least to most risk:

1. **Reconfigure, don't modify.** Server, port, APN, intervals and alarms are all runtime settings.
   This covers everything in our current plan (own server, Vodafone IoT APN) with zero risk to
   the firmware.
2. **Patch the settings store**, e.g. set our APN/server in NVRAM or in `default_config.txt` so
   they survive `FACTORY`. Needs (a) the record check algorithm, (b) a flash-write path. The
   write path now exists on the Mac (RAM programmer, [rom-flash-access.md](rom-flash-access.md));
   the record check algorithm is still unknown.
3. **Binary-patch the vendor code.** The code keeps its log strings, which carry function
   names (`sms_apn_handle`, `GprsSockNotify`, ...), and section 11 turns that into a
   decompile with strings and names. Good for targeted changes (e.g. disable the
   master password, change the default APN table). Code in the three compressed segments
   cannot be patched in place: the firmware checks a CRC over each segment after unpacking.
4. **Replace it with Logicrom.** Logicrom ships an RDA8955 core (`Logicrom_rda8955_core_v0.4.0.lod`),
   built for Ai-Thinker A9/A9G modules, not this R36 board. We would have to rewrite GPS,
   accelerometer, LEDs, buzzer, charging and removal sensor, recover the pin mapping from this
   dump, and check the RF/PA config matches. Logicrom's docs warn that the wrong RDA download tool
   erases calibration and IMEI, which is what this backup protects against.

**Writing and recovery** (updated 26-10-11). The Coolwatcher/Windows route is not used.
Forced ROM entry, a RAM programmer and full-image install and restore are demonstrated on
the spare units: see [rom-flash-access.md](rom-flash-access.md). The 2026-10-03 observation
that the vendor firmware accepted a ROM-monitor request and no ROM USB interface appeared
predates the force-bit method and is superseded; the register read of that day
(`Reset_Cause=0x00200000`, `BOOT_MODE=0x20`, `USB_MONITOR_DISABLE` clear) still stands.
Backup and file conversion alone never established recovery. No raw flash write has been
performed on the original `1403167417`.

## 9. Working native USB configuration

Verified on unit `1403167417`, firmware `R36S_RFHZ_V34_V1.0_2024.09.28_16.06.24`,
with the Vodafone data-only SIM installed and the tracker powered on.

Use `tools/rda_config.py`. It talks through PyUSB/libusb without a serial/kernel driver.
It only exposes status, APN readback, APN/server settings, and a normal firmware reboot.
Send one complete command per USB transfer and wait for its response before sending another.
Do not use a terminal that sends each keystroke separately.

| Operation | Exact USB bytes (CR shown as `\r`) | Observed acknowledgement |
|---|---|---|
| Status | `AT:ts#\r` | `sms_ts_handle.` and `AT RETURN:ts…` |
| APN readback | `AT:getapn#\r` | `get_apn_handle.apn:…UserName=,Password=,mccmnc=…` and `AT RETURN:getapn.` |
| Save Vodafone APN | `AT:apn,sme.vodafone.iot,,,90128#\r` | `set_APN_data.p_APN_name:sme.vodafone.iot…P_UserData:90128.` and `AT RETURN:apn.`; firmware reboots |
| Save vendor server | `AT:ip,47.106.163.223,8888#\r` | `set_url_port.url:47.106.163.223;port:8888…` and `AT RETURN:ip.` |
| Reboot | `AT:reset#\r` | `sms_reset_handle.`, `The device will be reboot soon.`, `AT RETURN:reset.` |

No `pw,123456,` prefix was required in the verified USB path. The USB acknowledgement
for APN is just `AT RETURN:apn.`; the longer “Set apn…is successful” string belongs to
another response path and must not be required by the host tool.

Example (use a new output filename on repeat runs):

```sh
mkdir -p firmware/live
.venv/bin/python tools/rda_config.py status --output firmware/live/status.raw
.venv/bin/python tools/rda_config.py set-apn --apn sme.vodafone.iot --plmn 90128 --output firmware/live/apn-set.raw
# Wait for the firmware reboot and USB re-enumeration.
.venv/bin/python tools/rda_config.py get-apn --output firmware/live/apn-check.raw
.venv/bin/python tools/rda_config.py set-server --host 47.106.163.223 --port 8888 --output firmware/live/server-set.raw
.venv/bin/python tools/rda_config.py status --output firmware/live/server-check.raw
```

Live evidence is stored locally in gitignored `firmware/live/` because logs include
IMEI/IMSI and nearby Wi-Fi identifiers. Key captures: `at-colon-status.raw`,
`set-vodafone-apn.raw`, `verify-vodafone-apn.raw`, `set-vendor-server.raw`.

Observed after the APN-triggered reboot (`pwon_count:15` → `16`):

```text
gprs_state_check apn:sme.vodafone.iot plmn:90128.
get_apn_handle.apn:sme.vodafone.iot.UserName=,Password=,mccmnc=90128
----active_gprs_rsp is_gprs_ready=nResult=1 nCid=1
dns_Event_Handler IP:47.106.163.223 PORT:8888
**************soc_connect************* result=1.
soc_sendto:len=30,ret=30.
```

This proves APN persistence, successful data activation and a TCP connection; app display
and GPS fix are separate checks. DNS also worked after fixing the APN.

A final normal reboot (`AT:reset#\r`, `pwon_count:16` → `17`) confirmed **both** saved
settings in `after-reboot-status.raw`: APN `sme.vodafone.iot` / PLMN `90128`, server
`47.106.163.223`, port `8888`, and status `NET:OK(100)`. The host tool's acknowledgements
were checked against these actual captures. Five offline tests cover wire framing,
the firmware's APN buffer limit, delimiter injection, and mismatched acknowledgements.

### Reverse-engineering evidence

The public [RDA8955 W17.44 SDK](https://github.com/cherryding1/RDA8955_W17.44_IDH)
provided the USB structure; the following addresses were traced in this unit's actual
MIPS16 little-endian dump, not assumed from that SDK:

| Address (function pointers include MIPS16 low bit) | Role |
|---|---|
| `0x881b91fd` | Registers vendor USB callback `0x881b9401` using `uat_transSetCallback` (`0x88039f55`) |
| `0x881b9401` | USB receive callback; forwards input through a UI event |
| `0x881b9381` / `0x881b9399` | Event dispatch/creation forwarding received bytes |
| `0x881b869d` | Parses `AT+uart2:` specially; otherwise strips three bytes and schedules the general parser |
| `0x881b88a5` | Passes `#`-terminated content to `0x881b59f9` with source type 2 |
| `0x881b59f9` | General command dispatcher |
| `0x881b4f3d` | APN command handler |
| `0x881aa3b9` | `set_APN_data`, calls the firmware's settings-write routine |

The APN field spans `0x82200b50`–`0x82200b6f` (32 bytes); the firmware uses `strcpy`.
The utility limits it to 31 ASCII characters. The receive event has a 200-byte buffer;
the utility also bounds command length and rejects delimiter injection. It never writes
memory or programs flash directly. On USB loss after a firmware reboot, it closes its
evidence file and bypasses libusb teardown, which otherwise hung on this Mac.

## 10. Settings UI

`tools/tracker_ui.py` is a local web page for every setting the parser accepts. It uses the
same `AT:<cmd>#\r` path as section 9 and has no dependencies beyond PyUSB.

```sh
.venv/bin/python tools/tracker_ui.py      # then open http://127.0.0.1:8724
```

- **Read from tracker** sends `ts` and `getapn` and fills the forms with the current values.
- Each setting shows the exact bytes it will send and the firmware's `AT RETURN:` result.
- The console takes any keyword. It autocompletes from the 258 keywords in this build's
  parser table (`0x1b5900`–`0x1b7f00`). The server refuses flash, identity and update
  keywords (`flashread`, `cleanfnv`, `delfile`, `setverno`, `upgrade`, `imei`, ...).
- The live log follows reboots and reconnects by itself.
- The server binds to 127.0.0.1 only. It accepts only JSON POSTs and local `Host`
  headers, so other web pages cannot send commands to it.

**The settings list is data, not code:** `tools/tracker_settings.json`. It names the
firmware it was written for, and the page warns when the tracker reports a different
`ver:`. For a custom firmware, copy that file, change the commands, and update `firmware`.

Live results on this build, 2026-10-02:

| Command | Result over USB |
|---|---|
| `verno`, `imsi`, `upload,600` | acknowledged with `AT RETURN:` |
| `iccid` | runs and logs `read_iccid=...`, no `AT RETURN` |
| `gsmsignal` | answers to the server (`[3G*id*000D*gsmsignal,100]`), no `AT RETURN` |
| `querynet` | logs IMSI, PLMN and attach state, no `AT RETURN` |
| `tsext` | prints its extended status, then **reboots the tracker** (`pwon_count` 17 to 18). Left out of the UI |

Settings marked "unverified" in the page use syntax from the vendor protocol document.
They are present in this build's keyword table but were not sent live.

The tracker still reports `zone:8.00`, the factory UTC+8. Portugal needs `lz,0,0` in winter
or `lz,0,1` in summer.

## 11. Decompile

`tools/ghidra/build.sh` rebuilds a Ghidra decompile of the 2026-10-03 backup. It is
offline and takes about 15 minutes. It refuses to run if the backup does not match
`firmware/backup/SHA256SUMS`. Design and evidence:
[spec](../done/superpowers/specs/26-10-08-readable-decompile-design.md), section 11.

```sh
tools/ghidra/build.sh        # needs: brew install ghidra openjdk@21
```

| Output (gitignored, holds vendor code) | Content |
|---|---|
| `firmware/decompiled/<address>.c` | decompiled C, one file per 64 KiB of address space |
| `firmware/decompiled/index.tsv` | every function: address, name, where the name came from, size, file, number of callers |
| `firmware/decompiled/name_candidates.tsv` | log-string names that were not applied because they are ambiguous |
| `firmware/ghidra/v24.gpr` | the Ghidra project, for browsing with `ghidraRun` |

To find a function: `awk -F'\t' '$2=="sms_apn_handle"' firmware/decompiled/index.tsv`.

What the build does to the raw image, and why:

- **Memory as the firmware sees it.** Flash is read-only. The sections that boot copies
  to SRAM and RAM are loaded at their run addresses, and the three LZMA segments at
  `0x2d7860`, `0x2f6300` and `0x353f80` are unpacked to `0x8201d5e0`, `0x82050260` and
  `0x820eab40`. The unpacked bytes give the CRCs the firmware itself checks
  (`0x8a7ac17c`, `0x76212f3e`, `0x25f19f18`).
- **Returns.** This compiler returns with `jr a3`; Ghidra is told so.
- **Functions.** Handlers reached only through pointer tables are found from the
  pointers and from the compiler's frame idiom.
- **Names.** A log line usually starts with the name of the function that prints it.
  ROM calls (`memcpy`, `sprintf`, ...) are named from the SDK's ROM map. Hand names go
  in `tools/ghidra/v24_names.tsv`, one row each with its evidence, and override the rest.

Result, measured by `tools/ghidra/metrics.py` on the old single-file export and on this build:

| | Old export | This build |
|---|---|---|
| functions | 8,521 | 16,300 |
| named functions | 0 | 685, plus 38 ROM functions |
| distinct string literals | 0 | 3,233 |
| functions ending in an "unrecovered jump table" | 2,777 | 0 |
| call targets with no function | 518 | 3 |
| functions that fail to decompile | 0 | 0 |

`sms_apn_handle` comes out at `0x881b4f3c`, the address traced by hand in section 9,
with its two log strings and a call to `0x881aa3b8`. There are 128 `sms_*_handle`
functions, not 56.

Not resolved:

- 129 log-string identifiers are ambiguous (several functions print them, or one
  function prints several) and were not applied. They are listed in `name_candidates.tsv`.
- The `sms_*_handle` functions call 202 distinct functions; 107 have no name. Nearly all
  of those sit next to the handlers in the vendor's own application code, which the
  public RDA SDK does not contain, so matching against SDK source was not done.
  One of them, `0x881b9304`, is the log `printf` every handler calls (824 callers).
- Three functions hit bad instruction data: `0x88050ca0` and `0x8807af8c` are real
  functions with a decoding fault inside, `0x88205a74` is 12 bytes of junk.
- The 3 call targets with no function are garbage calls in `0x8200499c`, decoded past
  a call that does not return.
- About 6 KiB of disassembled code is in no function, because other code falls or
  jumps into it.
- The compressed segments are loaded read-only because the public SDK's linker script
  puts only code and constants in them. That this build's script does the same is
  **(unverified)**.
- No types, structs or hand cleanup yet. That is the next piece of work, starting with
  the command parser and the settings store.
