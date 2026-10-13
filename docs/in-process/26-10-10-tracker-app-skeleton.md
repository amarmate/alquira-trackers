# Livestock tracker app skeleton — 2026-10-10

Offline skeleton for the sheep/goat tracker application. It **compiles
cleanly** (`-Wall -Wextra -Werror`) and **packages** into a unit-bound trial
image, but it has **never executed**: the license gate means no LogicROM app
has ever run on our units. Every hardware assumption below is marked TODO and
needs validation on a running (i.e. activated) core before any field claim.

Sources: `firmware/logicrom/tracker/`. Build staging and artifacts:
`firmware/live/usb-programmer-build/tracker-2026-10-10/`.

## Policy (all parameters in `tracker_config.h`)

- **GPS**: one fix attempt every 30 min while the window `[A, B)` is open.
  Window is minutes-since-midnight UTC; **A == B == midnight means always
  open** (current lax-testing configuration). Fix timeout 120 s; miss still
  records a slot (fix `V` + activity + battery) so gaps are visible.
- **Motion gate** (`CFG_REQUIRE_MOTION`, default **off** for testing): skip
  the fix when the IMU reports less than 30 motion-active seconds since the
  last fix. Fails open until the accelerometer driver exists.
- **Activity ("steps" proxy)**: there is **no SDK pedometer**, and goat gait
  needs its own validated detector (phase 2). Phase 1 records per slot:
  motion-active seconds + net-acceleration mean/max. Grazing, walking and
  resting separate on those signals.
- **GSM**: radio in flight mode between uploads; **two uploads/day** (06:00,
  18:00 UTC). At upload time: radio on, wait for GPRS attach, check
  serving-cell RSSI against the threshold (and the known-good cell list once
  populated — bounded deferral, max 4 h), open one TCP session, send the
  whole queue oldest-first, delete only what the server ACKs, radio off.
- **Battery**: capacity % + millivolts sampled at every fix and every
  upload; the drain curve per policy phase comes from these samples plus
  wall-clock runtime per charge.
- **Sleep**: deep sleep between slots in the field; task sleep while
  `CFG_TEST_NO_SLEEP` is set so USB/logs stay up on the bench.

## Record format (versioned, integers only on the wire)

`TREC_POS` (30-min slot): epoch, fix `A`/`V`, lat/lng in 1e-7 deg, speed in
dm/s, sats, HDOP in centi-units, battery %/mV, motion-active seconds,
accel mean/max in milli-g, skip reason (none / window closed / stationary).

`TREC_BATT` (upload time): epoch, battery %/mV, serving RSSI, LAC, cell ID.

Queue: one internal-flash FIFO partition, stop-when-full (never silently
drop), sized for ~21 days at 48 records/day.

## Draft upload protocol (JSON lines over TCP, server side TBD)

```text
device:  {"hello":"<imei>","v":1,"q":<queued>,"bp":<pct>,"bmv":<mv>}
server:  {"ok":1}
device:  <record json, oldest first>  (repeated)
device:  {"bye":<sent>}
server:  {"ack":<count>}   -> device deletes oldest <count> records
```

No ACK = nothing deleted. Record JSON keys: `v,t,e,f,lat,lng,spd,sat,hdop,
bp,bmv,mot,am,ax,sk` (pos) and `v,t,e,bp,bmv,rssi,lac,cid` (batt).

## Hardware TODOs before any trial

1. **GPS serial name** (`CFG_GPS_PORT`, guessed `/dev/ttyS0`) and **GPS chip
   driver** (`gps_set_driver_*`) — identify from vendor strings/NMEA talkers.
2. **Accelerometer chip + I2C driver** (GPIO 6/7) for `imu_add_sensor()`; the
   gate and activity stats are dead weight until then.
3. **GPRS-state poll** for attach wait (currently a timed placeholder).
4. **Socket receive callback** for the server ACK (currently a fail-safe
   stub that keeps everything queued).
5. **Deep-sleep clock retention and wake sources**; wall-clock sync strategy
   (GPS UTC → network time at upload).
6. **RSSI scale** for the coverage threshold; populate the good-cell list
   from field measurements.
7. **Server endpoint + protocol**: confirm the JSON contract with the
   Alquira backend before freezing `trec_to_json()`.

## Experiment mapping

The skeleton runs phases 1–2 as written (baseline drain, GSM batching). Phase
3 flips `CFG_REQUIRE_MOTION`; phase 4 populates the cell list; phase 5 adds
the goat step detector behind the same gate interface. Each phase is one
charge cycle minimum on one unit with one routine; change one knob per phase.

## Reproduction

```sh
docker --context colima-rda-build run --rm --network none --platform linux/amd64 \
  -v "$PWD/firmware/live/usb-programmer-build:/work/build" \
  -v "$PWD/firmware/live/usb-programmer-build/csdtk:/work/csdtk:ro" \
  -e V24_LOGICROM_WORK=/work/build/tracker-2026-10-10 \
  rda-usb-builder:local bash /work/build/tracker-2026-10-10/tracker/build_tracker.sh
.venv/bin/python tools/rda_logicrom_image.py \
  --core firmware/live/usb-programmer-build/logicrom/core_v0.5.1.lod \
  --app-raw firmware/live/usb-programmer-build/tracker-2026-10-10/build/tracker.raw.bin \
  --output firmware/live/usb-programmer-build/tracker-2026-10-10/v24-412-tracker-skel.bin
```

Built 2026-10-10: `tracker.raw.bin` 163,024 bytes, ELF text+data+bss 168,460
bytes; packaged trial image SHA-256
`9ce2e25d49707ba23dfe8190f454b56c106628c10c2fd10c32c996a8dc133f59`
(app region 196,608 bytes — fits). No device was touched.
