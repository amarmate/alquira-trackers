"""Single bounded force-ROM experiment on the user-confirmed original 417.

Default: dry plan. --execute changes only volatile boot-mode bits, sends one
internal debug reset, validates the ROM interface/handshake, then reads the ROM
and the whole flash twice from ROM mode. It writes nothing while in ROM mode.
No programmer load, RAM payload, flash erase or flash program command.
This tests warm forced-ROM access, not cold recovery from erased boot flash.

--plain-reset is the control: the same checks and the same reset, without the
force bit, so the two runs can be compared.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import time
from types import SimpleNamespace

import usb.backend.libusb1
import usb.core
import usb.util

from rda_dump import LIBUSB, read_block, xor
from rda_flash import FLASH_BASE, FLASH_SIZE, PROTECTED, Monitor
from rda_recovery_snapshot import read_word
from rda_usb_watch import snapshot

RESET_CAUSE = 0x01A000A0
BOOT_FIELDS = 0x0FFF0000
NORMAL_BOOT_FIELDS = 0x00200000
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


def compare(flash, backup):
    """How a live image differs from a backup, by 4 KiB sector. Settings change at runtime."""
    sectors = [offset for offset in range(0, FLASH_SIZE, 0x1000)
               if flash[offset:offset + 0x1000] != backup[offset:offset + 0x1000]]
    return dict(differing_bytes=sum(a != b for a, b in zip(flash, backup)),
                differing_4k_sectors=[hex(s) for s in sectors],
                protected_tail_matches=flash[PROTECTED:] == backup[PROTECTED:])


def observe(backend, emit, seconds, reset_at, stop_on=None):
    """Log every USB change for `seconds` after the reset; True once `stop_on` enumerates."""
    previous = None
    while time.monotonic() < reset_at + seconds:
        state = snapshot(backend)
        if state != previous:
            emit(event='transition', since_reset=round(time.monotonic() - reset_at, 3), **state)
            previous = state
        if stop_on and any(i.get('name') == stop_on
                           for d in state['trackers'] for i in d['interfaces']):
            return True
        time.sleep(0.2)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--unit', choices=['1403167417'])
    parser.add_argument('--output', type=Path)
    # The control for the forced run: the vendor firmware's own restart also left USB
    # dark on 2026-10-08, so "no USB after the reset" alone says nothing about the ROM.
    parser.add_argument('--plain-reset', action='store_true',
                        help='control run: the same debug reset without FORCE_MONITOR')
    parser.add_argument('--observe', type=int, default=30, choices=range(30, 181),
                        metavar='30..180', help='seconds to log USB after the reset')
    args = parser.parse_args()
    if args.plain_reset:
        print('Plan: verify 417 boot bytes and ROM hash; leave boot fields alone;', flush=True)
        print(f'send one debug reset; log USB for {args.observe} s. No handshake.', flush=True)
    else:
        print('Plan: verify 417 boot bytes and ROM hash; preserve boot fields; set FORCE_MONITOR;', flush=True)
        print(f'send one debug reset; observe {args.observe} s; handshake only with Coolsand Usb;', flush=True)
        print('write nothing in ROM mode; read the ROM and the whole flash twice,', flush=True)
        print('save the flash next to the log; exit monitor to original firmware.', flush=True)
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
        # Every read of this unit gave 0x00200000 until Run B wrote that value from ROM mode
        # and left 0x00350000. The SDK's ROM source copies a USB write with memcpy, which
        # is not a 32-bit register store. So registers are written here, through the vendor
        # firmware, only; and the whole known field is written, not what happens to be there.
        if cause & ~BOOT_FIELDS:
            raise RuntimeError(f'Unexpected reset cause {cause:#x}')
        saved = NORMAL_BOOT_FIELDS
        forced = saved | FORCE_MONITOR
        emit(event='preflight_ok', reset_cause=hex(cause), saved=hex(saved),
             forced=None if args.plain_reset else hex(forced))
        if not args.plain_reset:
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
        reset_at = time.monotonic()
        usb.util.dispose_resources(dev)
        dev = None
        if args.plain_reset:
            observe(backend, emit, args.observe, reset_at)
            emit(event='control_complete', seconds=args.observe)
            return
        if not observe(backend, emit, args.observe, reset_at, stop_on='Coolsand Usb'):
            emit(event='failed',
                 reason=f'No ROM interface in {args.observe} s; no reset retry or programmer load',
                 boot_fields_restored=False)
            raise RuntimeError('ROM absent; volatile force bit may remain until power cycle')
        dev = device_named(backend, 'Coolsand Usb')
        send(dev, MONITOR_START)
        emit(event='rom_handshake', rx=expect_start(dev).hex())
        # Read only: see the preflight comment. The force bit therefore stays set until
        # RST, a power loss or the next preflight; each warm reset until then waits in the
        # monitor for 30 s before booting.
        emit(event='rom_reset_cause', value=hex(read_word(dev, RESET_CAUSE)))
        # The writer's own reader, so this exercises the frames rda_flash.py will use.
        # Every request also restarts the monitor's 30 s idle timer.
        monitor = Monitor(dev, SimpleNamespace(emit=lambda event, **f: emit(event=event, **f)),
                          usb.core.USBTimeoutError)
        if hashlib.sha256(monitor.read(0xA1E00000, 0x6000)).hexdigest() != ROM_SHA256:
            raise RuntimeError('ROM mismatch in ROM mode')
        emit(event='rom_hash_matches')
        backup = (root / 'firmware/backup/v24_1403167417_2026-10-03_flash.bin').read_bytes()
        passes = []
        for n in (1, 2):
            t0 = time.monotonic()
            data = bytearray()
            for offset in range(0, FLASH_SIZE, 0x40000):
                data += monitor.read(FLASH_BASE + offset, 0x40000)
                emit(event='flash_read_progress', read_pass=n, kib=len(data) // 1024,
                     seconds=round(time.monotonic() - t0, 1))
            passes.append(bytes(data))
        flash = passes[0]
        if passes[1] != flash:
            raise RuntimeError('Two ROM-mode flash reads differ')
        args.output.with_suffix('.flash.bin').write_bytes(flash)
        emit(event='rom_flash_read', sha256=hashlib.sha256(flash).hexdigest(),
             two_reads_match=True, boot_matches=flash[:1024] == boot,
             **compare(flash, backup))
        emit(event='rom_reset_cause_end', value=hex(read_word(dev, RESET_CAUSE)))
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
