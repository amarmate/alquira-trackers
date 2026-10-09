"""Configure a ReachFar V24 through its native USB command parser.

Recovered and verified on R36S_RFHZ_V34_V1.0_2024.09.28_16.06.24.
Normal USB mode 1782:3d00, interface 1, bulk OUT 02 / IN 82.
Commands are ASCII: AT:<command># followed by CR, in one USB transfer.
Uses firmware settings handlers, never raw memory/flash writes.
"""
import argparse
import ipaddress
import os
from pathlib import Path
import re
import sys
import time

import usb.backend.libusb1
import usb.core
import usb.util

from rda_dump import LIBUSB


def build_command(args):
    if args.command == 'status':
        content = 'ts'
    elif args.command == 'get-apn':
        content = 'getapn'
    elif args.command == 'reboot':
        content = 'reset'
    elif args.command == 'gpio-test':
        # gpiotest makes the pin an output and writes the level once (sms_gpiotest_handle,
        # 0x881b030c). The firmware accepts pins 0-32; only the three LED pins are let
        # through, because forcing a pin that another chip drives could damage it.
        if args.pin not in (4, 27, 28):
            raise ValueError('--pin must be an LED pin: 4, 27 or 28')
        if args.level not in (0, 1):
            raise ValueError('--level must be 0 or 1')
        content = f'gpiotest,{args.pin},{args.level}'
    elif args.command == 'leds-off':
        # rfhzledtest,<n> calls rfhz_led_status(n) (0x8819c714). 100 is outside its table,
        # so it takes the default branch: both blink timers stopped, both LEDs off. The
        # timers otherwise rewrite GPIO 4 and 27 at every step and undo a gpio-test.
        # The LEDs stay off until the firmware next changes its LED state.
        content = 'rfhzledtest,100'
    elif args.command == 'buzzer-alarm':
        # hon,<mode> stops any buzzer alarm in progress and saves the "buzzer alarm mode"
        # (set_hon_flag, an NVRAM write; handler 0x881b0804). Mode 3 also sounds the buzzer
        # at once, for up to 120 s. The log prints the mode it replaces as
        # "set_hon_flag---before-hon_flag=<n>.": send that mode afterwards to put it back.
        if args.mode not in (0, 1, 2, 3):
            raise ValueError('--mode must be 0, 1, 2 or 3')
        content = f'hon,{args.mode}'
    elif args.command == 'set-apn':
        # set_APN_data uses strcpy into a 32-byte APN field (0x82200b50..b6f).
        if not args.apn or not re.fullmatch(r'[A-Za-z0-9.-]{1,31}', args.apn):
            raise ValueError('APN must be 1–31 letters, digits, dots, or hyphens')
        if not args.plmn or not re.fullmatch(r'[0-9]{5,6}', args.plmn):
            raise ValueError('PLMN must be the SIM home network’s 5 or 6 digits')
        content = f'apn,{args.apn},,,{args.plmn}'
    elif args.command == 'set-server':
        if not args.host:
            raise ValueError('--host is required')
        try:
            ipaddress.IPv4Address(args.host)
        except ipaddress.AddressValueError:
            if not re.fullmatch(r'(?=.{1,63}$)[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*', args.host):
                raise ValueError('Host must be an IPv4 address or a short DNS name')
        if args.port is None or not 1 <= args.port <= 65535:
            raise ValueError('--port must be 1–65535')
        content = f'ip,{args.host},{args.port}'
    else:
        raise ValueError('Unsupported command')
    frame = f'AT:{content}#\r'.encode('ascii')
    # The vendor callback copies into a 200-byte event buffer without bounds checks.
    if len(frame) > 190:
        raise ValueError('Command is too long for this firmware')
    return frame


