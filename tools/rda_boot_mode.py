"""Read Reset_Cause once through the vendor RDA USB monitor; never write memory.

Default: print the request without opening USB. Use --read --output <new log>
for one live attempt. No restart, register write, or flash command is available.
SDK references and address mapping: docs/v24-flash-restore-spec.md.
"""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import struct
import sys
import time

import usb.backend.libusb1
import usb.core
import usb.util

from rda_dump import LIBUSB, xor

ADDRESS = 0x01A000A0
RID = 3
# access=WORD (2), internal=0, rw=READ (0). Length excludes flow ID,
# includes trailing CRC; unlike rdatool's block request, no size bytes.
PAYLOAD = bytes([0xFF, 0x02]) + struct.pack('<I', ADDRESS) + bytes([RID])
FRAME = b'\xad' + struct.pack('>H', len(PAYLOAD)) + PAYLOAD + bytes([xor(PAYLOAD)])
KEEP = []  # Keep libusb objects alive until os._exit; teardown hangs on this Mac.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    print(f'Reset_Cause physical=0x{ADDRESS:08x}; uncached=0xa1a000a0')
    print(f'Request (one 4-byte read): {FRAME.hex(" ")}', flush=True)
    if not args.read:
        return
    if args.output is None:
        parser.error('--read requires --output')
    with args.output.open('x') as log:
        def record(message):
            print(message, flush=True)
            log.write(message + '\n')
            log.flush()

        record(datetime.now(timezone.utc).isoformat())
        try:
            backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
            devices = [d for d in usb.core.find(find_all=True, backend=backend)
                       if (d.idVendor, d.idProduct) in ((0x1E04, 0x0900), (0x1782, 0x3D00))]
            KEEP.extend(devices)
            record('Trackers: ' + ', '.join(f'{d.idVendor:04x}:{d.idProduct:04x}' for d in devices))
            if len(devices) != 1 or devices[0].idVendor != 0x1E04:
                raise RuntimeError('Expected exactly one tracker, in 1e04:0900 mode')
            dev = devices[0]
            cfg = dev.get_active_configuration()
            interface = cfg[(0, 0)]
            if (interface.bInterfaceClass, interface.bInterfaceSubClass,
                    interface.bInterfaceProtocol) != (0xFF, 0x66, 0x66):
                raise RuntimeError('Unexpected USB interface')
            if usb.util.get_string(dev, interface.iInterface) != 'RDA Usb':
                raise RuntimeError('Expected vendor RDA Usb interface')
            usb.util.claim_interface(dev, 0)
            # Refuse queued data instead of issuing a read into a busy stream.
            try:
                stale = dev.read(0x81, 4096, timeout=100)
            except usb.core.USBTimeoutError:
                stale = b''
            if stale:
                raise RuntimeError('USB stream already contains data; no request sent')
            record(f'USB 1e04:0900 bus={dev.bus} address={dev.address}')
            record(f'TX {FRAME.hex(" ")}')
            if dev.write(0x01, FRAME, timeout=1000) != len(FRAME):
                raise IOError('Short USB transfer; request will not be retried')
            reply = bytearray()
            deadline = time.monotonic() + 3
            while len(reply) < 10 and time.monotonic() < deadline:
                try:
                    reply.extend(dev.read(0x81, 4096, timeout=300))
                except usb.core.USBTimeoutError:
                    pass
            record(f'RX {reply.hex(" ")}')
            if len(reply) != 10 or reply[:5] != bytes([0xAD, 0, 6, 0xFF, RID]):
                raise IOError('Unexpected reply length/header; no retry')
            if xor(reply[3:-1]) != reply[-1]:
                raise IOError('Reply checksum mismatch; no retry')
            value = struct.unpack('<I', reply[5:9])[0]
            boot = (value >> 16) & 0x3F
            record(f'Reset_Cause=0x{value:08x}')
            record(f'BOOT_MODE=0x{boot:02x}; SW_BOOT_MODE=0x{(value >> 22) & 0x3F:02x}')
            record(f'USB_MONITOR_DISABLE={int(bool(boot & 8))}')
        except Exception as exc:
            record(f'ERROR {type(exc).__name__}: {exc}')
            raise


if __name__ == '__main__':
    status = 0
    try:
        main()
    except SystemExit as exc:
        status = exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        status = 1
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(status)
