import unittest
from unittest import mock

from rda_rom_recovery import boot_packet, compare, DEBUG_RESET, MONITOR_START, expect_start, observe


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

    def test_compare_names_the_changed_sectors_and_checks_the_protected_tail(self):
        backup = bytes(0x400000)
        same = compare(backup, backup)
        self.assertEqual((same['differing_bytes'], same['differing_4k_sectors']), (0, []))
        self.assertTrue(same['protected_tail_matches'])
        live = bytearray(backup)
        live[0x362004] = 1      # a settings byte
        live[0x3fa000] = 1      # first byte of the calibration sector
        changed = compare(bytes(live), backup)
        self.assertEqual(changed['differing_bytes'], 2)
        self.assertEqual(changed['differing_4k_sectors'], ['0x362000', '0x3fa000'])
        self.assertFalse(changed['protected_tail_matches'])

    def test_observe_logs_each_change_and_stops_on_the_named_interface(self):
        dark = dict(usb_device_count=0, trackers=[])
        rom = dict(usb_device_count=1, trackers=[dict(interfaces=[dict(name='Coolsand Usb')])])
        events = []
        clock = iter(range(100))
        with mock.patch('rda_rom_recovery.snapshot', side_effect=[dark, dark, rom]), \
                mock.patch('rda_rom_recovery.time.sleep'), \
                mock.patch('rda_rom_recovery.time.monotonic', side_effect=lambda: next(clock)):
            found = observe(None, lambda **e: events.append(e), 50, 0, stop_on='Coolsand Usb')
        self.assertTrue(found)
        self.assertEqual([e['usb_device_count'] for e in events], [0, 1])

    def test_observe_without_a_stop_name_runs_the_whole_window(self):
        vendor = dict(usb_device_count=1, trackers=[dict(interfaces=[dict(name='RDA Usb')])])
        events = []
        clock = iter(range(100))
        with mock.patch('rda_rom_recovery.snapshot', return_value=vendor), \
                mock.patch('rda_rom_recovery.time.sleep'), \
                mock.patch('rda_rom_recovery.time.monotonic', side_effect=lambda: next(clock)):
            self.assertFalse(observe(None, lambda **e: events.append(e), 5, 0))
        self.assertEqual(len(events), 1)


if __name__ == '__main__':
    unittest.main()
