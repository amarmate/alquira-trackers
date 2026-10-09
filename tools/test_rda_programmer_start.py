import contextlib
import io
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from rda_flash import (frame, read_lod, MAP, FLASH_BASE, FLASH_SIZE, FLASH_CONTEXT, BUFFER,
                       ROM_EXECUTING, ROM_START, READY, GEOMETRY_ADDRESS, GEOMETRY,
                       LAYOUT_ADDRESS, MAGIC, PROGRAM, ERASE, END, FINALIZE_INFO, PING, DONE)
import rda_flash
import rda_programmer_start
from rda_programmer_start import (StartMonitor, wait_ready, load_and_start, inspect_runtime,
                                  read_local_lod, MARKER_LOD, MARKER_SHA, MARKER_RUNTIME,
                                  STATUS_LOD, STATUS_SHA, STATUS_RUNTIME, UNLOCK_LOD, UNLOCK_SHA,
                                  UNLOCK_RUNTIME, PINNED_RUNTIME, RESET)

# The locally built programmers are gitignored artifacts, so each test skips a missing one.
LOCAL_BUILDS = {'marker': (MARKER_LOD, MARKER_SHA, MARKER_RUNTIME),
                'status': (STATUS_LOD, STATUS_SHA, STATUS_RUNTIME),
                'unlock': (UNLOCK_LOD, UNLOCK_SHA, UNLOCK_RUNTIME)}


class Endpoint:
    def __init__(self, chunks=()):
        self.chunks = iter(chunks)
        self.written = []

    def write(self, endpoint, data, **kwargs):
        self.written.append(data)
        return len(data)

    def read(self, *args, **kwargs):
        return next(self.chunks)


def event(value):
    return frame(b'\xff\x00' + struct.pack('<I', value))


class StartOnlyTests(unittest.TestCase):
    def setUp(self):
        self.journal = mock.Mock()
        self.device = Endpoint()
        self.segments = [(0xA1C000A0, struct.pack('<6I', 0, 0x81C00280, 0, 0, 0, 0)),
                         (0xA1C00280, b'\x11' * 1028)]
        self.monitor = StartMonitor(self.device, self.journal, TimeoutError, self.segments)

    def test_forbidden_frames_never_reach_usb(self):
        self.monitor.armed = True
        for address in (MAP + 4, MAP + 24, FLASH_BASE, BUFFER, 0xA1A000A0):
            for cmd in (1, 2, 4, 6, 9):
                payload = b'\xff\x83' + struct.pack('<II', address, cmd)
                with self.assertRaises(ValueError):
                    self.monitor.send(payload)
        for value in (0xFE, 0xEE):
            with self.assertRaises(ValueError):
                self.monitor.send(b'\xff\x84' + struct.pack('<I', 5) + bytes([value]))
        self.assertEqual(self.device.written, [])

    def test_load_requires_arm_and_exact_order(self):
        with self.assertRaises(ValueError):
            self.monitor.send(self.monitor.writes[0])
        self.monitor.armed = True
        with self.assertRaises(ValueError):
            self.monitor.send(self.monitor.writes[1])
        with self.assertRaises(ValueError):
            self.monitor.send(self.monitor.writes[0][:-1] + b'\x01')
        self.assertEqual(self.device.written, [])

    def test_execute_once_and_no_writes_afterwards(self):
        self.monitor.armed = True
        with self.assertRaises(ValueError):
            self.monitor.internal(0xFF)
        for packet in self.monitor.writes:
            self.monitor.send(packet)
        self.monitor.internal(0xFF)
        sent = len(self.device.written)
        for packet in self.monitor.writes:
            with self.assertRaises(ValueError):
                self.monitor.send(packet)
        with self.assertRaises(ValueError):
            self.monitor.internal(0xFF)
        with self.assertRaises(ValueError):
            self.monitor.internal(0xFD)
        self.assertEqual(len(self.device.written), sent)

    def test_short_load_transfer_cannot_be_retried(self):
        self.monitor.armed = True
        self.device.write = mock.Mock(return_value=0)
        with self.assertRaises(IOError):
            self.monitor.send(self.monitor.writes[0])
        with self.assertRaises(ValueError):
            self.monitor.send(self.monitor.writes[0])
        self.assertEqual(self.device.write.call_count, 1)

    def test_ram_mismatch_never_executes(self):
        self.monitor.read = mock.Mock(return_value=b'wrong')
        with self.assertRaisesRegex(IOError, 'RAM load mismatch'):
            load_and_start(self.monitor, self.segments, self.journal)
        self.assertFalse(self.monitor.executed)

    def test_fragmented_and_coalesced_diagnostics_with_ready_value_as_data(self):
        values = [ROM_EXECUTING, 0xEBC0EEE2, READY, 0xA5A5A5A5, 0, 0, 0xC0, READY]
        raw = b''.join(event(v) for v in values)
        self.device.chunks = iter([raw[:2], raw[2:7], raw[7:]])
        wait_ready(self.monitor)
        recorded = [call.kwargs['value'] for call in self.journal.emit.call_args_list
                    if call.args[0] == 'startup_event']
        self.assertEqual(recorded, [hex(v) for v in values])
        self.assertEqual(self.device.written, [])

    def test_high_address_diagnostic_has_five_data_words(self):
        self.device.chunks = iter([b''.join(event(v) for v in
            [ROM_EXECUTING, 0xEBC0EEE1, 0xA23C0000, READY, 0, 0, READY, 0xC0, READY])])
        wait_ready(self.monitor)
        self.assertEqual(self.journal.emit.call_args_list[-1].args[0], 'programmer_ready')

    def test_fatal_error_never_accepts_ready(self):
        self.device.chunks = iter([event(ROM_EXECUTING) + event(0xCE) + event(READY)])
        with self.assertRaisesRegex(IOError, 'fatal'):
            wait_ready(self.monitor)

    def test_ready_without_execution_ack_rejected(self):
        self.device.chunks = iter([event(READY)])
        with self.assertRaisesRegex(IOError, 'acknowledgement'):
            wait_ready(self.monitor)

    def test_corrupt_startup_event_rejected(self):
        raw = bytearray(event(ROM_EXECUTING))
        raw[-1] ^= 1
        self.device.chunks = iter([raw])
        with self.assertRaisesRegex(IOError, 'checksum'):
            self.monitor.startup_event(1)

    def test_stage_markers_are_recorded_without_changing_the_outcome(self):
        values = [ROM_EXECUTING, 0x5A000101, 0x5A000111, 0x5A00A001, 0x5A00000A, READY]
        self.device.chunks = iter([b''.join(event(v) for v in values)])
        wait_ready(self.monitor)
        recorded = [call.kwargs['value'] for call in self.journal.emit.call_args_list
                    if call.args[0] == 'startup_event']
        self.assertEqual(recorded, [hex(v) for v in values])
        self.assertEqual(self.journal.emit.call_args_list[-1].args[0], 'programmer_ready')

    def test_default_build_is_the_writers_pinned_programmer(self):
        # Without a flag the tool starts exactly what rda_flash.py would load, and
        # checks it at the writer's own addresses.
        self.need(rda_programmer_start.LOD)
        image = dict(read_lod(rda_programmer_start.LOD))[0xA1C00280]
        jedec = bytes(4) + bytes.fromhex('c8601600c8601600')

        def read(address, size):
            if address == FLASH_CONTEXT:
                return jedec  # filled in by the programmer at run time, not in the image
            return image[address - 0xA1C00280:][:size]
        self.monitor.read = read
        inspect_runtime(self.monitor, self.journal)
        self.assertEqual(self.journal.emit.call_args_list[-1].args[0], 'runtime_verified')

    def need(self, lod):
        if not lod.exists():
            self.skipTest(f'{lod.name} is a local, gitignored artifact')

    def test_local_lod_is_pinned_and_keeps_the_entry_context(self):
        for name, (lod, pinned_sha, where) in LOCAL_BUILDS.items():
            with self.subTest(build=name):
                self.need(lod)
                segments = read_local_lod(lod, pinned_sha, where)
                self.assertEqual(segments[0],
                                 (0xA1C000A0, struct.pack('<6I', 0, 0x81C00280, 0, 0, 0, 0)))
                self.assertEqual(segments[1][0], 0xA1C00280)
                with self.assertRaisesRegex(ValueError, 'not the pinned build'):
                    read_local_lod(lod, '0' * 64, where)

    def test_local_lod_with_another_builds_addresses_is_rejected(self):
        # Every build moves the flash tables, so one build's addresses must not pass for another.
        for name, (lod, pinned_sha, where) in LOCAL_BUILDS.items():
            with self.subTest(build=name):
                self.need(lod)
                with self.assertRaisesRegex(ValueError, 'flash layout mismatch'):
                    read_local_lod(lod, pinned_sha, PINNED_RUNTIME)

    def test_local_build_loads_and_executes_through_the_allowlist(self):
        # The marker image is larger than the stock one; the whole load path must accept it.
        for name, (lod, pinned_sha, where) in LOCAL_BUILDS.items():
            with self.subTest(build=name):
                self.need(lod)
                segments = read_local_lod(lod, pinned_sha, where)
                device = Endpoint()
                monitor = StartMonitor(device, self.journal, TimeoutError, segments)
                ram = bytearray(0x10000)

                def write(endpoint, request, **kwargs):
                    payload = request[3:-1]
                    if payload[:2] == b'\xff\x83':
                        offset = struct.unpack('<I', payload[2:6])[0] - 0xA1C00000
                        ram[offset:offset + len(payload) - 6] = payload[6:]
                    device.written.append(request)
                    return len(request)
                device.write = write
                monitor.read = lambda address, size: bytes(ram[address - 0xA1C00000:][:size])
                with mock.patch.object(rda_programmer_start, 'wait_ready'):
                    load_and_start(monitor, segments, self.journal, pinned_sha)
                self.assertTrue(monitor.executed)
                self.assertEqual(len(device.written), len(monitor.writes) + 1)

    def test_local_runtime_addresses_point_at_the_images_own_tables(self):
        for name, (lod, pinned_sha, where) in LOCAL_BUILDS.items():
            with self.subTest(build=name):
                self.need(lod)
                image = dict(read_local_lod(lod, pinned_sha, where))[0xA1C00280]
                jedec = bytes(4) + bytes.fromhex('c8601600c8601600')

                def read(address, size):
                    if address == where['flash_context']:
                        return jedec  # filled in by the programmer at run time, not in the image
                    return image[address - 0xA1C00280:][:size]
                self.monitor.read = read
                inspect_runtime(self.monitor, self.journal, where)
                self.assertEqual(self.journal.emit.call_args_list[-1].args[0], 'runtime_verified')
                self.monitor.read = lambda address, size: bytes(size)
                with self.assertRaisesRegex(IOError, 'ABI'):
                    inspect_runtime(self.monitor, self.journal, where)

    def test_read_status_loads_the_status_build_at_its_own_addresses(self):
        # The writer's build has no status command, and its mailbox is elsewhere.
        unit = rda_programmer_start.UNITS['1403167417']
        for path in (STATUS_LOD, unit['backup'], unit['baseline']):
            self.need(path)
        argv = ['rda_programmer_start.py', '--unit', '1403167417', '--read-status',
                '--execute', '--journal', str(rda_flash.LIVE_ROOT / 'never-created')]
        with mock.patch.object(rda_programmer_start, 'run') as run, \
                mock.patch('sys.argv', argv), contextlib.redirect_stdout(io.StringIO()):
            rda_programmer_start.main()
        args, _, _, segments, lod_sha, where = run.call_args.args
        self.assertEqual((lod_sha, where), (STATUS_SHA, STATUS_RUNTIME))
        self.assertEqual(segments, read_local_lod(STATUS_LOD, STATUS_SHA, STATUS_RUNTIME))
        self.assertTrue(args.query)  # the status read starts from the query's state

    def test_clear_protection_loads_the_unlock_build_at_its_own_addresses(self):
        # Only the unlock build has the command; the status build can only read.
        unit = rda_programmer_start.UNITS['1403167412']
        for path in (UNLOCK_LOD, unit['backup']):
            self.need(path)
        argv = ['rda_programmer_start.py', '--unit', '1403167412', '--clear-protection',
                '--execute', '--journal', str(rda_flash.LIVE_ROOT / 'never-created')]
        with mock.patch.object(rda_programmer_start, 'run') as run, \
                mock.patch('sys.argv', argv), contextlib.redirect_stdout(io.StringIO()):
            rda_programmer_start.main()
        args, _, _, segments, lod_sha, where = run.call_args.args
        self.assertEqual((lod_sha, where), (UNLOCK_SHA, UNLOCK_RUNTIME))
        self.assertEqual(segments, read_local_lod(UNLOCK_LOD, UNLOCK_SHA, UNLOCK_RUNTIME))
        self.assertTrue(args.query)


