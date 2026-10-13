import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import fcntl
import struct
import termios

from logicrom_console import configure, line_state, usb_devices, watch


def read_until(fd, wanted, seconds=3):
    data, end = b'', time.monotonic() + seconds
    os.set_blocking(fd, False)
    while wanted not in data and time.monotonic() < end:
        try:
            data += os.read(fd, 100)
        except BlockingIOError:
            time.sleep(0.05)
    return data


class ConsoleTests(unittest.TestCase):
    def setUp(self):
        # The watch prints every event for the person at the Terminal.
        quiet = contextlib.redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)

    def run_watch(self, root, **options):
        self.log = root / 'console.jsonl'
        thread = threading.Thread(target=watch, args=(self.log, 3), kwargs=dict(
            ports=str(root / 'cu.usbmodem*'), **options))
        thread.start()
        return thread

    def events(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_port_that_appears_is_logged_sent_one_line_and_seen_to_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master, slave = os.openpty()
            thread = self.run_watch(root, send='devinfo', send_after=1.0)
            time.sleep(0.4)
            # The node appears only after the watch has started, as the core's does.
            node = root / 'cu.usbmodem1'
            node.symlink_to(os.ttyname(slave))
            time.sleep(0.4)
            os.write(master, b'boot \xff ok\r\n')
            self.assertEqual(read_until(master, b'\n'), b'devinfo\r\n')
            node.unlink()
            os.close(slave)
            os.close(master)
            thread.join()
            events = self.events()
        names = [e['event'] for e in events]
        self.assertEqual([n for n in names if n not in ('usb', 'nodes', 'tx_bytes')],
                         ['start', 'opened_unconfigured', 'open', 'rx', 'tx', 'closed', 'complete'])
        # What the open left the line at, so a run can be compared with the next one.
        line = events[names.index('open')]['line']
        self.assertEqual({k: line[k] for k in ('baud', 'data_bits', 'parity', 'stop_bits',
                                              'hardware_flow', 'software_flow', 'hupcl')},
                         dict(baud=115200, data_bits=8, parity='none', stop_bits=1,
                              hardware_flow=False, software_flow=False, hupcl=False))
        self.assertIn('lines', line)
        rx = events[names.index('rx')]
        self.assertEqual(bytes.fromhex(rx['hex']), b'boot \xff ok\r\n')
        self.assertEqual(rx['text'], 'boot \\xff ok\r\n')
        self.assertEqual(events[-1], dict(events[-1], port_seen=True, line_sent=True,
                                          bytes_received=11, still_open=[]))

    def test_every_new_port_is_read_and_gets_the_line_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pairs = [os.openpty(), os.openpty()]
            thread = self.run_watch(root, send='devinfo', send_after=0.3)
            time.sleep(0.4)
            for index, (_, slave) in enumerate(pairs):
                (root / f'cu.usbmodem{index}').symlink_to(os.ttyname(slave))
            for index, (master, _) in enumerate(pairs):
                self.assertEqual(read_until(master, b'\n'), b'devinfo\r\n')
                os.write(master, b'port %d' % index)
            thread.join()
            events = self.events()
            for master, slave in pairs:
                self.assertEqual(read_until(master, b'\n', seconds=0.3), b'')
                os.close(slave)
                os.close(master)
        texts = {e['port'][-1]: e['text'] for e in events if e['event'] == 'rx'}
        self.assertEqual(texts, {'0': 'port 0', '1': 'port 1'})
        self.assertEqual(len(events[-1]['still_open']), 2)

    def test_port_already_there_is_left_alone_and_nothing_is_sent_unasked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master, slave = os.openpty()
            (root / 'cu.usbmodem0').symlink_to(os.ttyname(slave))
            thread = self.run_watch(root)
            time.sleep(0.4)
            other, other_slave = os.openpty()
            (root / 'cu.usbmodem1').symlink_to(os.ttyname(other_slave))
            time.sleep(0.6)
            os.write(other, b'hello')
            self.assertEqual(read_until(other, b'\n', seconds=1), b'')
            thread.join()
            events = self.events()
            for fd in (master, slave, other, other_slave):
                os.close(fd)
        opened = [e['port'] for e in events if e['event'] == 'open']
        self.assertEqual(opened, [str(root / 'cu.usbmodem1')])
        self.assertNotIn('tx', [e['event'] for e in events])
        self.assertEqual(events[0]['ports'], [str(root / 'cu.usbmodem0')])

    def test_passive_watch_reports_the_node_and_never_opens_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master, slave = os.openpty()
            thread = self.run_watch(root, open_ports=False)
            time.sleep(0.4)
            node = root / 'cu.usbmodem1'
            node.symlink_to(os.ttyname(slave))
            time.sleep(0.6)
            node.unlink()
            thread.join()
            events = self.events()
            os.close(slave)
            os.close(master)
        self.assertNotIn('open', [e['event'] for e in events])
        self.assertEqual([e['ports'] for e in events if e['event'] == 'nodes'], [[str(node)], []])
        self.assertEqual(events[-1], dict(events[-1], port_seen=True, bytes_received=0))

    def test_passive_watch_refuses_a_line_to_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                watch(Path(tmp) / 'console.jsonl', 1, send='devinfo', open_ports=False)

    def test_line_ending_is_the_one_asked_for(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master, slave = os.openpty()
            thread = self.run_watch(root, send='devinfo', send_after=0.2, ending='\r')
            time.sleep(0.4)
            (root / 'cu.usbmodem1').symlink_to(os.ttyname(slave))
            self.assertEqual(read_until(master, b'\n', seconds=1.5), b'devinfo\r')
            thread.join()
            events = self.events()
            os.close(slave)
            os.close(master)
        self.assertEqual([e['ending'] for e in events if e['event'] == 'tx'], ['\r'])

    def test_usb_listing_names_devices_only(self):
        for name in usb_devices():
            self.assertRegex(name, r'@[0-9a-f]+$')
            self.assertNotIn('XHCI', name)

    def test_explicit_existing_port_is_attached_with_selected_baud(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master, slave = os.openpty()
            node = root / 'cu.usbmodem0'
            node.symlink_to(os.ttyname(slave))
            thread = self.run_watch(root, attach_existing=True, baud=57600)
            time.sleep(0.6)
            os.write(master, b'existing')
            thread.join()
            events = self.events()
            os.close(master)
            os.close(slave)
        opened = [e for e in events if e['event'] == 'open']
        self.assertEqual([e['port'] for e in opened], [str(node)])
        self.assertEqual(opened[0]['line']['baud'], 57600)
        self.assertTrue(events[-1]['port_seen'])

    def test_partial_writes_and_would_block_do_not_repeat_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master, slave = os.openpty()
            (root / 'cu.usbmodem0').symlink_to(os.ttyname(slave))
            real_write = os.write
            calls = []

            def short_write(fd, data):
                calls.append(data)
                if len(calls) == 2:
                    raise BlockingIOError()
                return real_write(fd, data[:2])

            with patch('logicrom_console.os.write', side_effect=short_write):
                thread = self.run_watch(root, attach_existing=True, send='devinfo',
                                        ending='\r', send_after=0.1)
                self.assertEqual(read_until(master, b'\r'), b'devinfo\r')
                thread.join()
            events = self.events()
            os.close(master)
            os.close(slave)
        chunks = [bytes.fromhex(e['hex']) for e in events if e['event'] == 'tx_bytes']
        self.assertEqual(b''.join(chunks), b'devinfo\r')
        self.assertEqual(len([e for e in events if e['event'] == 'tx']), 1)

    def test_control_lines_change_only_when_selected(self):
        master, slave = os.openpty()
        try:
            with patch('logicrom_console.fcntl.ioctl') as ioctl:
                configure(slave, 115200, 'keep', 'keep', False)
                ioctl.assert_not_called()
                configure(slave, 115200, 'on', 'off', True)
                self.assertEqual(ioctl.call_args_list[0].args,
                                 (slave, termios.TIOCMBIS, struct.pack('i', termios.TIOCM_DTR)))
                self.assertEqual(ioctl.call_args_list[1].args,
                                 (slave, termios.TIOCMBIC, struct.pack('i', termios.TIOCM_RTS)))
            self.assertTrue(line_state(slave)['hupcl'])
        finally:
            os.close(master)
            os.close(slave)

    def test_selected_control_lines_are_logged_and_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master, slave = os.openpty()
            node = root / 'cu.usbmodem0'
            node.symlink_to(os.ttyname(slave))

            def ioctl(fd, operation, data):
                if operation == termios.TIOCMGET:
                    return struct.pack('i', termios.TIOCM_DTR | termios.TIOCM_RTS)
                return data

            try:
                with patch('logicrom_console.fcntl.ioctl', side_effect=ioctl):
                    log = root / 'controls.jsonl'
                    watch(log, 0.3, ports=str(node), attach_existing=True, dtr='on', rts='on')
                events = list(map(json.loads, log.read_text().splitlines()))
                self.assertEqual([(e['line'], e['value']) for e in events
                                  if e['event'] == 'control_line_request'], [('DTR', 'on'), ('RTS', 'on')])
                self.assertEqual(next(e['line']['lines'] for e in events if e['event'] == 'open'),
                                 ['DTR', 'RTS'])
            finally:
                os.close(master)
                os.close(slave)

    def test_rejected_settings_prevent_console_transmission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master, slave = os.openpty()
            node = root / 'cu.usbmodem0'
            node.symlink_to(os.ttyname(slave))
            try:
                log = root / 'rejected.jsonl'
                with patch('logicrom_console.configure'), patch('logicrom_console.usb_devices', return_value=[]):
                    watch(log, 0.3, ports=str(node), attach_existing=True, send='devinfo', send_after=0)
                events = list(map(json.loads, log.read_text().splitlines()))
                self.assertIn('settings_mismatch', [e['event'] for e in events])
                self.assertNotIn('open', [e['event'] for e in events])
                self.assertNotIn('tx', [e['event'] for e in events])
            finally:
                os.close(master)
                os.close(slave)

    def test_exception_after_open_closes_the_owned_descriptor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            master, slave = os.openpty()
            node = root / 'cu.usbmodem0'
            node.symlink_to(os.ttyname(slave))
            owned = []
            real_open = os.open

            def tracked_open(path, flags):
                fd = real_open(path, flags)
                owned.append(fd)
                return fd

            try:
                with patch('logicrom_console.usb_devices', side_effect=[[], RuntimeError('stop')]), \
                     patch('logicrom_console.os.open', side_effect=tracked_open) as opened:
                    with self.assertRaisesRegex(RuntimeError, 'stop'):
                        watch(root / 'failure.jsonl', 1, ports=str(node), attach_existing=True)
                fd = next(e for e in map(json.loads, (root / 'failure.jsonl').read_text().splitlines())
                          if e['event'] == 'open')
                self.assertEqual(fd['port'], str(node))
                # Only the watch's open was observed, and its returned fd is no longer live.
                self.assertEqual(opened.call_count, 1)
                with self.assertRaises(OSError):
                    fcntl.fcntl(owned[0], fcntl.F_GETFD)
            finally:
                os.close(master)
                os.close(slave)

    def test_embedded_newline_is_rejected_before_log_or_port_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'console.jsonl'
            with self.assertRaises(ValueError):
                watch(log, 1, send='devinfo\ngetlic')
            self.assertFalse(log.exists())


if __name__ == '__main__':
    unittest.main()
