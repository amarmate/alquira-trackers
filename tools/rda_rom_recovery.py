"""Single bounded force-ROM experiment on the user-confirmed original 417.

Default: dry plan. --execute changes only volatile boot-mode bits, sends one
internal debug reset, validates the ROM interface/handshake and restores boot
bits. No programmer load, RAM payload, flash erase or flash program command.
This tests warm forced-ROM access, not cold recovery from erased boot flash.
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
from rda_recovery_snapshot import read_word
from rda_usb_watch import snapshot

RESET_CAUSE = 0x01A000A0
BOOT_FIELDS = 0x0FFF0000
FORCE_MONITOR = 1 << 17
ROM_SHA256 = '3946ea195270620f0907997f96f32fbaa1e2ab405146235fef2afb5f3c4680d7'


def packet(command, address, data):
    payload = bytes([0xff, command]) + struct.pack('<I', address) + data
    return b'\xad' + struct.pack('>H', len(payload)) + payload + bytes([xor(payload)])


def boot_packet(value):
    if value & ~BOOT_FIELDS:
        raise ValueError('Only boot fields may be written')
    # The firmware HAL write decoder only ORs 0x80000000 into the supplied
    # address. Supply KSEG1 explicitly so MMIO writes cannot land in cache.
    # The ROM decoder also normalizes writes to KSEG1.
    return packet(0x82, 0xA1A000A0, struct.pack('<I', value))


DEBUG_RESET = packet(0x84, 0, b'\x01')
MONITOR_START = packet(0x84, 5, b'\xfd')
MONITOR_END = packet(0x84, 5, b'\xfe')


def send(dev, request):
    if dev.write(1, request, timeout=1000) != len(request):
        raise IOError('Short transfer; no retry')


def expect_start(dev):
    data = bytearray()
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        try:
            data.extend(dev.read(0x81, 4096, timeout=250))
        except usb.core.USBTimeoutError:
            continue
        while len(data) >= 3:
            if data[0] != 0xad:
                raise IOError('Bad event sync')
            size = int.from_bytes(data[1:3], 'big') + 4
            if size > 4096 or size < 5:
                raise IOError('Bad event length')
            if len(data) < size:
                break
            event = bytes(data[:size])
            del data[:size]
            if xor(event[3:-1]) != event[-1]:
                raise IOError('Bad event checksum')
            if event[:5] == b'\xad\x00\x06\xff\x00' and event[5:9] == b'\x01\x00\x00\xff':
                return event
    raise TimeoutError('No validated ROM start event')


def device_named(backend, expected):
    devices = [d for d in usb.core.find(find_all=True, backend=backend)
               if (d.idVendor, d.idProduct) in [(0x1e04, 0x0900), (0x1782, 0x3d00)]]
    if len(devices) != 1 or devices[0].idVendor != 0x1e04:
        raise RuntimeError('Expected exactly one debug-mode tracker')
    dev = devices[0]
    interface = dev.get_active_configuration()[(0, 0)]
    if usb.util.get_string(dev, interface.iInterface) != expected:
        raise RuntimeError(f'Expected {expected}')
    if sorted(ep.bEndpointAddress for ep in interface) != [1, 0x81]:
        raise RuntimeError('Unexpected endpoints')
    return dev


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--unit', choices=['1403167417'])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    print('Plan: verify 417 boot bytes and ROM hash; preserve boot fields; set FORCE_MONITOR;', flush=True)
    print('send one debug reset; observe 30 s; handshake only with Coolsand Usb;', flush=True)
    print('restore boot fields; verify ROM persists 5 s; exit monitor to original firmware.', flush=True)
    print('No RAM program loads or flash writes. Power/cable recovery may be needed on failure.', flush=True)
    if not args.execute:
        print('debug reset:', DEBUG_RESET.hex(' '))
        print('monitor start:', MONITOR_START.hex(' '))
        return
    root = Path(__file__).resolve().parents[1]
    if args.unit != '1403167417' or args.output is None:
        parser.error('--execute requires --unit 1403167417 and --output')
    if not args.output.resolve().is_relative_to(root / 'firmware/live'):
        parser.error('Output must be in firmware/live')
    with args.output.open('x') as log:
        started = time.monotonic()

        def emit(**data):
            data['elapsed'] = round(time.monotonic() - started, 3)
            line = json.dumps(data, sort_keys=True)
            log.write(line + '\n')
            log.flush()
            print(line, flush=True)

        backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
        emit(event='baseline', **snapshot(backend))
        dev = device_named(backend, 'RDA Usb')
        try:
            stale = dev.read(0x81, 4096, timeout=100)
        except usb.core.USBTimeoutError:
            stale = b''
        if stale:
            raise RuntimeError('Queued data; refusing experiment')
        boot = read_block(dev, 0x88000000)
        if boot != (root / 'firmware/backup/v24_1403167417_flash.bin').read_bytes()[:1024]:
            raise RuntimeError('Boot mismatch')
        rom = b''.join(read_block(dev, 0x81e00000 + n) for n in range(0, 0x6000, 1024))
        if hashlib.sha256(rom).hexdigest() != ROM_SHA256:
            raise RuntimeError('ROM mismatch')
        cause = read_word(dev, RESET_CAUSE)
        saved = cause & BOOT_FIELDS
        # Reject unexpected boot state rather than silently changing extra modes.
        if ((saved >> 16) & 0x3f) != 0x20 or cause & 0x80000000:
            raise RuntimeError(f'Unexpected boot state {cause:#x}')
        forced = saved | FORCE_MONITOR
        emit(event='preflight_ok', reset_cause=hex(cause), saved=hex(saved), forced=hex(forced))
        send(dev, boot_packet(forced))
        readback = read_word(dev, RESET_CAUSE)
        emit(event='force_readback', value=hex(readback))
        if readback & BOOT_FIELDS != forced:
            send(dev, boot_packet(saved))
            emit(event='pre_reset_restore', value=hex(read_word(dev, RESET_CAUSE)))
            raise RuntimeError('Force bit not confirmed; original bits restore attempted; no reset')
        emit(event='force_confirmed', tx=boot_packet(forced).hex())
        emit(event='reset_request', tx=DEBUG_RESET.hex())
        try:
            send(dev, DEBUG_RESET)
        except usb.core.USBError as exc:
            emit(event='reset_transfer_uncertain', error=str(exc))
        usb.util.dispose_resources(dev)
        dev = None
        deadline = time.monotonic() + 30
        previous = None
        found = False
        while time.monotonic() < deadline:
            state = snapshot(backend)
            if state != previous:
                emit(event='transition', **state)
                previous = state
            if any(i.get('name') == 'Coolsand Usb'
                   for d in state['trackers'] for i in d['interfaces']):
                found = True
                break
            time.sleep(0.2)
        if not found:
            emit(event='failed', reason='No ROM interface in 30 s; no reset retry or programmer load',
                 boot_fields_restored=False)
            raise RuntimeError('ROM absent; volatile force bit may remain until power cycle')
        dev = device_named(backend, 'Coolsand Usb')
        send(dev, MONITOR_START)
        emit(event='rom_handshake', rx=expect_start(dev).hex())
        send(dev, boot_packet(saved))
        restored = read_word(dev, RESET_CAUSE) & BOOT_FIELDS
        emit(event='boot_fields_restored', value=hex(restored))
        if restored != saved:
            raise RuntimeError('Boot fields restoration not confirmed; stopping in ROM')
        for n in range(6):
            if read_word(dev, 0x01e05ff8) != 0x51612152:
                raise RuntimeError('ROM version changed')
            if n != 5:
                time.sleep(1)
        if read_block(dev, 0x88000000) != boot:
            raise RuntimeError('Boot flash mismatch in ROM')
        emit(event='rom_stable', seconds=5, boot_flash_matches=True)
        send(dev, MONITOR_END)
        emit(event='monitor_exit_requested', tx=MONITOR_END.hex())
        usb.util.dispose_resources(dev)
        deadline = time.monotonic() + 20
        previous = None
        while time.monotonic() < deadline:
            state = snapshot(backend)
            if state != previous:
                emit(event='return_transition', **state)
                previous = state
            if any(i.get('name') == 'RDA Usb'
                   for d in state['trackers'] for i in d['interfaces']):
                dev = device_named(backend, 'RDA Usb')
                # Allow startup events to settle, but never discard arbitrary bulk data.
                emit(event='vendor_interface_returned')
                return
            time.sleep(0.25)
        emit(event='return_unconfirmed', message='ROM test passed; normal interface not observed')


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
