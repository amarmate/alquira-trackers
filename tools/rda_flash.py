"""RDA8955 host flash writer. Default is an OFFLINE plan; USB requires --execute.

Execution starts in an already established ROM monitor, never resets a running
tracker to get there. Board qualification is required before loading the stock
programmer (its startup itself can write flash status registers). See
docs/v24-flash-writer.md. No hardware qualification is supplied with this tool.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import time

from rda_lod_audit import audit

FLASH_SIZE = 0x400000
PROTECTED = 0x3FA000
FLASH_BASE = 0xA8000000
MAGIC = 0xD9EF0045
LOD_SHA = '8a3ea6257de0c4d584d9f04d8e19db73ee54d8eee0a47fc3ddcaebb2f8af9dd1'
ROM_SHA = '3946ea195270620f0907997f96f32fbaa1e2ab405146235fef2afb5f3c4680d7'
MAP = 0xA1C0BB68
BUFFER = 0xA2000000
GEOMETRY_ADDRESS = 0xA1C095C4
GEOMETRY = struct.pack('<7I', 0, 63, 0x10000, 16, 0x1000, 0, 0)
LAYOUT_ADDRESS = 0xA1C095E0
LAYOUT = struct.pack('<6I', 1, 0x81C095C4, FLASH_SIZE, 0x3F6000, 0x4000, 512)
FLASH_CONTEXT = 0xA1C076F0
ORIGINAL_UNIT = '1403167417'
LIVE_ROOT = Path(__file__).resolve().parents[1] / 'firmware/live'
ROM_START, ROM_EXECUTING, READY = 0xFF000001, 0xFF000004, 0xF0
EVENT_ERRORS = {0xB0, 0xB1, 0xC0, 0xCE, 0xD0, 0xD1, 0xE0, 0xE1,
                0xEBC0EEE1, 0xEBC0EEE2, 0xFF000002, 0xFF000003, 0xFF000005}
PROGRAM, ERASE, END, FINALIZE_INFO, PING = 1, 2, 4, 6, 9
DONE = 0xFFFFFF9C
ERRORS = {0xFFFFFF9D, 0xFFFFFF9E, 0xFFFFFF9F}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def span(offset, size, limit=PROTECTED):
    if (type(offset) is not int or type(size) is not int or offset < 0
            or size <= 0 or offset % 4 or size % 4 or offset + size > limit):
        raise ValueError('Invalid, unaligned, aliased or protected footprint')


def sector_size(offset):
    span(offset, 4, FLASH_SIZE)
    size = 0x10000 if offset < 0x3F0000 else 0x1000
    if offset % size:
        raise ValueError('Not an erase-sector boundary')
    return size


def plan(current, target, backup, unit):
    if not unit or any(len(x) != FLASH_SIZE for x in (current, target, backup)):
        raise ValueError('Unit and three exact 4 MiB images required')
    if current[PROTECTED:] != backup[PROTECTED:]:
        raise ValueError('Current protected bytes differ from unit backup')
    if target[PROTECTED:] != backup[PROTECTED:]:
        raise ValueError('Source would replace protected calibration/factory data')
    if struct.unpack_from('<I', target)[0] != MAGIC:
        raise ValueError('Source lacks expected RDA boot magic')
    sectors = []
    offset = 0
    while offset < PROTECTED:
        size = sector_size(offset)
        span(offset, size)
        if current[offset:offset + size] != target[offset:offset + size]:
            sectors.append({'offset': offset, 'erase_bytes': size,
                            'program_chunks': size // 4096,
                            'before_sha256': sha(current[offset:offset + size]),
                            'after_sha256': sha(target[offset:offset + size])})
        offset += size
    sectors.sort(key=lambda s: (s['offset'] == 0, s['offset']))
    return {'unit': unit, 'current_sha256': sha(current), 'source_sha256': sha(target),
            'backup_sha256': sha(backup), 'protected_start': PROTECTED,
            'sectors': sectors, 'finalize_boot_magic': any(s['offset'] == 0 for s in sectors),
            'verification': 'erased bytes, each programmed sector, then full 4 MiB after finalization',
            'hardware_validated': False}


class Journal:
    """Exclusive run directory; durable evidence before commands, never overwrite."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir(mode=0o700, parents=False, exist_ok=False)
        self.file = (self.path / 'operations.jsonl').open('x')
        self.sync_directory(self.path.parent)

    @staticmethod
    def sync_directory(path):
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def emit(self, event, **fields):
        self.file.write(json.dumps({'event': event, **fields}, sort_keys=True) + '\n')
        self.file.flush()
        os.fsync(self.file.fileno())
        self.sync_directory(self.path)

    def save(self, name, data):
        with (self.path / name).open('xb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        self.sync_directory(self.path)
        self.emit('saved', file=name, sha256=sha(data), size=len(data))

    def close(self):
        self.file.close()


def frame(payload):
    # Size excludes flow ID but includes the checksum; these cancel numerically.
    if not 2 <= len(payload) <= 0xFFFF or payload[0] != 0xFF:
        raise ValueError('Invalid monitor payload')
    checksum = 0
    for b in payload:
        checksum ^= b
    return b'\xad' + struct.pack('>H', len(payload)) + payload + bytes([checksum])


class Monitor:
    """Bounded USB framing; event packets may interleave with read responses."""
    def __init__(self, device, journal, timeout_error):
        self.device, self.journal, self.timeout_error = device, journal, timeout_error
        self.pending = bytearray()
        self.rid = 0

    def send(self, payload):
        request = frame(payload)
        if self.device.write(1, request, timeout=1000) != len(request):
            raise IOError('Short USB transfer; outcome uncertain, no retry')

    def receive(self, rid, size, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            while len(self.pending) >= 3:
                length = int.from_bytes(self.pending[1:3], 'big')
                if self.pending[0] != 0xAD or not 2 <= length <= 1030:
                    raise IOError('Invalid USB frame header')
                total = length + 4
                if len(self.pending) < total:
                    break
                packet = bytes(self.pending[:total])
                del self.pending[:total]
                if frame(packet[3:-1]) != packet or packet[3] != 0xFF:
                    raise IOError('USB checksum or flow mismatch')
                if packet[4] == 0:
                    if len(packet) != 10:
                        raise IOError('Invalid event length')
                    event = int.from_bytes(packet[5:9], 'little')
                    self.journal.emit('device_event', value=event)
                    if event in EVENT_ERRORS:
                        raise IOError(f'Programmer error event {event:#x}')
                    if event not in (ROM_START, ROM_EXECUTING, READY, READY + 1):
                        raise IOError(f'Unexpected monitor event {event:#x}')
                    if rid == 0:
                        return packet[5:9]
                    continue
                if packet[4] != rid or len(packet) != size + 6:
                    raise IOError('Unexpected read ID/length; no resynchronization')
                return packet[5:-1]
            try:
                self.pending.extend(self.device.read(0x81, 4096, timeout=200))
            except self.timeout_error:
                pass
        raise TimeoutError('USB response deadline exceeded; no retry')

    def read(self, address, size):
        span(address, size, 0x100000000)
        result = bytearray()
        for offset in range(0, size, 1024):
            count = min(1024, size - offset)
            self.rid = self.rid % 255 + 1
            # Both big-endian count bytes precede a separate XOR checksum.
            # The legacy vendor reader omits that CRC; do not copy its frame.
            self.send(b'\xff\x03' + struct.pack('<I', address + offset)
                      + bytes([self.rid]) + struct.pack('>H', count))
            result.extend(self.receive(self.rid, count))
        return bytes(result)

    def write_ram(self, address, data):
        span(address, len(data), 0x100000000)
        # Only pinned loader SRAM or its first 4 KiB transfer buffer.
        ranges = ((0xA1C000A0, 0xA1C000B8), (0xA1C00280, 0xA1C0BD20),
                  (BUFFER, BUFFER + 4096))
        if not any(lo <= address and address + len(data) <= hi for lo, hi in ranges):
            raise ValueError('RAM write outside pinned programmer allocations')
        for offset in range(0, len(data), 1024):
            self.send(b'\xff\x83' + struct.pack('<I', address + offset)
                      + data[offset:offset + 1024])

    def internal(self, value):
        if value not in (0xFD, 0xFF):
            raise ValueError('Only monitor handshake and execute are allowed')
        self.send(b'\xff\x84' + struct.pack('<I', 5) + bytes([value]))


def read_lod(path):
    raw = path.read_bytes()
    if sha(raw) != LOD_SHA:
        raise ValueError('Only the pinned USB programmer is supported')
    result = audit(path)
    if result['sha256'] != LOD_SHA:
        raise ValueError('Only the pinned USB programmer is supported')
    memory = {}
    # Parse the same immutable bytes we hashed, even if the file changes later.
    for line in raw.decode('ascii').splitlines():
        line = line.strip()
        if line.startswith('@'):
            address = int(line[1:], 16)
        elif line and not line.startswith('#'):
            memory[address] = struct.pack('<I', int(line, 16))
            address += 4
    segments = []
    for lo, hi in result['intervals']:
        lo, hi = int(lo, 16), int(hi, 16)
        segments.append((lo | 0xA0000000, b''.join(memory[a] for a in range(lo, hi, 4))))
    geometry = b''.join(memory[a] for a in range(GEOMETRY_ADDRESS & 0x1FFFFFFF,
                                               (GEOMETRY_ADDRESS & 0x1FFFFFFF) + 28, 4))
    if geometry != GEOMETRY:
        raise ValueError('Pinned binary erase layout mismatch')
    layout = b''.join(memory[a] for a in range(LAYOUT_ADDRESS & 0x1FFFFFFF,
                                             (LAYOUT_ADDRESS & 0x1FFFFFFF) + len(LAYOUT), 4))
    if layout != LAYOUT:
        raise ValueError('Pinned binary flash layout descriptor mismatch')
    return segments


def load_programmer(monitor, segments, journal):
    for address, data in segments:
        monitor.write_ram(address, data)
        if monitor.read(address, len(data)) != data:
            raise IOError('Programmer RAM load verification failed; not executing')
    journal.emit('programmer_load_verified', sha256=LOD_SHA)
    monitor.write_ram(0xA1C000A0, struct.pack('<I', 0xFF))
    if monitor.read(0xA1C000A0, 4) != struct.pack('<I', 0xFF):
        raise IOError('Execution context not confirmed')
    journal.emit('programmer_start_intent', conditional_flash_status_write=True)
    monitor.internal(0xFF)
    deadline = time.monotonic() + 10
    # The ROM acknowledges execution before entering the non-returning loader.
    for expected in (ROM_EXECUTING, READY):
        event = monitor.receive(0, 4, timeout=max(0.01, deadline - time.monotonic()))
        if event != struct.pack('<I', expected):
            raise IOError(f'Unexpected programmer startup sequence; expected {expected:#x}')
    journal.emit('programmer_ready')


class Programmer:
    def __init__(self, monitor, journal, timeout=30):
        self.monitor, self.journal, self.timeout = monitor, journal, timeout
        self.slot = 0
        self.failed = False

    def initialize(self, expected_flash_id):
        # A fresh launch is mandatory; attaching to unknown mailbox state is unsafe.
        expected = struct.pack('<15I', 0xFB05FA01, *([0] * 10),
                               BUFFER, BUFFER + 0x10000, BUFFER + 0x20000, 0x10000)
        if self.monitor.read(MAP, 60) != expected:
            raise IOError('Unexpected fresh programmer ABI/mailbox/buffers')
        if self.monitor.read(GEOMETRY_ADDRESS, 28) != GEOMETRY:
            raise IOError('Runtime erase geometry mismatch')
        if self.monitor.read(LAYOUT_ADDRESS, len(LAYOUT)) != LAYOUT:
            raise IOError('Runtime flash layout pointer/size mismatch')
        # Pinned HAL context: checkirq + padding, raw ID, three ID bytes,
        # high-performance opcode. This is a post-startup check, not a safe
        # way to discover an unknown chip: startup may already have set QE.
        context = self.monitor.read(FLASH_CONTEXT, 12)
        raw_id = struct.unpack_from('<I', context, 4)[0]
        if (raw_id != expected_flash_id or context[8:11] != raw_id.to_bytes(4, 'little')[:3]
                or context[10] != 22):
            raise IOError('Runtime flash identity/capacity differs from qualification')
        self.journal.emit('runtime_flash_identity', jedec_id=raw_id, capacity=FLASH_SIZE)
        self.command(PING)
        self.command(PING)  # proves both slots, serialized
        slot = self.slot
        self.command(FINALIZE_INFO)
        count = struct.unpack('<I', self.monitor.read(MAP + 4 + slot * 20 + 12, 4))[0]
        if count != 1 or self.monitor.read(BUFFER, 8) != struct.pack('<II', 0, MAGIC):
            raise IOError('Unexpected finalization write footprint')

    def command(self, command, offset=0, data=b''):
        if self.failed:
            raise RuntimeError('Session failed; fresh readback required, no retry')
        if command == ERASE:
            span(offset, sector_size(offset))
            if data:
                raise ValueError('Erase has no payload')
        elif command == PROGRAM:
            span(offset, len(data))
            if len(data) > 4096:
                raise ValueError('Program chunks must be <= 4096 bytes')
        elif command not in (PING, FINALIZE_INFO, END) or offset or data:
            raise ValueError('Unsupported command or parameters')
        address = MAP + 4 + self.slot * 20
        try:
            status = struct.unpack('<I', self.monitor.read(address, 4))[0]
            if status not in (0, DONE):
                raise IOError('Mailbox not idle')
            if data:
                self.monitor.write_ram(BUFFER, data)
                if self.monitor.read(BUFFER, len(data)) != data:
                    raise IOError('Transfer buffer verification failed')
            params = struct.pack('<4I', offset, BUFFER, len(data), 0)
            self.monitor.write_ram(address + 4, params)
            if self.monitor.read(address + 4, 16) != params:
                raise IOError('Mailbox parameter readback failed')
            self.journal.emit('command_intent', command=command, slot=self.slot,
                              offset=offset, size=len(data), data_sha256=sha(data))
            self.monitor.write_ram(address, struct.pack('<I', command))
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                status = struct.unpack('<I', self.monitor.read(address, 4))[0]
                if status == DONE:
                    self.journal.emit('command_done', command=command, slot=self.slot)
                    self.slot ^= 1
                    return
                if status in ERRORS or status != command:
                    raise IOError(f'Unexpected command status {status:#x}')
                time.sleep(0.01)
            raise TimeoutError('Command deadline exceeded')
        except BaseException as exc:
            self.failed = True
            self.journal.emit('command_uncertain_or_failed', command=command,
                              slot=self.slot, error=str(exc))
            raise

    def read_flash(self, offset=0, size=FLASH_SIZE):
        span(offset, size, FLASH_SIZE)
        return self.monitor.read(FLASH_BASE + offset, size)


def restore(programmer, target, backup, unit, journal):
    try:
        return _restore(programmer, target, backup, unit, journal)
    except BaseException:
        # Readback and journal failures poison the session too, not just a
        # mailbox timeout. The caller cannot continue writing in this session.
        programmer.failed = True
        raise


def _restore(programmer, target, backup, unit, journal):
    current = programmer.read_flash()
    work = plan(current, target, backup, unit)
    journal.save('before-flash.bin', current)
    journal.emit('live_plan', plan=work)
    if not work['sectors']:
        journal.emit('no_changes', write_capability_proven=False)
        return work
    for sector in work['sectors']:
        offset, size = sector['offset'], sector['erase_bytes']
        original = current[offset:offset + size]
        if programmer.read_flash(offset, size) != original:
            raise IOError('Flash changed since planning')
        journal.save(f'sector-{offset:06x}.bin', original)
        programmer.command(ERASE, offset)
        if programmer.read_flash(offset, size) != b'\xff' * size:
            raise IOError('Erase verification failed; stop without retry')
        for start in range(offset, offset + size, 4096):
            chunk = target[start:start + 4096]
            if start == 0:
                chunk = b'\xff' * 4 + chunk[4:]
            programmer.command(PROGRAM, start, chunk)
        expected = target[offset:offset + size]
        if offset == 0:
            expected = b'\xff' * 4 + expected[4:]
        if programmer.read_flash(offset, size) != expected:
            raise IOError('Program verification failed; stop without retry')
        journal.emit('sector_verified', offset=offset, size=size)
    if work['finalize_boot_magic']:
        # Catch corruption outside the sectors just read, before enabling boot.
        if programmer.read_flash() != b'\xff' * 4 + target[4:]:
            raise IOError('Full flash verification failed before finalization')
        journal.emit('finalize_intent', offset=0, size=4, value=MAGIC)
        programmer.command(END)
    final = programmer.read_flash()
    journal.save('after-flash.bin', final)
    if final != target:
        journal.emit('verification_failed', actual_sha256=sha(final))
        raise IOError('Full flash verification failed after finalization')
    journal.emit('verified', sha256=sha(final), changed_sectors=len(work['sectors']),
                 rebooted=False, cold_recovery_proven=False)
    return work


def qualification(path, unit, backup, target):
    """Check locally reviewed evidence binding; this is not hardware detection."""
    if path is None:
        raise ValueError('Live execution requires --qualification; board/ROM access remain unqualified')
    info = json.loads(path.read_text())
    if (not isinstance(info, dict) or info.get('schema') != 1
            or info.get('scope') != 'spare_writer_test' or unit == ORIGINAL_UNIT):
        raise ValueError('Only reviewed spare_writer_test qualification is supported; original blocked')
    if (info.get('unit') != unit or info.get('backup_sha256') != sha(backup)
            or info.get('source_sha256') != sha(target)
            or info.get('programmer_sha256') != LOD_SHA or info.get('rom_sha256') != ROM_SHA):
        raise ValueError('Qualification does not match unit, backup, source, ROM and programmer')
    flash_id = info.get('flash_jedec_id')
    if type(flash_id) is not int or not 0 < flash_id < 0x1000000 or flash_id >> 16 != 22:
        raise ValueError('Reviewed 4 MiB flash JEDEC identity required')
    if not isinstance(info.get('evidence'), dict):
        raise ValueError('Reviewed evidence required')
    required = ('two_matching_backups', 'repeatable_rom_access', 'board_ram_power',
                'flash_chip_and_startup', 'experiment_review')
    for name in required:
        item = info.get('evidence', {}).get(name, {})
        if (not isinstance(item, dict) or item.get('result') != 'pass'
                or not isinstance(item.get('reviewed_by'), str) or not item['reviewed_by'].strip()
                or not isinstance(item.get('path'), str) or not item['path']
                or not isinstance(item.get('sha256'), str)):
            raise ValueError(f'Missing reviewed evidence: {name}')
        evidence = path.parent / item['path']
        if sha(evidence.read_bytes()) != item['sha256']:
            raise ValueError(f'Evidence hash mismatch: {name}')
    return info


def execute(args, target, backup):
    info = qualification(args.qualification, args.unit, backup, target)
    if args.lod is None or args.journal is None:
        raise ValueError('--execute requires --lod and a new --journal directory')
    if not args.journal.resolve().is_relative_to(LIVE_ROOT.resolve()):
        raise ValueError('--journal must be a new directory under gitignored firmware/live/')
    segments = read_lod(args.lod)
    # Delay PyUSB import and discovery until all offline checks pass.
    import usb.backend.libusb1
    import usb.core
    import usb.util
    from rda_dump import LIBUSB
    from rda_rom_recovery import device_named
    journal = Journal(args.journal)
    device = None
    try:
        journal.save('source.bin', target)
        journal.save('unit-backup.bin', backup)
        journal.emit('qualification', data=info)
        for name, item in info['evidence'].items():
            if name not in ('two_matching_backups', 'repeatable_rom_access', 'board_ram_power',
                            'flash_chip_and_startup', 'experiment_review'):
                continue
            evidence = (args.qualification.parent / item['path']).read_bytes()
            if sha(evidence) != item['sha256']:
                raise ValueError(f'Evidence changed since validation: {name}')
            journal.save(f'evidence-{name}.txt', evidence)
        backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
        device = device_named(backend, 'Coolsand Usb')
        monitor = Monitor(device, journal, usb.core.USBTimeoutError)
        monitor.internal(0xFD)
        if monitor.receive(0, 4) != struct.pack('<I', ROM_START):
            raise IOError('ROM handshake mismatch')
        if sha(monitor.read(0xA1E00000, 0x6000)) != ROM_SHA:
            raise IOError('Unsupported ROM image')
        before = monitor.read(FLASH_BASE, FLASH_SIZE)
        if monitor.read(FLASH_BASE, FLASH_SIZE) != before:
            raise IOError('Two live preflight reads differ')
        work = plan(before, target, backup, args.unit)
        journal.save('before-startup.bin', before)
        journal.emit('preflight', plan=work)
        if not work['sectors']:
            journal.emit('no_changes', programmer_loaded=False, write_capability_proven=False)
            return work
        load_programmer(monitor, segments, journal)
        programmer = Programmer(monitor, journal)
        programmer.initialize(info['flash_jedec_id'])
        if programmer.read_flash() != before:
            raise IOError('Flash differs after programmer startup')
        return restore(programmer, target, backup, args.unit, journal)
    except BaseException as exc:
        journal.emit('stopped', error=str(exc), automatic_retry=False)
        raise
    finally:
        journal.close()
        if device is not None:
            usb.util.dispose_resources(device)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unit', required=True, help='Physically confirmed printed unit ID')
    parser.add_argument('--backup', type=Path, required=True, help="This unit's baseline dump")
    parser.add_argument('--image', type=Path, required=True, help='Full 4 MiB target image')
    parser.add_argument('--current', type=Path, help='Offline current snapshot; defaults to backup')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--qualification', type=Path)
    parser.add_argument('--check-qualification', action='store_true', help='Validate evidence offline; never opens USB')
    parser.add_argument('--lod', type=Path)
    parser.add_argument('--journal', type=Path)
    args = parser.parse_args()
    try:
        backup, target = args.backup.read_bytes(), args.image.read_bytes()
        current = args.current.read_bytes() if args.current else backup
        work = plan(current, target, backup, args.unit)
        print(json.dumps({'mode': 'OFFLINE_PLAN', **work}, indent=2), flush=True)
        if args.check_qualification:
            if args.execute:
                raise ValueError('--check-qualification cannot be combined with --execute')
            qualification(args.qualification, args.unit, backup, target)
            print('Evidence hashes and review fields valid; this is not hardware qualification.', flush=True)
        if args.execute:
            if args.current:
                raise ValueError('--current is offline-only; execution plans from live reads')
            live = execute(args, target, backup)
            print(json.dumps({'mode': 'LIVE_VERIFIED' if live['sectors'] else 'LIVE_NO_CHANGES',
                              'source_sha256': live['source_sha256'],
                              'changed_sectors': len(live['sectors']),
                              'rebooted': False, 'cold_recovery_proven': False}), flush=True)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f'Stopped: {exc}\n')


if __name__ == '__main__':
    status = 0
    try:
        main()
    except SystemExit as exc:
        status = exc.code if isinstance(exc.code, int) else 1
    except KeyboardInterrupt:
        status = 130
    except Exception as exc:
        print(f'Stopped: {type(exc).__name__}: {exc}', file=sys.stderr)
        status = 1
    finally:
        # Avoid the known PyUSB/libusb interpreter-teardown hang on this Mac.
        # Journal writes are fsynced before reaching here.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(status)
