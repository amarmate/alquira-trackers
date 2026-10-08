"""Read the vendor's cached flash ID with one fixed four-byte RAM request.

Default is an offline plan. --read requires a new log under firmware/live/.
No reset, configuration change, programmer launch, SPI command, or memory write.
This layout is from vendor FUN_820004e4, not the SDK programmer's gSpiFlashCtx.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import struct
import sys
import time

ADDRESS = 0x81C01F50
REQUEST = bytes.fromhex('ad 00 07 ff 02 50 1f c0 81 03 f0')
KEEP = []


def decode(reply):
    if len(reply) != 10 or reply[:5] != bytes.fromhex('ad 00 06 ff 03'):
        raise ValueError('Invalid response length/header; no retry')
    checksum = 0
    for byte in reply[3:-1]:
        checksum ^= byte
    if checksum != reply[-1]:
        raise ValueError('Invalid response checksum; no retry')
    data = reply[5:9]
    manufacturer, memory_type, capacity = data[1:4]
    return {
        'raw_bytes': data.hex(' '),
        'word_le': f'0x{struct.unpack("<I", data)[0]:08x}',
        'checkirq_byte': data[0],
        'manufacturer': f'0x{manufacturer:02x}',
        'memory_type': f'0x{memory_type:02x}',
        'capacity_code': f'0x{capacity:02x}',
        'jedec_bytes': data[1:4].hex(' '),
        'writer_id_le': f'0x{manufacturer | memory_type << 8 | capacity << 16:06x}',
        'capacity_matches_4_mib': capacity == 0x16,
        'source': 'vendor boot-cached RAM; not a fresh SPI transaction',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    print(f'One 4-byte RAM read at 0x{ADDRESS:08x}: {REQUEST.hex(" ")}', flush=True)
    if not args.read:
        return
    live = Path(__file__).resolve().parents[1] / 'firmware/live'
    if args.output is None or not args.output.resolve().is_relative_to(live):
        parser.error('--read requires a new --output inside firmware/live/')
    with args.output.open('x') as log:
        def record(**data):
            data['utc'] = datetime.now(timezone.utc).isoformat()
            line = json.dumps(data, sort_keys=True)
            log.write(line + '\n')
            log.flush()
            os.fsync(log.fileno())
            print(line, flush=True)

        try:
            import usb.backend.libusb1
            import usb.core
            import usb.util
            from rda_dump import LIBUSB

            backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
            if backend is None:
                raise RuntimeError('libusb backend unavailable')
            devices = [d for d in usb.core.find(find_all=True, backend=backend)
                       if (d.idVendor, d.idProduct) in [(0x1e04, 0x0900), (0x1782, 0x3d00)]]
            KEEP.extend(devices)
            if len(devices) != 1 or devices[0].idVendor != 0x1e04:
                raise RuntimeError('Expected exactly one 1e04:0900 tracker; no request sent')
            dev = devices[0]
            interface = dev.get_active_configuration()[(0, 0)]
            if usb.util.get_string(dev, interface.iInterface) != 'RDA Usb':
                raise RuntimeError('Expected vendor RDA Usb interface; no request sent')
            record(event='device', interface='RDA Usb', bus=dev.bus, address=dev.address,
                   physical_unit_identity='not established by this read')
            try:
                stale = dev.read(0x81, 4096, timeout=100)
            except usb.core.USBTimeoutError:
                stale = b''
            if stale:
                raise RuntimeError('Queued USB data; no request sent')
            record(event='request', address=f'0x{ADDRESS:08x}', size=4, tx=REQUEST.hex())
            if dev.write(0x01, REQUEST, timeout=1000) != len(REQUEST):
                raise IOError('Short request; no retry')
            reply = bytearray()
            deadline = time.monotonic() + 3
            while len(reply) < 10 and time.monotonic() < deadline:
                try:
                    reply.extend(dev.read(0x81, 4096, timeout=300))
                except usb.core.USBTimeoutError:
                    pass
            record(event='response', rx=reply.hex())
            record(event='cached_flash_identity', **decode(reply))
        except Exception as exc:
            record(event='error', error=f'{type(exc).__name__}: {exc}')
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
