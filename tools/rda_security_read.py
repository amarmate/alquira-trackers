"""Read 412 security register 0x1000 with a returning, pinned SRAM helper.

Default is offline validation. --execute requires 412 in ROM already. Sends no
reset or ROM exit. Exact SRAM load only; helper emits 9f/05/35/48 SPI reads and
returns to ROM. No SDK startup, flash erase/program, activation or status write.
"""
import argparse
import json
import os
from pathlib import Path
import struct
import sys

from rda_dump import LIBUSB
from rda_flash import (FLASH_SIZE, PROTECTED, ROM_START, ROM_EXECUTING, ROM_SHA,
                       frame, sha, Monitor)
from rda_programmer_start import ROOT, StartJournal, SPARE_412, SPARE_412_SHA
from rda_logicrom_license_capture import validate_local, validate_live

BUILD = ROOT / 'firmware/live/usb-programmer-build/security-reader-2026-10-10/build'
MANIFEST = BUILD / 'audit.json'
RESULT = 0xa1c02000
RESULT_SIZE = 13 * 4 + 512
CONTEXT = struct.pack('<6I', 0xff, 0x81c00280, 0xa1c04000, 0, 0, 0)
EXECUTE = b'\xff\x84' + struct.pack('<I', 5) + b'\xff'
HANDSHAKE = b'\xff\x84' + struct.pack('<I', 5) + b'\xfd'
ROM_RETURNED = 0xff000005


class SecurityMonitor(Monitor):
    """Reads, one handshake, exact audited load packets, one execute; nothing else."""
    def __init__(self, device, journal, timeout_error, payload):
        super().__init__(device, journal, timeout_error)
        writes = [(0xa1c00280 + n, payload[n:n + 1024])
                  for n in range(0, len(payload), 1024)]
        writes += [(RESULT, b'\xcc' * RESULT_SIZE), (0xa1c000a0, CONTEXT)]
        self.allowed = [b'\xff\x83' + struct.pack('<I', address) + data
                        for address, data in writes]
        self.handshaken = self.armed = self.executed = False

    def send(self, payload):
        if payload[:2] == b'\xff\x03' and len(payload) == 9:
            pass
        elif payload == HANDSHAKE and not self.handshaken:
            self.handshaken = True
        elif (self.armed and not self.executed and self.allowed
              and payload == self.allowed[0]):
            self.allowed.pop(0)  # consume before transfer; no uncertain retry
        elif (payload == EXECUTE and self.armed and self.handshaken
              and not self.allowed and not self.executed):
            self.executed = True
        else:
            raise ValueError('Forbidden security-reader request')
        super().send(payload)


def local_payload():
    audit = json.loads(MANIFEST.read_text())
    payload = (BUILD / 'security_reader.bin').read_bytes()
    source = (ROOT / 'firmware/logicrom/security_reader.c').read_bytes()
    if (audit['payload_sha256'] != sha(payload) or audit['source_sha256'] != sha(source)
            or not audit.get('offline_binary_checks_passed')
            or not audit.get('reduced_register_binary_check')
            or audit['spi_opcodes'] != [0x9f, 0x05, 0x35, 0x48]
            or len(payload) % 4 or not 0 < len(payload) < RESULT - 0xa1c00280):
        raise ValueError('Security reader does not match its offline audit')
    if audit['entry'] != '0x81c00280' or audit['result'] != hex(RESULT):
        raise ValueError('Security reader SRAM allocation mismatch')
    return payload


def parse_result(raw):
    if len(raw) != RESULT_SIZE:
        raise ValueError('Invalid result size')
    names = ('magic', 'version', 'state', 'error', 'jedec', 'status_before',
             'status_after', 'bytes_first', 'bytes_second', 'block_before',
             'config_before', 'block_after', 'config_after')
    fields = dict(zip(names, struct.unpack_from('<13I', raw)))
    first, second = raw[52:308], raw[308:564]
    if (fields['magic'] != 0x53454352 or fields['version'] != 1
            or fields['state'] != 2 or fields['error'] != 0
            or fields['jedec'] != 0x1660c8
            or fields['bytes_first'] != 256 or fields['bytes_second'] != 256
            or fields['status_before'] != fields['status_after']
            or fields['status_before'] & 3
            or fields['block_before'] != fields['block_after']
            or fields['config_before'] != fields['config_after']
            or first != second):
        raise ValueError(f'Incomplete or inconsistent security read: {fields}')
    fields.update(security_sha256=sha(first), reads_equal=True,
                  first_96_all_ff=first[:96] == b'\xff' * 96,
                  all_256_ff=first == b'\xff' * 256)
    return fields, first


