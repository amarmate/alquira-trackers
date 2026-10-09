"""Start the pinned USB programmer; flash writes require an explicit test mode.

Default is offline validation. --execute makes one vendor-to-ROM transition,
verifies two full flash reads, loads/verifies SRAM, executes once, records startup
events (including RAM retry diagnostics), and compares two full post-start reads.
--query then runs the writer's own start-up check, the first mailbox commands:
PING on each slot and the finalize-info query, which answer from RAM; two more
full reads must still match.
--write-test goes on to the first flash commands, on one sector that is blank and
shares its erase block with nothing: program its first and last 4 KiB, read the
whole flash back after each, erase the sector, and require the pre-start image
again. No other erase or program, and no finalize, is ever accepted.
--reset-test sends no flash command: after the query it sends one debug reset from
inside the programmer session and requires the ROM's USB port, its handshake and the
pre-start flash image again. The flash stays valid, so a ROM that came back without
USB would leave its monitor after 30 s and boot the vendor firmware.
--blank-word-test, on a spare only, is the first write to code: it erases block 0
and programs it back without the boot word, restarts, stays silent past the ROM's
30 s idle limit to show the blank word holds the monitor, then starts a fresh
programmer whose restore rewrites block 0 and writes the word with END. From the
erase to END the unit has no boot word: no RST and no unplug. --finish JOURNAL
picks a stopped run up from the ROM port and restores every changed unprotected
sector from its journaled pre-start image, with END only after full verification.
--blank-word-stop rewrites block 0 without the word and stops in the programmer,
without a reset or END. Leave USB connected and use --finish to restore the word.
--trial IMAGE --trial-sha256 HASH blanks block 0 before changing any other code,
installs core/app while preserving current bytes above 0x2e0000, verifies all flash,
resets to ROM, verifies again and sends one monitor exit to start the new core.
--trial-stop omits the reset/start, for a separately approved recovery rehearsal.
--read-status loads the status build instead: the pinned build plus one mailbox
command that reads flash status registers 1 and 2. It runs the query, sends that
command twice, requires equal readings and an unchanged flash, and sends no erase,
program or status write. --from-rom starts it on the ROM port, for a unit that has
no boot word; the unit is then bound by its calibration/factory tail alone.
--clear-protection, on a spare waiting in the ROM, loads the unlock build: the status
build plus one command that writes the status registers once, from 0x1c/0x02 (the
block protection Logicrom left on 412) to 0x00/0x02. The registers are read twice
before and twice after, and the command is refused in any other state.
Startup itself can set flash QE and changes power/clocks. Leave via physical RST.
The separately qualified flash writer and its original-unit block are unchanged.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import time

from rda_flash import (Monitor, Journal, Programmer, frame, sha, read_lod, restore, plan, FLASH_SIZE,
                       FLASH_BASE, PROTECTED, ROM_SHA, LOD_SHA, ROM_START, ROM_EXECUTING,
                       READY, BUFFER, GEOMETRY, LAYOUT, LIVE_ROOT, ORIGINAL_UNIT, PING,
                       FINALIZE_INFO, DONE, PROGRAM, ERASE, END, MAGIC, READ_STATUS,
                       CLEAR_PROTECTION, PINNED_RUNTIME, layout_for)
from rda_lod_audit import audit

BASELINE_SHA = '148c0d4240b3fb49160afe0c030628f774e2cebec060cf1d1ae3e64c4bb32f62'
BACKUP_SHA = 'c63a447aff0e3b457bda4cb7a049d3c2bfcb049b555f0d1398dc41b67a9982bd'
JEDEC = 0x1660C8  # c8 60 16, as the programmer cached it on 417 in every start so far
# Blank in every dump of 417 since October 3. It is a whole 64 KiB erase block, so
# the erase is one block-erase command with no neighbour inside its reach; the
# blank 4 KiB sectors above it share their block with calibration and IMEI.
TEST_SECTOR = 0x3E0000
# Debug-host CTRL_SET with Debug_Reset. In a ROM session the ROM's own USB decoder
# takes it (boot_usb_monitor.c:294-304): it resets USB and soft-resets the chip.
RESET = b'\xff\x84' + struct.pack('<I', 0) + b'\x01'
# Seconds of silence in the blank-word test: past the ROM's 30 s idle limit.
IDLE = 40
ROM_EXIT = b'\xff\x84' + struct.pack('<I', 5) + b'\xfe'


def pattern(offset):
    """4 KiB that is recognisably this test's, and different for each offset."""
    return b''.join(hashlib.sha256(b'V24 write test %06x %d' % (offset, n)).digest()
                    for n in range(128))


QUERY = [(PING, 0, b''), (PING, 0, b''), (FINALIZE_INFO, 0, b'')]
# Programs come first: one landing in the wrong place costs 4 KiB and shows in the
# read-back, before the erase, whose address goes through the same mailbox field.
WRITE_TEST = [(PROGRAM, TEST_SECTOR, pattern(TEST_SECTOR)),
              (PROGRAM, TEST_SECTOR + 0xF000, pattern(TEST_SECTOR + 0xF000)),
              (ERASE, TEST_SECTOR, b'')]


def mailbox_packets(commands, slot=0, where=PINNED_RUNTIME):
    """The exact RAM writes the writer's Programmer makes for these commands, in order."""
    packets = []
    for command, offset, data in commands:
        mailbox = where['map'] + 4 + slot * 20
        packets += [b'\xff\x83' + struct.pack('<I', BUFFER + n) + data[n:n + 1024]
                    for n in range(0, len(data), 1024)]
        packets.append(b'\xff\x83' + struct.pack('<I4I', mailbox + 4, offset, BUFFER, len(data), 0))
        packets.append(b'\xff\x83' + struct.pack('<II', mailbox, command))
        slot ^= 1
    return packets
ROOT = Path(__file__).resolve().parents[1]
# The programmer rda_flash.py is pinned to: the SDK build without the 104 MHz clock
# request and with the V24 charge current (200 mA, not the generic target's 400 mA).
LOD = LIVE_ROOT / ('usb-programmer-build/clean/artifacts/'
                   'usb_8955_flsh_spi32m_ramrun_noclk_200ma.lod')
BASELINE = LIVE_ROOT / '2026-10-08T225652Z-rom-session.flash.bin'
# Per unit: the backup that binds the connected tracker, and the image its code and
# protected tail must still match in ROM mode. 412 has no ROM-session dump yet, so
# its backup serves as both.
SPARE_412 = ROOT / 'firmware/backup/v24_1403167412_2026-10-09_a_flash.bin'
SPARE_412_SHA = 'b0250296dda7f0e6fd6eed44a561de740dbf52b158008d2ad416d7541d34a2c4'
UNITS = {
    ORIGINAL_UNIT: dict(backup=ROOT / 'firmware/backup/v24_1403167417_2026-10-03_flash.bin',
                        backup_sha=BACKUP_SHA, baseline=BASELINE, baseline_sha=BASELINE_SHA),
    '1403167412': dict(backup=SPARE_412, backup_sha=SPARE_412_SHA,
                       baseline=SPARE_412, baseline_sha=SPARE_412_SHA),
}
# Diagnostic build: the same SDK source plus 0x5a00xxxx stage events, and without
# the 104 MHz clock request that the stage events showed stops USB (the .patch
# beside the LOD is the whole difference). Its data moved, so the runtime checks
# take this build's own addresses, read from its linker map.
MARKER_LOD = LIVE_ROOT / ('usb-programmer-build/markers/artifacts/'
                          'usb_8955_flsh_spi32m_ramrun_markers_noclk.lod')
