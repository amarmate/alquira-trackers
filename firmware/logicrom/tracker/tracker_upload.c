#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <modem.h>
#include <net/sockets.h>
#include "tracker_config.h"
#include "tracker_store.h"
#include "tracker_upload.h"

#define LINE_MAX 256

/* Known-good cells, filled from field measurements (LAC, cell ID).
 * Empty while CFG_GOOD_CELL_COUNT is 0: RSSI threshold only. */
static const uint32_t good_cells[][2] = {
    {0u, 0u}, /* placeholder; loop is bounded by CFG_GOOD_CELL_COUNT */
};

int tupl_coverage_ok(void)
{
    struct md_cellinfo_t info;
    if (md_get_cellinfo(&info) != 0)
        return 0;
    if (info.cell.signal < CFG_UPLOAD_MIN_RSSI)
        return 0;
#if CFG_GOOD_CELL_COUNT == 0
    return 1; /* no good-cell list yet: RSSI threshold only */
#else
    {
        unsigned int i;
        for (i = 0u; i < CFG_GOOD_CELL_COUNT && i < sizeof(good_cells) / sizeof(good_cells[0]); ++i) {
            if (info.cell.lac == good_cells[i][0] && info.cell.cellid == good_cells[i][1])
                return 1;
        }
        return 0;
    }
#endif
}

static int wait_gprs(unsigned int timeout_s)
{
    unsigned int waited;
    for (waited = 0u; waited < timeout_s; ++waited) {
        /* TODO: replace with the SDK's GPRS-state poll once identified
         * (network.h status API); for the skeleton, pace attach attempts
         * with the socket layer reporting readiness on open/send. */
        sleep(5);
        if (waited >= 10u)
            return 0;    /* assume attached; socket errors still handled below */
    }
    return -1;
}

static int send_line(int sock, const char *line, int len)
{
    return socket_send(sock, line, len, (int)CFG_UPLOAD_TIMEOUT_S, NULL);
}

/* TODO: the socket API is callback-driven for receive (recv_callback via
 * socket_setcallback). This skeleton polls a small response window instead;
 * wire the real callback before hardware trials. Returns ACKed count or -1. */
static int await_ack(int sock, int sent)
{
    (void)sock;
    (void)sent;
    return -1;
}

int tupl_run_once(void)
{
    char line[LINE_MAX];
    char imei[32];
    uint32_t pct = 255u, mv = 0u;
    int sock, queued, sent = 0, acked, rc;
    if (md_set_flightmode(0) != 0)
        return -1;
    if (wait_gprs(CFG_GPRS_ATTACH_TIMEOUT_S) != 0) {
        md_set_flightmode(1);
        return -1;
    }
    if (!tupl_coverage_ok()) {
        md_set_flightmode(1);
        return 0;                /* deferred, not failed */
    }
    md_getbatt_status(&pct, &mv);
    sock = socket_request(SOCK_TYPE_TCP);
    if (sock < 0) {
        md_set_flightmode(1);
        return -1;
    }
    socket_setserverip(sock, CFG_SERVER_IP);
    socket_setserverport(sock, CFG_SERVER_PORT);
    if (socket_open(sock) != 0) {
        socket_free(sock);
        md_set_flightmode(1);
        return -1;
    }
    queued = tstore_count();
    if (queued < 0)
        queued = 0;
    rc = snprintf(line, sizeof(line), "{\"hello\":\"%s\",\"v\":%u,\"q\":%d,\"bp\":%lu,\"bmv\":%lu}\n",
                  md_get_imei(imei, (int)sizeof(imei)), TREC_VERSION,
                  queued, (unsigned long)pct, (unsigned long)mv);
    if (rc <= 0 || rc >= (int)sizeof(line) || send_line(sock, line, rc) != 0) {
        socket_close(sock);
        socket_free(sock);
        md_set_flightmode(1);
        return -1;
    }
    for (;;) {
        uint8_t peek[sizeof(struct trec_pos)];
        int len = (int)sizeof(peek), json_len;
        if (tstore_peek(peek, &len) != 0)
            break;
        json_len = trec_to_json(peek, line, (int)sizeof(line) - 1);
        if (json_len < 0)
            break;               /* corrupt head record: stop, keep for inspection */
        line[json_len] = '\n';
        if (send_line(sock, line, json_len + 1) != 0)
            break;
        ++sent;
        if (sent >= queued)
            break;
    }
    rc = snprintf(line, sizeof(line), "{\"bye\":%d}\n", sent);
    if (rc > 0 && rc < (int)sizeof(line))
        send_line(sock, line, rc);
    acked = await_ack(sock, sent);
    socket_close(sock);
    socket_free(sock);
    md_set_flightmode(1);
    if (acked <= 0)
        return -1;               /* nothing ACKed: keep everything queued */
    if (acked > sent)
        acked = sent;
    tstore_drop_acked(acked);
    return acked;
}
