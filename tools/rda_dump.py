"""Dump the SPI flash of an RDA8955 tracker (ReachFar V24) over its USB debug port.

    python3 -m venv .venv && .venv/bin/pip install pyusb   # needs `brew install libusb`
    .venv/bin/python tools/rda_dump.py firmware/backup/out.bin

The tracker enumerates as "Coolsand" 1e04:0900, interface "RDA Usb" (class ff/66/66),
bulk OUT 0x01 / bulk IN 0x81. There is no macOS driver for it, so we talk to the bulk
endpoints directly with libusb. The read command is the one used by
https://github.com/hitechshell/rdatool (GPL-3.0+).

Read-only: this script never sends a write command.

Request: AD <len BE16> FF 03 <addr LE32> <rid> 04 00
         The trailing byte must be 00. The device ignores a request with an XOR checksum there.
Reply:   AD 04 02 FF <rid> <1024 bytes> <xor of everything after the length>
"""
import hashlib
import struct
import sys
import time

import usb.backend.libusb1
import usb.core

EP_OUT = 0x01
EP_IN = 0x81
BLOCK = 1024
FLASH_BASE = 0x88000000         # SPI flash, KSEG0 cached window (Logicrom RDA8955 linker script)
FLASH_SIZE = 4 * 1024 * 1024    # measured: reads at +4 MB mirror +0

# ctypes does not search Homebrew's prefix, so point pyusb at it explicitly.
LIBUSB = "/opt/homebrew/lib/libusb-1.0.dylib"


def xor(data):
    ck = 0
    for b in data:
        ck ^= b
    return ck


def open_device():
    backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
    dev = usb.core.find(idVendor=0x1E04, idProduct=0x0900, backend=backend)
    if dev is None:
        sys.exit("No Coolsand 1e04:0900 device on USB. Is the tracker on the cable and powered?")
    dev.set_configuration()
    return dev


def drain(dev):
    while True:
        try:
            dev.read(EP_IN, 4096, timeout=50)
        except usb.core.USBTimeoutError:
            return


def read_block(dev, addr, rid=3):
    payload = bytes([0xFF, 0x03]) + struct.pack("<I", addr) + bytes([rid, 0x04])
    dev.write(EP_OUT, b"\xAD" + struct.pack(">H", len(payload)) + payload + b"\x00", timeout=1000)

    reply = bytearray()
    deadline = time.time() + 2
    while len(reply) < BLOCK + 6 and time.time() < deadline:
        try:
            reply += bytes(dev.read(EP_IN, 4096, timeout=500))
        except usb.core.USBTimeoutError:
            pass

    if len(reply) != BLOCK + 6:
        raise IOError(f"0x{addr:08x}: expected {BLOCK + 6} bytes, got {len(reply)}")
    if reply[:5] != bytes([0xAD, 0x04, 0x02, 0xFF, rid]):
        raise IOError(f"0x{addr:08x}: bad header {reply[:8].hex(' ')}")
    if xor(reply[3:-1]) != reply[-1]:
        raise IOError(f"0x{addr:08x}: checksum mismatch")
    return bytes(reply[5:5 + BLOCK])


def read_flash(dev, label):
    out = bytearray()
    t0 = time.time()
    for addr in range(FLASH_BASE, FLASH_BASE + FLASH_SIZE, BLOCK):
        for attempt in range(5):
            try:
                out += read_block(dev, addr)
                break
            except IOError as e:
                print(f"  retry {attempt + 1}: {e}", flush=True)
                drain(dev)
        else:
            sys.exit(f"giving up at 0x{addr:08x}")
        if len(out) % (512 * 1024) == 0:
            print(f"{label}: {len(out) // 1024} KB  {time.time() - t0:.0f}s", flush=True)
    return bytes(out)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    dev = open_device()
    drain(dev)
    # Two passes: the firmware keeps running while we read, so only keep an image
    # that came back identical twice.
    first = read_flash(dev, "pass 1")
    second = read_flash(dev, "pass 2")
    if first != second:
        n = sum(1 for a, b in zip(first, second) if a != b)
        sys.exit(f"passes differ in {n} bytes; not saving, run again")
    with open(sys.argv[1], "wb") as fh:
        fh.write(first)
    print(f"saved {sys.argv[1]}  sha256 {hashlib.sha256(first).hexdigest()}")


if __name__ == "__main__":
    main()