def read_image(monitor, journal, name):
    result = bytearray()
    for offset in range(0, FLASH_SIZE, 0x40000):
        result.extend(monitor.read(0xa8000000 + offset, 0x40000))
        journal.emit('read_progress', pass_name=name, bytes_read=len(result))
    result = bytes(result)
    journal.save(name + '.bin', result)
    return result


def run(path, payload, image, backup):
    import usb.backend.libusb1
    import usb.core
    from rda_rom_recovery import device_named
    journal = StartJournal(path)
    try:
        journal.emit('scope', unit='1403167412', operations='ROM reads, exact SRAM helper '
                     'load, one returning execution, security reads, full flash verification',
                     flash_writes=False, security_writes=False, status_writes=False,
                     reset=False, core_start=False, spi_opcodes=[0x9f, 0x05, 0x35, 0x48],
                     payload_sha256=sha(payload))
        backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
        device = device_named(backend, 'Coolsand Usb')
        monitor = SecurityMonitor(device, journal, usb.core.USBTimeoutError, payload)
        monitor.send(HANDSHAKE)
        if monitor.receive(0, 4) != struct.pack('<I', ROM_START):
            raise IOError('ROM handshake mismatch')
        if sha(monitor.read(0xa1e00000, 0x6000)) != ROM_SHA:
            raise IOError('ROM hash mismatch')
        first = read_image(monitor, journal, 'before-reader')
        validate_live(first, first, image, backup)
        second = read_image(monitor, journal, 'before-reader-second')
        validate_live(first, second, image, backup)
        journal.emit('unit_and_image_verified', two_reads_equal=True,
                     sha256=sha(first), protected_tail_sha256=sha(first[PROTECTED:]))
        monitor.armed = True
        while monitor.allowed:
            packet = monitor.allowed[0]
            address = struct.unpack_from('<I', packet, 2)[0]
            data = packet[6:]
            monitor.send(packet)
            if monitor.read(address, len(data)) != data:
                raise IOError('SRAM readback mismatch; no execute')
        journal.emit('ram_helper_verified', payload_sha256=sha(payload),
                     context=CONTEXT.hex(), result_prefill='cc')
        monitor.send(EXECUTE)
        if monitor.receive(0, 4) != struct.pack('<I', ROM_EXECUTING):
            raise IOError('Missing execution acknowledgement')
        # Existing Monitor.receive treats the returned event as a programmer
        # failure. startup_event validates arbitrary event framing without that
        # policy, so use the same parser on this returning monitor.
        from rda_programmer_start import StartMonitor
        monitor.startup = []
        returned = StartMonitor.startup_event(monitor, 5)
        if returned != ROM_RETURNED:
            raise IOError('Helper did not return to ROM; no retry')
        journal.emit('helper_returned_to_rom')
        context = monitor.read(0xa1c000a0, 24)
        journal.save('execution-context.bin', context)
        raw = monitor.read(RESULT, RESULT_SIZE)
        journal.save('security-result.bin', raw)
        if context != CONTEXT:
            journal.emit('execution_context', hex=context.hex())
            raise IOError('Helper returned a nonzero error or altered context')
        fields, record = parse_result(raw)
        journal.save('security-1000-first.bin', record)
        journal.save('security-1000-second.bin', raw[308:564])
        journal.emit('security_read_verified', **fields)
        for name in ('after-reader', 'after-reader-second'):
            after = read_image(monitor, journal, name)
            if after != first:
                raise IOError('Main flash changed during reader; evidence saved, no retry')
        journal.emit('complete', flash_unchanged=True, security_reads_equal=True,
                     license_record_blank=fields['first_96_all_ff'], remains_in_rom=True)
    except BaseException as exc:
        journal.emit('stopped', error=f'{type(exc).__name__}: {exc}', automatic_retry=False)
        raise
    finally:
        journal.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--journal', type=Path)
    args = parser.parse_args()
    payload = local_payload()
    image, backup = validate_local()
    print(f'Offline audit matched: {len(payload)} bytes, SHA256 {sha(payload)}', flush=True)
    if args.execute:
        raise RuntimeError('Live reader disabled after two return-event timeouts; '
                           'see docs/knowledge/rom-flash-access.md#6-returning-helpers-through-the-rom-monitor')
        if args.journal is None or args.journal.resolve().parent != ROOT / 'firmware/live':
            parser.error('--execute requires a new journal directly under firmware/live')
        run(args.journal, payload, image, backup)


if __name__ == '__main__':
    status_code = 0
    try:
        main()
    except KeyboardInterrupt:
        status_code = 130
    except Exception as exc:
        print(f'Stopped: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        status_code = 1
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(status_code)
