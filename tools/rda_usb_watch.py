"""Observe tracker USB enumeration and standard descriptors; never send tracker commands.

Run outside the sandbox if USB enumeration returns zero devices. This tool does
not reset, configure, claim interfaces, or access bulk endpoints. Interface names
distinguish the vendor's RDA Usb from the SDK ROM's Coolsand Usb; VID/PID alone
cannot identify a unit or prove ROM protocol compatibility.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

import usb.backend.libusb1
import usb.core
import usb.util

from rda_dump import LIBUSB


def snapshot(backend):
    devices = list(usb.core.find(find_all=True, backend=backend))
    trackers = []
    for dev in devices:
        if (dev.idVendor, dev.idProduct) not in [(0x1E04, 0x0900), (0x1782, 0x3D00)]:
            continue
        item = dict(vid=f'{dev.idVendor:04x}', pid=f'{dev.idProduct:04x}',
                    bus=dev.bus, address=dev.address, interfaces=[])
        try:
            for config in dev:
                for interface in config:
                    item['interfaces'].append(dict(
                        configuration=config.bConfigurationValue,
                        number=interface.bInterfaceNumber,
                        alternate=interface.bAlternateSetting,
                        name=usb.util.get_string(dev, interface.iInterface)
                        if interface.iInterface else None,
                        endpoints=[f'{ep.bEndpointAddress:02x}' for ep in interface]))
        except (usb.core.USBError, ValueError) as exc:
            # A device disappearing during enumeration may lose its string
            # descriptor language table before get_string() completes.
            item['descriptor_error'] = str(exc)
        finally:
            usb.util.dispose_resources(dev)
        trackers.append(item)
    return dict(usb_device_count=len(devices), trackers=trackers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=10, choices=range(1, 61),
                        metavar='1..60')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    live = Path(__file__).resolve().parents[1] / 'firmware' / 'live'
    target = args.output.resolve()
    if not target.is_relative_to(live):
        parser.error('--output must be inside firmware/live/')
    backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
    if backend is None:
        raise RuntimeError('libusb backend unavailable')
    with target.open('x') as log:
        start = time.monotonic()
        previous = None
        def emit(record):
            line = json.dumps(record, sort_keys=True)
            print(line, flush=True)
            log.write(line + '\n')
            log.flush()
        emit(dict(event='start', seconds=args.seconds,
                  operations='USB enumeration and standard descriptor reads only'))
        while True:
            current = snapshot(backend)
            if current != previous:
                emit(dict(event='state', elapsed=round(time.monotonic() - start, 3),
                          **current))
                if current['usb_device_count'] == 0:
                    emit(dict(event='notice', message='Zero USB devices is ambiguous: '
                              'check sandbox visibility before declaring a disconnect.'))
                previous = current
            remaining = args.seconds - (time.monotonic() - start)
            if remaining <= 0:
                break
            time.sleep(min(0.25, remaining))
        emit(dict(event='complete', elapsed=round(time.monotonic() - start, 3)))


if __name__ == '__main__':
    status = 0
    try:
        main()
    except SystemExit as exc:
        status = exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        status = 1
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        # libusb teardown can hang on this Mac; files are already closed.
        os._exit(status)
