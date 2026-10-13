"""Server for the stock V24 protocol: answers what the tracker waits for and logs every frame.

Run:  python3 tracker_server.py --port 48888 --log frames.jsonl --device 1403167417

The tracker holds one TCP connection and sends bracketed text frames:

    [3G*<10-digit id>*<content length, 4 hex digits>*<content>]

Protocol notes: docs/knowledge/tracker-intel.md, section 4. Standard library only, so
it runs on any host with Python 3. The port is open to the internet and the protocol has
no authentication, so everything received is treated as untrusted: it is logged, never
acted on, and only the listed device ids get an answer.
"""
import argparse
import json
import re
import socketserver
import threading
from collections import namedtuple
from datetime import datetime, timezone

Frame = namedtuple('Frame', 'vendor device_id content')

# Upper-case hex only, as the vendor document states. It lets the log rebuild a frame
# byte for byte; anything else shows up as junk rather than being silently normalised.
HEADER = re.compile(rb'\[([0-9A-Z]{2})\*(\d{10})\*([0-9A-F]{4})\*')
HEADER_SIZE = 20
# The keepalive comes every 5 minutes. Three missed ones mean the link is dead.
IDLE_SECONDS = 900
# A tracker sends clean frames. This much stray data on one connection is not a tracker.
JUNK_LIMIT = 4096


def build_frame(vendor, device_id, content):
    return f'[{vendor}*{device_id}*{len(content.encode("latin-1")):04X}*{content}]'.encode('latin-1')


def split_frames(buffer):
    """Return (frames, junk, rest): whole frames, bytes that fit no frame, an unfinished tail.

    The length field decides where a frame ends, because the content (a WiFi name, for
    one) may itself hold a bracket. The tail is at most one header plus 65535 bytes.
    """
    frames = []
    junk = b''
    while buffer:
        start = buffer.find(b'[')
        if start < 0:
            junk += buffer
            buffer = b''
            break
        junk += buffer[:start]
        buffer = buffer[start:]
        if len(buffer) < HEADER_SIZE:
            break  # header still arriving
        header = HEADER.match(buffer)
        if header:
            end = HEADER_SIZE + int(header.group(3), 16)
            if len(buffer) <= end:
                break  # content still arriving
            if buffer[end:end + 1] == b']':
                frames.append(Frame(header.group(1).decode(), header.group(2).decode(),
                                    buffer[HEADER_SIZE:end].decode('latin-1')))
                buffer = buffer[end + 1:]
                continue
        # Not a frame. Drop this bracket and look for the next one.
        junk += buffer[:1]
        buffer = buffer[1:]
    return frames, junk, buffer


def reply_for(frame):
    """The answer the tracker waits for, or None when it expects none."""
    parts = frame.content.split(',')
    if parts[0] == 'LK':
        # Unanswered, the tracker sends nothing else and reconnects every 5 minutes.
        return build_frame('SG', frame.device_id, 'LK')
    if parts[0] == 'CONFIG':
        return build_frame('SG', frame.device_id, 'CONFIG,1')
    if parts[0] == 'ICCID' and len(parts) > 2:
        return build_frame('3G', frame.device_id, 'RYIMEI,' + parts[2])
    if parts[0] == 'AL':
        # Unanswered, the tracker repeats the alarm.
        return build_frame('SG', frame.device_id, 'AL')
    return None


def fields_of(content):
    """Name the fields we read from a frame's content. The whole frame is logged regardless."""
    parts = content.split(',')
    fields = {'kw': parts[0]}
    try:
        if parts[0] == 'LK' and len(parts) > 1:
            fields.update(steps=int(parts[1]), rolls=int(parts[2]), bat=int(parts[3]))
        elif parts[0] in ('UD', 'UD2', 'AL'):
            # Layout from the vendor's protocol document. Not yet checked against a
            # position frame from one of our own units.
            fields.update(date=parts[1], time=parts[2], fix=parts[3] == 'A',
                          sats=int(parts[11]), gsm=int(parts[12]), bat=int(parts[13]),
                          steps=int(parts[14]), rolls=int(parts[15]), status=parts[16])
    except (IndexError, ValueError) as error:
        fields['parse_error'] = str(error)
    return fields


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        server = self.server
        peer = '%s:%d' % self.client_address[:2]
        if not server.slots.acquire(blocking=False):
            server.log(peer, event='busy')
            return
        server.log(peer, event='connect')
        self.request.settimeout(IDLE_SECONDS)
        buffer = b''
        junk_bytes = 0
        try:
            while True:
                data = self.request.recv(4096)
                if not data:
                    return
                frames, junk, buffer = split_frames(buffer + data)
                if junk:
                    if junk_bytes == 0:
                        server.log(peer, event='junk', hex=junk[:200].hex())
                    junk_bytes += len(junk)
                    if junk_bytes > JUNK_LIMIT:
                        server.log(peer, event='overflow', junk_bytes=junk_bytes)
                        return
                for frame in frames:
                    raw = build_frame(*frame).decode('latin-1')
                    if frame.device_id not in server.devices:
                        server.log(peer, event='refused', id=frame.device_id, raw=raw[:200])
                        return
                    server.log(peer, id=frame.device_id, raw=raw, **fields_of(frame.content))
                    reply = reply_for(frame)
                    if reply:
                        self.request.sendall(reply)
        except OSError as error:  # includes the idle timeout and a reset by the peer
            server.log(peer, event='error', error=repr(error))
        finally:
            server.log(peer, event='disconnect')
            server.slots.release()


class TrackerServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, log_path, devices, max_connections=32):
        self.log_path = log_path
        self.devices = set(devices)
        self.max_connections = max_connections
        self.slots = threading.BoundedSemaphore(max_connections)
        self.log_lock = threading.Lock()
        super().__init__(address, Handler)

    def log(self, peer, **fields):
        """Append one JSON line, stamped with this host's clock in UTC."""
        line = {'t': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'peer': peer, **fields}
        with self.log_lock:
            with open(self.log_path, 'a') as handle:
                handle.write(json.dumps(line) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--log', required=True, help='JSON-lines file, appended to')
    parser.add_argument('--device', action='append', required=True, metavar='ID',
                        help='10-digit id of a tracker to answer; repeat for more')
    args = parser.parse_args()
    for device in args.device:
        if not re.fullmatch(r'\d{10}', device):
            parser.error(f'--device must be 10 digits, got {device!r}')
    with TrackerServer((args.host, args.port), args.log, args.device) as server:
        print(f'listening on {args.host}:{args.port}, logging to {args.log}, answering {sorted(server.devices)}',
              flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
