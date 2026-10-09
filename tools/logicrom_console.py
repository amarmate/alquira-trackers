"""Log what the Logicrom core prints on its USB serial port; send at most one line.

The core enumerates as 1782:4d11 with a CDC modem interface, which macOS exposes as
/dev/cu.usbmodem*. Neither the vendor firmware nor the ROM creates such a node, so a
node that was not there at the start is taken to be the core's. USB devices are
watched through the IORegistry only: a libusb client opening the device while macOS
is still configuring it could cost the serial port, and on 412's first start the core
stayed on the bus for 10 s.
"""
import argparse
import glob
import json
import os
from pathlib import Path
import select
import subprocess
import termios
import time
import tty

PORTS = '/dev/cu.usbmodem*'


def usb_devices():
    out = subprocess.run(['ioreg', '-p', 'IOUSB', '-w0'], capture_output=True, text=True).stdout
    return sorted(line.split('+-o ')[1].split('  <')[0] for line in out.splitlines()
                  if 'IOUSBHostDevice' in line)


def usb_details():
    return subprocess.run(['ioreg', '-r', '-c', 'IOUSBHostDevice', '-l', '-w0'],
                          capture_output=True, text=True).stdout


def watch(output, seconds, send=None, send_after=3.0, ports=PORTS):
    start = time.monotonic()
    with open(output, 'x') as log:
        def emit(event, **record):
            record.update(event=event, elapsed=round(time.monotonic() - start, 2),
                          utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
            line = json.dumps(record, sort_keys=True)
            print(line, flush=True)
            log.write(line + '\n')
            log.flush()

        # known: nodes not to open, either there from the start or already handled.
        known, devices = set(glob.glob(ports)), usb_devices()
        emit('start', ports=sorted(known), usb=devices, send=send)
        opened = {}  # fd -> dict(path, since, sent)
        failed = {}
        received = 0
        sent = seen = False
        dumps = []
        while (now := time.monotonic()) - start < seconds:
            present = set(glob.glob(ports))
            # A node that went away and comes back is a new start of the core.
            known &= present
            for path in sorted(present - known):
                fd = None
                try:
                    fd = os.open(path, (os.O_RDWR if send else os.O_RDONLY)
                                 | os.O_NOCTTY | os.O_NONBLOCK)
                    tty.setraw(fd)
                except (OSError, termios.error) as exc:
                    if fd is not None:
                        os.close(fd)
                    # Tried again on the next pass; reported once per distinct error.
                    if failed.get(path) != str(exc):
                        failed[path] = str(exc)
                        emit('open_failed', port=path, error=str(exc))
                    continue
                opened[fd] = dict(path=path, since=now, sent=False)
                known.add(path)
                seen = True
                emit('open', port=path)
            if opened:
                ready = select.select(list(opened), [], [], 0.2)[0]
            else:
                ready = []
                time.sleep(0.2)
            for fd, port in list(opened.items()):
                data = None
                try:
                    if send and not port['sent'] and now - port['since'] >= send_after:
                        os.write(fd, send.encode() + b'\r\n')
                        port['sent'] = sent = True
                        emit('tx', port=port['path'], text=send)
                    if fd in ready:
                        data = os.read(fd, 4096)
                except OSError as exc:
                    data = b''
                    emit('port_error', port=port['path'], error=str(exc))
                if data:
                    received += len(data)
                    emit('rx', port=port['path'], text=data.decode('utf-8', 'backslashreplace'),
                         hex=data.hex())
                elif data == b'':
                    emit('closed', port=port['path'])
                    os.close(fd)
                    del opened[fd]
            current = usb_devices()
            if current != devices:
                emit('usb', devices=current)
                if set(current) - set(devices):
                    # Interfaces attach a moment after the device node does.
                    dumps = [now, now + 2]
                devices = current
            if dumps and now >= dumps[0]:
                dumps.pop(0)
                with open(str(output) + '.usb.txt', 'a') as details:
                    details.write(f'=== {time.strftime("%H:%M:%SZ", time.gmtime())} ===\n'
                                  + usb_details())
        emit('complete', port_seen=seen, bytes_received=received, line_sent=sent,
             still_open=sorted(port['path'] for port in opened.values()))
        for fd in opened:
            os.close(fd)
    return seen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path, help='new JSON-lines log')
    parser.add_argument('--seconds', type=float, default=180)
    parser.add_argument('--send', help='one console line, sent once after the port opens')
    parser.add_argument('--send-after', type=float, default=3.0)
    args = parser.parse_args()
    raise SystemExit(0 if watch(args.output, args.seconds, args.send, args.send_after) else 2)


if __name__ == '__main__':
    main()
