# ReachFar V24 (2G) cattle tracker: control intel

Compiled from the four vendor documents (V24 user manual, "Switch Server by SMS Command",
"GPS Tracker Transport Protocol V1.8_C / V2.0", "V24/V34/V44 Communication Examples").
Where something is inferred rather than written in the documents it is marked **(unverified)**.

Our deployment context:

| Item | Value |
|---|---|
| Device | ReachFar V24, **2G-only variant** (GSM/GPRS, no 3G/4G) |
| Device ID | 10 digits on the back label (this is the `YYYYYYYYYY` in every protocol frame) |
| Default password | `123456` |
| Vendor server (FQDN) | `a.igps123.com` |
| Vendor server (IP) | `47.106.163.223` |
| Vendor server port | `8888` (TCP) |
| Vendor web platform | `www.gps123.org` |
| Vendor app | "Anytracking" (App Store / Play), login = device ID, password `123456` |
| SIMs | Vodafone SME IoT (data only: no SMS, no voice). SPN reads `DATA ONLY` |
| SIM home network | IMSI `90128...`: Vodafone global IoT (MCC `901`), **not** `26801`. In Portugal it roams on Vodafone PT |
| SIM APN | `sme.vodafone.iot`, no user/password (confirmed by Vodafone) |
| Country / operator codes | Portugal MCC `268`. Vodafone MNC `01`, NOS `03`, MEO `06` |

---

## 1. Hardware quick reference

- Nano SIM slot under a screwed waterproof cover. Insert with tracker **off**.
- **Power on**: hold power button 5-7 s until red and blue LEDs light for 2 s and it beeps.
- **Power off**: with **no SIM** inserted, hold power 5-7 s (two beeps). With a SIM inserted the
  device can only be powered off remotely (app / server `POWEROFF`). This is deliberate anti-theft.
- **Hard reset when frozen**: short press the RST hole with the pin, then put it on the charger.
  Do not hold it.
- 4000 mAh battery, solar assist, IP67, magnet USB charging cable. Charge 10 h before first use.
- Removal sensor becomes active 3 minutes after power on.

LEDs:

| LED | Pattern | Meaning |
|---|---|---|
| Red (network) | slow flash | searching for GSM network |
| Red (network) | fast flash | registered on network |
| Blue (GPS) | slow flash | acquiring position |
| Blue (GPS) | fast flash | position uploaded to server |
| Red only, slow flash | | low battery |
| Charging: red slow flash / red solid | | charging / full |

The red LED is the first thing to look at when debugging: if it never goes to fast flash the SIM
is not registering (PIN lock, no 2G coverage, SIM not activated, plan without 2G).

---

## 2. What the SIM has to provide

The tracker has two independent control channels and each one needs something from the SIM:

| Channel | Needs from the SIM | Used for |
|---|---|---|
| **SMS** (phone -> tracker) | mobile-terminated **and** mobile-originated SMS, caller ID | initial setup: center number, APN, server IP. Also `ts#` status and SMS alerts |
| **Data / server** (tracker <-> TCP server) | GPRS data on a 2G network, APN that can reach the server | everything else: position upload, all app/platform settings, remote reboot / power off |
| Voice (optional) | voice | call the tracker, listen-in (`CALL`, `MONITOR`) |

Additional hard requirements:

- **No SIM PIN.** The tracker cannot enter a PIN. Put the SIM in a phone and disable the SIM lock first.
- **2G (GSM/GPRS) must be enabled** on the plan and present at the farm. Portuguese operators are
  switching 3G off first; 2G is still up but is on the decommissioning roadmap. A plan that is
  "4G only", "LTE-M" or "NB-IoT" will never register on this device.
- Caller ID (CLIP) must be active on the SIM in the tracker, otherwise it cannot match the sender
  of an SMS against the center number.

