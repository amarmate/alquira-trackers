"""Memory-only recovery verification after the SPI read stall; no helper/start.

Requires known 412 ROM and two complete flash reads equal the pre-MMIO snapshot.
Checks the volatile controller config returned to its saved reset state.
"""
import os
import struct
import sys

from rda_dump import LIBUSB
from rda_flash import ROM_SHA, ROM_START, sha
from rda_programmer_start import ROOT, StartJournal, StartMonitor
from rda_logicrom_license_capture import validate_local, validate_live
from rda_security_read import read_image


def main():
    import usb.backend.libusb1
    import usb.core
    from rda_rom_recovery import device_named
    image, backup = validate_local()
    before = (ROOT / 'firmware/live/2026-10-10-logicrom-412-security-mmio-1/before-mmio.bin').read_bytes()
    if sha(before) != 'b1dc8ccc2bb6ea1a26ee5bb353f7fff0627b65af34131a50a5d72b71be71b47d':
        raise ValueError('Pre-MMIO snapshot mismatch')
    validate_live(before, before, image, backup)
    journal = StartJournal(sys.argv[1])
    try:
        journal.emit('scope', operations='ROM handshake and memory reads only; recovery '
                     'check after SPI stall', reset=False, load=False, execute=False,
                     flash_write=False, mmio_write=False, exit=False)
        backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
        device = device_named(backend, 'Coolsand Usb')
        monitor = StartMonitor(device, journal, usb.core.USBTimeoutError, [])
        monitor.internal(0xfd)
        if monitor.receive(0, 4) != struct.pack('<I', ROM_START):
            raise IOError('ROM handshake mismatch')
        rom = monitor.read(0xa1e00000, 0x6000)
        journal.save('rom.bin', rom)
        if sha(rom) != ROM_SHA:
            raise IOError('ROM hash mismatch')
        controller = monitor.read(0xa7fff000, 0x38)
        journal.save('controller.bin', controller)
        words = struct.unpack('<14I', controller)
        journal.emit('controller_after_rst', words=[hex(w) for w in words],
                     block_size_matches=words[1] == 0x100,
                     config_matches=words[5] == 0x8a0, busy_clear=not words[3] & 1)
        if words[1] != 0x100 or words[5] != 0x8a0 or words[3] & 1:
            raise IOError('Controller reset state differs')
        for name in ('recovered-flash', 'recovered-flash-second'):
            after = read_image(monitor, journal, name)
            validate_live(after, after, image, backup)
            if after != before:
                raise IOError('Main flash differs from pre-MMIO snapshot')
        journal.emit('complete', flash_unchanged=True, two_reads_equal=True,
                     rom_verified=True, controller_reset_state_restored=True,
                     core_app_and_tail_intact=True, boot_word='0xffffffff',
                     remains_in_rom=True, license_state='unmeasured')
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