# A 4 MiB image whose only blank 64 KiB sector is the one the write test uses.
SECTOR = 0x3E0000
IMAGE = b'\x5a' * SECTOR + b'\xff' * 0x10000 + b'\x5a' * (FLASH_SIZE - SECTOR - 0x10000)


class RunningProgrammer:
    """USB endpoint of a started programmer: SRAM, mailbox, a flash image, and the
    commands the tool may send. Any other command is only recorded.

    `where` puts its tables at a local build's addresses. `status` makes it the status
    build, holding that value in flash status registers 2 and 1; without it the status
    command gets what the writer's build has for it, the default arm's error. `unlock`
    makes it the unlock build, which also has the command that clears protection."""
    def __init__(self, startup=(ROM_EXECUTING, READY), where=PINNED_RUNTIME, status=None,
                 unlock=False):
        self.startup = startup
        self.map = where['map']
        self.status = status
        self.unlock = unlock
        self.ram = {}
        self.replies = bytearray()
        self.writes = []
        self.commands = []
        self.resets = 0
        self.exits = 0
        self.boot_block_programmed = False
        self.flash = bytearray(IMAGE)
        self.footprints = []
        self.put(self.map, struct.pack('<15I', 0xFB05FA01, *([0] * 10),
                                       BUFFER, BUFFER + 0x10000, BUFFER + 0x20000, 0x10000))
        self.put(where['geometry'], GEOMETRY)
        # The descriptor points at the bank table by its cached address.
        self.put(where['layout'], struct.pack('<6I', 1, where['geometry'] - 0x20000000,
                                              FLASH_SIZE, 0x3F6000, 0x4000, 512))
        self.put(where['flash_context'], bytes(4) + bytes.fromhex('c8601600c8601600'))

    def put(self, address, data):
        self.ram.update({address + i: b for i, b in enumerate(data)})

    def get(self, address, size):
        if FLASH_BASE <= address < FLASH_BASE + FLASH_SIZE:
            return bytes(self.flash[address - FLASH_BASE:address - FLASH_BASE + size])
        return bytes(self.ram.get(address + i, 0) for i in range(size))

    def write(self, endpoint, request, **kwargs):
        payload = request[3:-1]
        if payload[:2] == b'\xff\x83':
            address = struct.unpack_from('<I', payload, 2)[0]
            self.writes.append((address, payload[6:]))
            self.put(address, payload[6:])
            if address in (self.map + 4, self.map + 24) and len(payload) == 10:
                self.run(address)
        elif payload[:2] == b'\xff\x03':
            address, rid = struct.unpack_from('<IB', payload, 2)
            count = int.from_bytes(payload[7:9], 'big')
            self.replies += frame(b'\xff' + bytes([rid]) + self.get(address, count))
        elif payload == b'\xff\x84' + struct.pack('<I', 5) + b'\xff':
            for value in self.startup:
                self.replies += event(value)
        elif payload == RESET:
            # The chip restarts into the ROM monitor: RAM state is gone, flash stays.
            self.resets += 1
            self.boot_block_programmed = False
            self.put(self.map, struct.pack('<15I', 0xFB05FA01, *([0] * 10),
                                           BUFFER, BUFFER + 0x10000, BUFFER + 0x20000, 0x10000))
        elif payload == rda_programmer_start.ROM_EXIT:
            self.exits += 1
        elif payload == b'\xff\x84' + struct.pack('<I', 5) + b'\xfd':
            self.replies += event(ROM_START)
        return len(request)

    def run(self, address):
        slot = (address - self.map - 4) // 20
        command, offset, buffer, size, _ = struct.unpack('<5I', self.get(address, 20))
        self.commands.append((slot, command))
        answered = False
        if command == 0x11 and self.status is not None:
            answered = True
        elif command == 0x12 and self.unlock and self.status == 0x021C:
            # As the unlock build's arm: only from QE with BP2-BP0, and only to QE alone.
            self.status = 0x0200
            answered = True
        elif command == 0x12 and self.unlock:
            # The arm's refusal of any other state: ERROR, and the error event.
            self.put(address, struct.pack('<I', 0xFFFFFF9D))
            self.replies += event(0xE0 + slot)
        elif command in (0x11, 0x12):
            # As flash_programmer.c's default arm: ERROR, and the unknown-command event.
            self.put(address, struct.pack('<I', 0xFFFFFF9D))
            self.replies += event(0xD0 + slot)
        if answered:
            # Both arms answer with the registers, and their complement above them.
            self.put(address + 12, struct.pack('<I', self.status | (self.status ^ 0xFFFF) << 16))
            self.put(address, struct.pack('<I', DONE))
            self.replies += event(READY + slot)
        if command == FINALIZE_INFO:
            self.put(buffer, struct.pack('<II', 0, MAGIC))
            self.put(address + 12, struct.pack('<I', 1))
        elif command == PROGRAM:
            self.footprints.append((offset, size))
            for i, b in enumerate(self.get(buffer, size)):
                self.flash[offset + i] &= b
            self.boot_block_programmed |= offset == 0
        elif command == ERASE:
            erase_size = rda_flash.sector_size(offset)
            self.footprints.append((offset, erase_size))
            self.flash[offset:offset + erase_size] = b'\xff' * erase_size
        elif command == END and self.boot_block_programmed:
            # As flash_programmer.c: END writes the word only after a program at zero.
            for i, b in enumerate(struct.pack('<I', MAGIC)):
                self.flash[i] &= b
            self.boot_block_programmed = False
        if command in (PING, FINALIZE_INFO, PROGRAM, ERASE, END):
            self.put(address, struct.pack('<I', DONE))
            # The event is queued ahead of the answer to the host's next status read.
            self.replies += event(READY + slot)

    def read(self, endpoint, size, **kwargs):
        if not self.replies:
            raise TimeoutError
        data = bytes(self.replies[:size])
        del self.replies[:size]
        return data


