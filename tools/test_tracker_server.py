"""Offline checks for the stock-protocol server: framing, replies, fields, and one socket run.

Run: .venv/bin/python -m unittest discover -s tools -p 'test_*.py'

Frames come from the vendor's examples (docs/knowledge/tracker-intel.md, section 9)
and from the one frame captured from our own unit (firmware/live/verify-vodafone-apn.raw).
"""
import json
import os
import socket
import tempfile
import threading
import time
import unittest

from tracker_server import Frame, TrackerServer, fields_of, reply_for, split_frames

OURS = b'[3G*1403167417*0009*LK,0,0,98]'  # captured from unit 417
ICCID = b'[3G*2104346361*003B*ICCID,89860321147558480556,865121043463619,460115056494601,]'
# The vendor's position example, with the 2G keyword our units send.
UD = ('UD,100222,221554,V,00.000000,,00.0000000,,0.00,0.0,0.0,0,80,40,0,0,00000000,'
      '2,0,460,0,10142,225274433,4,10142,54313355,-4,0,0.0')


class FramingTests(unittest.TestCase):
    def test_captured_frame(self):
        frames, junk, rest = split_frames(OURS)
        self.assertEqual(frames, [Frame('3G', '1403167417', 'LK,0,0,98')])
        self.assertEqual((junk, rest), (b'', b''))

    def test_two_frames_in_one_segment(self):
        frames, junk, rest = split_frames(OURS + b'[3G*1403167417*0002*LK]')
        self.assertEqual([f.content for f in frames], ['LK,0,0,98', 'LK'])
        self.assertEqual((junk, rest), (b'', b''))

    def test_frame_split_across_segments(self):
        frames, junk, rest = split_frames(OURS[:12])
        self.assertEqual((frames, junk, rest), ([], b'', OURS[:12]))
        frames, junk, rest = split_frames(rest + OURS[12:])
        self.assertEqual([f.content for f in frames], ['LK,0,0,98'])
        self.assertEqual(rest, b'')

    def test_bracket_inside_content_follows_declared_length(self):
        # A WiFi name may hold any byte, so the length field decides where a frame ends.
        frames, junk, rest = split_frames(b'[3G*1403167417*0008*UD,a]b,c]')
        self.assertEqual([f.content for f in frames], ['UD,a]b,c'])
        self.assertEqual((junk, rest), (b'', b''))

    def test_wrong_length_is_dropped_and_the_next_frame_is_found(self):
        frames, junk, rest = split_frames(b'[3G*1403167417*0005*LK]' + OURS)
        self.assertEqual([f.content for f in frames], ['LK,0,0,98'])
        self.assertEqual(junk, b'[3G*1403167417*0005*LK]')
        self.assertEqual(rest, b'')

    def test_scanner_traffic_is_junk(self):
        frames, junk, rest = split_frames(b'GET / HTTP/1.1\r\nHost: x\r\n\r\n')
        self.assertEqual(frames, [])
        self.assertEqual(junk, b'GET / HTTP/1.1\r\nHost: x\r\n\r\n')
        self.assertEqual(rest, b'')


class ReplyTests(unittest.TestCase):
    def reply(self, content):
        return reply_for(Frame('3G', '2104346361', content))

    def test_keepalive_is_always_answered(self):
        self.assertEqual(self.reply('LK'), b'[SG*2104346361*0002*LK]')
        self.assertEqual(self.reply('LK,0,0,4'), b'[SG*2104346361*0002*LK]')

    def test_config(self):
        self.assertEqual(self.reply('CONFIG,TY:1,VR:x'), b'[SG*2104346361*0008*CONFIG,1]')

    def test_iccid_is_answered_with_the_imei(self):
        frames, _, _ = split_frames(ICCID)
        self.assertEqual(reply_for(frames[0]), b'[3G*2104346361*0016*RYIMEI,865121043463619]')

    def test_iccid_without_an_imei_gets_no_reply(self):
        self.assertIsNone(self.reply('ICCID,89860321147558480556'))

    def test_alarm(self):
        self.assertEqual(self.reply('AL,100222,221554,V'), b'[SG*2104346361*0002*AL]')

    def test_positions_and_unknown_keywords_get_no_reply(self):
        self.assertIsNone(self.reply(UD))
        self.assertIsNone(self.reply('UD2,100222'))
        self.assertIsNone(self.reply('TKQ'))


