"""Offline protocol and destructive-operation fault tests. No USB discovery."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import rda_flash as f
from rda_lod_audit import audit

BUILD = f.LIVE_ROOT / 'usb-programmer-build'
PINNED_LOD = BUILD / 'clean/artifacts/usb_8955_flsh_spi32m_ramrun_noclk_200ma.lod'
# The unmodified SDK build. ROM acknowledges its execution, but it never reaches
# READY: its 104 MHz clock request runs on a clock framework that was never opened.
UNFIXED_LOD = BUILD / 'artifacts/usb_8955_flsh_spi32m_ramrun.lod'
UNFIXED_SHA = '8a3ea6257de0c4d584d9f04d8e19db73ee54d8eee0a47fc3ddcaebb2f8af9dd1'

# Synthetic Winbond-shaped ID for the simulator, NOT the tracker's identity.
TEST_FLASH_ID = 0x1640EF

def image():
    data = bytearray(b'\xff' * f.FLASH_SIZE)
    struct.pack_into('<I', data, 0, f.MAGIC)
    data[f.PROTECTED:] = b'\x57' * (f.FLASH_SIZE - f.PROTECTED)
    return bytes(data)


class Events:
    def __init__(self):
        self.events = []

    def emit(self, event, **fields):
        self.events.append((event, fields))


class Memory:
    """Independent RAM mailbox and NOR-flash model with strict slot scheduling."""
    def __init__(self, contents):
        self.flash = bytearray(contents)
        self.ram = {}
        self.expected_slot = 0
        self.commands = []
        self.failure = None
        self.finalize_pending = False
        self.put(f.MAP, struct.pack('<15I', 0xFB05FA01, *([0] * 10),
                                   f.BUFFER, f.BUFFER + 65536, f.BUFFER + 131072, 65536))
        self.put(f.GEOMETRY_ADDRESS, f.GEOMETRY)
        self.put(f.LAYOUT_ADDRESS, f.LAYOUT)
        self.put(f.FLASH_CONTEXT, struct.pack('<II4B', 0, TEST_FLASH_ID, 0xEF, 0x40, 22, 0xA3))

    def put(self, address, data):
        self.ram.update({address + i: b for i, b in enumerate(data)})

    def read(self, address, size):
        if f.FLASH_BASE <= address < f.FLASH_BASE + f.FLASH_SIZE:
            offset = address - f.FLASH_BASE
            return bytes(self.flash[offset:offset + size])
        return bytes(self.ram.get(address + i, 0) for i in range(size))

    def write_ram(self, address, data):
        self.put(address, data)
        if address not in (f.MAP + 4, f.MAP + 24) or len(data) != 4:
            return
        slot = (address - f.MAP - 4) // 20
        command, offset, buffer, size, checksum = struct.unpack('<5I', self.read(address, 20))
        if slot != self.expected_slot:
            raise AssertionError('Host used wrong command slot')
        self.commands.append((command, offset, size))
        if self.failure == 'disconnect':
            raise IOError('Injected disconnect after publishing command')
        if self.failure == 'timeout':
            return
        if self.failure == 'error':
            self.put(address, struct.pack('<I', 0xFFFFFF9D))
            return
        if command == f.ERASE:
            count = 65536 if offset < 0x3F0000 else 4096
            if offset % count or offset + count > f.PROTECTED:
                raise AssertionError('Destructive footprint violated')
            self.flash[offset:offset + count] = b'\xff' * count
            if self.failure == 'erase_corruption':
                self.flash[offset] = 0
        elif command == f.PROGRAM:
            if not 0 < size <= 4096 or offset + size > f.PROTECTED:
                raise AssertionError('Invalid program footprint')
            payload = self.read(buffer, size)
            for i, b in enumerate(payload):
                self.flash[offset + i] &= b
            if offset == 0:
                if payload[:4] != b'\xff' * 4:
                    raise AssertionError('Boot magic must remain erased until END')
                self.finalize_pending = True
            if self.failure == 'program_corruption':
                self.flash[offset + 8] ^= 1
        elif command == f.END:
            if not self.finalize_pending:
                raise AssertionError('Unexpected END')
            self.flash[:4] = struct.pack('<I', f.MAGIC)
            if self.failure == 'finalize_corruption':
                self.flash[f.PROTECTED] ^= 1
        elif command == f.FINALIZE_INFO:
            self.put(buffer, struct.pack('<II', 0, f.MAGIC))
            self.put(address + 12, struct.pack('<I', 1))
        elif command != f.PING:
            raise AssertionError('Unexpected command')
        self.put(address, struct.pack('<I', f.DONE))
        self.expected_slot ^= 1


class FlashTests(unittest.TestCase):
    def setUp(self):
        self.backup = image()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal = f.Journal(Path(self.temp.name) / 'run')
        self.addCleanup(self.journal.close)
        self.memory = Memory(self.backup)
        self.programmer = f.Programmer(self.memory, self.journal, timeout=0.02)

    def target(self, *offsets):
        data = bytearray(self.backup)
        for offset in offsets:
            data[offset] = 0x42
        return bytes(data)

    def test_exact_geometry_boot_last_and_tail_boundary(self):
        work = f.plan(self.backup, self.target(16, 0x10001, 0x3F9004), self.backup, '417')
        self.assertEqual([(s['offset'], s['erase_bytes']) for s in work['sectors']],
                         [(0x10000, 65536), (0x3F9000, 4096), (0, 65536)])

    def test_protected_and_bad_image_refused(self):
        for target in (self.target(f.PROTECTED), self.backup[:-1], b'\x00' * f.FLASH_SIZE):
            with self.assertRaises(ValueError):
                f.plan(self.backup, target, self.backup, '417')
        with self.assertRaises(ValueError):
            f.plan(self.target(f.PROTECTED), self.backup, self.backup, '417')

    def test_invalid_and_alias_footprints(self):
        for offset, size in [(-4, 4), (0, 0), (1, 4), (0, 3), (f.PROTECTED, 4),
                             (0x88000000, 4096), (0x3F0000, 65536), (0xFFFFFFFC, 8)]:
            with self.assertRaises(ValueError):
                f.span(offset, size)
        for offset in (4, 0x10004, 0x3F0004):
            with self.assertRaises(ValueError):
                f.sector_size(offset)

    def test_noop_never_sends_flash_commands(self):
        f.restore(self.programmer, self.backup, self.backup, '417', self.journal)
        self.assertEqual(self.memory.commands, [])

    def test_full_restore_boot_finalized_last_and_durable_evidence(self):
        self.programmer.initialize(TEST_FLASH_ID)
        target = self.target(16, 0x10004, 0x3F9004)
        f.restore(self.programmer, target, self.backup, '417', self.journal)
        self.assertEqual(bytes(self.memory.flash), target)
        self.assertEqual(self.memory.commands[-1][0], f.END)
        self.assertEqual([offset for cmd, offset, _ in self.memory.commands if cmd == f.ERASE],
                         [0x10000, 0x3F9000, 0])
        self.assertTrue(all(size <= 4096 for cmd, _, size in self.memory.commands if cmd == f.PROGRAM))
        self.assertEqual((self.journal.path / 'before-flash.bin').read_bytes(), self.backup)
        entries = [json.loads(line) for line in (self.journal.path / 'operations.jsonl').read_text().splitlines()]
        self.assertEqual(entries[-1]['event'], 'verified')
        intents = [e for e in entries if e['event'] == 'command_intent']
        self.assertEqual(len(intents), len(self.memory.commands))

    def test_nonboot_write_does_not_finalize(self):
        f.restore(self.programmer, self.target(0x20000), self.backup, '417', self.journal)
        self.assertNotIn(f.END, [c[0] for c in self.memory.commands])

    def test_erase_readback_failure_stops_before_program(self):
        self.memory.failure = 'erase_corruption'
        with self.assertRaisesRegex(IOError, 'Erase verification'):
            f.restore(self.programmer, self.target(0x10000), self.backup, '417', self.journal)
        self.assertEqual(len(self.memory.commands), 1)
        with self.assertRaisesRegex(RuntimeError, 'Session failed'):
            self.programmer.command(f.PROGRAM, 0x10000, b'\xff' * 4)

    def test_program_readback_failure_stops_before_next_sector(self):
        self.memory.failure = 'program_corruption'
        with self.assertRaisesRegex(IOError, 'Program verification'):
            f.restore(self.programmer, self.target(0x10000, 0x20000), self.backup, '417', self.journal)
        self.assertEqual(sum(c[0] == f.ERASE for c in self.memory.commands), 1)

    def test_finalization_must_pass_full_readback(self):
        self.memory.failure = 'finalize_corruption'
        with self.assertRaisesRegex(IOError, 'Full flash verification'):
            f.restore(self.programmer, self.target(16), self.backup, '417', self.journal)

    def test_uncertain_commands_never_retried(self):
        for failure in ('disconnect', 'timeout', 'error'):
            with self.subTest(failure=failure):
                memory = Memory(self.backup)
                memory.failure = failure
                programmer = f.Programmer(memory, self.journal, timeout=0.001)
                with self.assertRaises((IOError, TimeoutError)):
                    programmer.command(f.ERASE, 0x10000)
                with self.assertRaisesRegex(RuntimeError, 'Session failed'):
                    programmer.command(f.ERASE, 0x10000)
                self.assertEqual(len(memory.commands), 1)

    def test_bad_abi_and_geometry_before_commands(self):
        for address in (f.MAP, f.MAP + 44, f.GEOMETRY_ADDRESS,
                        f.LAYOUT_ADDRESS, f.LAYOUT_ADDRESS + 4, f.LAYOUT_ADDRESS + 8,
                        f.FLASH_CONTEXT + 4, f.FLASH_CONTEXT + 8):
            memory = Memory(self.backup)
            memory.put(address, b'\x01' * 4)
            with self.assertRaises(IOError):
                f.Programmer(memory, self.journal).initialize(TEST_FLASH_ID)
            self.assertEqual(memory.commands, [])

    def test_unsafe_commands_refused(self):
        for command, offset, data in [(3, 0, b''), (15, 0, b''), (f.ERASE, f.PROTECTED, b''),
                                      (f.PROGRAM, 0, b'\xff' * 65536), (f.END, 4, b'')]:
            with self.assertRaises(ValueError):
                self.programmer.command(command, offset, data)
        self.assertEqual(self.memory.commands, [])

    def test_journal_cannot_overwrite_a_previous_run(self):
        with self.assertRaises(FileExistsError):
            f.Journal(self.journal.path)

    def test_missing_qualification_refuses_execution_before_usb_import(self):
        with self.assertRaisesRegex(ValueError, 'qualification'):
            f.qualification(None, '417', self.backup, self.backup)

    def test_corruption_in_unchanged_sector_blocks_boot_finalization(self):
        real_read = self.programmer.read_flash

        def read(offset=0, size=f.FLASH_SIZE):
            if size == f.FLASH_SIZE and self.memory.finalize_pending:
                self.memory.flash[f.PROTECTED] ^= 1
            return real_read(offset, size)

        with patch.object(self.programmer, 'read_flash', side_effect=read):
            with self.assertRaisesRegex(IOError, 'before finalization'):
                f.restore(self.programmer, self.target(16), self.backup, '417', self.journal)
        self.assertNotIn(f.END, [c[0] for c in self.memory.commands])
        self.assertEqual(self.memory.flash[:4], b'\xff' * 4)

    def test_finalization_info_mismatch_aborts_initialization(self):
        real_read = self.memory.read
        with patch.object(self.memory, 'read', side_effect=lambda a, n:
                          b'\xff' * n if (a, n) == (f.BUFFER, 8) else real_read(a, n)):
            with self.assertRaisesRegex(IOError, 'finalization write footprint'):
                self.programmer.initialize(TEST_FLASH_ID)
        self.assertFalse(any(c[0] in (f.ERASE, f.PROGRAM, f.END) for c in self.memory.commands))

    def passing_qualification(self):
        root = Path(self.temp.name)
        evidence = root / 'review.txt'
        evidence.write_text('SIMULATED EVIDENCE ONLY')
        item = {'path': evidence.name, 'sha256': f.sha(evidence.read_bytes()),
                'result': 'pass', 'reviewed_by': 'test fixture'}
        info = {'schema': 1, 'scope': 'spare_writer_test', 'unit': 'simulated-spare',
                'backup_sha256': f.sha(self.backup), 'source_sha256': f.sha(self.backup),
                'programmer_sha256': f.LOD_SHA, 'rom_sha256': f.ROM_SHA,
                'flash_jedec_id': TEST_FLASH_ID,
                'evidence': {name: dict(item) for name in ('two_matching_backups',
                    'repeatable_rom_access', 'board_ram_power', 'flash_chip_and_startup', 'experiment_review')}}
        path = root / 'qualification.json'
        path.write_text(json.dumps(info))
        return path, info

    def test_qualification_for_the_unfixed_programmer_is_rejected(self):
        # Evidence gathered for one programmer binary says nothing about another.
        path, info = self.passing_qualification()
        info['programmer_sha256'] = UNFIXED_SHA
        path.write_text(json.dumps(info))
        with self.assertRaisesRegex(ValueError, 'programmer'):
            f.qualification(path, 'simulated-spare', self.backup, self.backup)

    def test_qualification_binds_review_unit_source_and_evidence(self):
        path, info = self.passing_qualification()
        self.assertEqual(f.qualification(path, 'simulated-spare', self.backup, self.backup), info)
        for unit, target in ((f.ORIGINAL_UNIT, self.backup), ('another', self.backup),
                             ('simulated-spare', self.target(16))):
            with self.assertRaises(ValueError):
                f.qualification(path, unit, self.backup, target)
        for field, value in (('result', 'fail'), ('reviewed_by', ''), ('sha256', '0' * 64)):
            bad = json.loads(json.dumps(info))
            bad['evidence']['repeatable_rom_access'][field] = value
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                f.qualification(path, 'simulated-spare', self.backup, self.backup)


class Endpoint:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.sent = []

    def read(self, *args, **kwargs):
        return next(self.chunks)

    def write(self, endpoint, data, **kwargs):
        self.sent.append(data)
        return len(data)


class TransportTests(unittest.TestCase):
    def monitor(self, chunks):
        endpoint = Endpoint(chunks)
        return f.Monitor(endpoint, Events(), TimeoutError), endpoint

    def test_fragmented_coalesced_event_and_read(self):
        event = f.frame(b'\xff\x00' + struct.pack('<I', 0xF0))
        reply = f.frame(b'\xff\x01abcd')
        packet = event + reply
        monitor, endpoint = self.monitor([packet[:2], packet[2:7], packet[7:]])
        self.assertEqual(monitor.read(f.BUFFER, 4), b'abcd')
        self.assertEqual(endpoint.sent[0], f.frame(b'\xff\x03\x00\x00\x00\xa2\x01\x00\x04'))

    def test_corruption_wrong_id_and_malformed_lengths(self):
        valid = f.frame(b'\xff\x01abcd')
        for packet in (valid[:-1] + bytes([valid[-1] ^ 1]), f.frame(b'\xff\x02abcd'),
                       b'\xad\xff\xff', f.frame(b'\xff\x01abcdefgh')):
            with self.subTest(packet=packet):
                monitor, _ = self.monitor([packet])
                with self.assertRaises(IOError):
                    monitor.read(f.BUFFER, 4)

    def test_error_event_aborts(self):
        for event in (0xCE, 0xC0, 0xE0, 0xE1, 0xEBC0EEE1, 0xEBC0EEE2, 0xFF000002, 0xFF000005):
            monitor, _ = self.monitor([f.frame(b'\xff\x00' + struct.pack('<I', event))])
            with self.assertRaisesRegex(IOError, 'error event'):
                monitor.read(f.BUFFER, 4)

    def test_source_derived_wire_vectors(self):
        # Literal source-derived vectors, independent of frame() in assertions.
        monitor, endpoint = self.monitor([bytes.fromhex('ad0006ff0161626364fa')])
        self.assertEqual(monitor.read(f.BUFFER, 4), b'abcd')
        self.assertEqual(endpoint.sent.pop(), bytes.fromhex('ad0009ff03000000a20100045b'))
        monitor.internal(0xFD)
        self.assertEqual(endpoint.sent.pop(), bytes.fromhex('ad0007ff8405000000fd83'))
        monitor.internal(0xFF)
        self.assertEqual(endpoint.sent.pop(), bytes.fromhex('ad0007ff8405000000ff81'))

    def test_write_length_does_not_write_checksum_into_ram(self):
        monitor, endpoint = self.monitor([])
        payload = bytes(range(256)) * 4 + b'abcd'
        monitor.write_ram(f.BUFFER, payload)
        self.assertEqual(len(endpoint.sent), 2)
        for packet, count, offset in zip(endpoint.sent, (1024, 4), (0, 1024)):
            size = int.from_bytes(packet[1:3], 'big')
            self.assertEqual(size, count + 6)  # cmd + address + data + CRC
            self.assertEqual(len(packet), size + 4)
            self.assertEqual(packet[3:5], b'\xff\x83')
            self.assertEqual(struct.unpack_from('<I', packet, 5)[0], f.BUFFER + offset)
            # ROM subtracts cmd(1), address(4), CRC(1) from header DataSize.
            self.assertEqual(packet[9:9 + size - 6], payload[offset:offset + count])

    def test_startup_requires_execution_ack_then_ready(self):
        for values, succeeds in (((f.ROM_EXECUTING, f.READY), True),
                                 ((f.READY,), False), ((f.ROM_EXECUTING, f.READY + 1), False)):
            monitor = Memory(image())
            monitor.internal = lambda _: None
            events = iter(struct.pack('<I', v) for v in values)
            monitor.receive = lambda *args, **kwargs: next(events)
            if succeeds:
                f.load_programmer(monitor, [(0xA1C00280, b'abcd')], Events())
            else:
                with self.assertRaisesRegex(IOError, 'startup sequence'):
                    f.load_programmer(monitor, [(0xA1C00280, b'abcd')], Events())

    def test_short_write_is_not_retried(self):
        monitor, endpoint = self.monitor([])
        with patch.object(endpoint, 'write', return_value=1) as write:
            with self.assertRaisesRegex(IOError, 'Short USB transfer'):
                monitor.write_ram(f.BUFFER, b'abcd')
            self.assertEqual(write.call_count, 1)

    def test_ram_allowlist_blocks_flash_mmio_and_overruns(self):
        monitor, endpoint = self.monitor([])
        for address, size in ((f.FLASH_BASE, 4), (0xA1A000A0, 4), (f.BUFFER, 4100),
                              (0xA1C000B4, 8), (f.IMAGE_END - 4, 8)):
            with self.assertRaises(ValueError):
                monitor.write_ram(address, b'\x00' * size)
        self.assertEqual(endpoint.sent, [])

    def test_loader_readback_failure_never_launches(self):
        monitor = Memory(image())
        monitor.internal = lambda _: self.fail('Must not launch')
        with patch.object(monitor, 'read', return_value=b'bad!'):
            with self.assertRaisesRegex(IOError, 'RAM load verification'):
                f.load_programmer(monitor, [(0xA1C00280, b'1234')], Events())


class Device:
    """Monitor-protocol endpoint over internal SRAM: keeps writes, answers reads, starts once."""
    def __init__(self):
        self.ram = bytearray(0x10000)
        self.replies = bytearray()
        self.executed = 0

    def write(self, endpoint, request, **kwargs):
        payload = request[3:-1]
        if payload[:2] == b'\xff\x83':
            offset = struct.unpack_from('<I', payload, 2)[0] - 0xA1C00000
            self.ram[offset:offset + len(payload) - 6] = payload[6:]
        elif payload[:2] == b'\xff\x03':
            address, rid = struct.unpack_from('<IB', payload, 2)
            count = int.from_bytes(payload[7:9], 'big')
            data = self.ram[address - 0xA1C00000:][:count]
            self.replies += f.frame(b'\xff' + bytes([rid]) + data)
        elif payload == b'\xff\x84' + struct.pack('<I', 5) + b'\xff':
            self.executed += 1
            for value in (f.ROM_EXECUTING, f.READY):
                self.replies += f.frame(b'\xff\x00' + struct.pack('<I', value))
        return len(request)

    def read(self, endpoint, size, **kwargs):
        if not self.replies:
            raise TimeoutError
        data = bytes(self.replies[:size])
        del self.replies[:size]
        return data


@unittest.skipUnless(PINNED_LOD.exists(), 'programmer builds are local, gitignored artifacts')
class PinnedProgrammerTests(unittest.TestCase):
    def test_pinned_image_holds_the_tables_where_the_writer_reads_them(self):
        segments = f.read_lod(PINNED_LOD)
        self.assertEqual(segments[0], (0xA1C000A0, struct.pack('<6I', 0, 0x81C00280, 0, 0, 0, 0)))
        start, image = segments[1]
        self.assertEqual(start, 0xA1C00280)
        self.assertEqual(image[f.MAP - start:][:60],
                         struct.pack('<15I', 0xFB05FA01, *([0] * 10),
                                     f.BUFFER, f.BUFFER + 0x10000, f.BUFFER + 0x20000, 0x10000))
        self.assertEqual(image[f.GEOMETRY_ADDRESS - start:][:28], f.GEOMETRY)
        self.assertEqual(image[f.LAYOUT_ADDRESS - start:][:len(f.LAYOUT)], f.LAYOUT)
        # The layout descriptor points at the bank table through its cached alias.
        self.assertEqual(struct.unpack_from('<I', f.LAYOUT, 4)[0],
                         f.GEOMETRY_ADDRESS - 0x20000000)

    @unittest.skipUnless(UNFIXED_LOD.exists(), 'programmer builds are local, gitignored artifacts')
    def test_unfixed_stock_build_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'Only the pinned'):
            f.read_lod(UNFIXED_LOD)

    def test_ram_write_allowlist_ends_exactly_at_the_pinned_image(self):
        end = int(audit(PINNED_LOD)['intervals'][-1][1], 16) | 0xA0000000
        endpoint = Endpoint([])
        monitor = f.Monitor(endpoint, Events(), TimeoutError)
        monitor.write_ram(end - 4, bytes(4))
        self.assertEqual(len(endpoint.sent), 1)
        with self.assertRaises(ValueError):
            monitor.write_ram(end - 4, bytes(8))
        self.assertEqual(len(endpoint.sent), 1)

    def test_allowlist_end_that_is_not_the_images_end_is_refused_at_load(self):
        # A build moves the end of the image; a stale end would leave the allowlist too wide.
        for wrong in (f.IMAGE_END + 4, f.IMAGE_END - 4):
            with patch.object(f, 'IMAGE_END', wrong):
                with self.assertRaisesRegex(ValueError, 'load range'):
                    f.read_lod(PINNED_LOD)

    def test_whole_pinned_image_loads_and_starts_through_the_writers_monitor(self):
        segments = f.read_lod(PINNED_LOD)
        device, journal = Device(), Events()
        f.load_programmer(f.Monitor(device, journal, TimeoutError), segments, journal)
        self.assertEqual(device.executed, 1)
        self.assertEqual(journal.events[-1][0], 'programmer_ready')
        start, image = segments[1]
        self.assertEqual(bytes(device.ram[start - 0xA1C00000:][:len(image)]), image)
        self.assertEqual(bytes(device.ram[0xA0:0xB8]),
                         struct.pack('<6I', 0xFF, 0x81C00280, 0, 0, 0, 0))


if __name__ == '__main__':
    unittest.main()
