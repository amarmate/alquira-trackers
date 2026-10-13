import struct
import unittest

from rda_flash import FLASH_SIZE, LIVE_ROOT, MAGIC
from rda_logicrom_image import (APP_START, APP_END, NVM_FORMAT_SIZE_AT, USB_UNPLUG_BRANCH_AT,
                                USB_TIMEOUT_PERIOD_AT, USB_TIMEOUT_PERIOD_10S,
                                USB_TIMEOUT_PERIOD_1HR,
                                extend_usb_timeout, fix_nvm_format_size, keep_usb_open, pack_app,
                                read_core, validate_trial)

# The published core is a local, gitignored artifact.
CORE_LOD = LIVE_ROOT / 'usb-programmer-build/logicrom/core_v0.5.1.lod'


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.backup = struct.pack('<I', MAGIC) + b'\x5a' * (FLASH_SIZE - 4)
        raw = struct.pack('<3I', 0x41505031, 0, 0) + bytes(116) + b'probe'
        self.app = pack_app(raw)
        self.image = (self.backup[:APP_START] + self.app
                      + b'\xff' * (APP_END - APP_START - len(self.app)) + self.backup[APP_END:])

    def test_packed_app_and_preserved_tail_validate(self):
        self.assertEqual(validate_trial(self.image, self.backup), 0x10000)
        self.assertEqual(len(self.image), FLASH_SIZE)

    def test_corrupt_app_header_crc_padding_and_data_tail_fail(self):
        for offset in (0, APP_START, APP_START + 4, APP_START + 8, APP_START + 128,
                       APP_START + 0x10000, APP_END, 0x3FA000, 0x3FE000):
            image = bytearray(self.image)
            image[offset] ^= 1
            with self.subTest(offset=hex(offset)), self.assertRaises(ValueError):
                validate_trial(bytes(image), self.backup)

    def test_pack_refuses_patched_missing_or_oversized_app(self):
        for raw in (b'', self.app, self.app[:8] + bytes(4) + self.app[12:],
                    struct.pack('<3I', 0x41505031, 0, 0) + bytes(APP_END - APP_START)):
            with self.assertRaises(ValueError):
                pack_app(raw)

    def test_core_with_the_unfixed_nvm_format_size_is_refused(self):
        image = bytearray(self.image)
        struct.pack_into('<I', image, NVM_FORMAT_SIZE_AT, 0x60000)
        with self.assertRaises(ValueError):
            validate_trial(bytes(image), self.backup)


class NvmFormatSizeTests(unittest.TestCase):
    def core(self, size):
        core = bytearray(b'\x5a' * APP_START)
        struct.pack_into('<I', core, NVM_FORMAT_SIZE_AT, size)
        return bytes(core)

    def test_format_size_becomes_the_mounted_size(self):
        before = self.core(0x60000)
        after = fix_nvm_format_size(before)
        self.assertEqual(struct.unpack_from('<I', after, NVM_FORMAT_SIZE_AT)[0], 0x6000)
        self.assertEqual(after[:NVM_FORMAT_SIZE_AT], before[:NVM_FORMAT_SIZE_AT])
        self.assertEqual(after[NVM_FORMAT_SIZE_AT + 4:], before[NVM_FORMAT_SIZE_AT + 4:])

    def test_refuses_a_core_without_the_reviewed_size(self):
        for size in (0x6000, 0, 0x60001):
            with self.subTest(size=hex(size)), self.assertRaises(ValueError):
                fix_nvm_format_size(self.core(size))

    @unittest.skipUnless(CORE_LOD.exists(), 'the core is a local, gitignored artifact')
    def test_published_core_changes_in_two_bytes_only(self):
        before = read_core(CORE_LOD)
        after = fix_nvm_format_size(before)
        self.assertEqual([i for i in range(APP_START) if before[i] != after[i]],
                         [NVM_FORMAT_SIZE_AT + 1, NVM_FORMAT_SIZE_AT + 2])
        # Both mount calls beside the format load the size as `li a1,0x6000`.
        for call in (0x232CD6, 0x232D18):
            self.assertEqual(before[call:call + 4], bytes.fromhex('0cf0006d'))


