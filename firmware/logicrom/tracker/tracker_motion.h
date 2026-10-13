/* Motion gating and per-slot activity stats (the livestock "steps" proxy).
 *
 * The SDK has no pedometer: true step counting on a goat collar is a phase-2
 * algorithm (peak detection on the accel stream, validated against observed
 * gait). Phase 1 records what the IMU library gives for free:
 * motion-active seconds plus net-acceleration mean/max per slot. Grazing,
 * walking and resting separate cleanly on those signals.
 *
 * Until the V24 accelerometer chip is identified and its I2C driver written,
 * the gate fails OPEN: tmo_should_fix() returns 1 and activity reads zero.
 */
#ifndef TRACKER_MOTION_H
#define TRACKER_MOTION_H

#include <stdint.h>

struct tmotion_slot {
    uint16_t active_s;     /* seconds the IMU reported motion-active */
    uint16_t mean_mg;      /* mean net-accel magnitude, milli-g */
    uint16_t max_mg;       /* max net-accel magnitude, milli-g */
};

/* Start the IMU (motion events + 20 ms sampling). 0 on success. */
int tmo_init(void);

/* True when the IMU is actually producing data. */
int tmo_ready(void);

/* Called once per second from the scheduler while awake. */
void tmo_tick_1s(void);

/* Begin a new 30-minute accumulation slot. */
void tmo_slot_begin(void);

/* Snapshot the current slot's accumulation (call at fix time). */
void tmo_slot_snapshot(struct tmotion_slot *slot);

/* Motion-gate decision: 1 = take the fix, 0 = skip as stationary. */
int tmo_should_fix(void);

#endif
