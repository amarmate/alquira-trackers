"""Read 412's flash security registers through ROM-controlled SPI MMIO.

No code execution, SRAM payload, reset, exit, flash/status write, or activation.
The only write targets are five SPI controller registers. SPI commands are
restricted to JEDEC/SR1/SR2/security reads. Original config/block size restored.

Disabled historical experiment. The pinned ROM implements these nominal word
writes and four-byte reads with byte accesses in memcpy, unlike the HAL's word
MMIO. See docs/knowledge/rom-flash-access.md#5-spi-controller-and-clock-facts; do not replay it.
"""
import argparse
import os
from pathlib import Path
import struct
import sys
import time

from rda_dump import LIBUSB
from rda_flash import ROM_SHA, ROM_START, sha
from rda_programmer_start import ROOT, StartJournal, StartMonitor
from rda_logicrom_license_capture import validate_local, validate_live
from rda_security_read import read_image

SPI = 0xa7fff000
READ_COMMANDS = {0x9f: 3, 5: 1, 0x35: 1, 0x48: 4}


class SpiMonitor(StartMonitor):
    def __init__(self, device, journal, timeout_error):
        super().__init__(device, journal, timeout_error, [])
        self.allowed_word = None
        self.block_values, self.config_values = set(), set()

    def send(self, payload):
        if payload[:2] == b'\xff\x82' and len(payload) == 10:
            if payload != self.allowed_word:
                raise ValueError('SPI write not exactly armed')
            self.allowed_word = None
            address, value = struct.unpack_from('<II', payload, 2)
            offset = address - SPI
            valid = (offset == 0 and value in (0x19f00, 0x10500, 0x13500, 0x14800)
                     or offset == 4 and value in self.block_values
                     or offset == 0x14 and value in self.config_values
                     or offset == 8 and 0 <= value <= 255
                     or offset == 0x18 and value == 3)
            if not valid:
                raise ValueError('Forbidden controller register/value')
            self.journal.emit('spi_mmio_write', address=hex(address), value=hex(value))
            # Parent only permits SRAM payloads; this separate narrow allowlist
            # permits the specific controller registers instead.
            from rda_flash import Monitor
            Monitor.send(self, payload)
        else:
            super().send(payload)

    def word(self, offset):
        return struct.unpack('<I', self.read(SPI + offset, 4))[0]

    def write_word(self, offset, value):
        if self.allowed_word is not None:
            raise ValueError('Unconsumed MMIO write')
        payload = b'\xff\x82' + struct.pack('<II', SPI + offset, value)
        self.allowed_word = payload
        self.send(payload)

    def idle(self):
        deadline = time.monotonic() + 1
        for _ in range(100):
            if not self.word(0x0c) & 1:
                if not self.word(0x0c) & 1:
                    return
            if time.monotonic() >= deadline:
                break
        raise TimeoutError('SPI controller busy; no further commands')


class Reader:
    def __init__(self, monitor):
        self.monitor = monitor
        monitor.idle()
        self.block, self.config = monitor.word(4), monitor.word(0x14)
        monitor.block_values = {self.block} | {
            (self.block & ~0x1ff00) | (count << 8) for count in (1, 3, 4)}
        monitor.config_values = {self.config} | {
            (self.config & ~(3 << 17)) | (mode << 17) for mode in (0, 2, 3)}

    def restore(self):
        m = self.monitor
        m.idle()
        m.write_word(0x14, self.config)
        m.write_word(4, self.block)
        m.idle()
        if (m.word(4), m.word(0x14)) != (self.block, self.config):
            raise IOError('SPI controller restoration mismatch')

    def read(self, opcode, address=None):
        if opcode not in READ_COMMANDS:
            raise ValueError('Only four SPI read commands permitted')
        if opcode == 0x48:
            if address is None or address % 4 or not 0x1000 <= address <= 0x10fc:
                raise ValueError('Security read outside fixed 256-byte record')
        elif address is not None:
            raise ValueError('Unexpected SPI read address')
        m = self.monitor
        count = READ_COMMANDS[opcode]
        m.idle()
        m.write_word(0x18, 3)
        m.idle()
        m.write_word(4, (self.block & ~0x1ff00) | (count << 8))
        m.write_word(0x14, (self.config & ~(3 << 17)) | ({1: 0, 3: 3, 4: 2}[count] << 17))
        m.idle()
        if address is not None:
            for byte in (*address.to_bytes(3, 'big'), 0):
                m.write_word(8, byte)
        m.write_word(0, (opcode | 0x100) << 8)
        m.idle()
        value = m.word(0x10) >> ((4 - count) * 8)
        self.restore()
        return value

    def status(self):
        return self.read(5) | (self.read(0x35) << 8)


