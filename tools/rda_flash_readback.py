"""Read flash twice through vendor RDA Usb and compare a saved baseline.

No reset, USB reconfiguration, RAM load, MMIO write or flash command. No retry.
Default validates the baseline offline; --read enables only memory-read requests.
"""
import argparse
import os
from pathlib import Path
import sys

from rda_flash import FLASH_SIZE, PROTECTED, LIVE_ROOT, sha
from rda_programmer_start import StartJournal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--read', action='store_true')
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--baseline-sha256', required=True)
    parser.add_argument('--journal', type=Path)
    args = parser.parse_args()
    baseline = args.baseline.read_bytes()
    if len(baseline) != FLASH_SIZE or sha(baseline) != args.baseline_sha256:
        raise ValueError('Baseline size/hash mismatch')
    print('Validated baseline. Read-only vendor flash comparison; no reset/load/write/retry.', flush=True)
    if not args.read:
        return
    if args.journal is None or not args.journal.resolve().is_relative_to(LIVE_ROOT.resolve()):
        parser.error('--read requires a new --journal under firmware/live')
    import usb.backend.libusb1
    import usb.core
    import usb.util
    from rda_dump import LIBUSB, read_block
    from rda_rom_recovery import device_named, compare, RESET_CAUSE
    from rda_recovery_snapshot import read_word
    journal = StartJournal(args.journal)
    device = None
    try:
        journal.emit('scope', baseline=str(args.baseline), baseline_sha256=sha(baseline),
                     operations='Vendor memory reads only; two full flash passes')
        backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
        device = device_named(backend, 'RDA Usb')
        try:
            stale = device.read(0x81, 4096, timeout=100)
        except usb.core.USBTimeoutError:
            stale = b''
        if stale:
            raise IOError('Queued vendor data; refusing requests')
        journal.emit('reset_cause', value=hex(read_word(device, RESET_CAUSE)))
        images = []
        for pass_number in (1, 2):
            data = bytearray()
            for offset in range(0, FLASH_SIZE, 1024):
                data.extend(read_block(device, 0x88000000 + offset))
                if len(data) % 0x40000 == 0:
                    journal.emit('read_progress', pass_number=pass_number, bytes_read=len(data))
            data = bytes(data)
            journal.save(f'flash-pass-{pass_number}.bin', data)
            journal.emit('baseline_comparison', pass_number=pass_number,
                         code_matches=data[:0x362000] == baseline[:0x362000],
                         **compare(data, baseline))
            images.append(data)
        if images[0] != images[1]:
            raise IOError('Two live reads differ; evidence saved, no retry')
        if images[0][:0x362000] != baseline[:0x362000] or images[0][PROTECTED:] != baseline[PROTECTED:]:
            raise IOError('Code or calibration/factory tail differs from baseline')
        journal.emit('verified', sha256=sha(images[0]), two_reads_identical=True,
                     full_baseline_match=images[0] == baseline,
                     code_and_protected_tail_match=True)
    except BaseException as exc:
        journal.emit('stopped', error=f'{type(exc).__name__}: {exc}', automatic_retry=False)
        raise
    finally:
        if device is not None:
            usb.util.dispose_resources(device)
        journal.close()


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
        os._exit(status)
