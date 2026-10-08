"""Bounded read-only recovery snapshot: fixed ROM, Reset_Cause, SRAM boot state, and boot flash.

No reset, configuration change, RAM write, flash command, or retry. Defaults to
printing the plan. --read requires a new output directory in firmware/live.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import time

import usb.backend.libusb1
import usb.core
import usb.util

from rda_dump import LIBUSB, read_block, xor
from rda_rom_identity import frame

WORDS = (
    ('reset_cause', 0x01A000A0),
    ('boot_mode_saved', 0x01C001A8),
    ('boot_sector_pointer', 0x01C00278),
    ('boot_sector_command', 0x01C0024C),
)


def read_word(dev, address):
    request = frame(address)
    if dev.write(1, request, timeout=1000) != len(request):
        raise IOError('Short request')
    reply = bytearray()
    deadline = time.monotonic() + 3
    while len(reply) < 10 and time.monotonic() < deadline:
        try:
            reply.extend(dev.read(0x81, 4096, timeout=300))
        except usb.core.USBTimeoutError:
            pass
    if len(reply) != 10 or reply[:5] != b'\xad\x00\x06\xff\x03':
        raise IOError('Bad word response')
    if xor(reply[3:-1]) != reply[-1]:
        raise IOError('Bad word checksum')
    return struct.unpack('<I', reply[5:9])[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    print('Read plan: 1 KiB boot flash; Reset_Cause and 3 SRAM words; 24 KiB ROM. No writes.', flush=True)
    if not args.read:
        return
    root = Path(__file__).resolve().parents[1]
    if args.output is None or not args.output.resolve().is_relative_to(root / 'firmware/live'):
        parser.error('New --output directory must be inside firmware/live')
    args.output.mkdir(exist_ok=False)
    with (args.output / 'audit.jsonl').open('x') as log:
        def emit(**data):
            line = json.dumps(data, sort_keys=True)
            log.write(line + '\n')
            log.flush()
            print(line, flush=True)
        backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
        devices = [d for d in usb.core.find(find_all=True, backend=backend)
                   if (d.idVendor, d.idProduct) in [(0x1e04, 0x0900), (0x1782, 0x3d00)]]
        if len(devices) != 1 or devices[0].idVendor != 0x1e04:
            raise RuntimeError('Expected exactly one debug-mode tracker')
        dev = devices[0]
        interface = dev.get_active_configuration()[(0, 0)]
        name = usb.util.get_string(dev, interface.iInterface)
        if name != 'RDA Usb':
            raise RuntimeError('Expected RDA Usb interface')
        emit(event='device', interface=name, bus=dev.bus, address=dev.address)
        try:
            stale = dev.read(0x81, 4096, timeout=100)
        except usb.core.USBTimeoutError:
            stale = b''
        if stale:
            raise RuntimeError('Queued data; refusing requests')
        boot = read_block(dev, 0x88000000)
        backup = root / 'firmware/backup/v24_1403167417_flash.bin'
        if boot != backup.read_bytes()[:1024]:
            raise RuntimeError('Boot flash differs from 417 backup')
        emit(event='boot_match', sha256=hashlib.sha256(boot).hexdigest())
        for name, address in WORDS:
            emit(event='word', name=name, address=hex(address), value=hex(read_word(dev, address)))
        rom = bytearray()
        for offset in range(0, 0x6000, 1024):
            rom.extend(read_block(dev, 0x81e00000 + offset))
        (args.output / 'rom.bin').write_bytes(rom)
        emit(event='rom', size=len(rom), sha256=hashlib.sha256(rom).hexdigest(),
             version=hex(struct.unpack_from('<I', rom, 0x5ff8)[0]))


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