class RomPort:
    """USB endpoint of the ROM monitor after a reset: it answers the handshake only."""
    def __init__(self, answer=ROM_START):
        self.answer = answer
        self.flash = bytearray(IMAGE)
        self.replies = bytearray()
        self.requests = []

    def write(self, endpoint, request, **kwargs):
        self.requests.append(request[3:-1])
        if request[3:-1] == b'\xff\x84' + struct.pack('<I', 5) + b'\xfd':
            self.replies += event(self.answer)
        return len(request)

    def read(self, endpoint, size, **kwargs):
        if not self.replies:
            raise TimeoutError
        data = bytes(self.replies[:size])
        del self.replies[:size]
        return data


class QueryTests(unittest.TestCase):
    IDLE = struct.pack('<4I', 0, BUFFER, 0, 0)
    SIX_WRITES = [(MAP + 8, IDLE), (MAP + 4, struct.pack('<I', PING)),
                  (MAP + 28, IDLE), (MAP + 24, struct.pack('<I', PING)),
                  (MAP + 8, IDLE), (MAP + 4, struct.pack('<I', FINALIZE_INFO))]

    def setUp(self):
        self.journal = mock.Mock()
        self.flash = IMAGE

    def started(self, device=None):
        """Load and execute through the real allowlist, as run() does before a query."""
        device = device or RunningProgrammer()
        segments = [(0xA1C000A0, struct.pack('<6I', 0, 0x81C00280, 0, 0, 0, 0)),
                    (0xA1C00280, b'\x11' * 1028)]
        monitor = StartMonitor(device, self.journal, TimeoutError, segments)
        load_and_start(monitor, segments, self.journal)
        device.writes.clear()
        return monitor, device

    def query(self, monitor, reads=None, before=IMAGE, **where):
        # A full read is 4096 frames; the tests take the device's image directly instead.
        with mock.patch.object(rda_programmer_start, 'read_flash',
                               side_effect=reads or (lambda *_: bytes(monitor.device.flash))):
            return rda_programmer_start.query(monitor, self.journal, before, **where)

    def write_test(self, device=None, before=IMAGE):
        monitor, device = self.started(device)
        programmer = self.query(monitor, before=before)
        device.writes.clear()
        with mock.patch.object(rda_programmer_start, 'read_flash',
                               side_effect=lambda *_: bytes(device.flash)):
            rda_programmer_start.write_test(programmer, monitor, self.journal, before)

    def events(self):
        return [call.args[0] for call in self.journal.emit.call_args_list]

    def test_query_writes_ping_on_each_slot_then_finalize_info_and_nothing_else(self):
        monitor, device = self.started()
        self.query(monitor)
        self.assertEqual(device.writes, self.SIX_WRITES)
        self.assertEqual(device.commands, [(0, PING), (1, PING), (0, FINALIZE_INFO)])
        self.assertEqual(self.events()[-1], 'query_verified')
        answered = [call.kwargs['value'] for call in self.journal.emit.call_args_list
                    if call.args[0] == 'device_event']
        self.assertEqual(answered, [READY, READY + 1, READY])

    def test_mailbox_writes_stay_refused_after_start_until_a_query_arms_them(self):
        monitor, device = self.started()
        for address, data in self.SIX_WRITES:
            with self.assertRaises(ValueError):
                monitor.write_ram(address, data)
        self.assertEqual(device.writes, [])

    def test_armed_query_passes_only_the_six_exact_packets_in_order(self):
        monitor, device = self.started()
        monitor.allowed = rda_programmer_start.mailbox_packets(rda_programmer_start.QUERY)
        refused = [(MAP + 4, struct.pack('<I', command))
                   for command in (PROGRAM, ERASE, 3, END, 5, 7, 8, 10, 11, 15, 16)]
        refused += [self.SIX_WRITES[1],                              # command before its parameters
                    (MAP + 8, struct.pack('<4I', 0x10000, BUFFER, 0, 0)),  # a flash offset
                    (MAP + 8, struct.pack('<4I', 0, BUFFER, 4, 0)),        # a payload size
                    (BUFFER, bytes(4)), (FLASH_BASE, bytes(4)), (0xA1A000A0, bytes(4))]
        for address, data in refused:
            with self.assertRaises(ValueError):
                monitor.write_ram(address, data)
        self.assertEqual(device.writes, [])
        for address, data in self.SIX_WRITES:
            monitor.write_ram(address, data)
        for address, data in self.SIX_WRITES:
            with self.assertRaises(ValueError):
                monitor.write_ram(address, data)
        self.assertEqual(device.writes, self.SIX_WRITES)

    def test_query_refused_when_start_up_reported_more_than_ack_and_ready(self):
        # 0xc0 is the programmer's memory-power retry: the writer treats it as an error.
        monitor, device = self.started(RunningProgrammer((ROM_EXECUTING, 0xC0, READY)))
        with self.assertRaisesRegex(IOError, 'Start-up'):
            self.query(monitor)
        self.assertEqual(device.writes, [])

    def test_query_stops_when_the_mailbox_holds_anything_unexpected_afterwards(self):
        class Stray(RunningProgrammer):
            def run(self, address):
                super().run(address)
                self.put(MAP + 32, struct.pack('<I', 4))  # the other slot's size
        monitor, device = self.started(Stray())
        with self.assertRaisesRegex(IOError, 'mailbox'):
            self.query(monitor)
        self.assertNotIn('query_verified', self.events())

    def test_query_stops_when_flash_reads_differ_afterwards(self):
        for reads in ([b'\x00' + self.flash[1:], self.flash], [self.flash, b'\x00' + self.flash[1:]]):
            monitor, device = self.started()
            with self.assertRaisesRegex(IOError, 'Flash changed'):
                self.query(monitor, reads)
        self.assertNotIn('query_verified', self.events())

    def test_mailbox_commands_are_refused_for_the_marker_build(self):
        # The packets are addressed to the pinned build's mailbox, not the marker build's.
        for flag in ('--query', '--write-test', '--reset-test'):
            argv = ['rda_programmer_start.py', '--unit', '1403167417', '--markers', flag]
            stderr = io.StringIO()
            with mock.patch('sys.argv', argv), contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    rda_programmer_start.main()
            self.assertIn(f'{flag} needs the pinned build', stderr.getvalue())

    # The status command, 0x11, twice. The query left slot 1 as the next one.
    STATUS_WRITES = [(MAP + 28, IDLE), (MAP + 24, struct.pack('<I', 0x11)),
                     (MAP + 8, IDLE), (MAP + 4, struct.pack('<I', 0x11))]

    def read_status(self, device, reads=None, **where):
        monitor, device = self.started(device)
        programmer = self.query(monitor, **where)
        device.writes.clear()
        with mock.patch.object(rda_programmer_start, 'read_flash',
                               side_effect=reads or (lambda *_: bytes(device.flash))):
            return rda_programmer_start.read_status(programmer, monitor, self.journal,
                                                    IMAGE), monitor

    def test_read_status_sends_the_status_command_on_each_slot_and_nothing_else(self):
        device = RunningProgrammer(status=0x0200)
        _, monitor = self.read_status(device)
        self.assertEqual(device.writes, self.STATUS_WRITES)
        self.assertEqual(device.commands[3:], [(1, 0x11), (0, 0x11)])
        self.assertEqual(monitor.allowed, [])
        self.assertEqual(bytes(device.flash), IMAGE)

    def test_read_status_returns_registers_2_and_1_as_the_chip_holds_them(self):
        # Every block-protect bit, with CMP and QE: 0x42 in register 2, 0x7c in register 1.
        status, _ = self.read_status(RunningProgrammer(status=0x427C))
        self.assertEqual(status, 0x427C)
        last = self.journal.emit.call_args_list[-1]
        self.assertEqual(last.args[0], 'status_read')
        self.assertEqual((last.kwargs['status1'], last.kwargs['status2']), ('0x7c', '0x42'))
        self.assertEqual(last.kwargs['set_bits'],
                         ['BP0', 'BP1', 'BP2', 'BP3', 'BP4', 'QE', 'CMP'])

    def test_read_status_stops_when_the_two_readings_differ(self):
        def fault(device):
            device.status = 0x0204  # BP0 appears after the first reading
        with self.assertRaisesRegex(IOError, 'differ'):
            self.read_status(self.faulty(fault, status=0x0200))
        self.assertNotIn('status_read', self.events())

    def test_read_status_stops_when_the_size_field_is_not_the_arms_answer(self):
        def fault(device):
            # DONE, with the size field as the host left it: no complement above it.
            slot = device.commands[-1][0]
            device.put(MAP + 4 + slot * 20 + 12, bytes(4))
        with self.assertRaisesRegex(IOError, 'complement'):
            self.read_status(self.faulty(fault, status=0x0200))
        self.assertNotIn('status_read', self.events())

    def test_read_status_stops_on_a_programmer_without_the_command(self):
        device = RunningProgrammer()  # the writer's build
        with self.assertRaises(IOError):
            self.read_status(device)
        self.assertEqual(device.commands[3:], [(1, 0x11)])
        self.assertNotIn('status_read', self.events())

    def test_read_status_stops_when_a_write_is_in_progress_or_enabled(self):
        for status in (0x0201, 0x0202):  # WIP, WEL
            with self.assertRaisesRegex(IOError, 'WIP or WEL'):
                self.read_status(RunningProgrammer(status=status))
        self.assertNotIn('status_read', self.events())
        self.assertIn('status_word', self.events())  # what was read is still on record

    def test_read_status_stops_when_flash_reads_differ_afterwards(self):
        for reads in ([b'\x00' + IMAGE[1:], IMAGE], [IMAGE, b'\x00' + IMAGE[1:]]):
            with self.assertRaisesRegex(IOError, 'Flash changed'):
                self.read_status(RunningProgrammer(status=0x0200), reads)
        self.assertNotIn('status_read', self.events())

    def test_query_and_read_status_follow_a_local_builds_own_tables(self):
        # Every build moves the mailbox and the flash tables; the status build's are
        # not at the writer's addresses.
        where = dict(map=MAP + 0x90, geometry=GEOMETRY_ADDRESS + 0x90,
                     layout=LAYOUT_ADDRESS + 0x90, flash_context=FLASH_CONTEXT + 0x90)
        device = RunningProgrammer(where=where, status=0x0200)
        status, _ = self.read_status(device, where=where)
        self.assertEqual(status, 0x0200)
        self.assertEqual([address for address, _ in device.writes],
                         [MAP + 0x90 + 28, MAP + 0x90 + 24, MAP + 0x90 + 8, MAP + 0x90 + 4])
        self.assertEqual(device.commands, [(0, PING), (1, PING), (0, FINALIZE_INFO),
                                           (1, 0x11), (0, 0x11)])

    def clear_protection(self, device, reads=None):
        monitor, device = self.started(device)
        programmer = self.query(monitor)
        device.writes.clear()
        with mock.patch.object(rda_programmer_start, 'read_flash',
                               side_effect=reads or (lambda *_: bytes(device.flash))):
            rda_programmer_start.clear_protection(programmer, monitor, self.journal, IMAGE)
        return monitor

    def test_clear_protection_reads_twice_writes_once_and_reads_twice_again(self):
        # 412 as measured: QE with BP2-BP0, 0x02 and 0x1c. The command is 0x12.
        device = RunningProgrammer(status=0x021C, unlock=True)
        monitor = self.clear_protection(device)
        self.assertEqual(device.status, 0x0200)
        self.assertEqual(device.commands[3:],
                         [(1, 0x11), (0, 0x11), (1, 0x12), (0, 0x11), (1, 0x11)])
        word = lambda command: struct.pack('<I', command)
        self.assertEqual(device.writes,
                         [(MAP + 28, self.IDLE), (MAP + 24, word(0x11)),
                          (MAP + 8, self.IDLE), (MAP + 4, word(0x11)),
                          (MAP + 28, self.IDLE), (MAP + 24, word(0x12)),
                          (MAP + 8, self.IDLE), (MAP + 4, word(0x11)),
                          (MAP + 28, self.IDLE), (MAP + 24, word(0x11))])
        self.assertEqual(monitor.allowed, [])
        self.assertEqual(bytes(device.flash), IMAGE)
        self.assertEqual(self.events()[-1], 'protection_cleared')

    def test_clear_protection_sends_no_write_from_any_state_but_the_reviewed_one(self):
        # Nothing to clear, fewer protect bits, a locked register, CMP: each is a
        # state nobody has looked at, and none of them gets the command.
        for status in (0x0200, 0x0218, 0x031C, 0x029C, 0x421C, 0x001C):
            device = RunningProgrammer(status=status, unlock=True)
            with self.assertRaisesRegex(IOError, 'reviewed state'):
                self.clear_protection(device)
            self.assertEqual(device.commands[3:], [(1, 0x11), (0, 0x11)])
            self.assertEqual(device.status, status)
        self.assertNotIn('protection_cleared', self.events())

    def test_clear_protection_stops_when_the_chip_keeps_its_bits(self):
        class Ignoring(RunningProgrammer):
            def run(self, address):
                super().run(address)
                if self.commands[-1][1] == 0x12:
                    # DONE, and the arm's read-back shows the write did nothing.
                    self.status = 0x021C
                    self.put(address + 12, struct.pack('<I', 0xFDE3021C))
        device = Ignoring(status=0x021C, unlock=True)
        with self.assertRaisesRegex(IOError, 'after the write'):
            self.clear_protection(device)
        self.assertEqual([c for _, c in device.commands].count(0x12), 1)  # no second try
        self.assertNotIn('protection_cleared', self.events())

    def test_clear_protection_stops_on_a_build_without_the_command(self):
        device = RunningProgrammer(status=0x021C)  # the status build: it can only read
        with self.assertRaises(IOError):
            self.clear_protection(device)
        self.assertEqual(device.status, 0x021C)
        self.assertEqual(device.commands[3:], [(1, 0x11), (0, 0x11), (1, 0x12)])
        self.assertNotIn('protection_cleared', self.events())

    def test_clear_protection_stops_when_flash_reads_differ_afterwards(self):
        for reads in ([b'\x00' + IMAGE[1:], IMAGE], [IMAGE, b'\x00' + IMAGE[1:]]):
            with self.assertRaisesRegex(IOError, 'Flash changed'):
                self.clear_protection(RunningProgrammer(status=0x021C, unlock=True), reads)
        self.assertNotIn('protection_cleared', self.events())

    def test_write_test_programs_both_ends_of_the_blank_sector_then_erases_it(self):
        seen = []

        class Watched(RunningProgrammer):
            def run(self, address):
                super().run(address)
                seen.append(bytes(self.flash[SECTOR:SECTOR + 0x10000]))
        device = Watched()
        self.write_test(device)
        first, last = (data for address, data in device.writes if address == BUFFER + 0)
        self.assertEqual((len(first), len(last)), (1024, 1024))
        self.assertNotEqual(first, last)
        self.assertEqual(device.commands[3:], [(1, PROGRAM), (0, PROGRAM), (1, ERASE)])
        self.assertEqual(device.footprints, [(SECTOR, 4096), (SECTOR + 0xF000, 4096),
                                             (SECTOR, 0x10000)])
        after_first, after_last, after_erase = seen[3:]
        self.assertEqual((after_first[:1024], after_first[4096:]), (first, b'\xff' * 0xF000))
        self.assertEqual((after_last[:1024], after_last[4096:0xF000], after_last[0xF000:0xF400]),
                         (first, b'\xff' * 0xE000, last))
        self.assertEqual(after_erase, b'\xff' * 0x10000)
        self.assertEqual(bytes(device.flash), IMAGE)
        self.assertEqual(self.events()[-1], 'write_test_verified')

    def test_write_test_refused_when_the_sector_is_not_blank(self):
        for offset in (SECTOR, SECTOR + 0x8000, SECTOR + 0xFFFF):
            used = bytearray(IMAGE)
            used[offset] = 0xFE
            device = RunningProgrammer()
            device.flash = used
            with self.assertRaisesRegex(IOError, 'not blank'):
                self.write_test(device, bytes(used))
            self.assertEqual(device.writes, [])

    def test_flash_commands_stay_refused_until_the_write_test_arms_them(self):
        monitor, device = self.started()
        self.query(monitor)
        device.writes.clear()
        packets = rda_programmer_start.mailbox_packets(rda_programmer_start.WRITE_TEST, 1)
        for packet in packets:
            with self.assertRaises(ValueError):
                monitor.send(packet)
        self.assertEqual(device.writes, [])

    def test_armed_write_test_passes_only_its_own_exact_packets(self):
        monitor, device = self.started()
        self.query(monitor)
        device.writes.clear()
        packets = rda_programmer_start.mailbox_packets(rda_programmer_start.WRITE_TEST, 1)
        monitor.allowed = list(packets)
        idle = lambda offset, size: struct.pack('<4I', offset, BUFFER, size, 0)
        refused = [(MAP + 24, struct.pack('<I', command)) for command in (ERASE, PROGRAM, END, 10, 11, 13, 15)]
        refused += [(MAP + 28, idle(offset, 0))                      # an erase anywhere
                    for offset in (0, 0x3D0000, SECTOR, 0x3F0000, 0x3FA000)]
        refused += [(MAP + 28, idle(offset, 4096))                   # a program anywhere else
                    for offset in (0, 0x3D0000, SECTOR + 0x1000, 0x3F0000, 0x3FA000)]
        refused += [(BUFFER, bytes(1024))]                           # other data for the sector
        for address, data in refused:
            with self.assertRaises(ValueError):
                monitor.write_ram(address, data)
        self.assertEqual(device.writes, [])
        for packet in packets:
            monitor.send(packet)
        for packet in packets:
            with self.assertRaises(ValueError):
                monitor.send(packet)
        self.assertEqual(device.footprints, [(SECTOR, 4096), (SECTOR + 0xF000, 4096),
                                             (SECTOR, 0x10000)])

    def faulty(self, fault, **build):
        class Faulty(RunningProgrammer):
            def run(self, address):
                super().run(address)
                if self.commands[3:]:
                    fault(self)
        return Faulty(**build)

    def test_write_test_stops_when_a_programmed_chunk_reads_back_wrong(self):
        def fault(device):
            device.flash[SECTOR + 8] = 0
        device = self.faulty(fault)
        with self.assertRaisesRegex(IOError, 'Program verification'):
            self.write_test(device)
        self.assertEqual(device.commands[3:], [(1, PROGRAM)])
        self.assertNotIn('write_test_verified', self.events())

    def test_write_test_stops_when_a_program_changes_anything_outside_its_chunk(self):
        for elsewhere in (0, SECTOR - 1, SECTOR + 4096, SECTOR + 0x10000, 0x3FA000):
            def fault(device):
                device.flash[elsewhere] ^= 1
            device = self.faulty(fault)
            with self.assertRaisesRegex(IOError, 'Program verification'):
                self.write_test(device)
            self.assertEqual(device.commands[3:], [(1, PROGRAM)])

    def test_write_test_stops_when_the_erase_does_not_restore_the_pre_start_image(self):
        for where in (SECTOR + 0xF000, SECTOR - 0x10000, SECTOR + 0x10000):
            def fault(device):
                if device.commands[-1][1] == ERASE:
                    device.flash[where] = 0
            device = self.faulty(fault)
            with self.assertRaisesRegex(IOError, 'Erase verification'):
                self.write_test(device)
            self.assertNotIn('write_test_verified', self.events())

    def reset_test(self, rom, device=None, before=IMAGE):
        monitor, device = self.started(device)
        self.query(monitor)
        device.writes.clear()
        with mock.patch.object(rda_programmer_start, 'read_flash',
                               side_effect=lambda *_: bytes(rom.flash)):
            rda_programmer_start.reset_test(
                monitor, self.journal, before,
                lambda: StartMonitor(rom, self.journal, TimeoutError, []))
        return monitor, device

    def test_reset_stays_refused_until_the_reset_test_arms_it(self):
        monitor, device = self.started()
        self.query(monitor)
        with self.assertRaises(ValueError):
            monitor.send(RESET)
        self.assertEqual(device.resets, 0)

    def test_reset_is_refused_on_a_fresh_monitor_until_armed(self):
        device = RunningProgrammer()
        monitor = StartMonitor(device, self.journal, TimeoutError, [])
        with self.assertRaises(ValueError):
            monitor.send(RESET)
        self.assertEqual(device.resets, 0)

    def test_reset_test_sends_one_reset_then_only_handshakes_and_reads(self):
        rom = RomPort()
        monitor, device = self.reset_test(rom)
        self.assertEqual(device.resets, 1)
        self.assertEqual(device.writes, [])  # no mailbox or RAM write, so no flash command
        self.assertEqual(rom.requests, [b'\xff\x84' + struct.pack('<I', 5) + b'\xfd'])
        self.assertEqual(self.events()[-1], 'reset_test_verified')
        with self.assertRaises(ValueError):
            monitor.send(RESET)
        self.assertEqual(device.resets, 1)

    def test_the_monitor_on_the_returned_rom_port_cannot_write_or_execute(self):
        rom = RomPort()
        after = StartMonitor(rom, self.journal, TimeoutError, [])
        for payload in (b'\xff\x83' + struct.pack('<II', MAP + 4, ERASE),
                        b'\xff\x84' + struct.pack('<I', 5) + b'\xff', RESET):
            with self.assertRaises(ValueError):
                after.send(payload)
        self.assertEqual(rom.requests, [])

    def test_reset_test_goes_on_to_look_for_the_rom_when_the_reset_transfer_fails(self):
        device = RunningProgrammer()
        accept = device.write
        def write(endpoint, request, **kwargs):
            if request[3:-1] == RESET:
                raise IOError('device left during the transfer')
            return accept(endpoint, request, **kwargs)
        device.write = write
        self.reset_test(RomPort(), device)
        self.assertIn('reset_transfer_uncertain', self.events())
        self.assertEqual(self.events()[-1], 'reset_test_verified')

    def test_reset_test_stops_on_a_wrong_handshake(self):
        with self.assertRaisesRegex(IOError, 'handshake'):
            self.reset_test(RomPort(answer=READY))
        self.assertNotIn('reset_test_verified', self.events())

    def test_reset_test_stops_when_the_flash_differs_afterwards(self):
        rom = RomPort()
        rom.flash[0] ^= 1
        with self.assertRaisesRegex(IOError, 'Flash differs'):
            self.reset_test(rom)
        self.assertNotIn('reset_test_verified', self.events())

    def test_write_test_and_reset_test_are_separate_runs(self):
        argv = ['rda_programmer_start.py', '--unit', '1403167412', '--write-test', '--reset-test']
        stderr = io.StringIO()
        with mock.patch('sys.argv', argv), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                rda_programmer_start.main()
        self.assertIn('separate runs', stderr.getvalue())

    # A bootable image: block 0 holds code and the boot word, the test sector is blank.
    BOOTABLE = struct.pack('<I', MAGIC) + IMAGE[4:]
    BLANK = b'\xff' * 4 + IMAGE[4:]
    SEGMENTS = [(0xA1C000A0, struct.pack('<6I', 0, 0x81C00280, 0, 0, 0, 0)),
                (0xA1C00280, b'\x11' * 1028)]

    def through_the_device(self, device):
        """Full reads come straight from the device's image; a real one is 4096 frames."""
        return (mock.patch.object(rda_programmer_start, 'read_flash',
                                  side_effect=lambda *_: bytes(device.flash)),
                mock.patch.object(rda_flash.Programmer, 'read_flash',
                                  lambda _, offset=0, size=FLASH_SIZE:
                                  bytes(device.flash[offset:offset + size])))

    def blank(self, device, before=None):
        before = self.BOOTABLE if before is None else before
        monitor, device = self.started(device)
        programmer = self.query(monitor, before=bytes(device.flash))
        full, sector = self.through_the_device(device)
        with full, sector:
            return rda_programmer_start.blank_boot_word(programmer, monitor, self.journal,
                                                        before), monitor, device

    def bootable(self):
        device = RunningProgrammer()
        device.flash[:] = self.BOOTABLE
        return device

    def test_blank_word_rewrites_block_0_without_its_boot_word_and_sends_no_end(self):
        blank, monitor, device = self.blank(self.bootable())
        self.assertEqual(blank, self.BLANK)
        self.assertEqual(bytes(device.flash), self.BLANK)
        self.assertEqual([c for _, c in device.commands[3:]], [ERASE] + [PROGRAM] * 16)
        self.assertEqual(device.footprints,
                         [(0, 0x10000)] + [(n, 4096) for n in range(0, 0x10000, 4096)])
        self.assertEqual(monitor.allowed, [])
        self.assertEqual(self.events()[-1], 'boot_word_blank')

    def test_blank_word_is_refused_when_block_0_does_not_start_with_the_boot_word(self):
        device = RunningProgrammer()
        with self.assertRaisesRegex(IOError, 'not the magic'):
            self.blank(device, before=IMAGE)
        self.assertEqual(len(device.commands), 3)  # the query's, and no flash command

    def test_blank_word_stops_before_programming_when_the_erase_left_data(self):
        def fault(device):
            if device.commands[-1][1] == ERASE:
                device.flash[0x8000] = 0
        device = self.faulty(fault)
        device.flash[:] = self.BOOTABLE
        with self.assertRaisesRegex(IOError, 'Erase verification'):
            self.blank(device)
        self.assertEqual([c for _, c in device.commands[3:]], [ERASE])

    def rewrite(self, device, current):
        monitor = StartMonitor(device, self.journal, TimeoutError, self.SEGMENTS)
        full, sector = self.through_the_device(device)
        with full, sector:
            rda_programmer_start.rewrite_boot_block(
                monitor, self.journal, current, self.BOOTABLE, self.BOOTABLE, '1403167412',
                self.SEGMENTS, 'sha', PINNED_RUNTIME)
        return monitor

    def test_rewrite_restores_block_0_and_end_writes_the_boot_word(self):
        device = RunningProgrammer()
        device.flash[:] = self.BLANK
        monitor = self.rewrite(device, self.BLANK)
        self.assertEqual(bytes(device.flash), self.BOOTABLE)
        self.assertEqual([c for _, c in device.commands],
                         [PING, PING, FINALIZE_INFO, ERASE] + [PROGRAM] * 16 + [END])
        self.assertEqual(monitor.allowed, [])
        self.assertEqual(self.events()[-1], 'boot_block_restored')

    def test_rewrite_recovers_a_block_0_left_erased(self):
        device = RunningProgrammer()
        device.flash[:] = b'\xff' * 0x10000 + self.BOOTABLE[0x10000:]
        self.rewrite(device, bytes(device.flash))
        self.assertEqual(bytes(device.flash), self.BOOTABLE)

    def test_rewrite_sends_nothing_to_any_sector_but_block_0(self):
        device = RunningProgrammer()
        device.flash[:] = self.BLANK
        device.flash[0x20000] ^= 0xff  # the writer's plan would now include this sector
        with self.assertRaises(ValueError):
            self.rewrite(device, bytes(device.flash))
        self.assertEqual([c for _, c in device.commands], [PING, PING, FINALIZE_INFO])

    def test_the_blank_word_sequence_on_one_simulated_chip_as_run_composes_it(self):
        device = self.bootable()
        blank, monitor, _ = self.blank(device)
        full, sector = self.through_the_device(device)
        with full, sector:
            rom = rda_programmer_start.restart(
                monitor, self.journal,
                lambda: StartMonitor(device, self.journal, TimeoutError, self.SEGMENTS))
            self.assertEqual(rda_programmer_start.read_flash(rom, self.journal, 'x'), blank)
            rda_programmer_start.rewrite_boot_block(
                rom, self.journal, blank, self.BOOTABLE, self.BOOTABLE, '1403167412',
                self.SEGMENTS, 'sha', PINNED_RUNTIME)
        self.assertEqual(device.resets, 1)
        self.assertEqual(bytes(device.flash), self.BOOTABLE)
        # The reset lost the first session's "block 0 programmed" flag, so the word
        # only comes back because the second session programs block 0 before END.
        self.assertEqual([c for _, c in device.commands],
                         [PING, PING, FINALIZE_INFO, ERASE] + [PROGRAM] * 16
                         + [PING, PING, FINALIZE_INFO, ERASE] + [PROGRAM] * 16 + [END])
        self.assertEqual(self.events()[-1], 'boot_block_restored')

    def test_end_alone_after_a_restart_would_not_write_the_boot_word(self):
        # Why the second session cannot just send END: the fake follows
        # flash_programmer.c, where END writes the word only after a program at zero.
        device = self.bootable()
        blank, monitor, _ = self.blank(device)
        rda_programmer_start.restart(
            monitor, self.journal,
            lambda: StartMonitor(device, self.journal, TimeoutError, self.SEGMENTS))
        device.put(MAP + 4, struct.pack('<I', END))
        device.run(MAP + 4)
        self.assertEqual(bytes(device.flash), blank)

    def run_on(self, device, journal, **flags):
        """The real run() with a real journal on disk; only the USB plumbing is replaced.

        The tests above hand the pieces a mock journal, which cannot show two steps
        saving a read under one name. The real journal never overwrites, so that stops
        the run: here, between the blank word and its restore.
        """
        import usb.backend.libusb1
        import usb.core
        import usb.util
        import rda_dump
        import rda_recovery_snapshot
        import rda_rom_recovery
        args = SimpleNamespace(**{**dict(journal=journal, unit='1403167412', query=True,
                                         write_test=False, reset_test=False,
                                         blank_word_test=False, blank_word_stop=False,
                                         finish=None, trial=None, trial_sha256=None,
                                         trial_stop=False, repair_tail=False,
                                         read_status=False, from_rom=False,
                                         clear_protection=False), **flags})
        port = SimpleNamespace(idVendor=0x1E04, idProduct=0x0900, reset=lambda: None)
        causes = iter([0x00200000, 0x00220000])  # Reset_Cause before and after the force bit
        replaced = [
            (usb.backend.libusb1, 'get_backend', lambda **_: None),
            (usb.core, 'find', lambda **_: [port]),
            (usb.core, 'USBTimeoutError', TimeoutError),
            (usb.util, 'dispose_resources', lambda _: None),
            (rda_rom_recovery, 'device_named', lambda backend, name: device),
            (rda_rom_recovery, 'snapshot', lambda backend: {}),
            (rda_rom_recovery, 'observe', lambda *_, **__: True),
            (rda_rom_recovery, 'send', lambda _, request: None),
            # The vendor firmware reads through the cached window, 0x20000000 below.
            (rda_dump, 'read_block', lambda _, address: device.get(address + 0x20000000, 1024)),
            (rda_recovery_snapshot, 'read_word', lambda *_: next(causes)),
            (rda_programmer_start, 'ROM_SHA', rda_flash.sha(bytes(0x6000))),
            (rda_programmer_start.time, 'sleep', lambda _: None)]
        with contextlib.ExitStack() as stack, contextlib.redirect_stdout(io.StringIO()):
            for target, name, value in replaced:
                stack.enter_context(mock.patch.object(target, name, value))
            rda_programmer_start.run(args, self.BOOTABLE, self.BOOTABLE, self.SEGMENTS, 'sha',
                                     PINNED_RUNTIME)

    def test_run_composes_the_blank_word_test_with_a_journal_on_disk(self):
        device = self.bootable()
        with tempfile.TemporaryDirectory() as root:
            self.run_on(device, Path(root) / 'run', blank_word_test=True)
            saved = {path.name for path in (Path(root) / 'run').iterdir()}
        self.assertEqual(bytes(device.flash), self.BOOTABLE)
        self.assertEqual(device.resets, 1)
        self.assertEqual([c for _, c in device.commands],
                         [PING, PING, FINALIZE_INFO, ERASE] + [PROGRAM] * 16
                         + [PING, PING, FINALIZE_INFO, ERASE] + [PROGRAM] * 16 + [END])
        self.assertLessEqual({'after-query.bin', 'blank-after-idle.bin', 'before-restore.bin',
                              'after-restore.bin'}, saved)

    def test_run_composes_finish_with_a_journal_on_disk(self):
        device = self.bootable()
        device.flash[:0x10000] = b'\xff' * 0x10000  # a run stopped after its erase
        with tempfile.TemporaryDirectory() as root:
            stopped = Path(root) / 'stopped'
            saved = rda_flash.Journal(stopped)
            saved.emit('scope', unit='1403167412')
            saved.save('before-startup.bin', self.BOOTABLE)
            saved.close()
            self.run_on(device, Path(root) / 'finish', finish=stopped)
        self.assertEqual(bytes(device.flash), self.BOOTABLE)
        self.assertEqual([c for _, c in device.commands],
                         [PING, PING, FINALIZE_INFO, ERASE] + [PROGRAM] * 16 + [END])

    def test_run_blanks_and_stops_then_finish_restores_from_its_actual_journal(self):
        device = self.bootable()
        with tempfile.TemporaryDirectory() as root:
            stopped = Path(root) / 'stopped'
            self.run_on(device, stopped, blank_word_stop=True)
            self.assertEqual(bytes(device.flash), self.BLANK)
            self.assertEqual(device.resets, 0)
            self.assertEqual([c for _, c in device.commands],
                             [PING, PING, FINALIZE_INFO, ERASE] + [PROGRAM] * 16)
            self.assertEqual((stopped / 'before-startup.bin').read_bytes(), self.BOOTABLE)
            self.assertEqual((stopped / 'after-blank.bin').read_bytes(), self.BLANK)
            self.assertFalse((stopped / 'blank-after-idle.bin').exists())
            self.assertFalse((stopped / 'after-restore.bin').exists())
            self.run_on(device, Path(root) / 'finish', finish=stopped)
            self.assertEqual((Path(root) / 'finish' / 'after-restore.bin').read_bytes(),
                             self.BOOTABLE)
        self.assertEqual(bytes(device.flash), self.BOOTABLE)
        self.assertEqual(device.resets, 1)
        self.assertEqual([c for _, c in device.commands],
                         [PING, PING, FINALIZE_INFO, ERASE] + [PROGRAM] * 16
                         + [PING, PING, FINALIZE_INFO, ERASE] + [PROGRAM] * 16 + [END])

    def journaled(self, path, event):
        import json
        events = [json.loads(line) for line in (path / 'operations.jsonl').read_text().splitlines()]
        return [e for e in events if e['event'] == event]

    def test_run_reads_the_status_registers_from_the_vendor_firmware(self):
        device = RunningProgrammer(status=0x0200)
        device.flash[:] = self.BOOTABLE
        with tempfile.TemporaryDirectory() as root:
            self.run_on(device, Path(root) / 'status', read_status=True)
            read = self.journaled(Path(root) / 'status', 'status_read')
            saved = {path.name for path in (Path(root) / 'status').iterdir()}
        self.assertEqual([c for _, c in device.commands], [PING, PING, FINALIZE_INFO, 0x11, 0x11])
        self.assertEqual([(e['status1'], e['status2'], e['set_bits']) for e in read],
                         [('0x0', '0x2', ['QE'])])
        self.assertLessEqual({'after-query.bin', 'after-status.bin'}, saved)
        self.assertEqual(bytes(device.flash), self.BOOTABLE)
        self.assertEqual(device.resets, 0)

    def test_run_reads_the_status_registers_from_the_rom_port(self):
        # As 412 is: no boot word, another firmware's code, its own tail. Only the
        # tail binds the unit, and the run starts on the ROM port with one reset.
        device = RunningProgrammer(status=0x027C)
        device.flash[:] = self.BLANK
        device.flash[0x20000] ^= 0xff
        before = bytes(device.flash)
        with tempfile.TemporaryDirectory() as root:
            self.run_on(device, Path(root) / 'status', read_status=True, from_rom=True)
            read = self.journaled(Path(root) / 'status', 'status_read')
            saved = (Path(root) / 'status' / 'before-startup.bin').read_bytes()
        self.assertEqual([c for _, c in device.commands], [PING, PING, FINALIZE_INFO, 0x11, 0x11])
        self.assertEqual([(e['status1'], e['status2']) for e in read], [('0x7c', '0x2')])
        self.assertEqual(saved, before)
        self.assertEqual(bytes(device.flash), before)
        self.assertEqual(device.resets, 1)

    def test_run_from_the_rom_port_loads_nothing_on_another_units_tail(self):
        device = RunningProgrammer(status=0x0200)
        device.flash[:] = self.BLANK
        device.flash[FLASH_SIZE - 1] ^= 0xff
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(IOError, 'identity'):
                self.run_on(device, Path(root) / 'status', read_status=True, from_rom=True)
        self.assertEqual(device.writes, [])
        self.assertEqual(device.commands, [])

    def test_run_clears_protection_from_the_rom_port(self):
        # As 412 is: no boot word, another firmware's code, its own tail, and the
        # registers at 0x02 and 0x1c.
        device = RunningProgrammer(status=0x021C, unlock=True)
        device.flash[:] = self.BLANK
        device.flash[0x20000] ^= 0xff
        before = bytes(device.flash)
        with tempfile.TemporaryDirectory() as root:
            self.run_on(device, Path(root) / 'clear', clear_protection=True)
            cleared = self.journaled(Path(root) / 'clear', 'protection_cleared')
            saved = {path.name for path in (Path(root) / 'clear').iterdir()}
        self.assertEqual(device.status, 0x0200)
        self.assertEqual([c for _, c in device.commands],
                         [PING, PING, FINALIZE_INFO, 0x11, 0x11, 0x12, 0x11, 0x11])
        self.assertEqual([(e['before'], e['after'], e['status_writes_sent']) for e in cleared],
                         [('0x021c', '0x0200', 1)])
        self.assertLessEqual({'before-startup.bin', 'after-clear.bin'}, saved)
        self.assertEqual(bytes(device.flash), before)
        self.assertEqual(device.resets, 1)

    def test_run_clears_nothing_on_another_units_tail(self):
        device = RunningProgrammer(status=0x021C, unlock=True)
        device.flash[:] = self.BLANK
        device.flash[FLASH_SIZE - 1] ^= 0xff
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(IOError, 'identity'):
                self.run_on(device, Path(root) / 'clear', clear_protection=True)
        self.assertEqual((device.writes, device.commands, device.status), ([], [], 0x021C))

    def test_clear_protection_refuses_the_original_unit_other_modes_and_markers(self):
        for unit, extra, message in (
                ('1403167417', [], 'never written on the original unit'),
                ('1403167412', ['--read-status'], 'separate runs'),
                ('1403167412', ['--write-test'], 'separate runs'),
                ('1403167412', ['--finish', 'firmware/live/x'], 'separate runs'),
                ('1403167412', ['--markers'], 'loads the unlock build')):
            argv = ['rda_programmer_start.py', '--unit', unit, '--clear-protection'] + extra
            stderr = io.StringIO()
            with mock.patch('sys.argv', argv), contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    rda_programmer_start.main()
            self.assertIn(message, stderr.getvalue())

    def test_read_status_refuses_other_modes_and_the_marker_build(self):
        for extra in (['--write-test'], ['--reset-test'], ['--blank-word-stop'],
                      ['--finish', 'firmware/live/x'], ['--markers']):
            argv = ['rda_programmer_start.py', '--unit', '1403167412', '--read-status'] + extra
            stderr = io.StringIO()
            with mock.patch('sys.argv', argv), contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    rda_programmer_start.main()
            self.assertIn('loads the status build' if '--markers' in extra else 'separate runs',
                          stderr.getvalue())

    def test_from_rom_is_only_for_the_status_read(self):
        argv = ['rda_programmer_start.py', '--unit', '1403167412', '--from-rom']
        stderr = io.StringIO()
        with mock.patch('sys.argv', argv), contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                rda_programmer_start.main()
        self.assertIn('--from-rom needs --read-status', stderr.getvalue())

    def test_block_0_is_never_rewritten_on_the_original_unit(self):
        for flag in (['--blank-word-test'], ['--blank-word-stop'],
                     ['--finish', 'firmware/live/x']):
            argv = ['rda_programmer_start.py', '--unit', '1403167417'] + flag
            stderr = io.StringIO()
            with mock.patch('sys.argv', argv), contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    rda_programmer_start.main()
            self.assertIn('never rewritten on the original', stderr.getvalue())

    def test_blank_word_stop_refuses_other_modes_and_marker_build(self):
        for extra in (['--write-test'], ['--reset-test'], ['--blank-word-test'],
                      ['--finish', 'firmware/live/x'], ['--markers']):
            argv = ['rda_programmer_start.py', '--unit', '1403167412',
                    '--blank-word-stop'] + extra
            stderr = io.StringIO()
            with mock.patch('sys.argv', argv), contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    rda_programmer_start.main()
            self.assertIn('needs the pinned build' if '--markers' in extra else 'separate runs',
                          stderr.getvalue())

    def test_an_unknown_unit_is_refused(self):
        argv = ['rda_programmer_start.py', '--unit', '1403167413', '--reset-test']
        with mock.patch('sys.argv', argv), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                rda_programmer_start.main()


if __name__ == '__main__':
    unittest.main()
