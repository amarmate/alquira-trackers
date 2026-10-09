import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest

from logicrom_console import usb_devices, watch


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
        self.assertEqual([n for n in names if n != 'usb'],
                         ['start', 'open', 'rx', 'tx', 'closed', 'complete'])
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

    def test_usb_listing_names_devices_only(self):
        for name in usb_devices():
            self.assertRegex(name, r'@[0-9a-f]+$')
            self.assertNotIn('XHCI', name)


if __name__ == '__main__':
    unittest.main()
