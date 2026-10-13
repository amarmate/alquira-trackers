/* Livestock tracker (sheep/goat) — tunable policy parameters.
 *
 * Testing posture is deliberately LAX: the GPS window is the full 24 h
 * (A == B == midnight means "always open"), the motion gate defaults OFF so
 * every slot takes a fix, and deep sleep defaults OFF so the USB console
 * stays up for observation. Tighten each knob as phases validate.
 */
#ifndef TRACKER_CONFIG_H
#define TRACKER_CONFIG_H

/* ---- GPS schedule: one fix attempt every slot while the window is open ---- */
#define CFG_FIX_INTERVAL_S 1800u      /* 30 minutes */
#define CFG_WIN_A_MIN 0u              /* window start, minutes since midnight UTC */
#define CFG_WIN_B_MIN 0u              /* window end; A == B means always open */
#define CFG_FIX_TIMEOUT_S 120u        /* give up on a fix after this long */

/* ---- Motion gate: skip the fix when the animal has been stationary ----
 * 0 = always fix (lax testing). 1 = require motion since the last fix.
 * The gate fails OPEN (fixes anyway) until the IMU driver works. */
#define CFG_REQUIRE_MOTION 0
#define CFG_MOTION_MIN_ACTIVE_S 30u   /* motion-active seconds since last fix to trigger GPS */

/* ---- GSM uploads: twice daily, batched, coverage-aware ---- */
#define CFG_UPLOAD_1_MIN (6u * 60u)   /* 06:00 UTC */
#define CFG_UPLOAD_2_MIN (18u * 60u)  /* 18:00 UTC */
#define CFG_UPLOAD_DEFER_MAX_MIN 240u /* wait at most 4 h for a good spot */
#define CFG_UPLOAD_MIN_RSSI (-90)     /* minimum serving-cell RSSI; TODO: validate scale on hardware */
#define CFG_UPLOAD_TIMEOUT_S 90u
#define CFG_GPRS_ATTACH_TIMEOUT_S 120u

/* ---- Known-good coverage spots (serving cell identities) ----
 * TODO: populate from field measurements. Empty list = RSSI threshold only. */
#define CFG_GOOD_CELL_COUNT 0u

/* ---- Server endpoint (draft JSON-lines-over-TCP protocol, see doc) ---- */
#define CFG_SERVER_IP "192.0.2.10"    /* TODO: real Alquira endpoint */
#define CFG_SERVER_PORT 9001

/* ---- V24 hardware ----
 * GPS power is GPIO 32 (high = on) per docs/knowledge/pin-map.md.
 * GPS UART is on GPIO 0/1 at 9600 baud; the LogicROM device name below is
 * a guess until verified on a running core. */
#define CFG_GPS_PWR_GPIO 32u
#define CFG_GPS_PORT "/dev/ttyS0"     /* TODO: verify on hardware */
#define CFG_GPS_BAUD 9600

/* ---- Store-and-forward queue (one partition, record type byte) ---- */
#define CFG_STORE_PART 0
#define CFG_STORE_MAX_PACKETS 1024u   /* ~21 days at 48 records/day */

/* ---- Testing ---- */
#define CFG_TEST_NO_SLEEP 1           /* 1: task sleep (console stays up); 0: deep sleep between slots */

#endif
