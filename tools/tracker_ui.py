"""Local web UI for configuring a ReachFar V24 over USB.

    .venv/bin/python tools/tracker_ui.py        # then open http://127.0.0.1:8724

Talks to the firmware's own command parser (interface 1 of 1782:3d00, see
docs/knowledge/firmware-analysis.md section 9): every command goes out as AT:<cmd>#\\r in
one transfer, and success is the firmware's own "AT RETURN:<keyword>" line.

The settings shown in the page come from tools/tracker_settings.json. That file is
written for one firmware build; when the firmware changes, edit the JSON, not this file.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import sys
import threading
import time

import usb.backend.libusb1
import usb.core

from rda_dump import LIBUSB

HERE = Path(__file__).parent
CATALOG = HERE / 'tracker_settings.json'
PAGE = HERE / 'tracker_ui.html'
EP_OUT, EP_IN = 0x02, 0x82

# Keywords the firmware parses that rewrite flash, identity or code. The docs mark them
# "do not send blind"; refuse them here so a typo in the console cannot brick a unit.
BLOCKED = {'flashread', 'cleanfnv', 'delfile', 'setverno', 'upgrade', 'recovery',
           'imei', 'url', 'ipdurl', 'tpinit', 'tpreset', 'setlcdid', 'opendisk'}

# The firmware copies the frame into a 200-byte event buffer without bounds checks.
MAX_FRAME = 190

# Lines the firmware prints every second regardless of commands; hidden from replies.
NOISE = re.compile(r'^(Gs:\d|gps:\d|lacci=|rfhz_led|wifi_|check_scan|####wifi)')


def build_frame(command):
    """Validate a console/catalog command and return the exact USB bytes."""
    command = command.strip()
    if not command:
        raise ValueError('Empty command')
    if not re.fullmatch(r'[\x20-\x7e]+', command) or re.search(r'[#;]', command):
        raise ValueError('Use printable ASCII only, without # or ; (the frame adds #)')
    keyword = command.split(',', 1)[0].lower()
    if keyword in BLOCKED:
        raise ValueError(f'"{keyword}" rewrites flash or identity; refused by this tool')
    frame = f'AT:{command}#\r'.encode('ascii')
    if len(frame) > MAX_FRAME:
        raise ValueError(f'Command is {len(frame)} bytes; this firmware allows {MAX_FRAME}')
    return frame


def parse_status(text):
    """Pull settings out of a ts reply and a getapn reply."""
    values = {}
    for key, value in re.findall(r'^([A-Za-z][A-Za-z0-9 _]*):([^;\n]*);', text, re.M):
        values.setdefault(key.strip(), value.strip())
    m = re.search(r'get_apn_handle\.apn:(.*?)\.UserName=(.*?),Password=(.*?),mccmnc=(\d*)', text)
    if m:
        values.update(apn=m[1], apn_user=m[2], apn_pass=m[3], apn_mccmnc=m[4])
    return values


class Tracker:
    """Owns the USB device: one reader thread fills the log, commands go one at a time."""

    def __init__(self):
        self.backend = usb.backend.libusb1.get_backend(find_library=lambda _: LIBUSB)
        if self.backend is None:
            sys.exit(f'libusb not found at {LIBUSB}. Run: brew install libusb')
        self.dev = None
        self.error = 'Not connected yet'
        self.log = ''          # rolling text log
        self.offset = 0        # absolute position of self.log[0]
        self.cond = threading.Condition()
        self.send_lock = threading.Lock()
        threading.Thread(target=self._reader, daemon=True).start()

    def _connect(self):
        found = list(usb.core.find(find_all=True, idVendor=0x1782, idProduct=0x3d00,
                                   backend=self.backend))
        if len(found) != 1:
            self.error = (f'Found {len(found)} trackers in 1782:3d00 mode; connect exactly one'
                          if found else 'No tracker on USB (1782:3d00). Check the cable and power.')
            return None
        dev = found[0]
        # Do not resend SET_CONFIGURATION to a running tracker; just check the layout.
        intf = dev.get_active_configuration()[(1, 0)]
        if {ep.bEndpointAddress for ep in intf} != {EP_OUT, EP_IN}:
            self.error = 'Unexpected USB interface layout; refusing to talk to it'
            return None
        return dev

    def _append(self, text):
        with self.cond:
            self.log += text
            if len(self.log) > 2_000_000:
                cut = len(self.log) - 1_000_000
                self.log = self.log[cut:]
                self.offset += cut
            self.cond.notify_all()

    def _reader(self):
        dev = None
        while True:
            if dev is None:
                try:
                    dev = self._connect()
                except usb.core.USBError as e:
                    self.error = f'USB error while connecting: {e}'
                if dev is None:
                    time.sleep(1)
                    continue
            try:
                chunk = bytes(dev.read(EP_IN, 4096, timeout=250))
            except usb.core.USBTimeoutError:
                chunk = b''
            except usb.core.USBError as e:
                # The firmware reboots after some commands and re-enumerates. Drop the
                # handle without disposing it: libusb teardown hangs on macOS here.
                # For a few seconds after a reboot macOS still holds the old interface
                # and reads fail with "Access denied"; that is not a new disconnect.
                if self.dev is not None:
                    self._append(f'\n[ui] USB link lost: {e}\n')
                dev = self.dev = None
                self.error = f'Waiting for the tracker to come back ({e})'
                time.sleep(1)
                continue
            if self.dev is None:
                # Only a read that worked proves the link; commands may use it now.
                self.dev, self.error = dev, None
                self._append('\n[ui] tracker connected\n')
            if chunk:
                self._append(chunk.decode('ascii', 'replace').replace('�', '.').replace('\x00', ''))

    def tail(self, since):
        with self.cond:
            start = max(since, self.offset)
            return self.offset + len(self.log), self.log[start - self.offset:]

    def send(self, command, timeout=10):
        frame = build_frame(command)
        keyword = command.strip().split(',', 1)[0]
        if not self.send_lock.acquire(timeout=timeout):
            raise RuntimeError('Another command is still waiting for its reply')
        try:
            dev = self.dev
            if dev is None:
                raise RuntimeError(self.error)
            mark, _ = self.tail(0)
            self._append(f'\n[ui] TX {frame!r}\n')
            sent = dev.write(EP_OUT, frame, timeout=1000)
            if sent != len(frame):
                raise RuntimeError(f'Partial USB write ({sent}/{len(frame)}); not retrying')
            ack = f'AT RETURN:{keyword}'
            deadline = time.monotonic() + timeout
            acked_at = None
            with self.cond:
                while True:
                    text = self.log[max(mark - self.offset, 0):]
                    if acked_at is None and ack.lower() in text.lower():
                        # Multi-line replies (ts) keep printing for a moment after the ack.
                        acked_at = time.monotonic()
                    now = time.monotonic()
                    if acked_at and now - acked_at > 1.5:
                        break
                    if now > deadline:
                        break
                    self.cond.wait(0.25)
            lines = [l for l in text.splitlines() if l.strip() and not NOISE.match(l)]
            return {'ok': acked_at is not None, 'frame': frame.decode().replace('\r', '\\r'),
                    'reply': '\n'.join(lines)}
        finally:
            self.send_lock.release()


class Handler(BaseHTTPRequestHandler):
    tracker = None

    def log_message(self, *args):
        pass

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _local_only(self):
        # Blocks DNS-rebinding pages from reaching this server through a hostile hostname.
        host = (self.headers.get('Host') or '').split(':')[0]
        if host not in ('127.0.0.1', 'localhost'):
            self._json(403, {'error': 'Open the UI via http://127.0.0.1'})
            return False
        return True

    def do_GET(self):
        if not self._local_only():
            return
        path, _, query = self.path.partition('?')
        if path == '/':
            data = PAGE.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        elif path == '/api/catalog':
            self._json(200, json.loads(CATALOG.read_text()))
        elif path == '/api/log':
            m = re.search(r'since=(\d+)', query)
            pos, text = self.tracker.tail(int(m[1]) if m else 0)
            t = self.tracker
            self._json(200, {'pos': pos, 'text': text,
                             'connected': t.dev is not None, 'error': t.error})
        else:
            self._json(404, {'error': 'Not found'})

    def do_POST(self):
        if not self._local_only():
            return
        # A JSON content type forces a CORS preflight, which this server never approves,
        # so other web pages cannot make the browser post commands here.
        if self.headers.get('Content-Type') != 'application/json':
            self._json(415, {'error': 'Send application/json'})
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            if self.path == '/api/send':
                self._json(200, self.tracker.send(str(body['command'])))
            elif self.path == '/api/read':
                ts = self.tracker.send('ts')
                apn = self.tracker.send('getapn')
                values = parse_status(ts['reply'] + '\n' + apn['reply'])
                self._json(200, {'ok': ts['ok'] and apn['ok'], 'values': values,
                                 'reply': ts['reply'] + '\n' + apn['reply']})
            else:
                self._json(404, {'error': 'Not found'})
        except ValueError as e:
            self._json(400, {'error': str(e)})
        except (RuntimeError, usb.core.USBError) as e:
            self._json(503, {'error': str(e)})


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--port', type=int, default=8724)
    a = p.parse_args()
    Handler.tracker = Tracker()
    server = ThreadingHTTPServer(('127.0.0.1', a.port), Handler)
    print(f'Tracker UI on http://127.0.0.1:{a.port}  (Ctrl+C to stop)', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