def run(path):
    import usb.backend.libusb1
    import usb.core
    from rda_rom_recovery import device_named
    image, backup = validate_local()
    journal = StartJournal(path)
    reader = None
    try:
        journal.emit('scope', unit='1403167412', operations='ROM reads and SPI '
                     'controller MMIO for fixed read commands only; no payload execution',
                     flash_writes=False, status_writes=False, security_writes=False,
                     execute=False, load=False, reset=False, exit=False,
                     spi_opcodes=list(READ_COMMANDS))
        backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
        device = device_named(backend, 'Coolsand Usb')
        monitor = SpiMonitor(device, journal, usb.core.USBTimeoutError)
        monitor.internal(0xfd)
        if monitor.receive(0, 4) != struct.pack('<I', ROM_START):
            raise IOError('ROM handshake mismatch')
        if sha(monitor.read(0xa1e00000, 0x6000)) != ROM_SHA:
            raise IOError('ROM hash mismatch')
        first = read_image(monitor, journal, 'before-mmio')
        validate_live(first, first, image, backup)
        second = read_image(monitor, journal, 'before-mmio-second')
        validate_live(first, second, image, backup)
        journal.emit('unit_image_verified', sha256=sha(first), two_reads_equal=True)
        reader = Reader(monitor)
        journal.emit('controller_original', block_size=hex(reader.block), config=hex(reader.config))
        jedec = reader.read(0x9f)
        journal.emit('jedec_read', value=hex(jedec))
        if jedec != 0x1660c8:
            raise IOError('Unexpected JEDEC; no security read')
        before_status = reader.status()
        journal.emit('status_before', value=hex(before_status))
        if before_status & 3:
            raise IOError('WIP/WEL not clear; no security read')
        records = []
        for pass_number in (1, 2):
            record = bytearray()
            for address in range(0x1000, 0x1100, 4):
                record.extend(reader.read(0x48, address).to_bytes(4, 'little'))
            record = bytes(record)
            journal.save(f'security-1000-pass-{pass_number}.bin', record)
            records.append(record)
        after_status = reader.status()
        reader.restore()
        journal.emit('status_after', value=hex(after_status))
        if records[0] != records[1] or before_status != after_status:
            raise IOError('Security reads or flash status differ')
        journal.emit('security_read_verified', reads_equal=True, security_sha256=sha(records[0]),
                     first_96_all_ff=records[0][:96] == b'\xff' * 96,
                     all_256_ff=records[0] == b'\xff' * 256,
                     controller_restored=True, status_unchanged=True)
        for name in ('after-mmio', 'after-mmio-second'):
            if read_image(monitor, journal, name) != first:
                raise IOError('Main flash changed; no retry')
        journal.emit('complete', flash_unchanged=True, remains_in_rom=True,
                     license_record_blank=records[0][:96] == b'\xff' * 96)
    except BaseException as exc:
        journal.emit('stopped', error=f'{type(exc).__name__}: {exc}', automatic_retry=False)
        if reader is not None:
            try:
                reader.restore()
                journal.emit('controller_restored_after_failure')
            except Exception as restore_error:
                journal.emit('controller_restore_failed', error=str(restore_error))
        raise
    finally:
        journal.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--journal', type=Path)
    args = parser.parse_args()
    validate_local()
    print('SPI controller plan: 9f/05/35/48 reads only, no payload, original config restored.', flush=True)
    if args.execute:
        raise RuntimeError('Live MMIO reader disabled after JEDEC receive stalled ROM; '
                           'ROM memcpy uses byte MMIO; see '
                           'docs/knowledge/rom-flash-access.md#5-spi-controller-and-clock-facts')
        if args.journal is None or args.journal.resolve().parent != ROOT / 'firmware/live':
            parser.error('--execute needs a new firmware/live journal')
        run(args.journal)


if __name__ == '__main__':
    status = 0
    try:
        main()
    except Exception as exc:
        print(type(exc).__name__, exc, flush=True)
        status = 1
    finally:
        sys.stdout.flush()
        os._exit(status)
