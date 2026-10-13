"""One guarded start of 412's installed diagnostic image and one `secr` capture.

Default validates local inputs only. --execute requires 412 in ROM already.
ROM operations: handshake, memory reads, and one exit after two equal full reads.
No reset, RAM load, firmware replacement, or flash mailbox command is allowed.
The ordinary core startup may write its own runtime storage.
"""
import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

from rda_flash import FLASH_SIZE, PROTECTED, ROM_SHA, ROM_START, sha
from rda_programmer_start import (ROOT, SPARE_412, SPARE_412_SHA, StartJournal,
                                  StartMonitor, ROM_EXIT, read_flash)

IMAGE = ROOT / 'firmware/live/2026-10-10-logicrom-offline/v24-412-diag-entry-v2.bin'
IMAGE_SHA = '90ae7ffa47824eee169fcc9ea9a06268a8184ad4fdf7f5d49256efd7b861c079'


def validate_local():
    image, backup = IMAGE.read_bytes(), SPARE_412.read_bytes()
    if len(image) != FLASH_SIZE or sha(image) != IMAGE_SHA:
        raise ValueError('Pinned diagnostic image mismatch')
    if len(backup) != FLASH_SIZE or sha(backup) != SPARE_412_SHA:
        raise ValueError('412 backup mismatch')
    if image[PROTECTED:] != backup[PROTECTED:]:
        raise ValueError('Diagnostic image does not retain 412 tail')
    return image, backup


def validate_live(first, second, image, backup):
    if len(first) != FLASH_SIZE or first != second:
        raise ValueError('Two full ROM reads must be equal')
    if first[:4] != b'\xff' * 4:
        raise ValueError('Installed image must retain the blank boot word')
    if first[4:0x2e0000] != image[4:0x2e0000]:
        raise ValueError('Installed core/application differs from pinned diagnostic v2')
    if first[PROTECTED:] != backup[PROTECTED:]:
        raise ValueError('Unit calibration/factory identity mismatch')


def run(journal_path, image, backup):
    import usb.backend.libusb1
    import usb.core
    from rda_dump import LIBUSB
    from rda_rom_recovery import device_named

    journal = StartJournal(journal_path)
    child, console_output = None, None
    try:
        journal.emit('scope', unit='1403167412', firmware_writes=False,
                     security_writes=False, resets=False, ram_load=False,
                     core_image_sha256=IMAGE_SHA, backup_sha256=SPARE_412_SHA,
                     operations='ROM handshake, memory reads, one exit; CDC secr CR once',
                     ordinary_core_startup_may_write_runtime_storage=True)
        backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
        device = device_named(backend, 'Coolsand Usb')
        monitor = StartMonitor(device, journal, usb.core.USBTimeoutError, [])
        monitor.internal(0xFD)
        if monitor.receive(0, 4) != struct.pack('<I', ROM_START):
            raise IOError('ROM handshake mismatch')
        if sha(monitor.read(0xA1E00000, 0x6000)) != ROM_SHA:
            raise IOError('ROM hash mismatch')
        journal.emit('rom_verified', reset_cause=hex(struct.unpack(
            '<I', monitor.read(0xA1A000A0, 4))[0]))
        first = read_flash(monitor, journal, 'before-start')
        # Fail identity/code checks promptly, before spending a second read.
        validate_live(first, first, image, backup)
        second = read_flash(monitor, journal, 'before-start-second')
        validate_live(first, second, image, backup)
        journal.emit('installed_image_verified', two_reads_equal=True,
                     boot_word='0xffffffff', sha256=sha(first), core_app_match=True,
                     protected_tail_match=True)
        capture = journal.path / 'console.jsonl'
        console_output = (journal.path / 'console.log').open('x')
        command = [sys.executable, str(ROOT / 'tools/logicrom_console.py'),
                   '--output', str(capture), '--seconds', '120', '--send', 'secr',
                   '--send-after', '1', '--ending', 'cr', '--baud', '115200',
                   '--dtr', 'on', '--rts', 'on']
        journal.emit('console_capture_intent', command=command)
        child = subprocess.Popen(command, stdout=console_output,
                                 stderr=subprocess.STDOUT, cwd=ROOT)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise IOError('Console capture stopped before image start')
            if capture.exists() and capture.stat().st_size:
                initial = json.loads(capture.read_text().splitlines()[0])
                if initial.get('event') != 'start' or initial.get('ports'):
                    raise IOError('Capture not ready or existing serial node present')
                break
            time.sleep(0.05)
        else:
            raise TimeoutError('Console capture did not become ready; no start')
        journal.emit('console_capture_ready', pid=child.pid, output=str(capture))
        journal.emit('trial_exit_intent', expected_sha256=sha(first),
                     recovery_journal='firmware/live/2026-10-10-logicrom-412-diag-1')
        monitor.exit_armed = True
        monitor.send(ROM_EXIT)
        journal.emit('trial_exit_sent', firmware_boot_verified=False)
        result = child.wait(timeout=130)
        journal.emit('console_capture_finished', exit_code=result)
        if result != 0:
            raise IOError(f'Console capture exit {result}; no repeat')
    except BaseException as exc:
        journal.emit('stopped', error=f'{type(exc).__name__}: {exc}', automatic_retry=False)
        raise
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
        if console_output is not None:
            console_output.close()
        journal.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--journal', type=Path)
    args = parser.parse_args()
    image, backup = validate_local()
    print('Pinned image and 412 backup validated. One existing-image start, secr CR once.',
          flush=True)
    if args.execute:
        if (args.journal is None or args.journal.resolve().parent != ROOT / 'firmware/live'):
            parser.error('--execute requires a new journal directly under firmware/live')
        run(args.journal, image, backup)


if __name__ == '__main__':
    status = 0
    try:
        main()
    except KeyboardInterrupt:
        status = 130
    except Exception as exc:
        print(f'Stopped: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        status = 1
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(status)  # libusb teardown can hang on this Mac
