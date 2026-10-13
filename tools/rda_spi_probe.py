"""Staged 412 ROM diagnostics. Default is an offline plan; --read is read-only.

Read-only snapshot: one handshake, pinned ROM, fixed clock/controller words,
Cache_Control, ROM USB-context pointer, and two complete flash reads. Never
resets or exits.
"""
import argparse
import json
import os
from pathlib import Path
import struct
import sys

from rda_dump import LIBUSB
from rda_flash import FLASH_SIZE, PROTECTED, ROM_SHA, ROM_START, Monitor, sha
from rda_programmer_start import ROOT, StartJournal, StartMonitor
from rda_logicrom_license_capture import validate_local, validate_live
from rda_security_read import HANDSHAKE, read_image

BASELINE = ROOT / 'firmware/live/2026-10-10-logicrom-412-security-recovered-1/recovered-flash.bin'
BASELINE_SHA = 'b1dc8ccc2bb6ea1a26ee5bb353f7fff0627b65af34131a50a5d72b71be71b47d'
WORDS = {
    'sys_reset': 0xa1a00004,
    'other_clock_mode': 0xa1a00038,
    'other_clock_enable': 0xa1a0003c,
    'pll_control': 0xa1a00044,
    'clock_select': 0xa1a00048,
    'spi_clock_frequency': 0xa1a000ac,
    'cache_control': 0xa1a2b444,
    'rom_usb_context': 0xa1c001d8,
}
SPI_NAMES = ('command', 'block', 'fifo_data', 'status', 'readback', 'config',
             'fifo_control', 'cs_size', 'read_command', 'reg24', 'reg28',
             'reg2c', 'reg30', 'timeout')
READ_RANGES = ((0xa1e00000, 0xa1e06000), (0xa8000000, 0xa8400000),
               (0xa7fff000, 0xa7fff008), (0xa7fff00c, 0xa7fff038))


class SnapshotMonitor(Monitor):
    def __init__(self, device, journal, timeout_error):
        super().__init__(device, journal, timeout_error)
        self.handshaken = False
        self.read_ranges = READ_RANGES

    def send(self, payload):
        if payload == HANDSHAKE and not self.handshaken:
            self.handshaken = True
        elif payload[:2] == b'\xff\x03' and len(payload) == 9:
            address = struct.unpack_from('<I', payload, 2)[0]
            count = int.from_bytes(payload[7:9], 'big')
            if (not 0 < count <= 1024 or not payload[6]
                    or not (count == 4 and address in WORDS.values()
                            or any(lo <= address and address + count <= hi for lo, hi in self.read_ranges))):
                raise ValueError('Read outside fixed snapshot scope')
        else:
            raise ValueError('Only one handshake and fixed memory reads permitted')
        super().send(payload)


def validate_baseline():
    image, backup = validate_local()
    baseline = BASELINE.read_bytes()
    if sha(baseline) != BASELINE_SHA:
        raise ValueError('Recovery baseline mismatch')
    validate_live(baseline, baseline, image, backup)
    return image, backup, baseline


def capture(monitor, journal, name):
    values = {key: struct.unpack('<I', monitor.read(address, 4))[0]
              for key, address in WORDS.items()}
    spi = monitor.read(0xa7fff000, 8) + b'\x00' * 4 + monitor.read(0xa7fff00c, 0x2c)
    journal.save(name + '-controller-with-fifo-omitted.bin', spi)
    controller = dict(zip(SPI_NAMES, struct.unpack('<14I', spi)))
    controller.pop('fifo_data')
    pointer = values['rom_usb_context']
    physical = pointer & 0x1fffffff
    if pointer & 3 or not 0x01c00200 <= physical <= 0x01c10000 - 0x1114:
        raise ValueError(f'Unexpected ROM USB-context pointer {pointer:#x}')
    return dict(words=values, controller=controller,
                decoded=dict(pll_enabled=bool(values['pll_control'] & 1),
                             pll_fast_output=bool(values['pll_control'] & 0x1000),
                             pll_locked=bool(values['clock_select'] & 0x100),
                             spi_source_slow=bool(values['clock_select'] & 0x400),
                             spi_frequency_selector=values['spi_clock_frequency'] & 15,
                             spi_out_of_reset=bool(values['sys_reset'] & 0x800000),
                             spi_system_clock_enabled=bool(values['other_clock_enable'] & 0x80000),
                             spi_clock_enabled=bool(values['other_clock_enable'] & 0x100000),
                             dcache_inhibit=bool(values['cache_control'] & 1),
                             icache_inhibit=bool(values['cache_control'] & 2),
                             cache_hit_disable=bool(values['cache_control'] & 4)),
                rom_usb_context_range=[hex(physical), hex(physical + 0x1114)],
                omitted_registers=['SPI FIFO data at a7fff008', 'read-sensitive SC at a1a01014'])


