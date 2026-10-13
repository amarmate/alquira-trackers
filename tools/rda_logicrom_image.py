"""Prepare a unit-bound Logicrom trial image offline; never opens USB."""
import argparse
import json
from pathlib import Path
import re
import struct
import zlib

from rda_flash import FLASH_SIZE, MAGIC, PROTECTED, sha

CORE_SHA = '0499c0e051f166e899daf13503c8d2b07ba65c884de047f17bb8f8cd38d31df7'
APP_START, APP_END = 0x250000, 0x2E0000
# Core 0.5.1 mounts its /nvm block device with (0x3f0000, 0x6000) but, when that mount
# fails on a first boot, formats it with (0x3f0000, 0x60000). The format zeroes the
# 32-byte head of 96 erase blocks instead of 6, which on 412 reached every 4 KiB sector
# up to the end of flash, calibration and factory included. This word is the size the
# format call at 0x88232cf0 loads; nothing else reads it.
NVM_FORMAT_SIZE_AT, NVM_FORMAT_SIZE_BAD, NVM_FORMAT_SIZE = 0x232D88, 0x60000, 0x6000


def fix_nvm_format_size(core):
    if struct.unpack_from('<I', core, NVM_FORMAT_SIZE_AT)[0] != NVM_FORMAT_SIZE_BAD:
        raise ValueError('Core does not hold the reviewed /nvm format size')
    fixed = bytearray(core)
    struct.pack_into('<I', fixed, NVM_FORMAT_SIZE_AT, NVM_FORMAT_SIZE)
    return bytes(fixed)


# The core opens its USB port when the modem layer reports "charger connected" and
# closes it on "charger disconnected" (handler at 0x8823c9c8, fed by EV_PM_BC_IND).
# The 9.9 s USB loss was not proven to be this report, and ignoring this branch
# did not prevent it. Offline tracing also found a separate 10 s enumeration
# timeout that calls hal_UsbClose directly. This is `beqz a0` to the closing path;
# pointed at the function's return instead, the disconnected report is ignored.
# Retained for historical image reconstruction, not the next diagnostic image.
USB_UNPLUG_BRANCH_AT, USB_UNPLUG_BRANCH, USB_UNPLUG_IGNORED = 0x23C9D0, 0x241A, 0x2432


def keep_usb_open(core):
    """Legacy failed experiment; see extend_usb_timeout() for the reviewed path."""
    if struct.unpack_from('<H', core, USB_UNPLUG_BRANCH_AT)[0] != USB_UNPLUG_BRANCH:
        raise ValueError('Core does not hold the reviewed charger-disconnected branch')
    changed = bytearray(core)
    struct.pack_into('<H', changed, USB_UNPLUG_BRANCH_AT, USB_UNPLUG_IGNORED)
    return bytes(changed)


# Mode 0 of FUN_880fcd6c arms FUN_8200cd54(0x28000, 0x880fcce9, ...) — 163,840 HAL
# ticks at 16,384 Hz = 10 s — whose timeout body calls hal_UsbClose directly.
# The descriptor callback cancels only on its second event (state 3->4); every 412
# run loses USB at ~9.9 s. Reviewed in docs/knowledge/logicrom-core.md#4-usb:
# extending the period literal tests timing causality with no code-flow change.
# 0x03840000 = 58,982,400 ticks = 3,600 s. The literal is private to this arm.
USB_TIMEOUT_PERIOD_AT, USB_TIMEOUT_PERIOD_10S, USB_TIMEOUT_PERIOD_1HR = \
    0x0FCE08, 0x00028000, 0x03840000


def extend_usb_timeout(core):
    if struct.unpack_from('<I', core, USB_TIMEOUT_PERIOD_AT)[0] != USB_TIMEOUT_PERIOD_10S:
        raise ValueError('Core does not hold the reviewed 10 s USB timeout period')
    changed = bytearray(core)
    struct.pack_into('<I', changed, USB_TIMEOUT_PERIOD_AT, USB_TIMEOUT_PERIOD_1HR)
    return bytes(changed)