MARKER_SHA = '025f49fea9e88f8defca6dbf7025f9719b598e78d338daf8825592c1b8a5225a'
MARKER_RUNTIME = dict(map=0xA1C0BBD8, geometry=0xA1C0963C, layout=0xA1C09658,
                      flash_context=0xA1C077A0)
# Status build: the pinned build's source plus one mailbox command, 0x11, that reads
# flash status registers 1 and 2 (opcodes 0x05 and 0x35) and writes nothing to the
# flash (the .patch beside the LOD is the whole difference). No status-register write
# is linked in beyond the start-up's QE check, which the pinned build has too.
STATUS_LOD = LIVE_ROOT / ('usb-programmer-build/status/artifacts/'
                          'usb_8955_flsh_spi32m_ramrun_noclk_200ma_status.lod')
STATUS_SHA = 'b4231c542bc020f98399ce5ae90aa2094b64e0dc3c16357015bcdbfff177000f'
STATUS_RUNTIME = dict(map=0xA1C0BA78, geometry=0xA1C094DC, layout=0xA1C094F8,
                      flash_context=0xA1C07640)
# Unlock build: the status build's source plus one more command, 0x12, that makes one
# status-register write. Its arm holds both values: it writes 0x02/0x00 (01h 00h 02h
# after a write-enable) only when the registers read 0x02/0x1c, and refuses any other
# state. The SDK's two-byte write is the only one linked in.
UNLOCK_LOD = LIVE_ROOT / ('usb-programmer-build/unlock/artifacts/'
                          'usb_8955_flsh_spi32m_ramrun_noclk_200ma_unlock.lod')
UNLOCK_SHA = 'ca324886c4326abee3d62c30bda541c220fe2064e17fa19e2e9b4cd180a3944f'
UNLOCK_RUNTIME = dict(map=0xA1C0BAF8, geometry=0xA1C0955C, layout=0xA1C09578,
                      flash_context=0xA1C076C0)
# GD25LQ32D (c8 60 16) status bits S0 to S15: register 1 below register 2.
STATUS_BITS = ('WIP', 'WEL', 'BP0', 'BP1', 'BP2', 'BP3', 'BP4', 'SRP0',
               'SRP1', 'QE', 'SUS2', 'LB1', 'LB2', 'LB3', 'CMP', 'SUS1')
# Registers 2 and 1 as 412 held them after the Logicrom trials (QE, BP2-BP0: the
# whole array protected) and as 417 holds them (QE alone), both read 2026-10-09.
PROTECTED_STATUS, CLEAR_STATUS = 0x021C, 0x0200


def read_local_lod(lod, pinned_sha, where):
    """Load a locally built programmer: pinned by hash, with its own table addresses."""
    raw = lod.read_bytes()
    result = audit(lod)  # checksum, internal-SRAM-only records, entry inside the image
    if sha(raw) != pinned_sha or result['sha256'] != pinned_sha:
        raise ValueError(f'{lod.name} is not the pinned build')
    memory = {}
    for line in raw.decode('ascii').split():
        if line.startswith('@'):
            address = int(line[1:], 16)
        elif not line.startswith('#'):
            memory[address] = struct.pack('<I', int(line, 16))
            address += 4
    def loaded(address, size):
        return b''.join(memory[a] for a in range(address & 0x1FFFFFFF,
                                                 (address & 0x1FFFFFFF) + size, 4))
    if (loaded(where['geometry'], 28) != GEOMETRY
            or loaded(where['layout'], len(LAYOUT)) != layout_for(where)):
        raise ValueError(f'{lod.name} flash layout mismatch')
    return [(int(lo, 16) | 0xA0000000, loaded(int(lo, 16), int(hi, 16) - int(lo, 16)))
            for lo, hi in result['intervals']]


