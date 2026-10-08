"""Stream the ReachFar V24 debug log over USB.

    .venv/bin/python tools/rda_log.py | grep -iE 'apn|active_gprs|gethost|dns|ip_url'

In normal operation the tracker enumerates as 1782:3d00 "Coolsand" with two vendor bulk
interfaces. Interface 1's IN endpoint 0x82 is a plain-text log the firmware writes all the
time (network, APN, sockets, GPS). We only read from it.

Not the same mode as tools/rda_dump.py, which needs the 1e04:0900 debug-host enumeration.
"""
import argparse
import sys
import time

import usb.backend.libusb1
import usb.core
import usb.util

LIBUSB = "/opt/homebrew/lib/libusb-1.0.dylib"
EP_LOG = 0x82


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=float, default=0, help='Stop after this many seconds (0: forever)')
    parser.add_argument('--output', help='Also save the unmodified USB bytes locally')
    args = parser.parse_args()
    backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
    dev = usb.core.find(idVendor=0x1782, idProduct=0x3D00, backend=backend)
    if dev is None:
        sys.exit("No 1782:3d00 tracker on USB. Is it on the cable and powered on?")
    # Do not resend SET_CONFIGURATION to an already-running tracker.
    dev.get_active_configuration()
    deadline = time.monotonic() + args.seconds if args.seconds else float('inf')
    raw = open(args.output, 'xb') if args.output else None
    try:
        while time.monotonic() < deadline:
            try:
                chunk = bytes(dev.read(EP_LOG, 4096, timeout=500))
            except usb.core.USBTimeoutError:
                continue
            if raw:
                raw.write(chunk)
                raw.flush()
            # The log mixes text with binary padding (0xff, NUL); keep it greppable.
            sys.stdout.write(chunk.decode("ascii", "replace").replace("�", ".").replace("\x00", ""))
            sys.stdout.flush()
    finally:
        if raw:
            raw.close()
        usb.util.dispose_resources(dev)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
