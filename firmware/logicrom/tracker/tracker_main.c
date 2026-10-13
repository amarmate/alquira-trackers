/* Alquira livestock tracker (sheep/goat) — application skeleton.
 *
 * Policy loop:
 *   every 30 min (inside the GPS window): motion gate -> GPS fix -> record
 *   twice daily: radio on -> coverage check -> upload batch -> radio off
 *   between slots: deep sleep (task sleep while testing, console stays up)
 *
 * Time: wall clock comes from GPS UTC after the first valid fix, refreshed
 * from the network at each upload. Until the first sync, slots run on the
 * monotonic scheduler and records carry epoch 0. Deep-sleep clock retention
 * is still to be verified on hardware (TODO).
 *
 * Nothing here is hardware-validated: the app has never executed on a
 * tracker (license gate). Every SDK assumption is marked where it matters.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <console.h>
#include <lib.h>
#include <modem.h>
#include <os_api.h>
#include "tracker_config.h"
#include "tracker_store.h"
#include "tracker_motion.h"
#include "tracker_gps.h"
#include "tracker_upload.h"

static void log_line(const char *text)
{
    unsigned int length = (unsigned int)strlen(text);
    const char *data = text;
    while (length) {
        int count = write(STDOUT_FILENO, data, length);
        if (count <= 0)
            break;
        data += (unsigned int)count;
        length -= (unsigned int)count;
    }
}

#define LOGF(...) do { \
        char line[160]; \
        int size = snprintf(line, sizeof(line), __VA_ARGS__); \
        if (size > 0 && (unsigned int)size < sizeof(line)) \
            log_line(line); \
    } while (0)

static int window_open(unsigned int minute_of_day)
{
#if CFG_WIN_A_MIN == CFG_WIN_B_MIN
    /* A == B: window always open (current lax-testing configuration). */
    (void)minute_of_day;
    return 1;
#else
    /* Half-open interval [A,B) on a 1440-minute ring. */
    const unsigned int span = (CFG_WIN_B_MIN + 1440u - CFG_WIN_A_MIN) % 1440u;
    if (span == 0u)
        return 1;
    return (minute_of_day + 1440u - CFG_WIN_A_MIN) % 1440u < span;
#endif
}

static unsigned int now_minute(void)
{
    /* Minute-of-day UTC by arithmetic; avoids struct tm entirely. */
    time_t now = time(NULL);
    long day;
    if (now < 0)
        return 0u;
    day = (long)(now % 86400L);
    if (day < 0)
        day += 86400L;
    return (unsigned int)(day / 60L);
}

static void sleep_until_next_slot(void)
{
#if CFG_TEST_NO_SLEEP
    /* Bench testing: stay awake so USB/logs keep working. */
    unsigned int waited;
    for (waited = 0u; waited < CFG_FIX_INTERVAL_S; ++waited) {
        sleep(1);
        tmo_tick_1s();
    }
#else
    /* Field policy: deep sleep, wake on timeout. The 1 s motion sampler
     * cannot run while asleep; the IMU must latch motion-active across
     * sleep (TODO: verify wake sources and IMU retention on hardware). */
    sys_setsleep_timeout(CFG_FIX_INTERVAL_S * 1000u);
    sys_setsleep(SLEEP_TYPE_DEEP);
#endif
}

static void do_fix_slot(void)
{
    struct trec_pos rec;
    struct tmotion_slot motion;
    memset(&rec, 0, sizeof(rec));
    rec.type = TREC_POS;
    if (!window_open(now_minute())) {
        rec.fix = 'V';
        rec.skip_reason = TREC_SKIP_WINDOW_CLOSED;
        tstore_push_pos(&rec);
        LOGF("TRACKER slot skipped: window closed\r\n");
        return;
    }
    tmo_slot_snapshot(&motion);
    rec.motion_s = motion.active_s;
    rec.accel_mean_mg = motion.mean_mg;
    rec.accel_max_mg = motion.max_mg;
    if (!tmo_should_fix()) {
        rec.fix = 'V';
        rec.skip_reason = TREC_SKIP_STATIONARY;
        tstore_push_pos(&rec);
        LOGF("TRACKER slot skipped: stationary mot=%us\r\n", motion.active_s);
        tmo_slot_begin();
        return;
    }
    if (tgps_fix_once(&rec) == 0) {
        rec.motion_s = motion.active_s;
        rec.accel_mean_mg = motion.mean_mg;
        rec.accel_max_mg = motion.max_mg;
        LOGF("TRACKER fix lat=%ld lng=%ld sat=%u bp=%u mot=%us\r\n",
             (long)rec.lat_e7, (long)rec.lng_e7, rec.sats, rec.batt_pct,
             motion.active_s);
    } else {
        rec.motion_s = motion.active_s;
        rec.accel_mean_mg = motion.mean_mg;
        rec.accel_max_mg = motion.max_mg;
        LOGF("TRACKER fix MISS bp=%u mot=%us\r\n", rec.batt_pct, motion.active_s);
    }
    tstore_push_pos(&rec);
    tmo_slot_begin();
}

static int upload_due(unsigned int minute_of_day, unsigned int *last_done)
{
    unsigned int due = (minute_of_day >= CFG_UPLOAD_1_MIN && *last_done < CFG_UPLOAD_1_MIN)
        || (minute_of_day >= CFG_UPLOAD_2_MIN && *last_done < CFG_UPLOAD_2_MIN);
    if (due)
        *last_done = minute_of_day;
    return (int)due;
}

static void do_upload(void)
{
    struct trec_batt batt;
    struct md_cellinfo_t cell;
    int acked;
    memset(&batt, 0, sizeof(batt));
    batt.type = TREC_BATT;
    acked = tupl_run_once();
    if (acked > 0) {
        uint32_t pct, mv;
        LOGF("TRACKER upload acked=%d queued=%d\r\n", acked, tstore_count());
        if (md_getbatt_status(&pct, &mv) == 0) {
            batt.batt_pct = (uint8_t)(pct > 100u ? 100u : pct);
            batt.batt_mv = (uint16_t)(mv > 0xffffu ? 0xffffu : mv);
        }
        batt.epoch = (uint32_t)time(NULL);
        if (md_get_cellinfo(&cell) == 0) {
            batt.rssi = (int16_t)cell.cell.signal;
            batt.cell_lac = cell.cell.lac;
            batt.cell_id = cell.cell.cellid;
        }
        tstore_push_batt(&batt);
    } else if (acked == 0) {
        LOGF("TRACKER upload deferred: poor coverage\r\n");
    } else {
        LOGF("TRACKER upload FAILED queued=%d\r\n", tstore_count());
    }
}

static void urc(unsigned int code, unsigned int value)
{
    (void)code;
    (void)value;
}

static int reboot_reason(int reason)
{
    LOGF("TRACKER reboot_reason=%d allow=1\r\n", reason);
    return 1; /* record the reason; never suppress resets in testing */
}

int main(int argc, char **argv)
{
    unsigned int last_upload_min = 0u;
    (void)argc;
    (void)argv;
    logicrom_init("/dev/ttyUSB0", urc);
    system_set_reboot_callback(reboot_reason);
    cli_init(NULL);
    LOGF("TRACKER start sdk=%s store=%d gps=%d motion=%d\r\n",
         get_logicrom_version(), tstore_init(), tgps_init(), tmo_init());
    /* Radio off until the first scheduled upload. */
    md_set_flightmode(1);
    tmo_slot_begin();
    for (;;) {
        unsigned int minute = now_minute();
        if (upload_due(minute, &last_upload_min))
            do_upload();
        do_fix_slot();
        sleep_until_next_slot();
    }
}