**Vodafone SME IoT SIMs have no SMS.** That means: while a Vodafone IoT SIM is inside the tracker,
every SMS you send to it is silently dropped by the network. Nothing you type on your phone reaches
the device. The server channel provides remote control. **Local USB configuration also works**
with that SIM installed: see section 6 and [the firmware investigation](v24-firmware-analysis.md#9-working-native-usb-configuration).

---

## 3. SMS command channel

### Password and sender rules (from the protocol document)

- The tracker has one **center** (master) number and optionally one **slave** number.
- SMS from the center number can omit the password: `ip,a.igps123.com,8888#`
- SMS from any other number must be prefixed with `pw,<password>,`: `pw,123456,ip,a.igps123.com,8888#`
- Default password `123456`. Changeable with the `PW` server command.
- The device replies to an accepted command with an SMS. **No reply means the command was not
  received or not accepted.** Always wait for the reply before sending the next command.
- All lowercase, no spaces, terminate with `#`. Empty fields are kept as consecutive commas.

### Documented SMS commands

| Purpose | SMS | Notes |
|---|---|---|
| Set center number | `pw,123456,center,<phone>#` | The phone **you send commands from**, never the tracker's own number. Start with the plain national number (9 digits in PT); if the tracker later does not recognise you as center, re-set it as `00351xxxxxxxxx` **(format unverified)** |
| Set SOS numbers | `sos1,<phone>#`, `sos2,<phone>#`, `sos3,<phone>#` | up to 3 |
| Check device status | `ts#` | replies with a status SMS (network, GPS, server link, battery). Your main diagnostic |
| Set server | `ip,<host_or_ip>,<port>#` | `ip,a.igps123.com,8888#` or `ip,47.106.163.223,8888#`. The device disconnects and reconnects to the new server, no SMS reply is guaranteed |
| Set APN | `apn,<apn>,<user>,<password>,<MCCMNC>#` | e.g. `apn,internet,,,78502#`. Empty user/password stay as `,,`. The MCCMNC is the network the APN belongs to |
| Change IMEI | `imei,<15 digits>#` | avoid |

### Likely-supported SMS commands (unverified)

The server protocol keywords are usually also accepted over SMS on ReachFar firmware with the same
`pw,123456,` prefix. Test one at a time and expect an SMS reply:

`pw,123456,upload,600#` (interval, seconds) · `pw,123456,reset#` · `pw,123456,factory#` ·
`pw,123456,verno#` · `pw,123456,cr#` (force a GPS fix) · `pw,123456,lz,0,1#` (English, UTC+1) ·
`pw,123456,sos,<n1>,<n2>,<n3>#` · `pw,123456,gprsgps,1#`

---

## 4. Server / TCP channel (the protocol)

This is what the vendor platform uses and what our own server has to speak.

### Framing

```
[<vendor>*<deviceId>*<len>*<content>]
```

- `vendor`: 2 chars. Device sends `3G` (older firmware `SG`). Server replies with `SG`
  (examples show the server may also use `3G`; the device accepts both).
- `deviceId`: the 10-digit ID.
- `len`: length of `content` in bytes, as **4 uppercase hex ASCII chars** (`0002` = 2, `00A2` = 162).
- Multiple frames can arrive in one TCP segment; parse by brackets, not by newline.
- Port is plain TCP, no TLS. One long-lived connection per device.

### Device -> server messages

| Content | Meaning | Server must reply |
|---|---|---|
| `CONFIG,TY:...,VR:<firmware>` | sent once at connect: capability flags and firmware version | `[SG*id*0008*CONFIG,1]` |
| `ICCID,<iccid>,<imei>,<imsi>,` | SIM identity at connect | `[3G*id*0016*RYIMEI,<imei>]` |
| `LK` or `LK,<steps>,<rolls>,<battery%>` | keepalive every 5 min | **`[SG*id*0002*LK]` always**. If not answered the device sends nothing else and reconnects every 5 min |
| `UD,<position>` | position report (2G firmware). `UD_LTE` / `UD_WCDMA` on other variants | none |
| `UD2,<position>` | re-upload of positions stored while offline | none |
| `AL,<position>` | alarm report with alarm bits set (`AL_LTE` on 4G) | `[SG*id*0002*AL]` or it repeats |
| `TKQ` / `TKQ2` | voice chat request | echo it back |

### Position payload (comma separated, after `UD,` / `AL,`)

```
ddmmyy, hhmmss(UTC), A|V, lat, N|S, lon, E|W, speed_kmh, heading_deg, altitude_m,
satellites, gsm_signal(0-100), battery%, steps, rolls, status_hex(8),
nCells, gsm_delay, MCC, MNC, [lac, cellId, rssi] x nCells,
nWifi, [ssid, mac, rssi] x nWifi, accuracy_m
```

- `A` = valid GPS fix, `V` = no fix (position is then cell/WiFi based, treat as coarse).
- `status_hex`: 32-bit, low 16 bits = status, high 16 bits = alarms.

| Bit | Meaning |
|---|---|
| 0 | low battery status |
| 3 | worn / attached status |
| 4 | at rest |
| 15 | vibration alarm |
| 16 | SOS alarm |
| 17 | low battery alarm |
| 18 | out of geo-fence |
| 19 | entered geo-fence |
| 20 | removal alarm |
| 21 / 22 | fall alarm (unused on V24) |

Examples from the vendor: removal alarm `00100000`, vibration `00008000`, SOS `00010000`.

### Server -> device commands

Send as `[SG*<id>*<len>*<content>]`. The device echoes the keyword back as acknowledgement
(`[3G*id*0006*CENTER]`) unless noted.

| Content | Effect |
|---|---|
| `UPLOAD,<seconds>` | position upload interval. Shorter = more accurate, much shorter battery |
| `CENTER,<phone>` | set center number |
| `SLAVE,<phone>` | set assistant number |
| `PW,<6 digits>` | change SMS password |
| `SOS1,<phone>` / `SOS2` / `SOS3` / `SOS,<p1>,<p2>,<p3>` | SOS numbers |
| `CALL,<phone>` | device calls that number |
| `MONITOR` | device calls the center number silently (listen-in) |
| `IP,<host_or_ip>,<port>` | change server. **No reply**: the device drops the link and connects to the new server |
| `APN,<apn>,<user>,<pass>,<MCCMNC>` | set APN |
| `FACTORY` | factory reset |
| `RESET` | reboot |
| `POWEROFF` | power off (only way to switch off with a SIM inside) |
| `CR` | wake GPS, upload every 30 s for 3 min |
| `VERNO` | reply `VERNO,<firmware string>` |
| `LZ,<lang>,<tz>` | language 0=English 1=Chinese, timezone e.g. `1` or `-4` |
| `SOSSMS,0|1` | SMS to SOS numbers on SOS alarm |
| `LOWBAT,0|1` | SMS to center on low battery |
| `SMSONOFF,0|1` | all SMS alerts to center |
| `REMOVESMS,0|1` | SMS to center on removal alarm |
| `REMOVE,0|1` | removal alarm on/off |
| `VON,0..4` | vibration alarm off / sensitivity 1 (most sensitive) to 4 |
| `HON,0|1` | local siren when an alarm triggers |
| `MOD,0..3` | alarm delivery: 0 server only, 1 server+SMS+call, 2 server+call, 3 server+SMS |
| `DND,0|1` | 1 = only center and SOS numbers may call the tracker |
| `BON,1` / `FIND` | ring the device (find it) |
| `LED,0|1` | signal LEDs off/on |
| `LSN,0|1|2` | white LED off / flashing / always on |
| `ANY,0|1` | 0 = only center/slave may send SMS commands, 1 = anyone with password |
| `WHITELIST1,<5 numbers>` / `WHITELIST2,...` | numbers allowed to call |
| `PHB,<num,name>x5` / `PHB2` | phone book (names in Unicode hex) |
| `WIFIFENCE,1,<mac>,2,<mac>,3,<mac>` | WiFi fence, 2.4 GHz only |
| `SPOF,hh:mm-state-type,...` | timed on/off schedule |
| `GETTEMP` | temperature, reply `GETTEMP,<value>` |
| `PEDO,0|1` / `PED0,0|1` | step counter |
| `WALKTIME,hh:mm-hh:mm,...` | pedometer active windows |
| `gprsgps,0|1` | 0 = stop data and GPS (deep sleep), 1 = on |
| `UPGRADE,<http url>` | remote firmware upgrade. Do not use casually |

Minimal server behaviour to keep a device alive and reporting:

1. Accept TCP on 8888, keep the socket open.
2. On `CONFIG` reply `CONFIG,1`; on `ICCID` reply `RYIMEI,<imei>`.
3. Reply `LK` to every `LK`. Reply `AL` to every `AL`.
4. Store every `UD` / `UD2` / `AL`.
5. Queue outgoing commands and write them to the socket when the device is connected.

---

## 5. Vendor platform details

- Devices ship pointed at `a.igps123.com:8888`. The vendor asks that you first verify each
  device on their platform (app "Anytracking" or `www.gps123.org`, login = device ID, pw `123456`)
  and only then switch it to your own server with `ip,<host>,<port>#`.
- The app shows "Stationary" / "Moving" when the device is online. Anything else means the
  device never reached the server: SIM, APN or firewall problem.
- App settings only work while the device is online (they travel over the server channel).
- Recommended upload interval: 10 min normal, 1 min temporarily when searching for an animal.
- FAQ: online in SMS but "Not enabled" on the platform = no data plan or wrong APN.

---

## 6. Setup procedure for the Vodafone SME IoT SIMs

**Preferred local setup: USB, verified 2026-10-02.** Leave the IoT SIM installed and the
tracker powered on. Interface 1 of `1782:3d00` accepts `AT:apn,sme.vodafone.iot,,,90128#`
followed by CR, then, after its automatic reboot, `AT:ip,47.106.163.223,8888#` followed
by CR. Use [tools/rda_config.py](../tools/rda_config.py), which sends each command in one
transfer, records the reply and checks its acknowledgement. Read back with `AT:getapn#`
and `AT:ts#`. The APN survived reboot, data activation succeeded and the device connected
to the vendor server. See [full commands and evidence](v24-firmware-analysis.md#9-working-native-usb-configuration).
For every other setting, use the local settings page `tools/tracker_ui.py`
(see [section 10 of the firmware notes](v24-firmware-analysis.md#10-settings-ui)).

The SMS/staging-SIM procedure below remains an alternative for units where USB is unavailable.
All settings live in the tracker, not in the SIM, so they survive the swap.

### Step 0: check the Vodafone IoT portal once

- SIM state: activated, data enabled.
- Radio: **2G/GSM allowed** on the plan (not 4G-only, not NB-IoT/LTE-M).
- APN: read the exact APN name and whether it needs user/password. We currently assume
  `sme.vodafone.iot` with no credentials; confirm it in the SIM details page.
- Firewall / whitelist: `a.igps123.com` **and** `47.106.163.223`, TCP port `8888` outbound.
  If the platform lets you allow DNS, allow it; if not, point the tracker at the IP instead of the
  FQDN so it never needs DNS.
- Optional but ideal: ask Vodafone whether **SMS (MT and MO) can be added** to the IoT plan. If
  yes, the staging-SIM dance below becomes unnecessary.

### Step 1: staging SIM in, get the tracker online with it

1. Disable PIN on the staging SIM (in a phone). Note the staging SIM's own APN and MCCMNC
   (Vodafone PT consumer: `internet.vodafone.pt` / `26801`; MEO: `internet` / `26806`;
   NOS: `internet` / `26803`).
2. Tracker off, insert staging SIM, power on. Wait for red LED **fast** flash.
3. From phonenumber1 send, one at a time, waiting for the SMS reply each time:
   - `pw,123456,center,<phonenumber1>#`
   - `pw,123456,apn,<staging apn>,,,<staging MCCMNC>#`
   - `ts#`  (should report GSM ok, and after a minute GPRS/server link ok)
4. Open the Anytracking app with the device ID. It must show Stationary/Moving. If it does not,
   the APN is wrong or the staging SIM has no data; fix that before going on. This proves the
   device, antenna, server and firmware are fine.

### Step 2: pre-load the Vodafone IoT settings

Still with the staging SIM inside, send:

- `pw,123456,apn,sme.vodafone.iot,,,90128#`
  The last field is the **SIM's home network from its IMSI** (`90128`), not the Portuguese network
  it roams on (`26801`). The firmware's own APN table follows the same rule (1NCE is listed as
  `90140`, Tele2 IoT as `24007`).
- `pw,123456,ip,47.106.163.223,8888#`  (IP, not FQDN, to avoid DNS issues on the private APN)

Each command should get a `Set apn,... is successful` style SMS reply. With the tracker on USB,
`tools/rda_log.py` also shows `sms_apn_handle.apn:...` when the command lands.

Caveat **(unverified)**: the firmware may hold only one APN, in which case the tracker loses data
on the staging SIM after this step. That is fine, SMS still works; do this as the last step.
If the staging SIM is itself Vodafone PT (also `26801`) the APN entry is simply overwritten.

### Step 3: swap to the IoT SIM

1. Power the tracker off. With a SIM inside this needs the app: Settings -> Remote power-off.
   (Or pull the SIM cover, remove the staging SIM, then hold the button 5-7 s.)
2. Insert the Vodafone IoT SIM, power on.
3. Red LED must go to fast flash within about a minute. Then blue fast flash = uploaded.
4. In the Vodafone portal, look at the SIM's session / data usage: a PDP session on the
   right APN with bytes flowing proves the tracker attached and got data.
5. Anytracking must show Stationary/Moving. From now on all control is through the app,
   the web platform, or our own server. SMS no longer exists for this device.

### Step 4 (later): move to our own server

Once our server speaks the protocol in section 4, send `IP,<host>,<port>` from the vendor
platform (or `ip,...#` by SMS while a staging SIM is in). The device drops the vendor link and
connects to ours. The same command sent from our server sends it back.

---

## 7. What went wrong in the first attempt

Commands sent from phonenumber1 while an SMS-capable SIM was in the tracker:

```
pw,123456,center,phonenumber2#
pw,123456,apn,sme.vodafone.iot,,,26801#
pw,123456,center,phonenumber1#
```

Then the Vodafone IoT SIM was inserted and "it doesn't work".

1. **With the IoT SIM inside, SMS cannot work at all.** The network never delivers SMS to that
   SIM. This is not a tracker fault. Judge the IoT SIM by the LEDs, the Vodafone portal session
   log, and the app, never by SMS.
2. **The APN command, if it was accepted, was pointed at the IoT APN**, so with the staging SIM
   inside the tracker had no working data and could not be verified on the platform. Verify with
   the staging SIM's own APN first (Step 1), then load the IoT APN last (Step 2).
3. **Did the tracker ever reply to an SMS?** If there was no reply to any command, the staging SIM
   never registered (PIN lock, no 2G, or the SIM's SMS centre) and none of the three commands took
   effect. Check the red LED for fast flash and send `ts#`.
4. **Center must be the phone that sends commands** (phonenumber1). Setting it to phonenumber2
   first was harmless because the `pw,123456,` prefix authorises any sender, but it is not needed.
5. **Unknowns to confirm in the Vodafone portal**: exact APN string, 2G enabled on the plan,
   whitelist covering the IP as well as the FQDN, and whether DNS is allowed.

### Confirmed root cause (2026-10-02, live USB log, unit `1403167417`, Vodafone IoT SIM inside)

```
read_imsi.901280021272480,
gprs_state_check plmn:90128.nMNCLen=2          SIM is Vodafone global IoT
---is_gprs_ready ... is_gprs_attached=1        2G attach works, roaming works
gprs_state_check apn:m2m.tele2.com plmn:24007. tracker still uses the factory APN
----active_gprs_rsp is_gprs_ready=nResult=241 nCid=1
active_gprs_rsp error                          Vodafone rejects the data session, every retry
soc_gethostbynameExt ret_val=-1,ip_url:a.igps123.com   DNS fails because there is no data session
```

The SIM, the radio, roaming and Vodafone's side are fine. The **tracker** never received the APN,
so it asks Vodafone for `m2m.tele2.com`. Vodafone's DNS/whitelist theory is a symptom: no PDP
context means no DNS at all. After enough failures the tracker reboots itself (`pwon_count`
increments), which also drops the USB connection.

**Resolved over USB on 2026-10-02:** `AT:apn,sme.vodafone.iot,,,90128#\r`, then
`AT:ip,47.106.163.223,8888#\r`. A staging SIM was not required. The initial USB probes failed
because they omitted `AT:`; the earlier conclusion that USB could not configure the APN
was incorrect. The general command parser is reachable through the normal USB data port.
Success in the log is `active_gprs_rsp` **without** `error`, followed by a socket to
`47.106.163.223:8888`.

---

## 8. Troubleshooting matrix

| Symptom | Likely cause | Check / fix |
|---|---|---|
| Red LED slow flash forever | SIM PIN, SIM not active, no 2G on plan or at site | disable PIN, portal state, try the SIM in a 2G phone at the farm |
| Red fast flash, no SMS reply (staging SIM) | wrong tracker number, SMS centre, commands with spaces/uppercase | resend exactly, lowercase, wait 1 min |
| Red fast flash, SMS ok, app says Not enabled / offline | APN wrong, no data, server blocked | `ts#`, fix `apn` command, portal session log, whitelist |
| USB log: `active_gprs_rsp error` | tracker's APN is not the SIM's APN | re-send `apn,...,<IMSI MCCMNC>#` (section 7) |
| USB log: `gethostbyname ret_val=-1` | no data session (see above), or DNS blocked | fix the APN first; then use the IP, not the FQDN |
| Device online, app says "wait for the device responses" | weak signal or device busy | wait and retry |
| Position always `V` / jumping | indoors or under roof, LBS/WiFi fallback | expected; GPS needs sky. Filter LBS in the app |
| Removal alarms when handling | removal sensor active 3 min after power on | expected |
| Cannot power off | SIM inside | app -> remote power off, or remove SIM then hold button |
| Frozen | | RST pin short press, then charge |
| Device connects to our server but sends only `LK` | we did not reply `LK` | reply every keepalive |

---

## 9. Frame examples (copy for tests)

```
Device:  [3G*2104346361*0008*LK,0,0,4]
Server:  [SG*2104346361*0002*LK]

Device:  [3G*2104346361*003B*ICCID,89860321147558480556,865121043463619,460115056494601,]
Server:  [3G*2104346361*0016*RYIMEI,865121043463619]

Server:  [SG*2104346361*0009*UPLOAD,60]
Device:  [3G*2104346361*0006*UPLOAD]

Server:  [SG*2104346361*0002*CR]
Device:  [3G*2104346361*00E1*UD_LTE,100222,221554,V,00.000000,,00.0000000,,0.00,0.0,0.0,0,80,40,0,0,00000000,2,0,460,0,10142,225274433,4,10142,54313355,-4,4,,8c:14:b4:5e:4b:a8,-80,...,0.0]

Server:  [SG*2104346361*0014*IP,113.81.229.9,5900]
Device:  (no reply, reconnects to the new server)
```

Length check: `UPLOAD,60` is 9 bytes -> `0009`. `IP,113.81.229.9,5900` is 20 bytes -> `0014`.