class FieldTests(unittest.TestCase):
    def test_keepalive_fields(self):
        self.assertEqual(fields_of('LK,0,0,98'), {'kw': 'LK', 'steps': 0, 'rolls': 0, 'bat': 98})
        self.assertEqual(fields_of('LK'), {'kw': 'LK'})

    def test_position_fields(self):
        got = fields_of(UD)
        self.assertEqual(got['kw'], 'UD')
        self.assertEqual((got['date'], got['time'], got['fix']), ('100222', '221554', False))
        self.assertEqual((got['sats'], got['gsm'], got['bat']), (0, 80, 40))
        self.assertEqual((got['steps'], got['rolls'], got['status']), (0, 0, '00000000'))

    def test_a_position_we_cannot_read_says_so(self):
        got = fields_of('UD,100222,221554')
        self.assertEqual(got['kw'], 'UD')
        self.assertIn('parse_error', got)

    def test_a_keepalive_we_cannot_read_says_so(self):
        self.assertIn('parse_error', fields_of('LK,x,y,z'))


class SocketTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.log = os.path.join(self.dir.name, 'frames.jsonl')
        self.server = TrackerServer(('127.0.0.1', 0), self.log, {'1403167417'}, max_connections=3)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def connect(self):
        sock = socket.create_connection(self.server.server_address, timeout=5)
        self.addCleanup(sock.close)
        return sock

    def lines(self):
        if not os.path.exists(self.log):  # nothing logged yet
            return []
        with open(self.log) as handle:
            return [json.loads(line) for line in handle]

    def events_after(self, name, count=1):
        """The logged events, once `name` is there `count` times. Handlers run on their own threads."""
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            events = [line['event'] for line in self.lines() if 'event' in line]
            if events.count(name) >= count:
                return events
            time.sleep(0.02)
        self.fail(f'fewer than {count} {name!r} events in the log: {self.lines()}')

    def test_a_unit_gets_its_replies_and_every_frame_is_logged(self):
        sock = self.connect()
        sock.sendall(b'[3G*1403167417*0009*CONFIG,TY]' + OURS)
        want = b'[SG*1403167417*0008*CONFIG,1][SG*1403167417*0002*LK]'
        got = b''
        while len(got) < len(want):
            got += sock.recv(1024)
        self.assertEqual(got, want)
        sock.close()
        self.assertEqual(self.events_after('disconnect'), ['connect', 'disconnect'])
        frames = [line for line in self.lines() if 'raw' in line]
        self.assertEqual([f['raw'] for f in frames], ['[3G*1403167417*0009*CONFIG,TY]', OURS.decode()])
        self.assertEqual(frames[1]['bat'], 98)
        self.assertEqual(frames[1]['id'], '1403167417')
        self.assertTrue(frames[1]['t'].endswith('+00:00'))

    def test_an_unknown_device_is_logged_and_dropped_without_a_reply(self):
        sock = self.connect()
        sock.sendall(b'[3G*2104346361*0002*LK]')
        self.assertEqual(sock.recv(1024), b'')  # closed, nothing sent
        self.assertIn('refused', self.events_after('disconnect'))

    def test_connections_beyond_the_limit_are_closed_at_once(self):
        held = [self.connect() for _ in range(self.server.max_connections)]
        self.events_after('connect', count=len(held))
        extra = self.connect()
        self.assertEqual(extra.recv(1024), b'')
        self.assertIn('busy', self.events_after('busy'))
        held[0].sendall(OURS)  # the held ones still work
        self.assertEqual(held[0].recv(1024), b'[SG*1403167417*0002*LK]')

    def test_a_flood_without_frames_is_cut_off(self):
        sock = self.connect()
        try:
            sock.sendall(b'[' + b'A' * 200_000)
        except OSError:
            pass  # the server may close while we are still sending
        self.assertIn('overflow', self.events_after('disconnect'))


if __name__ == '__main__':
    unittest.main()
