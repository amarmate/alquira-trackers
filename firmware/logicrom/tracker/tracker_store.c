#include <stdio.h>
#include <string.h>
#include <storage.h>
#include "tracker_config.h"
#include "tracker_store.h"

int tstore_init(void)
{
    struct storagecfg_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.media = STORAGE_MEDIA_FS; /* internal flash */
    cfg.parts = 1u;
    cfg.mode = STORAGE_MODE_FIFO;
    cfg.on_full = STORAGE_ONFULL_STOP; /* never silently drop data */
    cfg.max_storage = CFG_STORE_MAX_PACKETS;
    cfg.packet_sz = sizeof(struct trec_pos);
    cfg.reserved_mem = 16u * 1024u;
    return storage_init(&cfg);
}

int tstore_push_pos(const struct trec_pos *rec)
{
    return storage_save(CFG_STORE_PART, rec, (int)sizeof(*rec));
}

int tstore_push_batt(const struct trec_batt *rec)
{
    return storage_save(CFG_STORE_PART, rec, (int)sizeof(*rec));
}

int tstore_count(void)
{
    return storage_getcount(CFG_STORE_PART);
}

int tstore_peek(void *buffer, int *len)
{
    return storage_read_indexed(CFG_STORE_PART, 0, buffer, len);
}

int tstore_drop_acked(int count)
{
    return storage_delete(CFG_STORE_PART, count);
}

int trec_to_json(const void *rec, char *out, int out_len)
{
    const uint8_t type = *(const uint8_t *)rec;
    int written;
    if (type == TREC_POS) {
        const struct trec_pos *p = (const struct trec_pos *)rec;
        written = snprintf(out, (unsigned int)out_len,
                           "{\"v\":%u,\"t\":\"pos\",\"e\":%lu,\"f\":\"%c\",\"lat\":%ld,\"lng\":%ld,"
                           "\"spd\":%d,\"sat\":%u,\"hdop\":%u,\"bp\":%u,\"bmv\":%u,"
                           "\"mot\":%u,\"am\":%u,\"ax\":%u,\"sk\":%u}",
                           TREC_VERSION, (unsigned long)p->epoch, p->fix,
                           (long)p->lat_e7, (long)p->lng_e7, p->speed_dms,
                           p->sats, p->hdop_c, p->batt_pct, p->batt_mv,
                           p->motion_s, p->accel_mean_mg, p->accel_max_mg,
                           p->skip_reason);
    } else if (type == TREC_BATT) {
        const struct trec_batt *b = (const struct trec_batt *)rec;
        written = snprintf(out, (unsigned int)out_len,
                           "{\"v\":%u,\"t\":\"batt\",\"e\":%lu,\"bp\":%u,\"bmv\":%u,"
                           "\"rssi\":%d,\"lac\":%lu,\"cid\":%lu}",
                           TREC_VERSION, (unsigned long)b->epoch,
                           b->batt_pct, b->batt_mv, b->rssi,
                           (unsigned long)b->cell_lac, (unsigned long)b->cell_id);
    } else {
        return -1;
    }
    if (written < 0 || written >= out_len)
        return -1;
    return written;
}