class ProbeMonitor(SnapshotMonitor):
    def __init__(self, device, journal, timeout_error, binary, cmd=0xff, result_size=64):
        super().__init__(device, journal, timeout_error)
        from audit_rda_rom_probe import ENTRY, RESULT, STACK, ARGUMENT
        self.result_size = result_size
        self.read_ranges += ((ENTRY, ENTRY + 0x1000), (RESULT, RESULT + result_size),
                             (0xa1c000a0, 0xa1c000b8))
        # Command 0xff runs boot_HstMonitorX (drops its return on a write-back
        # cache). Any other command takes the extended arm: the word at
        # 0xa1c000b4 (BOOT_HST_EXECUTOR_T.hstMonitorExtendedHandler) is called
        # with a0 = 0xa1c000a0 and no cache operation, then the end event sends.
        handler = ENTRY if cmd != 0xff else 0
        self.context = struct.pack('<6I', cmd, ENTRY, STACK, ARGUMENT, 0, handler)
        self.writes = [b'\xff\x83' + struct.pack('<I', ENTRY + n) + binary[n:n + 1024]
                       for n in range(0, len(binary), 1024)]
        self.writes += [b'\xff\x83' + struct.pack('<I', RESULT) + b'\xcc' * result_size,
                        b'\xff\x83' + struct.pack('<I', 0xa1c000a0) + self.context]
        self.armed, self.executed, self.startup = False, False, []

    def send(self, payload):
        execute = b'\xff\x84' + struct.pack('<I', 5) + b'\xff'
        if self.armed and not self.executed and self.writes and payload == self.writes[0]:
            self.writes.pop(0)
            Monitor.send(self, payload)
        elif payload == execute and self.armed and self.handshaken and not self.writes and not self.executed:
            self.executed = True
            Monitor.send(self, payload)
        else:
            super().send(payload)


def payload_for(stage):
    from audit_rda_rom_probe import BUILD, RETURN_WORDS
    report = json.loads((BUILD / 'audit.json').read_text())
    binary_stage = {'return-fc': 'return'}.get(stage, stage)
    binary = (BUILD / (binary_stage + '.bin')).read_bytes()
    pinned = {'return': '90813fa73099e76bb82032c6b031e4269a0ae93e3bb6374c1fb69167344916c5',
              'jedec': 'd58e59d6312d888c1dff2da2708db89460e14fcf0246852e5f296bcfca23ed10',
              'jedec-fc': '1fc6b2edf93f9b04f3b69753d636ad137bc880466e55882fa074e914179acdaa',
              'security-fc': '3c89fc6197af76e9cf2fb8f44a029f4d3e6baf19fef6d4df5223cfdeeb685dbb'}
    report_key = {'jedec-fc': 'jedec_fc_sha256',
                  'security-fc': 'security_fc_sha256'}.get(binary_stage, binary_stage + '_sha256')
    if sha(binary) != pinned[binary_stage] or report[report_key] != pinned[binary_stage]:
        raise ValueError('Probe binary differs from reviewed artifact')
    if binary_stage == 'return' and binary != struct.pack('<10I', *RETURN_WORDS):
        raise ValueError('Return probe instruction words differ')
    if not report['reduced_register_check'] or not all(case['passed'] for case in report['cases']):
        raise ValueError('Probe audit incomplete')
    for source, expected in report['sources'].items():
        if sha((ROOT / 'firmware/logicrom' / source).read_bytes()) != expected:
            raise ValueError('Probe source differs from audit')
    return binary


def validate_return_control(path, stage='return'):
    records = [json.loads(line) for line in (path / 'operations.jsonl').read_text().splitlines()]
    if (not records or records[-1].get('event') != 'complete'
            or records[-1].get('stage') != stage or not records[-1].get('probe_passed')
            or records[-1].get('flash_sha256') != BASELINE_SHA
            or records[0].get('payload_sha256') != sha(payload_for(stage))):
        raise ValueError(f'Single JEDEC requires this exact successful {stage} control')


