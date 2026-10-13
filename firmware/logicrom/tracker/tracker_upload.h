/* Twice-daily batched upload over GSM/GPRS.
 *
 * Between uploads the radio stays in flight mode (modem off the network).
 * At upload time: radio on, wait for GPRS attach, check serving-cell
 * coverage (RSSI threshold + known-good cell list, bounded deferral), open
 * one TCP session, send every queued record, delete what the server ACKs,
 * radio back off.
 *
 * Draft wire protocol (JSON lines over TCP, server side TBD):
 *   device:  {"hello":"<imei>","v":1,"q":<queued>,"bp":<pct>,"bmv":<mv>}\n
 *   server:  {"ok":1}\n
 *   device:  <record json>\n ... (oldest first)
 *   device:  {"bye":<sent>}\n
 *   server:  {"ack":<count>}\n
 * The device deletes the oldest <count> records. No ACK = nothing deleted.
 */
#ifndef TRACKER_UPLOAD_H
#define TRACKER_UPLOAD_H

/* Run one upload attempt. Returns number of records ACKed, 0 if deferred
 * (poor coverage, retry later), negative on hard failure. */
int tupl_run_once(void);

/* Coverage check: 1 = good enough to upload now, 0 = defer. */
int tupl_coverage_ok(void);

#endif