def acknowledged(args, reply):
    expected = {
        'status': b'AT RETURN:ts',
        'get-apn': b'AT RETURN:getapn.',
        'reboot': b'AT RETURN:reset.',
        # Seen from unit 1403167417 on 2026-10-08 as "AT RETURN:gpiotest.".
        'gpio-test': b'AT RETURN:gpiotest',
        'leds-off': b'rfhz_led_status---case=default.',
        'buzzer-alarm': b'AT RETURN:hon.',
        'set-apn': b'AT RETURN:apn.',
        'set-server': b'AT RETURN:ip.',
    }[args.command]
    if expected not in reply:
        return False
    if args.command == 'buzzer-alarm':
        return f'set_hon_flag---after-hon_flag={args.mode}.'.encode() in reply
    if args.command == 'set-apn':
        return f'set_APN_data.p_APN_name:{args.apn}.p_UserName:.p_PassWd:.P_UserData:{args.plmn}.'.encode() in reply
    if args.command == 'set-server':
        return f'set_url_port.url:{args.host};port:{args.port}.'.encode() in reply
    return True


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['status', 'get-apn', 'set-apn', 'set-server', 'reboot', 'gpio-test', 'leds-off',
                                             'buzzer-alarm'])
    p.add_argument('--pin', type=int)
    p.add_argument('--mode', type=int)
    p.add_argument('--level', type=int)
    p.add_argument('--apn')
    p.add_argument('--plmn')
    p.add_argument('--host')
    p.add_argument('--port', type=int)
    p.add_argument('--seconds', type=float, default=12)
    p.add_argument('--output', required=True, help='New raw log file (contains device identifiers)')
    a = p.parse_args()
    if not 2 <= a.seconds <= 60:
        p.error('--seconds must be 2–60')
    try:
        frame = build_command(a)
    except ValueError as e:
        p.error(str(e))
    backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
    ds = list(usb.core.find(find_all=True, idVendor=0x1782, idProduct=0x3d00, backend=backend))
    if len(ds) != 1:
        p.error(f'Expected one 1782:3d00 tracker; found {len(ds)}. Reconnect its USB cable.')
    d = ds[0]
    reply = bytearray()
    disconnected = False
    try:
        cfg = d.get_active_configuration()
        intf = cfg[(1, 0)]
        if {ep.bEndpointAddress for ep in intf} != {0x02, 0x82}:
            p.error('Unexpected interface layout; refusing to send')
        with Path(a.output).open('xb') as out:
            # Bounded drain prevents an old AT RETURN from being mistaken for our reply.
            until = time.monotonic() + 1
            while time.monotonic() < until:
                try:
                    d.read(0x82, 4096, timeout=100)
                except usb.core.USBTimeoutError:
                    break
            print('TX', repr(frame), flush=True)
            sent = d.write(0x02, frame, timeout=1000)
            if sent != len(frame):
                raise IOError(f'Partial write ({sent}/{len(frame)}); not retrying')
            until = time.monotonic() + a.seconds
            while time.monotonic() < until:
                try:
                    chunk = bytes(d.read(0x82, 4096, timeout=250))
                except usb.core.USBTimeoutError:
                    continue
                except usb.core.USBError as e:
                    disconnected = True
                    print(f'USB disconnected or failed after sending: {e}', file=sys.stderr)
                    break
                reply.extend(chunk)
                out.write(chunk)
                out.flush()
                sys.stdout.write(chunk.decode('ascii', 'replace').replace('\x00', ''))
                sys.stdout.flush()
    finally:
        if not disconnected:
            usb.util.dispose_resources(d)
    # Fail explicitly when the firmware did not acknowledge the requested operation.
    ok = acknowledged(a, reply)
    if ok:
        print('\nMatching firmware acknowledgement received.', flush=True)
        if a.command in ('set-apn', 'set-server'):
            print('Query settings after restart to verify persistence.', flush=True)
    else:
        print('\nNo matching acknowledgement. Inspect the saved log and query settings; do not blindly retry.', file=sys.stderr)
    if disconnected:
        # libusb on macOS can hang indefinitely releasing an interface after a
        # firmware reboot. All evidence files are closed above; let the OS close
        # the vanished device's handles instead of running libusb finalizers.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0 if ok else 1)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
