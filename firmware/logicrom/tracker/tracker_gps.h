/* Scheduled GPS fix: power the receiver, wait for a fix with a timeout,
 * fill one position record, power the receiver off.
 *
 * V24 wiring: GPS power is GPIO 32 (high = on); GPS UART is GPIO 0/1 at
 * 9600 baud. The LogicROM serial device name is still to be verified.
 */
#ifndef TRACKER_GPS_H
#define TRACKER_GPS_H

#include "tracker_store.h"

/* One-time library init (idempotent). 0 on success. */
int tgps_init(void);

/* Power the GPS on (1) or off (0). 0 on success. */
int tgps_power(int on);

/* Attempt one fix, blocking up to the configured timeout. Always fills rec:
 * fix='A' with coordinates on success, fix='V' with the last known/zero
 * coordinates on timeout. Returns 0 if a valid fix was obtained. */
int tgps_fix_once(struct trec_pos *rec);

#endif