class StartJournal(Journal):
    def __init__(self, path):
        self.started = time.monotonic()
        super().__init__(path)

    def emit(self, event, **fields):
        fields['elapsed'] = round(time.monotonic() - self.started, 3)
        fields['utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        super().emit(event, **fields)
        print(json.dumps(dict(event=event, **fields), sort_keys=True), flush=True)


class StartMonitor(Monitor):
    """Wire-level allowlist: exact pinned load packets, one execute, then reads only.

The load image includes zero mailbox slots; arbitrary SRAM/mailbox writes, flash
commands, MMIO writes, exit/finalize and re-execution are never accepted here.
After execute, a write passes only if it is the next packet of `allowed`, which
is empty until query() or write_test() fills it with the exact packets of its
own commands: see QUERY, WRITE_TEST and boot_block_commands(). One debug reset
passes, once, each time restart() arms it.
"""
    def __init__(self, device, journal, timeout_error, segments):
        super().__init__(device, journal, timeout_error)
        self.writes = [b'\xff\x83' + struct.pack('<I', address + offset)
                       + data[offset:offset + 1024]
                       for address, data in segments for offset in range(0, len(data), 1024)]
        self.writes.append(b'\xff\x83' + struct.pack('<I', 0xA1C000A0)
                           + struct.pack('<I', 0xFF))
        self.write_index = 0
        self.handshaken = False
        self.armed = False
        self.executed = False
        self.startup = []
        self.allowed = []
        self.reset_armed = False
        self.exit_armed = False

    def send(self, payload):
        if payload[:2] == b'\xff\x03' and len(payload) == 9:
            pass
        elif payload == b'\xff\x84' + struct.pack('<I', 5) + b'\xfd':
            if self.handshaken or self.executed:
                raise ValueError('Handshake already sent')
            self.handshaken = True
        elif payload[:2] == b'\xff\x83' and self.executed:
            if not self.allowed or payload != self.allowed[0]:
                raise ValueError('Only the next exact mailbox packet is permitted')
            del self.allowed[0]  # consume before transmission: no uncertain retry
        elif payload[:2] == b'\xff\x83':
            if (not self.armed or self.executed or self.write_index >= len(self.writes)
                    or payload != self.writes[self.write_index]):
                raise ValueError('Only the next exact pinned load packet is permitted')
            self.write_index += 1  # consume before transmission: no uncertain retry
        elif payload == b'\xff\x84' + struct.pack('<I', 5) + b'\xff':
            if not self.armed or self.executed or self.write_index != len(self.writes):
                raise ValueError('Execution requires the complete verified load')
            self.executed = True
        elif payload == RESET:
            if not self.reset_armed:
                raise ValueError('A reset is permitted once, where restart() arms it')
            self.reset_armed = False  # consume before transmission: no uncertain retry
        elif payload == ROM_EXIT:
            if not self.exit_armed or not self.handshaken or self.executed:
                raise ValueError('ROM exit requires a verified trial in a fresh ROM session')
            self.exit_armed = False
        else:
            raise ValueError('Forbidden start-only request')
        super().send(payload)

    def write_ram(self, address, data):
        # The writer's write_ram pins its own image's address range, which the
        # larger marker image exceeds. send() above is the stricter rule here: it
        # passes only the next exact packet of the image this monitor was built for.
        for offset in range(0, len(data), 1024):
            self.send(b'\xff\x83' + struct.pack('<I', address + offset)
                      + data[offset:offset + 1024])

    def startup_event(self, timeout):
        """Validate framing but retain every diagnostic word, including unknown values."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.pending) >= 3:
                length = int.from_bytes(self.pending[1:3], 'big')
                if self.pending[0] != 0xAD or length != 6:
                    raise IOError('Invalid startup event header')
                if len(self.pending) >= 10:
                    packet = bytes(self.pending[:10])
                    del self.pending[:10]
                    if frame(packet[3:-1]) != packet or packet[3:5] != b'\xff\x00':
                        raise IOError('Invalid startup event checksum/flow')
                    value = int.from_bytes(packet[5:9], 'little')
                    self.journal.emit('startup_event', value=hex(value), packet=packet.hex())
                    self.startup.append(value)
                    return value
            try:
                self.pending.extend(self.device.read(0x81, 4096, timeout=200))
            except self.timeout_error:
                pass
        raise TimeoutError('Startup deadline; no retry or further writes')


def wait_ready(monitor, seconds=30):
    deadline = time.monotonic() + seconds
    acknowledged = False
    diagnostic_words = 0
    fatal = False
    while time.monotonic() < deadline:
        value = monitor.startup_event(max(0.01, deadline - time.monotonic()))
        if diagnostic_words:
            diagnostic_words -= 1
            continue
        if value == ROM_EXECUTING:
            if acknowledged:
                raise IOError('Duplicate execution acknowledgement')
            acknowledged = True
        elif not acknowledged:
            raise IOError('Missing ROM execution acknowledgement')
        elif value in (0xEBC0EEE1, 0xEBC0EEE2):
            diagnostic_words = 5 if value == 0xEBC0EEE1 else 4
        elif value == 0xCE:
            fatal = True  # keep recording until deadline, but never proceed to reads
        elif value == READY:
            if fatal:
                raise IOError('READY after fatal memory error')
            monitor.journal.emit('programmer_ready', writes_disabled=True)
            return
        # C0 is a recoverable memory-power retry. Other startup words are logged.
    raise TimeoutError('No programmer READY; no retry')


def load_and_start(monitor, segments, journal, lod_sha=LOD_SHA):
    monitor.armed = True
    for address, data in segments:
        monitor.write_ram(address, data)
        if monitor.read(address, len(data)) != data:
            raise IOError('RAM load mismatch; not executing')
    journal.emit('programmer_load_verified', sha256=lod_sha)
    monitor.write_ram(0xA1C000A0, struct.pack('<I', 0xFF))
    if monitor.read(0xA1C000A0, 24) != struct.pack('<6I', 0xFF, 0x81C00280, 0, 0, 0, 0):
        raise IOError('Execution context mismatch; not executing')
    journal.emit('programmer_start_intent', conditional_flash_status_write=True)
    monitor.internal(0xFF)
    wait_ready(monitor)


def inspect_runtime(monitor, journal, where=PINNED_RUNTIME):
    abi = monitor.read(where['map'], 60)
    geometry = monitor.read(where['geometry'], 28)
    layout = monitor.read(where['layout'], len(LAYOUT))
    context = monitor.read(where['flash_context'], 12)
    # Record what was read before judging it, so a mismatch can be diagnosed from the journal.
    journal.emit('runtime_read', abi=abi.hex(), geometry=geometry.hex(), layout=layout.hex(),
                 flash_context=context.hex())
    if abi != struct.pack('<15I', 0xFB05FA01, *([0] * 10),
                          BUFFER, BUFFER + 0x10000, BUFFER + 0x20000, 0x10000):
        raise IOError('Unexpected fresh ABI/mailbox/buffers')
    if geometry != GEOMETRY or layout != layout_for(where):
        raise IOError('Runtime flash layout mismatch')
    if context[4:8] != bytes.fromhex('c8601600') or context[8:11] != bytes.fromhex('c86016'):
        raise IOError('Runtime JEDEC differs from the reviewed c8 60 16')
    journal.emit('runtime_verified', flash_context=context.hex(), mailbox_commands_sent=0)


def read_flash(monitor, journal, name):
    data = bytearray()
    for offset in range(0, FLASH_SIZE, 0x40000):
        data.extend(monitor.read(FLASH_BASE + offset, 0x40000))
        journal.emit('read_progress', pass_name=name, bytes_read=len(data), total=FLASH_SIZE)
    result = bytes(data)
    journal.save(name + '.bin', result)
    return result


def query(monitor, journal, before, name='after-query', where=PINNED_RUNTIME):
    """The first mailbox commands: the writer's own start-up check, no flash command."""
    # The writer accepts no start-up word but these two, so neither does its check.
    if monitor.startup != [ROM_EXECUTING, READY]:
        raise IOError('Start-up reported more than acknowledgement and READY; no mailbox command')
    journal.emit('query_intent', commands=['PING', 'PING', 'GET_FINALIZE_INFO'])
    monitor.allowed = mailbox_packets(QUERY, where=where)
    programmer = Programmer(monitor, journal, where=where)
    programmer.initialize(JEDEC)
    mailbox = monitor.read(where['map'], 60)
    journal.emit('mailbox_after_query', abi=mailbox.hex())
    # Both slots done, the query's one-sector count in slot 0, nothing else moved.
    if mailbox != struct.pack('<15I', 0xFB05FA01, DONE, 0, BUFFER, 1, 0, DONE, 0, BUFFER, 0, 0,
                              BUFFER, BUFFER + 0x10000, BUFFER + 0x20000, 0x10000):
        raise IOError('Unexpected mailbox after the queries')
    after = read_flash(monitor, journal, name)
    if after != before or read_flash(monitor, journal, name + '-second') != after:
        raise IOError('Flash changed across the queries; no repair or retry')
    journal.emit('query_verified', mailbox_commands_sent=3, flash_commands_sent=0,
                 flash_unchanged_by_queries=True)
    return programmer


def status_answer(programmer, monitor, journal, command):
    """One command of the status or unlock build: the registers its arm read last."""
    size_field = programmer.where['map'] + 4 + programmer.slot * 20 + 12
    programmer.command(command)
    word = struct.unpack('<I', monitor.read(size_field, 4))[0]
    # Record what was read before judging it.
    journal.emit('status_word', command=command, value=hex(word))
    # The command went out with size 0. Only these arms fill the field, with the
    # registers under their complement, so anything else is not their answer.
    if word >> 16 != ~word & 0xFFFF:
        raise IOError('Status word lacks its complement; not a reading')
    return word & 0xFFFF


def status_registers(programmer, monitor, journal):
    """Flash status registers 2 and 1, from two status commands that must agree."""
    monitor.allowed = mailbox_packets([(READ_STATUS, 0, b'')] * 2, programmer.slot,
                                      programmer.where)
    first = status_answer(programmer, monitor, journal, READ_STATUS)
    if status_answer(programmer, monitor, journal, READ_STATUS) != first:
        raise IOError('Two status readings differ; no retry')
    if first & 3:
        raise IOError('WIP or WEL is set with no write under way; not a settled reading')
    return first


def read_status(programmer, monitor, journal, before):
    """Flash status registers 1 and 2, read twice by the status build. No flash write."""
    journal.emit('status_intent', commands=['READ_STATUS', 'READ_STATUS'],
                 flash_opcodes=['0x05', '0x35'])
    status = status_registers(programmer, monitor, journal)
    after = read_flash(monitor, journal, 'after-status')
    if after != before or read_flash(monitor, journal, 'after-status-second') != after:
        raise IOError('Flash changed across the status read; no repair or retry')
    journal.emit('status_read', status1=hex(status & 0xFF), status2=hex(status >> 8),
                 set_bits=[name for bit, name in enumerate(STATUS_BITS) if status >> bit & 1],
                 erase_or_program_commands_sent=0, flash_unchanged=True)
    return status


def clear_protection(programmer, monitor, journal, before):
    """One status-register write by the unlock build: QE with BP2-BP0 to QE alone.

    The arm holds both values and refuses any other state; so does this, first.
    Whatever happens after the command is sent, it is not sent again.
    """
    status = status_registers(programmer, monitor, journal)
    if status != PROTECTED_STATUS:
        raise IOError(f'Status registers read {status:#06x}, not the reviewed state '
                      f'{PROTECTED_STATUS:#06x}; no write')
    journal.emit('clear_protection_intent', before=f'{status:#06x}',
                 value=f'{CLEAR_STATUS:#06x}', flash_opcodes=['0x06', '0x01 0x00 0x02', '0x04'])
    monitor.allowed = mailbox_packets([(CLEAR_PROTECTION, 0, b'')], programmer.slot,
                                      programmer.where)
    # The arm's own read-back goes in the journal; two status commands decide.
    status_answer(programmer, monitor, journal, CLEAR_PROTECTION)
    status = status_registers(programmer, monitor, journal)
    if status != CLEAR_STATUS:
        raise IOError(f'Status registers read {status:#06x} after the write, not '
                      f'{CLEAR_STATUS:#06x}; no retry')
    after = read_flash(monitor, journal, 'after-clear')
    if after != before or read_flash(monitor, journal, 'after-clear-second') != after:
        raise IOError('Flash changed across the status write; no repair or retry')
    journal.emit('protection_cleared', before=f'{PROTECTED_STATUS:#06x}',
                 after=f'{status:#06x}', status_writes_sent=1,
                 erase_or_program_commands_sent=0, flash_unchanged=True)


def write_test(programmer, monitor, journal, before):
    """The first flash commands: program both ends of one blank sector, then erase it."""
    if before[TEST_SECTOR:TEST_SECTOR + 0x10000] != b'\xff' * 0x10000:
        raise IOError('Test sector is not blank; no flash command')
    journal.emit('write_test_intent', sector=hex(TEST_SECTOR),
                 commands=['PROGRAM', 'PROGRAM', 'ERASE'])
    monitor.allowed = mailbox_packets(WRITE_TEST, programmer.slot)
    expected = bytearray(before)
    for command, offset, data in WRITE_TEST:
        programmer.command(command, offset, data)
        if command == PROGRAM:
            expected[offset:offset + len(data)] = data
            # The whole flash, not the chunk: a write that landed elsewhere must show.
            if read_flash(monitor, journal, f'after-program-{offset:06x}') != expected:
                raise IOError('Program verification failed; no repair or retry')
    after = read_flash(monitor, journal, 'after-erase')
    if after != before or read_flash(monitor, journal, 'after-erase-second') != after:
        raise IOError('Erase verification failed; no repair or retry')
    journal.emit('write_test_verified', flash_commands_sent=3,
                 flash_identical_to_pre_start=True)


def reset_test(monitor, journal, before, reopen):
    """One reset from inside the programmer session: does the ROM's USB come back?

    This is the restart a blank boot word would depend on, tried while the word is
    still valid. `reopen` waits for the ROM port and returns a read-only monitor on it.
    """
    journal.emit('reset_test_intent', flash_commands_sent=0)
    rom = restart(monitor, journal, reopen)
    if read_flash(rom, journal, 'after-reset') != before:
        raise IOError('Flash differs after the reset; no repair or retry')
    journal.emit('reset_test_verified', rom_usb_returned=True, flash_commands_sent=0,
                 flash_identical_to_pre_start=True)


def restart(monitor, journal, reopen):
    """One debug reset, then the monitor `reopen` returns on the ROM port, handshaken."""
    journal.emit('restart_intent', tx=frame(RESET).hex())
    monitor.reset_armed = True
    try:
        monitor.send(RESET)
    except IOError as exc:
        # The chip resets while the transfer is still being acknowledged.
        journal.emit('reset_transfer_uncertain', error=str(exc))
    rom = reopen()
    rom.internal(0xFD)
    if rom.receive(0, 4) != struct.pack('<I', ROM_START):
        raise IOError('ROM handshake mismatch after the reset')
    return rom


def boot_block_commands(image, finalize):
    """Erase block 0 and program it back in 4 KiB chunks, the boot word withheld.

    These are the commands the writer's restore() sends for sector zero; END, which
    writes the boot word, comes last and only when asked for.
    """
    commands = [(ERASE, 0, b'')]
    for start in range(0, 0x10000, 4096):
        chunk = image[start:start + 4096]
        commands.append((PROGRAM, start, b'\xff' * 4 + chunk[4:] if start == 0 else chunk))
    if finalize:
        commands.append((END, 0, b''))
    return commands


def blank_boot_word(programmer, monitor, journal, before):
    """Rewrite block 0 as it is, except the boot word, which stays blank. No END."""
    if struct.unpack_from('<I', before)[0] != MAGIC:
        raise IOError('Boot word is not the magic value; no flash command')
    blank = b'\xff' * 4 + before[4:]
    commands = boot_block_commands(before, finalize=False)
    journal.emit('blank_word_intent', commands=['ERASE'] + ['PROGRAM'] * 16)
    monitor.allowed = mailbox_packets(commands, programmer.slot)
    programmer.command(*commands[0])
    if monitor.read(FLASH_BASE, 0x10000) != b'\xff' * 0x10000:
        raise IOError('Erase verification failed; stop without retry')
    for command in commands[1:]:
        programmer.command(*command)
    # The whole flash, not the block: a write that landed elsewhere must show.
    if read_flash(monitor, journal, 'after-blank') != blank:
        raise IOError('Flash is not the pre-start image with a blank boot word')
    journal.emit('boot_word_blank', flash_commands_sent=len(commands))
    return blank


def rewrite_boot_block(monitor, journal, current, target, backup, unit, segments, lod_sha, where):
    """On a ROM monitor: start the programmer and run the writer's restore of block 0."""
    load_and_start(monitor, segments, journal, lod_sha)
    inspect_runtime(monitor, journal, where)
    # The journal never overwrites a file, and a blank-word run has already saved its
    # first session's reads under the query's default name.
    programmer = query(monitor, journal, current, 'before-restore')
    # restore() plans from the flash itself. Anything but block 0 in its plan is
    # refused here, packet by packet.
    monitor.allowed = mailbox_packets(boot_block_commands(target, finalize=True),
                                      programmer.slot)
    restore(programmer, target, backup, unit, journal)
    if read_flash(monitor, journal, 'after-restore') != target:
        raise IOError('Flash is not the target image after the restore')
    journal.emit('boot_block_restored', boot_word=hex(MAGIC), flash_identical_to_target=True)


def image_commands(current, target, backup, unit, finalize):
    """Exact wire allowlist, independently bound to current flash and target bytes."""
    work = plan(current, target, backup, unit)
    if unit == ORIGINAL_UNIT:
        raise ValueError('Block 0 is never rewritten on the original unit')
    commands = []
    for sector in work['sectors']:
        offset, size = sector['offset'], sector['erase_bytes']
        commands.append((ERASE, offset, b''))
        for start in range(offset, offset + size, 4096):
            chunk = target[start:start + 4096]
            commands.append((PROGRAM, start, b'\xff' * 4 + chunk[4:] if start == 0 else chunk))
    if finalize and work['finalize_boot_magic']:
        commands.append((END, 0, b''))
    return commands


def write_image(programmer, monitor, journal, current, target, backup, unit, *, finalize):
    commands = image_commands(current, target, backup, unit, finalize)
    monitor.allowed = mailbox_packets(commands, programmer.slot)
    restore(programmer, target, backup, unit, journal, finalize=finalize)
    if monitor.allowed:
        raise IOError('Image write did not consume its exact command plan')
    expected = target if finalize else b'\xff' * 4 + target[4:]
    if read_flash(monitor, journal, 'after-image') != expected:
        raise IOError('Second full image verification failed')


# Logicrom 0.5.1 takes flash up to its end for its file system and marks a sector by
# zeroing its first 32 bytes. On 412 it did that to all six calibration/factory
# sectors before the core reset (2026-10-09); the rest of each sector was untouched.
TAIL_MARK = 32


def tail_repair_sectors(current, backup):
    """The protected 4 KiB sectors a repair may rewrite; ValueError for anything else.

    A byte may differ from the unit's backup only by being zero inside the mark, or
    erased: a repair that stopped after an erase leaves the sector blank. Any other
    difference is another unit's data, or damage nobody has looked at.
    """
    sectors = []
    for offset in range(PROTECTED, FLASH_SIZE, 0x1000):
        now, good = current[offset:offset + 0x1000], backup[offset:offset + 0x1000]
        if now == good:
            continue
        for index, (byte, wanted) in enumerate(zip(now, good)):
            if byte != wanted and byte != 0xFF and not (index < TAIL_MARK and byte == 0):
                raise ValueError('Protected bytes differ beyond the known marks; no repair')
        sectors.append(offset)
    return sectors


def repair_tail(programmer, monitor, journal, current, backup, sectors):
    """Erase the marked calibration/factory sectors and program them from the backup."""
    commands = []
    for offset in sectors:
        commands += [(ERASE, offset, b''), (PROGRAM, offset, backup[offset:offset + 0x1000])]
    journal.emit('tail_repair_intent', sectors=[hex(offset) for offset in sectors],
                 source='unit backup', commands=['ERASE', 'PROGRAM'] * len(sectors))
    monitor.allowed = mailbox_packets(commands, programmer.slot)
    programmer.limit = FLASH_SIZE
    try:
        for offset in sectors:
            wanted = backup[offset:offset + 0x1000]
            journal.save(f'tail-sector-{offset:06x}.bin', current[offset:offset + 0x1000])
            programmer.command(ERASE, offset)
            if programmer.read_flash(offset, 0x1000) != b'\xff' * 0x1000:
                raise IOError('Erase verification failed; stop without retry')
            programmer.command(PROGRAM, offset, wanted)
            if programmer.read_flash(offset, 0x1000) != wanted:
                raise IOError('Program verification failed; stop without retry')
            journal.emit('tail_sector_restored', offset=offset)
    finally:
        programmer.limit = PROTECTED
    repaired = current[:PROTECTED] + backup[PROTECTED:]
    # The whole flash, not the sectors: an erase that reached further must show.
    if read_flash(monitor, journal, 'after-tail-repair') != repaired:
        raise IOError('Flash is not the pre-repair image with the backup tail')
    journal.emit('tail_repaired', sectors=len(sectors), tail_sha256=sha(backup[PROTECTED:]))
    return repaired


def recovery_target(path, backup, unit):
    target = (path / 'before-startup.bin').read_bytes()
    # A power/process interruption can truncate the final journal event. The scope
    # and durable pre-start save precede every flash command; only those are needed.
    events = []
    for line in (path / 'operations.jsonl').read_text().splitlines():
        events.append(json.loads(line))
        if events[-1].get('event') == 'saved' and events[-1].get('file') == 'before-startup.bin':
            break
    if (len(target) != FLASH_SIZE or target[:0x362000] != backup[:0x362000]
            or target[PROTECTED:] != backup[PROTECTED:]
            or not any(e.get('event') == 'scope' and e.get('unit') == unit for e in events)
            or not any(e.get('event') == 'saved' and e.get('file') == 'before-startup.bin'
                       and e.get('sha256') == sha(target) for e in events)):
        raise ValueError('Not an intact, journaled pre-start image of this unit')
    return target


def trial_source(args, backup):
    from rda_logicrom_image import validate_trial
    image = args.trial.read_bytes()
    if sha(image) != args.trial_sha256:
        raise ValueError('Trial image SHA-256 mismatch')
    validate_trial(image, backup)
    return image


def start_trial(monitor, journal, expected):
    """Exit the ROM once, only after two complete reads of the blank-word image."""
    if expected[:4] != b'\xff' * 4:
        raise ValueError('Trial start requires a blank boot word')
    for name in ('trial-before-exit', 'trial-before-exit-second'):
        if read_flash(monitor, journal, name) != expected:
            raise IOError('Trial changed across reset; not starting')
    journal.emit('trial_exit_intent', tx=frame(ROM_EXIT).hex(), boot_word='0xffffffff',
                 expected_entry='0x88000010')
    monitor.exit_armed = True
    monitor.send(ROM_EXIT)
    journal.emit('trial_exit_sent', firmware_boot_verified=False,
                 recovery='Press RST, then separately approved --finish on installation journal')


def run(args, baseline, backup, segments, lod_sha, where):
    import usb.backend.libusb1
    import usb.core
    import usb.util
    from rda_dump import LIBUSB, read_block
    from rda_recovery_snapshot import read_word
    from rda_rom_recovery import (device_named, snapshot, observe, send, boot_packet,
                                  DEBUG_RESET, RESET_CAUSE, NORMAL_BOOT_FIELDS, FORCE_MONITOR,
                                  BOOT_FIELDS, compare)
    # Validate all disk inputs before touching USB. Keep immutable bytes for the run.
    target = recovery_target(args.finish, backup, args.unit) if args.finish else None
    trial = trial_source(args, backup) if args.trial else None
    # A tail repair is bound to the unit this journal installed its trial image on.
    installed = ((args.finish / 'trial-target.bin').read_bytes()
                 if args.finish and args.repair_tail else None)
    if (args.finish or args.trial) and args.unit == ORIGINAL_UNIT:
        raise ValueError('Block 0 is never rewritten on the original unit')
    journal = StartJournal(args.journal)
    device = None

    def emit(event, **fields):
        journal.emit(event, **fields)

    def reopen(load=()):
        """After a debug reset sent in a ROM session: a monitor on the returned ROM port."""
        nonlocal device
        reset_at = time.monotonic()
        stale, device = device, None
        # The ROM resets the chip without dropping off the bus, so the Mac can keep the
        # old device entry and never re-enumerate (run 1 on 412: listed but silent for
        # 30 s). Give the chip a second to restart, look, and only then ask the Mac for
        # a port reset. All of it stays inside the monitor's 30 s idle limit.
        time.sleep(1)
        returned = observe(backend, emit, 3, reset_at, stop_on='Coolsand Usb')
        if not returned:
            journal.emit('host_port_reset_intent')
            try:
                stale.reset()
            except (usb.core.USBError, ValueError) as exc:
                journal.emit('host_port_reset_error', error=str(exc))
            returned = observe(backend, emit, 23, reset_at, stop_on='Coolsand Usb')
        usb.util.dispose_resources(stale)
        if not returned:
            raise IOError('No ROM enumeration after the reset; no retry')
        journal.emit('rom_port_returned', since_reset=round(time.monotonic() - reset_at, 3))
        device = device_named(backend, 'Coolsand Usb')
        # With no load image it passes the handshake and reads only.
        return StartMonitor(device, journal, usb.core.USBTimeoutError, list(load))

    def from_rom_port(name):
        """A unit in a ROM monitor or programmer of unknown state: a fresh ROM session.

        Both take the debug reset through the ROM's decoder. Returns the monitor and
        the flash as two equal reads found it.
        """
        nonlocal device
        found = [d for d in usb.core.find(find_all=True, backend=backend)
                 if (d.idVendor, d.idProduct) == (0x1E04, 0x0900)]
        if len(found) != 1:
            raise IOError('Expected exactly one tracker in 1e04:0900 mode')
        try:
            found[0].reset()  # make a stale entry reachable before talking to it
        except (usb.core.USBError, ValueError) as exc:
            journal.emit('host_port_reset_error', error=str(exc))
        usb.util.dispose_resources(found[0])
        time.sleep(1)
        device = device_named(backend, 'Coolsand Usb')
        monitor = StartMonitor(device, journal, usb.core.USBTimeoutError, [])
        monitor = restart(monitor, journal, lambda: reopen(segments))
        if sha(monitor.read(0xA1E00000, 0x6000)) != ROM_SHA:
            raise IOError('ROM hash mismatch')
        current = read_flash(monitor, journal, name)
        if read_flash(monitor, journal, name + '-second') != current:
            raise IOError('Two ROM flash reads differ; not loading')
        return monitor, current

    try:
        journal.emit('scope', unit=args.unit, programmer_sha256=lod_sha,
                     baseline_sha256=sha(baseline), mailbox_commands_allowed=args.query,
                     flash_commands_allowed=args.write_test or args.blank_word_test
                     or args.blank_word_stop or bool(args.finish) or bool(args.trial),
                     finish=bool(args.finish), reset_test=args.reset_test,
                     read_status=args.read_status, from_rom=args.from_rom,
                     status_write_allowed=args.clear_protection,
                     trial=bool(args.trial), repair_tail=bool(args.repair_tail), recovery='No RST/unplug during writes; use --finish')
        backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
        journal.emit('usb_preflight', **snapshot(backend))
        if args.finish:
            # A blank-word/trial run stopped: flash may differ in any writable sector,
            # and the chip is in a ROM monitor or programmer of unknown state.
            journal.save('recovery-target.bin', target)
            journal.emit('recovery_source', journal=str(args.finish), sha256=sha(target))
            monitor, current = from_rom_port('before-finish')
            journal.emit('target_comparison', **compare(current, target))
            repair = []
            if args.repair_tail and current[PROTECTED:] != backup[PROTECTED:]:
                from rda_logicrom_image import APP_END
                repair = tail_repair_sectors(current, backup)
                if current[4:APP_END] != installed[4:APP_END]:
                    raise ValueError('Not the unit this journal installed the trial on; '
                                     'no repair')
            # Binds the live protected tail, or the one the repair must restore first.
            work = plan(current[:PROTECTED] + backup[PROTECTED:] if repair else current,
                        target, backup, args.unit)
            if not repair and current[0x10000:] == target[0x10000:] and work['sectors']:
                rewrite_boot_block(monitor, journal, current, target, backup, args.unit,
                                   segments, lod_sha, where)
            elif work['sectors'] or repair:
                if current[:4] != b'\xff' * 4:
                    raise IOError('Full recovery requires blank boot word; not loading')
                load_and_start(monitor, segments, journal, lod_sha)
                inspect_runtime(monitor, journal, where)
                programmer = query(monitor, journal, current, 'before-restore')
                if repair:
                    # Before any other sector, and before END can make the unit bootable.
                    current = repair_tail(programmer, monitor, journal, current, backup,
                                          repair)
                write_image(programmer, monitor, journal, current, target, backup,
                            args.unit, finalize=True)
                journal.emit('full_image_restored', sha256=sha(target),
                             flash_identical_to_pre_start=True)
            else:
                journal.emit('no_changes', sha256=sha(current))
            return
        if args.from_rom or args.clear_protection:
            # A unit without a boot word waits in the ROM, and its code may be any
            # firmware's. Only the calibration/factory tail binds it to its backup.
            monitor, before = from_rom_port('before-startup')
            if before[PROTECTED:] != backup[PROTECTED:]:
                raise IOError('Unit calibration/factory identity mismatch')
            load_and_start(monitor, segments, journal, lod_sha)
            inspect_runtime(monitor, journal, where)
            programmer = query(monitor, journal, before, where=where)
            if args.clear_protection:
                clear_protection(programmer, monitor, journal, before)
            else:
                read_status(programmer, monitor, journal, before)
            return
        device = device_named(backend, 'RDA Usb')
        try:
            stale = device.read(0x81, 4096, timeout=100)
        except usb.core.USBTimeoutError:
            stale = b''
        if stale:
            raise IOError('Queued vendor data; stopping before requests')
        if read_block(device, 0x88000000) != backup[:1024]:
            raise IOError('Vendor boot mismatch')
        # Calibration/factory tail binds the connected unit, unlike shared boot code.
        tail = b''.join(read_block(device, 0x88000000 + n)
                        for n in range(PROTECTED, FLASH_SIZE, 1024))
        if tail != backup[PROTECTED:]:
            raise IOError('Unit calibration/factory identity mismatch')
        rom = b''.join(read_block(device, 0x81E00000 + n) for n in range(0, 0x6000, 1024))
        if sha(rom) != ROM_SHA:
            raise IOError('Vendor ROM mismatch')
        cause = read_word(device, RESET_CAUSE)
        if cause not in (NORMAL_BOOT_FIELDS, NORMAL_BOOT_FIELDS | FORCE_MONITOR):
            raise IOError(f'Unexpected boot fields {cause:#x}; no write/reset')
        forced = NORMAL_BOOT_FIELDS | FORCE_MONITOR
        journal.emit('force_intent', previous=hex(cause), value=hex(forced))
        send(device, boot_packet(forced))
        if read_word(device, RESET_CAUSE) & BOOT_FIELDS != forced:
            raise IOError('Force readback mismatch; no reset or retry')
        journal.emit('reset_intent', tx=DEBUG_RESET.hex())
        try:
            send(device, DEBUG_RESET)
        except usb.core.USBError as exc:
            journal.emit('reset_transfer_uncertain', error=str(exc))
        reset_at = time.monotonic()
        usb.util.dispose_resources(device)
        device = None
        if not observe(backend, emit, 30, reset_at, stop_on='Coolsand Usb'):
            raise IOError('No ROM enumeration; no reset retry')
        device = device_named(backend, 'Coolsand Usb')
        monitor = StartMonitor(device, journal, usb.core.USBTimeoutError, segments)
        monitor.internal(0xFD)
        if monitor.receive(0, 4) != struct.pack('<I', ROM_START):
            raise IOError('ROM handshake mismatch')
        if sha(monitor.read(0xA1E00000, 0x6000)) != ROM_SHA:
            raise IOError('ROM hash mismatch')
        before = read_flash(monitor, journal, 'before-startup')
        if read_flash(monitor, journal, 'before-startup-second') != before:
            raise IOError('Two ROM flash reads differ; not loading')
        journal.emit('baseline_comparison_before', **compare(before, baseline))
        if before[:0x362000] != baseline[:0x362000] or before[PROTECTED:] != baseline[PROTECTED:]:
            raise IOError('Code or protected tail changed; not loading')
        load_and_start(monitor, segments, journal, lod_sha)
        inspect_runtime(monitor, journal, where)
        after = read_flash(monitor, journal, 'after-startup')
        repeated = read_flash(monitor, journal, 'after-startup-second')
        journal.emit('startup_comparison', **compare(after, before))
        journal.emit('baseline_comparison_after', **compare(after, baseline))
        if after != before or repeated != after:
            raise IOError('Post-start flash mismatch; no repair or retry')
        inspect_runtime(monitor, journal, where)
        journal.emit('verified', sha256=sha(after), flash_unchanged_by_startup=True,
                     matches_baseline=after == baseline, mailbox_commands_sent=0,
                     recovery='Press physical RST', flash_writing_qualified=False)
        if args.query:
            programmer = query(monitor, journal, before, where=where)
            if args.write_test:
                write_test(programmer, monitor, journal, before)
            if args.read_status:
                read_status(programmer, monitor, journal, before)
        if trial is not None:
            from rda_logicrom_image import APP_END
            # Vendor settings can change since the backup. Preserve the fresh snapshot.
            target = trial[:APP_END] + before[APP_END:]
            journal.save('trial-target.bin', target)
            journal.emit('trial_source', sha256=sha(trial), live_target_sha256=sha(target))
            plan(before, target, backup, args.unit)
            blank = blank_boot_word(programmer, monitor, journal, before)
            write_image(programmer, monitor, journal, blank, target, backup, args.unit,
                        finalize=False)
            if args.trial_stop:
                journal.emit('trial_installed_stopped', boot_word='0xffffffff',
                             firmware_started=False, recovery='Use --finish on this journal')
                return
            rom = restart(monitor, journal, reopen)
            start_trial(rom, journal, b'\xff' * 4 + target[4:])
            return
        if args.reset_test:
            reset_test(monitor, journal, before, reopen)
        if args.blank_word_test or args.blank_word_stop:
            blank = blank_boot_word(programmer, monitor, journal, before)
            if args.blank_word_stop:
                journal.emit('blank_word_stopped', boot_word='0xffffffff',
                             flash_identical_except_boot_word=True,
                             recovery='No RST, unplug or power button; run --finish on this journal')
                return
            monitor = restart(monitor, journal, lambda: reopen(segments))
            # With a valid boot word the ROM leaves an idle monitor after 30 s (Run B,
            # and reset test run 1). Stay silent past that: an answer afterwards means
            # the blank word is what holds it.
            journal.emit('idle_wait', seconds=IDLE)
            time.sleep(IDLE)
            if read_flash(monitor, journal, 'blank-after-idle') != blank:
                raise IOError('Flash changed across the restart; block 0 still lacks its word')
            journal.emit('monitor_held_by_blank_word', idle_seconds=IDLE)
            rewrite_boot_block(monitor, journal, blank, before, backup, args.unit,
                               segments, lod_sha, where)
    except BaseException as exc:
        journal.emit('stopped', error=f'{type(exc).__name__}: {exc}', automatic_retry=False)
        raise
    finally:
        if device is not None:
            usb.util.dispose_resources(device)
        journal.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--unit', choices=sorted(UNITS), required=True)
    parser.add_argument('--journal', type=Path)
    parser.add_argument('--markers', action='store_true',
                        help='load the stage-marker diagnostic build instead of the pinned one')
    parser.add_argument('--query', action='store_true',
                        help='after the start, PING both mailbox slots and query finalize info')
    parser.add_argument('--write-test', action='store_true',
                        help='after the query, program and erase one blank 64 KiB sector')
    parser.add_argument('--reset-test', action='store_true',
                        help='after the query, one debug reset; the ROM port must return')
    parser.add_argument('--blank-word-test', action='store_true',
                        help='after the query, rewrite block 0 without its boot word, restart, '
                             'require the monitor past its idle limit, then restore the word')
    parser.add_argument('--blank-word-stop', action='store_true',
                        help='rewrite block 0 without its boot word and stop; no reset or END; '
                             'keep USB connected and restore with --finish')
    parser.add_argument('--finish', type=Path, metavar='JOURNAL',
                        help="restore all changed unprotected sectors from a run's pre-start image, "
                             'starting from the ROM port instead of the vendor firmware')
    parser.add_argument('--repair-tail', action='store_true',
                        help='with --finish: first rewrite, from the unit backup, the '
                             'calibration/factory sectors whose 32-byte heads Logicrom zeroed')
    parser.add_argument('--trial', type=Path, metavar='IMAGE',
                        help='install core/app with boot word blank, reset to ROM, verify and exit '
                             'the monitor once to start it; no END')
    parser.add_argument('--trial-sha256', help='required exact hash of the reviewed trial image')
    parser.add_argument('--trial-stop', action='store_true',
                        help='with --trial: stop after installation, without starting the core')
    parser.add_argument('--read-status', action='store_true',
                        help='load the status build and, after the query, read flash status '
                             'registers 1 and 2 twice; no erase, program or status write')
    parser.add_argument('--from-rom', action='store_true',
                        help='with --read-status: start on the ROM port of a unit that has '
                             'no boot word, instead of from the vendor firmware')
    parser.add_argument('--clear-protection', action='store_true',
                        help='on a spare waiting in the ROM: load the unlock build and write '
                             'the flash status registers once, from 0x1c/0x02 (BP2-BP0 set) '
                             'to 0x00/0x02; any other state is refused; no erase or program')
    args = parser.parse_args()
    tests = ('--write-test', '--reset-test', '--blank-word-test', '--blank-word-stop', '--finish',
             '--trial', '--read-status', '--clear-protection')
    if args.read_status and args.markers:
        parser.error('--read-status loads the status build, not --markers')
    if args.clear_protection and args.markers:
        parser.error('--clear-protection loads the unlock build, not --markers')
    if args.clear_protection and args.unit == ORIGINAL_UNIT:
        # 417 stays the reference: its registers are what the write aims for.
        parser.error('Status registers are never written on the original unit')
    if args.from_rom and not args.read_status:
        parser.error('--from-rom needs --read-status')
    for flag in ('--query',) + tests:
        if args.markers and getattr(args, flag[2:].replace('-', '_')):
            # The mailbox packets are addressed to the pinned build's mailbox.
            parser.error(f'{flag} needs the pinned build, not --markers')
    if sum(bool(getattr(args, flag[2:].replace('-', '_'))) for flag in tests) > 1:
        parser.error(' and '.join(tests) + ' are separate runs')
    if bool(args.trial) != bool(args.trial_sha256) or (args.trial_stop and not args.trial):
        parser.error('--trial needs --trial-sha256; --trial-stop needs --trial')
    if args.repair_tail and not args.finish:
        parser.error('--repair-tail needs --finish')
    if (args.blank_word_test or args.blank_word_stop or args.finish or args.trial) and args.unit == ORIGINAL_UNIT:
        # 417 stays the untouched reference, as in the writer.
        parser.error('Block 0 is never rewritten on the original unit')
    # Every test starts from the query's state.
    args.query = (args.query or args.write_test or args.reset_test or args.blank_word_test
                  or args.blank_word_stop or bool(args.trial) or args.read_status
                  or args.clear_protection)
    unit = UNITS[args.unit]
    baseline = unit['baseline'].read_bytes()
    backup = unit['backup'].read_bytes()
    if (len(baseline) != FLASH_SIZE or sha(baseline) != unit['baseline_sha']
            or len(backup) != FLASH_SIZE or sha(backup) != unit['backup_sha']):
        raise ValueError('Pinned baseline/backup hash mismatch')
    if args.trial:
        trial_source(args, backup)
    if args.finish:
        recovery_target(args.finish, backup, args.unit)
    if args.markers:
        name, lod_sha, where = 'marker', MARKER_SHA, MARKER_RUNTIME
        segments = read_local_lod(MARKER_LOD, lod_sha, where)
    elif args.read_status:
        name, lod_sha, where = 'status', STATUS_SHA, STATUS_RUNTIME
        segments = read_local_lod(STATUS_LOD, lod_sha, where)
    elif args.clear_protection:
        name, lod_sha, where = 'unlock', UNLOCK_SHA, UNLOCK_RUNTIME
        segments = read_local_lod(UNLOCK_LOD, lod_sha, where)
    else:
        name, lod_sha, where = "writer's", LOD_SHA, PINNED_RUNTIME
        segments = read_lod(LOD)
    print(f'Validated pinned {name} programmer {lod_sha[:8]} and the baseline and backup of '
          f'{args.unit}. One ROM reset/load/start, then two full flash reads. '
          'No RST, unplug or power button during the run.', flush=True)
    if args.query:
        print('Then PING on each mailbox slot and the finalize-info query.', flush=True)
    if args.read_status:
        print('Then the status command twice: flash status registers 1 and 2 are read '
              '(opcodes 0x05 and 0x35) and must agree, and the whole flash must read back '
              'unchanged.' + (' The run starts on the ROM port and binds the unit by its '
                              'calibration/factory tail; the unit stays in the programmer, '
                              'still without a boot word.' if args.from_rom else ''),
              flush=True)
    if args.clear_protection:
        print('Then ONE FLASH STATUS-REGISTER WRITE, from the ROM port, with the unit bound '
              'by its calibration/factory tail: registers 1 and 2 must read '
              f'{PROTECTED_STATUS & 0xFF:#04x} and {PROTECTED_STATUS >> 8:#04x} twice; one '
              f'command writes {CLEAR_STATUS & 0xFF:#04x} and {CLEAR_STATUS >> 8:#04x} '
              '(01h 00h 02h after a write-enable); they must then read those values twice '
              'and the whole flash must read back unchanged. The command is never sent '
              'twice. The unit stays in the programmer, still without a boot word.',
              flush=True)
    if args.reset_test:
        print(f'Then one debug reset ({frame(RESET).hex(" ")}); the ROM port, its handshake '
              'and the pre-start flash image must return.', flush=True)
    if args.write_test:
        print(f'Then FLASH WRITES in blank sector {TEST_SECTOR:#x} only: program its first and '
              'last 4 KiB, erase the sector, and require the pre-start image again.', flush=True)
    elif args.blank_word_stop:
        print('Then FLASH WRITES in block 0 only: erase it and program it back without the '
              'boot word; check the whole flash and stop in the programmer. No reset or END. '
              'No RST, unplug or power button: the unit has no boot word until --finish '
              'restores it from this journal.', flush=True)
    elif args.blank_word_test:
        print('Then FLASH WRITES in block 0 only: erase it and program it back without the '
              f'boot word; one debug reset; {IDLE} s of silence; then a fresh programmer '
              'erases and programs block 0 again and END writes the boot word. The pre-start '
              'image must return. If it stops part-way: no RST, no unplug, run --finish.',
              flush=True)
    elif args.finish:
        print(f'FLASH WRITES to every changed unprotected sector, from the ROM port: restore '
              f'{args.finish}/before-startup.bin, verify all 4 MiB, then write the boot word.', flush=True)
        if args.repair_tail:
            print('First, FLASH WRITES TO THE CALIBRATION/FACTORY TAIL: sectors that differ '
                  'from the unit backup only by a zeroed 32-byte head are erased and '
                  'programmed from that backup. Any other difference stops the run.', flush=True)
    elif args.trial:
        print(f'FLASH WRITES: blank block 0 first, install {args.trial} with current data '
              'above 0x2e0000 preserved; verify twice; never send END. '
              + ('Stop in programmer for recovery rehearsal.' if args.trial_stop else
                 'Reset, verify twice in ROM, exit once to start the trial.'), flush=True)
    else:
        print('No erase, program or finalize.', flush=True)
    if args.execute:
        if args.journal is None or not args.journal.resolve().is_relative_to(LIVE_ROOT.resolve()):
            parser.error('--execute requires a new --journal under firmware/live')
        run(args, baseline, backup, segments, lod_sha, where)


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
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(status)  # avoid the documented libusb teardown hang