class KeepUsbOpenTests(unittest.TestCase):
    def core(self, branch):
        core = bytearray(b'\x5a' * APP_START)
        struct.pack_into('<H', core, USB_UNPLUG_BRANCH_AT, branch)
        return bytes(core)

    def test_only_the_branch_offset_changes(self):
        before = self.core(0x241A)
        after = keep_usb_open(before)
        self.assertEqual([i for i in range(APP_START) if before[i] != after[i]],
                         [USB_UNPLUG_BRANCH_AT])
        self.assertEqual(struct.unpack_from('<H', after, USB_UNPLUG_BRANCH_AT)[0], 0x2432)

    def test_refuses_a_core_without_the_reviewed_branch(self):
        for branch in (0x2432, 0x241B, 0x6500):
            with self.subTest(branch=hex(branch)), self.assertRaises(ValueError):
                keep_usb_open(self.core(branch))

    @unittest.skipUnless(CORE_LOD.exists(), 'the core is a local, gitignored artifact')
    def test_published_core_branch_lands_on_the_handlers_return(self):
        after = keep_usb_open(read_core(CORE_LOD))
        offset = struct.unpack_from('<H', after, USB_UNPLUG_BRANCH_AT)[0] & 0xFF
        target = USB_UNPLUG_BRANCH_AT + 2 + 2 * offset
        # lw a3,20(sp); lw s0,16(sp); jr a3; addiu sp,24
        self.assertEqual(after[target:target + 8], bytes.fromhex('0597049000ef0363'))


class UsbTimeoutTests(unittest.TestCase):
    def core(self, period):
        core = bytearray(b'\x5a' * APP_START)
        struct.pack_into('<I', core, USB_TIMEOUT_PERIOD_AT, period)
        return bytes(core)

    def test_only_the_period_word_changes(self):
        before = self.core(USB_TIMEOUT_PERIOD_10S)
        after = extend_usb_timeout(before)
        self.assertEqual([i for i in range(APP_START) if before[i] != after[i]],
                         [USB_TIMEOUT_PERIOD_AT + 1, USB_TIMEOUT_PERIOD_AT + 2,
                          USB_TIMEOUT_PERIOD_AT + 3])
        self.assertEqual(struct.unpack_from('<I', after, USB_TIMEOUT_PERIOD_AT)[0],
                         USB_TIMEOUT_PERIOD_1HR)

    def test_refuses_a_core_without_the_reviewed_period(self):
        for period in (USB_TIMEOUT_PERIOD_1HR, 0, 0x28001):
            with self.subTest(period=hex(period)), self.assertRaises(ValueError):
                extend_usb_timeout(self.core(period))

    @unittest.skipUnless(CORE_LOD.exists(), 'the core is a local, gitignored artifact')
    def test_published_core_period_and_arm_site(self):
        before = read_core(CORE_LOD)
        self.assertEqual(struct.unpack_from('<I', before, USB_TIMEOUT_PERIOD_AT)[0],
                         USB_TIMEOUT_PERIOD_10S)
        after = extend_usb_timeout(before)
        self.assertEqual(struct.unpack_from('<I', after, USB_TIMEOUT_PERIOD_AT)[0],
                         USB_TIMEOUT_PERIOD_1HR)
        # Arm loads the period: lw a0,0x880fce08 at 0x880fcd8c.
        self.assertEqual(before[0x0fcd8c:0x0fcd8e], bytes.fromhex('1fb4'))
        # Timeout body still calls hal_UsbClose; cancel sites unchanged.
        self.assertEqual(before[0x0fccec:0x0fccec + 6], bytes.fromhex('30180ece0065'))
        self.assertEqual(after[0x0fccec:0x0fccec + 6], bytes.fromhex('30180ece0065'))
