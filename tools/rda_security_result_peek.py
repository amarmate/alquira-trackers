"""Recover evidence after one attempted returning security-helper execution.

No handshake, reset, load, execute, exit or MMIO write. Memory reads only, in the
same ROM connection. Retain a delayed return event if present. Never infer success
from absent data, sentinel bytes, or incomplete helper state.
"""
import os
import struct
import sys
import time

from rda_dump import LIBUSB
from rda_flash import frame, sha, ROM_SHA, ROM_EXECUTING, ROM_START
from rda_programmer_start import StartJournal, StartMonitor
from rda_security_read import RESULT, RESULT_SIZE, ROM_RETURNED, parse_result


class PeekMonitor(StartMonitor):
    def receive(self, rid, size, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            while len(self.pending) >= 3:
                length = int.from_bytes(self.pending[1:3], 'big')
                if self.pending[0] != 0xad or not 2 <= length <= 1030:
                    raise IOError('Bad packet header')
                total = length + 4
                if len(self.pending) < total:
                    break
                packet = bytes(self.pending[:total])
                del self.pending[:total]
                if frame(packet[3:-1]) != packet or packet[3] != 0xff:
                    raise IOError('Bad packet checksum/flow')
                if packet[4] == 0:
                    if total != 10:
                        raise IOError('Bad event size')
                    value = int.from_bytes(packet[5:9], 'little')
                    self.journal.emit('delayed_event', value=hex(value))
                    if value not in (ROM_RETURNED, ROM_EXECUTING, ROM_START):
                        raise IOError('Unexpected event')
                    continue
                if packet[4] != rid or total != size + 6:
                    raise IOError('Unexpected memory response')
                return packet[5:-1]
            try:
                self.pending.extend(self.device.read(0x81, 4096, timeout=200))
            except self.timeout_error:
                pass
        raise TimeoutError('Read-only peek deadline; no retry')


def main():
    import usb.backend.libusb1
    import usb.core
    from rda_rom_recovery import device_named
    journal = StartJournal(sys.argv[1])
    try:
        journal.emit('scope', operations='Memory reads only after helper return-event timeout',
                     handshake=False, reset=False, load=False, execute=False, exit=False)
        backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
        dev = device_named(backend, 'Coolsand Usb')
        monitor = PeekMonitor(dev, journal, usb.core.USBTimeoutError, [])
        for name, address, size in (('context', 0xa1c000a0, 24),
                                    ('result', RESULT, RESULT_SIZE),
                                    ('spi-controller', 0xa7fff000, 0x38),
                                    ('helper-stack', 0xa1c03e00, 512),
                                    ('rom', 0xa1e00000, 0x6000)):
            first = monitor.read(address, size)
            journal.save(name + '.bin', first)
            if monitor.read(address, size) != first:
                raise IOError(f'{name} changed across reads')
            journal.emit('stable_read', name=name, sha256=sha(first),
                         hex=first.hex() if size < 100 else None)
        try:
            fields, _ = parse_result((journal.path / 'result.bin').read_bytes())
            journal.emit('helper_result', **fields)
        except ValueError as exc:
            journal.emit('incomplete_result', error=str(exc))
        if sha((journal.path / 'rom.bin').read_bytes()) != ROM_SHA:
            raise IOError('ROM hash mismatch')
        journal.emit('complete', remains_responding_to_memory_reads=True)
    except BaseException as exc:
        journal.emit('stopped', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        journal.close()


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
