"""Bounded, read-only protocol probes for the V24 USB data interface.

Does not touch interface 0 of 1782:3d00, clear stalls, reset USB, or write memory.
--configure explicitly reapplies the device's existing USB configuration.
Raw replies may contain device identifiers; use an ignored firmware/live path.
"""
import argparse
from pathlib import Path
import struct
import time

import usb.backend.libusb1
import usb.core
import usb.util

from rda_dump import LIBUSB, xor


def capture(dev, ep, seconds):
    data = bytearray()
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        try:
            data.extend(dev.read(ep, 4096, timeout=200))
        except usb.core.USBTimeoutError:
            pass
    return bytes(data)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('probe', choices=['listen', 'host-read', 'sxs-read', 'at', 'status', 'status-password'])
    p.add_argument('--configure', action='store_true')
    p.add_argument('--seconds', type=float, default=5)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    # Exclusively create the evidence file before any USB operation.
    with Path(a.output).open('xb') as out:
        backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
        devices = [d for d in usb.core.find(find_all=True, backend=backend)
                   if (d.idVendor, d.idProduct) in [(0x1782, 0x3d00), (0x1e04, 0x0900)]]
        if len(devices) != 1:
            raise SystemExit(f'Expected one tracker; found {len(devices)}')
        d = devices[0]
        ep = 2 if d.idVendor == 0x1782 else 1
        print(f'USB {d.idVendor:04x}:{d.idProduct:04x}, endpoint {ep}', flush=True)
        try:
            cfg = d.get_active_configuration()
            if a.configure:
                print(f'Reapply configuration {cfg.bConfigurationValue}', flush=True)
                d.set_configuration(cfg.bConfigurationValue)
            if a.probe == 'host-read':
                # Known-good rdatool request: first 1024 flash bytes, no writes.
                frame = bytes.fromhex('ad0008ff0300000088030400')
            elif a.probe == 'sxs-read':
                # SDK sxs_FlwRW_t: size LE16, access u8, readId u8, address LE32.
                payload = bytes([0x84]) + struct.pack('<HBBI', 16, 1, 0x31, 0x88000000)
                frame = b'\xad' + struct.pack('>H', len(payload)) + payload + bytes([xor(payload)])
            elif a.probe == 'at':
                frame = b'AT\r\n'
            elif a.probe == 'status':
                frame = b'AT:ts#\r'
            elif a.probe == 'status-password':
                frame = b'AT:pw,123456,ts#\r'
            else:
                frame = None
            if frame:
                print(f'TX {frame.hex(" ")}', flush=True)
                print(f'Accepted {d.write(ep, frame, timeout=1000)} bytes', flush=True)
            data = capture(d, ep | 0x80, a.seconds)
            out.write(data)
            print(f'RX {len(data)} bytes; saved {a.output}', flush=True)
            print('First 80 bytes:', data[:80].hex(' '))
        finally:
            usb.util.dispose_resources(d)


if __name__ == '__main__':
    main()
