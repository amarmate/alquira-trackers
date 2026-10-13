#include <stddef.h>
#include <stdint.h> /* imu_sensor.h uses int32_t without including this */
#include <hw/imu_sensor.h>
#include "tracker_config.h"
#include "tracker_motion.h"

/* TODO: identify the V24 accelerometer (I2C on GPIO 6/7) and implement
 * init/read/read_raw/get_offset/set_offset/calib_status over hw/i2c.h.
 * Until then imu_add_sensor() is never called and tmo_ready() stays false. */

static int ready;
static unsigned int slot_active_s;
static unsigned int slot_samples;
static unsigned long slot_accel_sum_mg;
static unsigned int slot_accel_max_mg;

static void motion_event(int event)
{
    (void)event;
    /* The IMU library owns debouncing; the sampler below polls
     * imu_is_motionactive() once per second for the slot count. */
}

int tmo_init(void)
{
    struct imuconf_t config;
    if (imu_initconfig(&config) != 0)
        return -1;
    /* Livestock tuning: goats at rest still shift and ruminate; require a
     * clearly ambulatory threshold before calling it motion. Validate on
     * collar data in phase 1. */
    config.motion_detect_threshold = 0.12f;
    config.sample_ms = 20;
    if (imu_lib_init(&config, motion_event) != 0)
        return -1;
    /* No sensor registered yet (see TODO above): library present, no data. */
    ready = imu_is_ready();
    return 0;
}

int tmo_ready(void)
{
    return ready && imu_is_ready();
}

/* Called once per second from the scheduler while awake. Accumulates the
 * slot statistics. Cheap: two library getters. */
void tmo_tick_1s(void)
{
    float force;
    if (!tmo_ready())
        return;
    if (imu_is_motionactive())
        ++slot_active_s;
    if (imu_get_netaccel(&force) == 0) {
        unsigned int mg = (unsigned int)(force * 1000.0f);
        slot_accel_sum_mg += mg;
        ++slot_samples;
        if (mg > slot_accel_max_mg)
            slot_accel_max_mg = mg;
    }
}

void tmo_slot_begin(void)
{
    slot_active_s = 0u;
    slot_samples = 0u;
    slot_accel_sum_mg = 0u;
    slot_accel_max_mg = 0u;
}

void tmo_slot_snapshot(struct tmotion_slot *slot)
{
    if (slot == NULL)
        return;
    slot->active_s = (uint16_t)(slot_active_s > 0xffffu ? 0xffffu : slot_active_s);
    slot->mean_mg = (uint16_t)(slot_samples ? slot_accel_sum_mg / slot_samples : 0u);
    slot->max_mg = (uint16_t)(slot_accel_max_mg > 0xffffu ? 0xffffu : slot_accel_max_mg);
}

int tmo_should_fix(void)
{
    if (!CFG_REQUIRE_MOTION)
        return 1;              /* lax testing: always fix */
    if (!tmo_ready())
        return 1;              /* fail open until the IMU driver exists */
    return slot_active_s >= CFG_MOTION_MIN_ACTIVE_S;
}
