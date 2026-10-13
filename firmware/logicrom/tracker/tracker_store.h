/* Store-and-forward record format and queue.
 *
 * Records are fixed-size packed structs (versioned) written to one storage
 * partition as a FIFO. Uploaded records are encoded as one JSON object per
 * line; the JSON field names are the contract with the server (see doc).
 * Integers only on the wire — no float printf on the device.
 */
#ifndef TRACKER_STORE_H
#define TRACKER_STORE_H

#include <stdint.h>

#define TREC_VERSION 1u

enum trec_type_e {
    TREC_POS = 1,    /* scheduled GPS slot: fix (or miss) + activity + battery */
    TREC_BATT = 2,   /* battery sample taken at upload time */
};

/* One 30-minute slot. All multi-byte fields are little-endian in flash;
 * the JSON encoding carries the same values as decimal integers. */
struct trec_pos {
    uint8_t type;            /* TREC_POS */
    uint8_t fix;             /* 'A' = valid, 'V' = invalid/timeout/skipped */
    uint8_t batt_pct;        /* 0-100, 255 = unknown */
    uint8_t sats;            /* satellites used in fix */
    uint32_t epoch;          /* UTC seconds; 0 if time never synced */
    int32_t lat_e7;          /* latitude in 1e-7 degrees */
    int32_t lng_e7;          /* longitude in 1e-7 degrees */
    int16_t speed_dms;       /* speed in decimetres/second */
    uint16_t hdop_c;         /* HDOP in centi-units */
    uint16_t batt_mv;        /* battery millivolts, truncated to 16 bits */
    uint16_t motion_s;       /* motion-active seconds accumulated this slot */
    uint16_t accel_mean_mg;  /* mean net-accel magnitude this slot, milli-g */
    uint16_t accel_max_mg;   /* max net-accel magnitude this slot, milli-g */
    uint16_t skip_reason;    /* 0 = fix attempted; else TREC_SKIP_* */
};

enum trec_skip_e {
    TREC_SKIP_NONE = 0,
    TREC_SKIP_WINDOW_CLOSED = 1,
    TREC_SKIP_STATIONARY = 2,   /* motion gate: no motion since last fix */
    TREC_SKIP_IMU_DOWN = 3,     /* gate wanted but IMU unavailable (still fixes when gate off) */
};

struct trec_batt {
    uint8_t type;            /* TREC_BATT */
    uint8_t batt_pct;
    uint8_t reserved[2];
    uint32_t epoch;
    uint16_t batt_mv;
    int16_t rssi;            /* serving-cell RSSI at upload, or 0 */
    uint32_t cell_lac;
    uint32_t cell_id;
};

/* Queue API. Returns 0 on success, negative on error. */
int tstore_init(void);
int tstore_push_pos(const struct trec_pos *rec);
int tstore_push_batt(const struct trec_batt *rec);
int tstore_count(void);
/* Peek at the oldest record without removing it; len is set to bytes. */
int tstore_peek(void *buffer, int *len);
/* Drop the oldest count records (after server ACK). */
int tstore_drop_acked(int count);

/* Encode one record as a JSON line; returns bytes written (no NUL) or -1. */
int trec_to_json(const void *rec, char *out, int out_len);

#endif
