"""Read two fixed mask-ROM words; no reset, MMIO access, or memory writes.

Addresses come from SDK 8955 mem_bridge_rom_CHIP.map. A match is diagnostic
evidence only, not permission to execute a programmer or proof of recovery.
Without --read, print the two requests without opening USB.
"""
import argparse
import json
import os
from pathlib import Path
import struct
import sys
import time

import usb.backend.libusb1
import usb.core
import usb.util

from rda_dump import LIBUSB, xor

WORDS = (('usb_monitor_pointer', 0x01E00FFC), ('rom_version', 0x01E05FF8))
KEEP = []


def frame(address):
    payload = b'\xff\x02' + struct.pack('<I', address) + b'\x03'
    return b'\xad' + struct.pack('>H', len(payload)) + payload + bytes([xor(payload)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    for name, address in WORDS:
        print(f'{name} 0x{address:08x}: {frame(address).hex(" ")}', flush=True)
    if not args.read:
        return
    live = Path(__file__).resolve().parents[1] / 'firmware' / 'live'
    if args.output is None or not args.output.resolve().is_relative_to(live):
        parser.error('--read requires a new --output inside firmware/live/')
    with args.output.open('x') as log:
        def record(**data):
            line = json.dumps(data, sort_keys=True)
            print(line, flush=True)
            log.write(line + '\n')
            log.flush()
        backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
        if backend is None:
            raise RuntimeError('libusb backend unavailable')
        devices = [d for d in usb.core.find(find_all=True, backend=backend)
                   if (d.idVendor, d.idProduct) in [(0x1e04, 0x0900), (0x1782, 0x3d00)]]
        KEEP.extend(devices)
        if len(devices) != 1 or devices[0].idVendor != 0x1e04:
            raise RuntimeError('Expected exactly one 1e04:0900 tracker')
        dev = devices[0]
        interface = dev.get_active_configuration()[(0, 0)]
        if usb.util.get_string(dev, interface.iInterface) != 'RDA Usb':
            raise RuntimeError('Expected vendor RDA Usb interface')
        try:
            stale = dev.read(0x81, 4096, timeout=100)
        except usb.core.USBTimeoutError:
            stale = b''
        if stale:
            raise RuntimeError('Queued USB data; refusing to send requests')
        for name, address in WORDS:
            request = frame(address)
            record(name=name, address=f'0x{address:08x}', tx=request.hex())
            if dev.write(0x01, request, timeout=1000) != len(request):
                raise IOError('Short request; no retry')
            reply = bytearray()
            deadline = time.monotonic() + 3
            while len(reply) < 10 and time.monotonic() < deadline:
                try:
                    reply.extend(dev.read(0x81, 4096, timeout=300))
                except usb.core.USBTimeoutError:
                    pass
            record(name=name, rx=reply.hex())
            if len(reply) != 10 or reply[:5] != b'\xad\x00\x06\xff\x03':
                raise IOError('Invalid response length/header; no retry')
            if xor(reply[3:-1]) != reply[-1]:
                raise IOError('Invalid response checksum; no retry')
            record(name=name, value=f'0x{struct.unpack("<I", reply[5:9])[0]:08x}')


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
