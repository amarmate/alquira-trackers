#include <string.h>
#include <unistd.h>
#include <gpslib.h>
#include <modem.h>
#include <hw/gpio.h>
#include "tracker_config.h"
#include "tracker_gps.h"

static int lib_ready;
static int pwr_handle = -1;

static void gps_event(int event)
{
    (void)event; /* slot logic polls gps_getdata(); events unused for now */
}

int tgps_init(void)
{
    struct gpsconfig_t config;
    if (lib_ready)
        return 0;
    /* TODO: select the V24 GPS chip driver (gps_set_driver_*) once the chip
     * is identified from vendor firmware strings or NMEA `$` talker IDs.
     * NMEA parsing works without it; power/reset lines may not. */
    memset(&config, 0, sizeof(config));
    config.baud = CFG_GPS_BAUD;
    config.gps_event_cb = gps_event;
    if (gpslib_init(CFG_GPS_PORT, &config) != 0)
        return -1;
    if (gps_motionassist_config(GPS_MOTIONASSIST_TYPE_MOTIONSENSE) != 0)
        return -1;
    pwr_handle = gpio_request(CFG_GPS_PWR_GPIO, GPIO_FLAG_DEFLOW);
    if (pwr_handle < 0)
        return -1;
    lib_ready = 1;
    return 0;
}

int tgps_power(int on)
{
    if (!lib_ready || pwr_handle < 0)
        return -1;
    return gpio_write(pwr_handle, on ? 1 : 0);
}

static void sample_battery(struct trec_pos *rec)
{
    uint32_t pct, mv;
    if (md_getbatt_status(&pct, &mv) == 0) {
        rec->batt_pct = (uint8_t)(pct > 100u ? 100u : pct);
        rec->batt_mv = (uint16_t)(mv > 0xffffu ? 0xffffu : mv);
    } else {
        rec->batt_pct = 255u;
        rec->batt_mv = 0u;
    }
}

int tgps_fix_once(struct trec_pos *rec)
{
    struct gpsdata_t gps;
    unsigned int waited;
    if (rec == NULL || !lib_ready)
        return -1;
    memset(rec, 0, sizeof(*rec));
    rec->type = TREC_POS;
    rec->fix = 'V';
    if (tgps_power(1) != 0)
        return -1;
    for (waited = 0u; waited < CFG_FIX_TIMEOUT_S; ++waited) {
        sleep(1);
        if (gps_getstatus() == 0)
            continue;
        memset(&gps, 0, sizeof(gps));
        gps_getdata(&gps);
        if (gps.fix == 'A') {
            rec->fix = 'A';
            rec->lat_e7 = (int32_t)(gps.lat * 10000000.0);
            rec->lng_e7 = (int32_t)(gps.lng * 10000000.0);
            rec->speed_dms = (int16_t)(gps.speedkmph * (10.0f / 3.6f)); /* km/h -> dm/s */
            rec->sats = (uint8_t)(gps.satinview < 0 ? 0 : gps.satinview);
            rec->hdop_c = (uint16_t)(gps.hdop * 100.0f);
            rec->epoch = (uint32_t)gpsmktime(gps.date, gps.time);
            break;
        }
    }
    sample_battery(rec);
    tgps_power(0);
    return rec->fix == 'A' ? 0 : -1;
}