def read_core(path):
    raw = path.read_bytes()
    if sha(raw) != CORE_SHA:
        raise ValueError('Not the reviewed Logicrom RDA8955 v0.5.1 core')
    image = bytearray(b'\xff' * APP_START)
    seen = bytearray(APP_START // 4)
    address, checksum, expected = None, 0, None
    for line in raw.decode('ascii').splitlines():
        if line.startswith('#$'):
            continue
        if line.startswith('#checksum='):
            if expected is not None:
                raise ValueError('Duplicate LOD checksum')
            expected = int(line.split('=')[1], 16)
        elif re.fullmatch(r'@[0-9a-fA-F]{8}', line):
            address = int(line[1:], 16) - 0x08000000
        elif re.fullmatch(r'[0-9a-fA-F]{8}', line):
            if (expected is not None or address is None or address % 4
                    or not 0 <= address <= APP_START - 4 or seen[address // 4]):
                raise ValueError('Invalid, overlapping or out-of-core LOD record')
            value = int(line, 16)
            struct.pack_into('<I', image, address, value)
            seen[address // 4] = 1
            checksum = (checksum + value) & 0xFFFFFFFF
            address += 4
        elif line.strip():
            raise ValueError('Unexpected LOD syntax')
    if expected != checksum or not all(seen) or image[:4] != b'\xff' * 4:
        raise ValueError('Core checksum, coverage or boot placeholder mismatch')
    # The LOD deliberately leaves the boot word for the programmer's END command.
    # The host writer requires a bootable target but withholds this word in trial mode.
    struct.pack_into('<I', image, 0, MAGIC)
    return bytes(image)


def pack_app(raw):
    if len(raw) < 128 or raw[:12] != struct.pack('<3I', 0x41505031, 0, 0):
        raise ValueError('Expected unpatched APP1 application header')
    size = (len(raw) + 0xFFFF) & ~0xFFFF
    if size > APP_END - APP_START:
        raise ValueError('Application exceeds SDK flash partition')
    data = bytearray(raw + b'\xff' * (size - len(raw)))
    struct.pack_into('<I', data, 4, size)
    struct.pack_into('<I', data, 8, zlib.crc32(data))
    return bytes(data)


def validate_trial(image, backup):
    if (len(image) != FLASH_SIZE or len(backup) != FLASH_SIZE
            or image[:4] != struct.pack('<I', MAGIC)):
        raise ValueError('Trial needs a full 4 MiB image with expected boot magic')
    if image[APP_END:] != backup[APP_END:]:
        raise ValueError('Trial would replace data outside core/application partitions')
    if struct.unpack_from('<I', image, NVM_FORMAT_SIZE_AT)[0] == NVM_FORMAT_SIZE_BAD:
        raise ValueError('Core still has the /nvm format size that overwrote the tail on 412')
    app = image[APP_START:APP_END]
    magic, size, crc = struct.unpack_from('<3I', app)
    if magic != 0x41505031 or not 0x10000 <= size <= len(app) or size % 0x10000:
        raise ValueError('Invalid APP1 header or length')
    check = app[:8] + bytes(4) + app[12:size]
    if zlib.crc32(check) != crc or app[size:] != b'\xff' * (len(app) - size):
        raise ValueError('Application CRC or unused partition mismatch')
    return size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core', required=True, type=Path)
    parser.add_argument('--app-raw', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--keep-usb-open', action='store_true',
                        help='experiment: ignore the charger-disconnected report that '
                             "closes the core's USB port")
    parser.add_argument('--usb-timeout-1hr', action='store_true',
                        help='diagnostic: extend the 10 s USB enumeration timeout '
                             'period to 3,600 s (one literal, no code-flow change)')
    args = parser.parse_args()
    if args.keep_usb_open and args.usb_timeout_1hr:
        raise ValueError('Only one USB experiment per image; see the one-change rule')
    # This preparation is deliberately restricted to the backed-up spare 412.
    from rda_programmer_start import SPARE_412, SPARE_412_SHA
    backup = SPARE_412.read_bytes()
    if sha(backup) != SPARE_412_SHA:
        raise ValueError('Spare 412 backup hash mismatch')
    core = fix_nvm_format_size(read_core(args.core))
    if args.keep_usb_open:
        core = keep_usb_open(core)
    if args.usb_timeout_1hr:
        core = extend_usb_timeout(core)
    app = pack_app(args.app_raw.read_bytes())
    target = core + app + b'\xff' * (APP_END - APP_START - len(app)) + backup[APP_END:]
    validate_trial(target, backup)
    report = dict(unit='1403167412', core_version='0.5.1', core_lod_sha256=CORE_SHA,
                  core_change=f'/nvm format size at {NVM_FORMAT_SIZE_AT:#x}: '
                              f'{NVM_FORMAT_SIZE_BAD:#x} -> {NVM_FORMAT_SIZE:#x}',
                  core_experiment=f'charger-disconnected branch at {USB_UNPLUG_BRANCH_AT:#x}: '
                                  f'{USB_UNPLUG_BRANCH:#x} -> {USB_UNPLUG_IGNORED:#x}'
                                  if args.keep_usb_open else None,
                  usb_timeout_experiment=f'USB timeout period at {USB_TIMEOUT_PERIOD_AT:#x}: '
                                          f'{USB_TIMEOUT_PERIOD_10S:#x} -> '
                                          f'{USB_TIMEOUT_PERIOD_1HR:#x}'
                                          if args.usb_timeout_1hr else None,
                  app_raw_sha256=sha(args.app_raw.read_bytes()), app_bytes=len(app),
                  backup_sha256=SPARE_412_SHA, image_sha256=sha(target),
                  protected_sha256=sha(target[PROTECTED:]),
                  replaced_range=[hex(0), hex(APP_END)],
                  preserved_range=[hex(APP_END), hex(FLASH_SIZE)],
                  hardware_tested=False, boot_word='withheld by trial installer')
    with args.output.open('xb') as out:
        out.write(target)
    with args.output.with_suffix('.json').open('x') as out:
        json.dump(report, out, indent=2)
        out.write('\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