def validate_jedec_control(path, stage='jedec-fc'):
    records = [json.loads(line) for line in (path / 'operations.jsonl').read_text().splitlines()]
    if (not records or records[-1].get('event') != 'complete'
            or records[-1].get('stage') != stage or not records[-1].get('probe_passed')
            or records[-1].get('flash_sha256') != BASELINE_SHA
            or records[0].get('payload_sha256') != sha(payload_for(stage))):
        raise ValueError(f'Security read requires this exact successful {stage} control')


def probe(stage, path, control_path=None):
    import usb.backend.libusb1
    import usb.core
    from rda_rom_recovery import device_named
    from audit_rda_rom_probe import (ENTRY, RESULT, STACK, ARGUMENT, RETURN_VALUE,
                                     SECURITY_RESULT_SIZE)
    extended = stage.endswith('-fc')
    result_size = SECURITY_RESULT_SIZE if stage == 'security-fc' else 64
    image, backup, baseline = validate_baseline()
    binary = payload_for(stage)
    if stage == 'jedec':
        validate_return_control(control_path)
    elif stage == 'jedec-fc':
        validate_return_control(control_path, 'return-fc')
    elif stage == 'security-fc':
        validate_jedec_control(control_path, 'jedec-fc')
    journal = StartJournal(path)
    try:
        journal.emit('scope', stage=stage, unit='1403167412', payload_sha256=sha(binary),
                     operations='Exact SRAM load and one returning execution; ' +
                     ('SRAM marker only via the 0xfc extended-handler arm' if stage == 'return-fc' else
                      'SRAM marker only' if stage == 'return' else
                      'two 256-byte security passes with JEDEC/status and volatile SPI clock/config restoration via the 0xfc extended-handler arm'
                      if stage == 'security-fc' else
                      'one JEDEC and volatile SPI clock/config restoration' +
                      (' via the 0xfc extended-handler arm' if stage == 'jedec-fc' else '')),
                     spi_opcodes=([0x9f, 0x05, 0x35, 0x48] if stage == 'security-fc'
                                  else [0x9f] if stage.startswith('jedec') else []),
                     flash_write=False, status_write=False,
                     security_read=(stage == 'security-fc'), reset=False, exit=False,
                     context_command=hex(0xfc if extended else 0xff),
                     return_control=str(control_path) if control_path else None)
        backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
        device = device_named(backend, 'Coolsand Usb')
        monitor = ProbeMonitor(device, journal, usb.core.USBTimeoutError, binary,
                               cmd=0xfc if extended else 0xff, result_size=result_size)
        monitor.send(HANDSHAKE)
        if monitor.receive(0, 4) != struct.pack('<I', ROM_START):
            raise IOError('ROM handshake mismatch')
        if sha(monitor.read(0xa1e00000, 0x6000)) != ROM_SHA:
            raise IOError('ROM hash mismatch')
        before = capture(monitor, journal, 'before')
        journal.save('snapshot-before.json', (json.dumps(before, indent=2) + '\n').encode())
        context_physical = int(before['rom_usb_context_range'][0], 16)
        if context_physical != 0x1c0eeb4 or STACK & 0x1fffffff >= context_physical - 0x400:
            raise IOError('Probe allocation not separate from live ROM context/stack')
        if stage in ('jedec', 'jedec-fc', 'security-fc') and (before['words']['clock_select'] != 0x5f16
                or before['words']['spi_clock_frequency'] != 2
                or before['words']['pll_control'] != 0x1011
                or before['controller']['config'] != 0x8a0
                or before['controller']['block'] != 0x100 or before['controller']['status'] & 1):
            raise IOError('Single-JEDEC baseline changed')
        for name in ('before-flash', 'before-flash-second'):
            first = read_image(monitor, journal, name)
            validate_live(first, first, image, backup)
            if first != baseline:
                raise IOError('Live flash differs from recovery baseline')
        monitor.armed = True
        while monitor.writes:
            packet = monitor.writes[0]
            address, contents = struct.unpack_from('<I', packet, 2)[0], packet[6:]
            monitor.send(packet)
            if monitor.read(address, len(contents)) != contents:
                raise IOError('Exact SRAM load readback differs; no execution')
        journal.emit('probe_load_verified', entry=hex(ENTRY), stack=hex(STACK),
                     context=monitor.context.hex(), rom_usb_context=before['rom_usb_context_range'])
        monitor.send(b'\xff\x84' + struct.pack('<I', 5) + b'\xff')
        expected = [0xff000004] + ([] if stage in ('return', 'return-fc') else
                    [0x53500001, 0x53500002, 0x53500003, 0x53500004]) + [0xff000005]
        for event in expected:
            actual = StartMonitor.startup_event(monitor, 5)
            if actual != event:
                raise IOError(f'Probe checkpoint {actual:#x}; expected {event:#x}; no retry')
        context = monitor.read(0xa1c000a0, 24)
        result = monitor.read(RESULT, result_size)
        journal.save('context-after.bin', context)
        journal.save('result.bin', result)
        if monitor.read(RESULT, result_size) != result:
            raise IOError('Probe result changed across reads')
        if extended:
            # The extended arm stores no returnedValue; the context is unchanged.
            expected_context = monitor.context
        else:
            expected_context = struct.pack('<6I', 0xff, ENTRY, STACK, ARGUMENT,
                                           RETURN_VALUE if stage == 'return' else 0, 0)
        if context != expected_context:
            raise IOError('ROM return context differs')
        if stage == 'return':
            if result != struct.pack('<2I', 0x52544e31, ARGUMENT) + b'\xcc' * 56:
                raise IOError('SRAM-only return control differs')
        elif stage == 'return-fc':
            # The extended arm calls the helper with a0 = &boot_HstMonitorXCtx
            # (0xa1c000a0), so the control echoes the context pointer, not ARGUMENT.
            if result != struct.pack('<2I', 0x52544e31, 0xa1c000a0) + b'\xcc' * 56:
                raise IOError('Extended-arm return control differs')
        elif stage == 'security-fc':
            words = struct.unpack('<20I', result[:80])
            first, second = result[80:336], result[336:592]
            journal.emit('security_result', words=[hex(value) for value in words],
                         first_sha256=sha(first), second_sha256=sha(second))
            if (words[:4] != (0x53454352, 2, 4, 0) or words[4] != 0x1660c8
                    or words[5] != words[6] or words[5] & 3
                    or words[7:9] != (256, 256) or words[10] != 133
                    or words[12:16] != words[16:20] or first != second):
                raise IOError('Security result, restoration or pass equality failed')
            journal.save('security-1000-first.bin', first)
            journal.save('security-1000-second.bin', second)
            journal.emit('security_read_verified', jedec=hex(words[4]),
                         status=hex(words[5]), bytes_first=words[7], bytes_second=words[8],
                         commands=words[10], reads_equal=True,
                         first_96_all_ff=first[:96] == b'\xff' * 96,
                         all_256_ff=first == b'\xff' * 256,
                         security_sha256=sha(first))
        else:
            words = struct.unpack('<16I', result)
            journal.emit('jedec_result', words=[hex(value) for value in words])
            if words[:5] != (0x4a454443, 1, 4, 0, 0x1660c8) or words[14] != 1 or words[6:10] != words[10:14]:
                raise IOError('Single-JEDEC result or restoration failed')
        after = capture(monitor, journal, 'after')
        journal.save('snapshot-after.json', (json.dumps(after, indent=2) + '\n').encode())
        if before['words'] != after['words']:
            raise IOError('Clock/reset/context registers changed')
        for key in ('block', 'config', 'cs_size', 'read_command', 'reg24', 'reg28', 'reg2c', 'reg30', 'timeout'):
            if before['controller'][key] != after['controller'][key]:
                raise IOError('Persistent controller setting changed')
        if after['controller']['status'] & 1:
            raise IOError('Controller remains busy')
        for name in ('after-flash', 'after-flash-second'):
            if read_image(monitor, journal, name) != baseline:
                raise IOError('Main flash changed during probe')
        journal.emit('complete', stage=stage, probe_passed=True, flash_sha256=BASELINE_SHA,
                     two_before_and_two_after_equal=True, controller_and_clocks_restored=True,
                     remains_in_rom=True,
                     license_state='measured' if stage == 'security-fc' else 'unmeasured')
    except BaseException as exc:
        journal.emit('stopped', stage=stage, error=f'{type(exc).__name__}: {exc}', automatic_retry=False)
        raise
    finally:
        journal.close()


