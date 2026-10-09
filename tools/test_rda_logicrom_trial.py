import contextlib
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

import rda_flash as f
import rda_programmer_start as s
from rda_logicrom_image import APP_START, APP_END, pack_app
import test_rda_programmer_start as fixture
from test_rda_programmer_start import RunningProgrammer


class TrialTests(unittest.TestCase):
    BOOTABLE = fixture.QueryTests.BOOTABLE
    SEGMENTS = fixture.QueryTests.SEGMENTS
    run_on = fixture.QueryTests.run_on
    bootable = fixture.QueryTests.bootable

    def image(self):
        raw = struct.pack('<3I', 0x41505031, 0, 0) + bytes(116) + b'probe'
        app = pack_app(raw)
        core = bytearray(self.BOOTABLE[:APP_START])
        core[0x10004] ^= 1
        return (bytes(core) + app + b'\xff' * (APP_END - APP_START - len(app))
                + self.BOOTABLE[APP_END:])

    def install(self, device, root, stop=True):
        root = Path(root)
        image = self.image()
        source = root / 'trial.bin'
        source.write_bytes(image)
        self.run_on(device, root / 'install', trial=source,
                    trial_sha256=f.sha(image), trial_stop=stop)
        return root / 'install'

    def test_trial_stop_and_full_recovery_with_real_journals_and_live_settings(self):
        device = self.bootable()
        device.flash[0x382000] ^= 1  # legitimate vendor settings newer than backup
        before = bytes(device.flash)
        with tempfile.TemporaryDirectory() as root:
            stopped = self.install(device, root)
            expected = b'\xff' * 4 + self.image()[4:APP_END] + before[APP_END:]
            self.assertEqual(bytes(device.flash), expected)
            self.assertEqual(device.exits, 0)
            self.assertNotIn(f.END, [cmd for _, cmd in device.commands])
            self.assertEqual(device.footprints[0], (0, 0x10000))
            self.assertEqual((stopped / 'before-startup.bin').read_bytes(), before)
            self.assertEqual((stopped / 'after-image.bin').read_bytes(), expected)
            # The running core may change its own writable storage, including 4 KiB sectors.
            device.flash[0x3F9000] ^= 1
            self.run_on(device, Path(root) / 'restore', finish=stopped)
            self.assertEqual(bytes(device.flash), before)
            self.assertEqual((Path(root) / 'restore/after-image.bin').read_bytes(), before)
        self.assertTrue(all(off + size <= f.PROTECTED for off, size in device.footprints))
        self.assertEqual([cmd for _, cmd in device.commands].count(f.END), 1)
        self.assertEqual(device.commands[-1][1], f.END)
        self.assertIn((0x3F9000, 0x1000), device.footprints)

    def test_trial_starts_once_only_after_verified_blank_image(self):
        device = self.bootable()
        with tempfile.TemporaryDirectory() as root:
            installed = self.install(device, root, stop=False)
            expected = b'\xff' * 4 + self.image()[4:]
            self.assertEqual((installed / 'trial-before-exit-second.bin').read_bytes(), expected)
        self.assertEqual(bytes(device.flash), expected)
        self.assertEqual(device.exits, 1)
        self.assertEqual(device.resets, 1)
        self.assertNotIn(f.END, [cmd for _, cmd in device.commands])

    def test_interrupted_trial_recovers_from_fresh_runs_without_automatic_retry(self):
        class Interrupted(RunningProgrammer):
            stop_at = None

            def run(self, address):
                super().run(address)
                if self.stop_at is not None and len(self.footprints) == self.stop_at:
                    raise IOError('simulated lost acknowledgement after flash write')

        for number in (1, 2, 19, 38):
            with self.subTest(write=number), tempfile.TemporaryDirectory() as root:
                device = Interrupted()
                device.flash[:] = self.BOOTABLE
                device.stop_at = number
                with self.assertRaisesRegex(IOError, 'lost acknowledgement'):
                    self.install(device, root, stop=False)
                self.assertEqual(len(device.footprints), number)
                self.assertEqual(device.exits, 0)
                self.assertNotIn(f.END, [cmd for _, cmd in device.commands])
                device.stop_at = None
                device.replies.clear()  # a new process/reset discards stale USB input
                self.run_on(device, Path(root) / 'recover', finish=Path(root) / 'install')
                self.assertEqual(bytes(device.flash), self.BOOTABLE)

    def test_recovery_refuses_wrong_unit_tail_before_loading_programmer(self):
        device = self.bootable()
        with tempfile.TemporaryDirectory() as root:
            stopped = self.install(device, root)
            device.flash[f.PROTECTED] ^= 1
            commands = len(device.commands)
            with self.assertRaisesRegex(ValueError, 'protected bytes'):
                self.run_on(device, Path(root) / 'restore', finish=stopped)
            self.assertEqual(len(device.commands), commands)

    def logicrom_ran(self, device):
        """What the core did on 412 on 2026-10-09 before it reset: file-system writes
        above the app partition, and a zeroed 32-byte mark at the head of sectors up
        to the end of flash, the calibration/factory sectors included."""
        device.flash[0x2F0000:0x2F0020] = bytes(32)
        device.flash[0x3F9000] ^= 1
        for offset in range(f.PROTECTED, f.FLASH_SIZE, 0x1000):
            device.flash[offset:offset + 32] = bytes(32)

    def test_recovery_with_repair_restores_marked_tail_sectors_from_the_backup_first(self):
        device = self.bootable()
        before = bytes(device.flash)
        with tempfile.TemporaryDirectory() as root:
            stopped = self.install(device, root)
            self.logicrom_ran(device)
            writes = len(device.footprints)
            self.run_on(device, Path(root) / 'restore', finish=stopped, repair_tail=True)
            self.assertEqual(bytes(device.flash), before)
            repaired = (Path(root) / 'restore/after-tail-repair.bin').read_bytes()
            self.assertEqual(repaired[f.PROTECTED:], before[f.PROTECTED:])
            self.assertEqual(repaired[:4], b'\xff' * 4)
        # One erase and one program per tail sector, in order, before anything else.
        tail = [(offset, 0x1000) for offset in range(f.PROTECTED, f.FLASH_SIZE, 0x1000)
                for _ in range(2)]
        self.assertEqual(device.footprints[writes:writes + 12], tail)
        self.assertTrue(all(off + size <= f.PROTECTED
                            for off, size in device.footprints[writes + 12:]))
        self.assertEqual([cmd for _, cmd in device.commands].count(f.END), 1)
        self.assertEqual(device.commands[-1][1], f.END)

    def test_tail_repair_is_refused_without_its_flag_or_beyond_the_known_marks(self):
        cases = [('no flag', {}, None, 'protected bytes'),
                 ('other damage', dict(repair_tail=True), f.PROTECTED + 100, 'beyond'),
                 ('another unit', dict(repair_tail=True), 0x10008, 'this journal')]
        for label, flags, spoil, error in cases:
            with self.subTest(label), tempfile.TemporaryDirectory() as root:
                device = self.bootable()
                stopped = self.install(device, root)
                self.logicrom_ran(device)
                if spoil is not None:
                    device.flash[spoil] ^= 1
                count = len(device.commands)
                with self.assertRaisesRegex(ValueError, error):
                    self.run_on(device, Path(root) / 'restore', finish=stopped, **flags)
                self.assertEqual(len(device.commands), count)

    def test_interrupted_tail_repair_resumes_from_an_erased_sector(self):
        second = (f.PROTECTED + 0x1000, 0x1000)

        class Interrupted(RunningProgrammer):
            interrupt = False

            def run(self, address):
                super().run(address)
                if (self.interrupt and self.commands[-1][1] == f.ERASE
                        and self.footprints[-1] == second):
                    raise IOError('interrupted repair')

        device = Interrupted()
        device.flash[:] = self.BOOTABLE
        with tempfile.TemporaryDirectory() as root:
            stopped = self.install(device, root)
            self.logicrom_ran(device)
            device.interrupt = True
            with self.assertRaisesRegex(IOError, 'interrupted repair'):
                self.run_on(device, Path(root) / 'failed', finish=stopped, repair_tail=True)
            self.assertEqual(device.flash[second[0]:second[0] + 0x1000], b'\xff' * 0x1000)
            self.assertNotIn(f.END, [cmd for _, cmd in device.commands])
            device.interrupt = False
            device.replies.clear()
            self.run_on(device, Path(root) / 'resumed', finish=stopped, repair_tail=True)
            self.assertEqual(bytes(device.flash), self.BOOTABLE)

    def test_interrupted_full_recovery_can_resume_from_original_install_journal(self):
        class Interrupted(RunningProgrammer):
            interrupt = False

            def run(self, address):
                super().run(address)
                if self.interrupt and self.commands[-1][1] == f.PROGRAM:
                    raise IOError('interrupted recovery')

        device = Interrupted()
        device.flash[:] = self.BOOTABLE
        with tempfile.TemporaryDirectory() as root:
            stopped = self.install(device, root)
            device.interrupt = True
            with self.assertRaisesRegex(IOError, 'interrupted recovery'):
                self.run_on(device, Path(root) / 'failed-restore', finish=stopped)
            self.assertEqual(device.flash[:4], b'\xff' * 4)
            self.assertNotIn(f.END, [cmd for _, cmd in device.commands])
            device.interrupt = False
            device.replies.clear()
            self.run_on(device, Path(root) / 'resumed-restore', finish=stopped)
            self.assertEqual(bytes(device.flash), self.BOOTABLE)

    def test_full_recovery_refuses_a_valid_boot_word_on_changed_core(self):
        device = self.bootable()
        with tempfile.TemporaryDirectory() as root:
            stopped = self.install(device, root)
            device.flash[:4] = struct.pack('<I', f.MAGIC)
            count = len(device.commands)
            with self.assertRaisesRegex(IOError, 'requires blank boot word'):
                self.run_on(device, Path(root) / 'restore', finish=stopped)
            self.assertEqual(len(device.commands), count)

    def test_readback_corruption_never_finalizes_or_starts_trial(self):
        class Corrupt(RunningProgrammer):
            def run(self, address):
                super().run(address)
                # Corrupt a protected byte when the first new core block is programmed.
                if self.commands[-1][1] == f.PROGRAM and self.footprints[-1][0] == 0x10000:
                    self.flash[f.PROTECTED] ^= 1

        device = Corrupt()
        device.flash[:] = self.BOOTABLE
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(IOError, 'Full flash verification failed'):
                self.install(device, root, stop=False)
        self.assertEqual(device.exits, 0)
        self.assertNotIn(f.END, [cmd for _, cmd in device.commands])

    def test_disk_inputs_fail_before_usb_or_journal_creation(self):
        device = self.bootable()
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source = root / 'trial.bin'
            source.write_bytes(self.image())
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                self.run_on(device, root / 'bad', trial=source, trial_sha256='0' * 64)
            self.assertFalse((root / 'bad').exists())
            stopped = self.install(device, root)
            original = (stopped / 'before-startup.bin').read_bytes()
            tampered = bytearray(original)
            tampered[0x382000] ^= 1
            (stopped / 'before-startup.bin').write_bytes(tampered)
            with self.assertRaisesRegex(ValueError, 'intact, journaled'):
                self.run_on(device, root / 'bad-recovery', finish=stopped)
            self.assertFalse((root / 'bad-recovery').exists())
            (stopped / 'before-startup.bin').write_bytes(original)
            with (stopped / 'operations.jsonl').open('a') as out:
                out.write('{truncated last event')
            self.assertEqual(s.recovery_target(stopped, self.BOOTABLE, '1403167412'), original)
            with self.assertRaises(ValueError):
                s.recovery_target(stopped, self.BOOTABLE, '1403167417')

    def test_trial_exit_rejects_corrupt_readback_and_is_never_retried(self):
        device = self.bootable()
        journal = mock.Mock()
        monitor = s.StartMonitor(device, journal, TimeoutError, [])
        monitor.internal(0xFD)
        monitor.receive(0, 4)
        expected = b'\xff' * 4 + self.image()[4:]
        with mock.patch.object(s, 'read_flash', side_effect=[expected, self.BOOTABLE]):
            with self.assertRaisesRegex(IOError, 'changed across reset'):
                s.start_trial(monitor, journal, expected)
        self.assertEqual(device.exits, 0)
        with mock.patch.object(s, 'read_flash', return_value=expected):
            s.start_trial(monitor, journal, expected)
        self.assertEqual(device.exits, 1)
        with self.assertRaises(ValueError):
            monitor.send(s.ROM_EXIT)
        self.assertEqual(device.exits, 1)

    def test_original_and_conflicting_modes_are_blocked_offline(self):
        cases = [(['--unit', f.ORIGINAL_UNIT, '--trial', 'x', '--trial-sha256', 'a'], 'original'),
                 (['--unit', '1403167412', '--trial-stop'], 'needs'),
                 (['--unit', '1403167412', '--trial', 'x'], 'needs'),
                 (['--unit', '1403167412', '--trial', 'x', '--markers'], 'pinned'),
                 (['--unit', '1403167412', '--trial', 'x', '--finish', 'x'], 'separate'),
                 (['--unit', '1403167412', '--repair-tail'], 'needs')]
        for argv, message in cases:
            stderr = io.StringIO()
            with mock.patch('sys.argv', ['rda_programmer_start.py'] + argv), contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit):
                    s.main()
            self.assertIn(message, stderr.getvalue())
