/* V24 first-boot probe: USB output and modem state only. No board GPIO/UART setup. */
#include <stdio.h>
#include <unistd.h>
#include <lib.h>
#include <ril.h>

static void urc(unsigned int code, unsigned int value)
{
    switch (code) {
    case URC_SYS_INIT_STATE_IND:
    case URC_SIM_CARD_STATE_IND:
    case URC_GSM_NW_STATE_IND:
    case URC_GPRS_NW_STATE_IND:
    case URC_CFUN_STATE_IND:
    case URC_MODULE_VOLTAGE_IND:
        printf("V24-PROBE event=%u value=%u\r\n", code, value);
        break;
    default:
        break;
    }
}

int main(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    logicrom_init("/dev/ttyUSB0", urc);
    printf("V24-PROBE 1 ready sdk=%s\r\n", get_logicrom_version());
    for (unsigned int tick = 0; ; ++tick) {
        printf("V24-PROBE alive=%u\r\n", tick);
        sleep(10);
    }
}
