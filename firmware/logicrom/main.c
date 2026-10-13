/* V24 diagnostic probe. No activation bypass, reset suppression, or flash writes. */
#include <errno.h>
#include <stdio.h>
#include <unistd.h>
#include <console.h>
#include <lib.h>
#include <ril.h>
#include "v24_diag.h"

static void message(const char *data, unsigned int length)
{
    while (length) {
        int count = write(STDOUT_FILENO, data, length);
        if (count < 0 && errno == EINTR)
            continue;
        if (count <= 0)
            break;
        data += count;
        length -= (unsigned int)count;
    }
}

static int reboot_reason(int reason)
{
    char line[64];
    int size = snprintf(line, sizeof(line), "V24-DIAG reboot_reason=%d allow=1\r\n", reason);
    if (size > 0 && (unsigned int)size < sizeof(line))
        message(line, (unsigned int)size);
    return 1; /* Preserve the requested reset. */
}

static void urc(unsigned int code, unsigned int value)
{
    char line[80];
    int size;
    switch (code) {
    case URC_SYS_INIT_STATE_IND:
    case URC_SIM_CARD_STATE_IND:
    case URC_GSM_NW_STATE_IND:
    case URC_GPRS_NW_STATE_IND:
    case URC_CFUN_STATE_IND:
    case URC_MODULE_VOLTAGE_IND:
        size = snprintf(line, sizeof(line), "V24-DIAG event=%u value=%u\r\n", code, value);
        if (size > 0 && (unsigned int)size < sizeof(line))
            message(line, (unsigned int)size);
        break;
    default:
        break;
    }
}

int main(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    v24_entry_marker(0); /* Blue: main() entered, before any SDK initialization. */
    logicrom_init("/dev/ttyUSB0", urc);
    v24_entry_marker(1); /* Red: logicrom_init() returned. */
    {
        static const char entry[] = "V24-DIAG init-returned direct-write\r\n";
        char line[128];
        int callback_rc, console_rc, size;
        message(entry, sizeof(entry) - 1u);
        callback_rc = system_set_reboot_callback(reboot_reason);
        console_rc = cli_init(NULL);
        size = snprintf(line, sizeof(line), "V24-DIAG ready sdk=%s cli=%d reboot_callback=%d\r\n",
                        get_logicrom_version(), console_rc, callback_rc);
        if (size > 0 && (unsigned int)size < sizeof(line))
            message(line, (unsigned int)size);
    }
    for (unsigned int tick = 0; ; ++tick) {
        char line[64];
        int size = snprintf(line, sizeof(line), "V24-DIAG alive=%u\r\n", tick);
        if (size > 0 && (unsigned int)size < sizeof(line))
            message(line, (unsigned int)size);
        sleep(10);
    }
}