def snapshot(path):
    import usb.backend.libusb1
    import usb.core
    from rda_rom_recovery import device_named
    image, backup, baseline = validate_baseline()
    journal = StartJournal(path)
    try:
        journal.emit('scope', unit='1403167412', operations='One handshake and fixed memory reads only',
                     reset=False, exit=False, load=False, execute=False, mmio_write=False,
                     spi_commands=False, flash_write=False)
        backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
        device = device_named(backend, 'Coolsand Usb')
        monitor = SnapshotMonitor(device, journal, usb.core.USBTimeoutError)
        monitor.send(HANDSHAKE)
        if monitor.receive(0, 4) != struct.pack('<I', ROM_START):
            raise IOError('ROM handshake mismatch')
        rom = monitor.read(0xa1e00000, 0x6000)
        journal.save('rom.bin', rom)
        if sha(rom) != ROM_SHA:
            raise IOError('ROM hash mismatch')
        first = capture(monitor, journal, 'before')
        journal.save('snapshot-before.json', (json.dumps(first, indent=2) + '\n').encode())
        journal.emit('snapshot', **first)
        flash_first = read_image(monitor, journal, 'flash-first')
        validate_live(flash_first, flash_first, image, backup)
        if flash_first != baseline:
            raise IOError('Flash changed since verified recovery')
        flash_second = read_image(monitor, journal, 'flash-second')
        validate_live(flash_first, flash_second, image, backup)
        second = capture(monitor, journal, 'after')
        journal.save('snapshot-after.json', (json.dumps(second, indent=2) + '\n').encode())
        if first != second:
            raise IOError('Snapshot changed across reads')
        journal.emit('complete', rom_verified=True, two_flash_reads_equal=True,
                     flash_sha256=sha(flash_first), tail_sha256=sha(flash_first[PROTECTED:]),
                     snapshot_stable=True, remains_in_rom=True, license_state='unmeasured')
    except BaseException as exc:
        journal.emit('stopped', error=f'{type(exc).__name__}: {exc}', automatic_retry=False)
        raise
    finally:
        journal.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--read', action='store_true')
    modes.add_argument('--return-control', action='store_true')
    modes.add_argument('--return-control-fc', action='store_true')
    modes.add_argument('--jedec', action='store_true')
    modes.add_argument('--jedec-fc', action='store_true')
    modes.add_argument('--security-fc', action='store_true')
    parser.add_argument('--return-journal', type=Path)
    parser.add_argument('--jedec-journal', type=Path)
    parser.add_argument('--journal', type=Path)
    args = parser.parse_args()
    validate_baseline()
    print('Snapshot: one ROM handshake, fixed clock/controller words (FIFO/SC omitted), two flash reads.', flush=True)
    if args.read or args.return_control or args.return_control_fc or args.jedec or args.jedec_fc or args.security_fc:
        if args.journal is None or args.journal.resolve().parent != ROOT / 'firmware/live':
            parser.error('--read requires a fresh journal directly under firmware/live')
        if args.read:
            snapshot(args.journal)
        elif args.return_control_fc:
            # Reviewed in docs/done/26-10-10-rom-extended-handler.md; each live
            # run still requires the user's go per the standing constraint.
            probe('return-fc', args.journal)
        elif args.return_control:
            raise RuntimeError('Live return control disabled after the SRAM-only helper failed to return; '
                               'see docs/done/26-10-10-rom-jedec-probe.md')
        elif args.jedec_fc:
            # Audited in firmware/live/usb-programmer-build/rom-probe-fc-2026-10-10/build/audit.json;
            # each live run still requires the user's go per the standing constraint.
            if args.return_journal is None:
                parser.error('--jedec-fc requires --return-journal with the validated return-fc control')
            probe('jedec-fc', args.journal, args.return_journal)
        elif args.security_fc:
            raise RuntimeError('Live security-fc completed successfully on 2026-10-10; '
                               'a repeat requires a new explicit go; '
                               'see docs/done/26-10-10-rom-extended-handler.md')
            if args.jedec_journal is None:
                parser.error('--security-fc requires --jedec-journal with the validated jedec-fc control')
            probe('security-fc', args.journal, args.jedec_journal)
        else:
            raise RuntimeError('Live JEDEC probe disabled: SRAM-only return control failed; '
                               'see docs/done/26-10-10-rom-jedec-probe.md')


if __name__ == '__main__':
    status = 0
    try:
        main()
    except Exception as exc:
        print(f'Stopped: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        status = 1
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(status)
