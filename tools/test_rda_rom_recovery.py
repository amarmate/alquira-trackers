import unittest

from rda_rom_recovery import boot_packet, DEBUG_RESET, MONITOR_START, expect_start


class Endpoint:
    def __init__(self, chunks):
        self.chunks = iter(chunks)

    def read(self, *args, **kwargs):
        return next(self.chunks)


class RecoveryProtocolTests(unittest.TestCase):
    def test_exact_debug_reset_command(self):
        self.assertEqual(DEBUG_RESET.hex(), 'ad0007ff8400000000017a')
        self.assertEqual(MONITOR_START.hex(), 'ad0007ff8405000000fd83')

    def test_boot_write_cannot_set_status_or_test_mode(self):
        for value in [1, 0x80000000, 0x10000000, -1]:
            with self.assertRaises(ValueError):
                boot_packet(value)
        self.assertEqual(boot_packet(0x00220000).hex(), 'ad000aff82a000a0a100002200fe')

    def test_fragmented_rom_ack(self):
        event = bytes.fromhex('ad0006ff00010000ff01')
        self.assertEqual(expect_start(Endpoint([event[:2], event[2:7], event[7:]])), event)

    def test_corrupt_ack_rejected(self):
        with self.assertRaises(IOError):
            expect_start(Endpoint([bytes.fromhex('ad0006ff00010000ff00')]))

    def test_invalid_length_rejected(self):
        with self.assertRaises(IOError):
            expect_start(Endpoint([bytes.fromhex('adffff')]))


if __name__ == '__main__':
    unittest.main()
