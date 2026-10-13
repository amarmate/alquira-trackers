"""Log what the Logicrom core prints on its USB serial port; send at most one line.
With --no-open it only reports the serial node coming and going and never opens it.

The core enumerates as 1782:4d11 with a CDC modem interface, which macOS exposes as
/dev/cu.usbmodem*. Neither the vendor firmware nor the ROM creates such a node, so a
node that was not there at the start is taken to be the core's. USB devices are
watched through the IORegistry only: a libusb client opening the device while macOS
is still configuring it could cost the serial port, and on 412's first start the core
stayed on the bus for 10 s.
"""
import argparse
import fcntl
import glob
import json
import os
from pathlib import Path
import select
import struct
import subprocess
import termios
import time

PORTS = '/dev/cu.usbmodem*'
ENDINGS = {'cr': '\r', 'lf': '\n', 'crlf': '\r\n'}
MODEM_LINES = {'DTR': termios.TIOCM_DTR, 'RTS': termios.TIOCM_RTS, 'CTS': termios.TIOCM_CTS,
               'DSR': termios.TIOCM_DSR, 'CD': termios.TIOCM_CD}
BAUDS = {value: getattr(termios, f'B{value}') for value in (9600, 19200, 38400, 57600, 115200)}
HW_FLOW = (getattr(termios, 'CRTSCTS', 0) | getattr(termios, 'CCTS_OFLOW', 0)
           | getattr(termios, 'CRTS_IFLOW', 0))


def usb_devices():
    out = subprocess.run(['ioreg', '-p', 'IOUSB', '-w0'], capture_output=True, text=True).stdout
    return sorted(line.split('+-o ')[1].split('  <')[0] for line in out.splitlines()
                  if 'IOUSBHostDevice' in line)


def usb_details():
    return subprocess.run(['ioreg', '-r', '-c', 'IOUSBHostDevice', '-l', '-w0'],
                          capture_output=True, text=True).stdout


def _cc_number(value):
    return value if isinstance(value, int) else value[0]


def line_state(fd):
    """Read effective settings; unavailable modem lines are reported, never invented."""
    attrs = termios.tcgetattr(fd)
    state = dict(zip(('iflag', 'oflag', 'cflag', 'lflag', 'ispeed', 'ospeed'), attrs))
    state.update(baud=next((n for n, speed in BAUDS.items() if speed == attrs[5]), None),
                 data_bits={termios.CS5: 5, termios.CS6: 6, termios.CS7: 7,
                            termios.CS8: 8}.get(attrs[2] & termios.CSIZE),
                 parity=('odd' if attrs[2] & termios.PARODD else 'even')
                        if attrs[2] & termios.PARENB else 'none',
                 stop_bits=2 if attrs[2] & termios.CSTOPB else 1,
                 hardware_flow=bool(attrs[2] & HW_FLOW),
                 software_flow=bool(attrs[0] & (termios.IXON | termios.IXOFF)),
                 hupcl=bool(attrs[2] & termios.HUPCL),
                 vmin=_cc_number(attrs[6][termios.VMIN]), vtime=_cc_number(attrs[6][termios.VTIME]))
    try:
        bits = struct.unpack('i', fcntl.ioctl(fd, termios.TIOCMGET, bytes(4)))[0]
        state['lines'] = sorted(name for name, bit in MODEM_LINES.items() if bits & bit)
    except OSError as exc:
        state['lines'] = f'not readable: {exc}'
    return state


def configure(fd, baud, dtr, rts, hupcl, report=None):
    """One immediate raw 8N1 change, no queue flush; control-line changes are explicit."""
    attrs = termios.tcgetattr(fd)
    attrs[0] &= ~(termios.BRKINT | termios.ICRNL | termios.INPCK | termios.ISTRIP
                  | termios.IXON | termios.IXOFF | termios.IXANY | termios.INLCR
                  | termios.IGNCR | termios.PARMRK)
    attrs[1] &= ~termios.OPOST
    attrs[2] &= ~(termios.CSIZE | termios.PARENB | termios.PARODD | termios.CSTOPB | HW_FLOW)
    attrs[2] |= termios.CS8 | termios.CLOCAL | termios.CREAD
    attrs[2] = (attrs[2] | termios.HUPCL) if hupcl else (attrs[2] & ~termios.HUPCL)
    attrs[3] &= ~(termios.ECHO | termios.ECHONL | termios.ICANON | termios.ISIG | termios.IEXTEN)
    attrs[4] = attrs[5] = BAUDS[baud]
    attrs[6][termios.VMIN] = 1
    attrs[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    for name, value in (('DTR', dtr), ('RTS', rts)):
        if value != 'keep':
            if report:
                report(name, value)
            operation = termios.TIOCMBIS if value == 'on' else termios.TIOCMBIC
            fcntl.ioctl(fd, operation, struct.pack('i', MODEM_LINES[name]))


def watch(output, seconds, send=None, send_after=3.0, ports=PORTS, ending='\r\n',
          open_ports=True, baud=115200, dtr='keep', rts='keep', hupcl=False,
          attach_existing=False):
    # Opening a CDC node makes macOS send control requests to the device, so a watch
    # that must not disturb the core cannot open it, and then cannot send either.
    if send is not None and not open_ports:
        raise ValueError('A passive watch cannot send a line')
    if baud not in BAUDS or dtr not in ('keep', 'on', 'off') or rts not in ('keep', 'on', 'off'):
        raise ValueError('Unsupported baud or control-line selection')
    if send is not None and ('\r' in send or '\n' in send):
        raise ValueError('Send must be one line without embedded CR or LF')
    start = time.monotonic()
    with open(output, 'x') as log:
        def emit(event, **record):
            record.update(event=event, elapsed=round(time.monotonic() - start, 3),
                          utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
            line = json.dumps(record, sort_keys=True)
            print(line, flush=True)
            log.write(line + '\n')
            log.flush()

        # known: nodes not to open, either there from the start or already handled.
        initial, devices = set(glob.glob(ports)), usb_devices()
        requested = dict(baud=baud, data_bits=8, parity='none', stop_bits=1,
                         hardware_flow=False, software_flow=False, dtr=dtr, rts=rts, hupcl=hupcl)
        emit('start', ports=sorted(initial), usb=devices, send=send, ending=ending,
             open_ports=open_ports, requested=requested, attach_existing=attach_existing,
             control_note='Opening may change DTR/RTS before the first readable snapshot; '
                          'keep means no additional ioctl, not pre-open preservation.')
        known = set() if attach_existing else set(initial)
        nodes = set(initial)
        opened = {}  # fd -> dict(path, since, sent)
        failed = {}
        received = 0
        sent, seen = False, bool(initial) if attach_existing else False
        dumps = []
        try:
            while (now := time.monotonic()) - start < seconds:
                present = set(glob.glob(ports))
                if present != nodes:
                    nodes = present
                    seen = seen or bool(present - known)
                    emit('nodes', ports=sorted(present))
                # A node that went away and comes back is a new start of the core.
                known &= present
                for path in sorted(present - known) if open_ports else ():
                    fd = None
                    try:
                        fd = os.open(path, (os.O_RDWR if send is not None else os.O_RDONLY)
                                     | os.O_NOCTTY | os.O_NONBLOCK)
                        before = line_state(fd)
                        emit('opened_unconfigured', port=path, line=before)
                        configure(fd, baud, dtr, rts, hupcl,
                                  lambda name, value: emit('control_line_request', port=path,
                                                          line=name, value=value))
                        effective = line_state(fd)
                        expected = {key: requested[key] for key in ('baud', 'data_bits', 'parity',
                                    'stop_bits', 'hardware_flow', 'software_flow', 'hupcl')}
                        if any(effective[key] != value for key, value in expected.items()):
                            emit('settings_mismatch', port=path, line=effective, requested=expected)
                            raise OSError('Serial driver did not accept the requested settings')
                        if isinstance(effective['lines'], list):
                            for name, value in (('DTR', dtr), ('RTS', rts)):
                                if value != 'keep' and ((name in effective['lines']) != (value == 'on')):
                                    raise OSError(f'Serial driver did not report requested {name}={value}')
                        elif dtr != 'keep' or rts != 'keep':
                            emit('control_lines_unverified', port=path, error=effective['lines'])
                    except BaseException as exc:
                        if fd is not None:
                            os.close(fd)
                        if not isinstance(exc, (OSError, termios.error)):
                            raise
                        # Tried again on the next pass; reported once per distinct error.
                        if failed.get(path) != str(exc):
                            failed[path] = str(exc)
                            emit('open_failed', port=path, error=str(exc))
                        continue
                    opened[fd] = dict(path=path, since=now, sent=False, offset=0)
                    known.add(path)
                    emit('open', port=path, line=effective, requested=requested)
                if opened:
                    ready = select.select(list(opened), [], [], 0.2)[0]
                else:
                    ready = []
                    time.sleep(0.2)
                for fd, port in list(opened.items()):
                    data = None
                    try:
                        if send is not None and not port['sent'] and now - port['since'] >= send_after:
                            payload = (send + ending).encode()
                            try:
                                count = os.write(fd, payload[port['offset']:])
                            except BlockingIOError:
                                count = 0
                            if count:
                                emit('tx_bytes', port=port['path'], offset=port['offset'],
                                     hex=payload[port['offset']:port['offset'] + count].hex())
                                port['offset'] += count
                            if port['offset'] == len(payload):
                                port['sent'] = sent = True
                                emit('tx', port=port['path'], text=send, ending=ending,
                                     hex=payload.hex())
                        if fd in ready:
                            data = os.read(fd, 4096)
                    except BlockingIOError:
                        pass
                    except OSError as exc:
                        data = b''
                        emit('port_error', port=port['path'], error=str(exc))
                    if data:
                        received += len(data)
                        emit('rx', port=port['path'], text=data.decode('utf-8', 'backslashreplace'),
                             hex=data.hex())
                    elif data == b'':
                        emit('closed', port=port['path'], bytes_transmitted=port['offset'],
                             send_complete=port['sent'])
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
        finally:
            for fd in opened:
                os.close(fd)
    return seen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path, help='new JSON-lines log')
    parser.add_argument('--seconds', type=float, default=180)
    parser.add_argument('--send', help='one console line, sent once after the port opens')
    parser.add_argument('--send-after', type=float, default=3.0)
    parser.add_argument('--ending', choices=sorted(ENDINGS), default='crlf')
    parser.add_argument('--baud', type=int, choices=sorted(BAUDS), default=115200)
    parser.add_argument('--dtr', choices=('keep', 'on', 'off'), default='keep')
    parser.add_argument('--rts', choices=('keep', 'on', 'off'), default='keep')
    parser.add_argument('--hupcl', action='store_true', help='drop modem lines on close')
    parser.add_argument('--port', help='only this node; also attach if already present')
    parser.add_argument('--no-open', action='store_true',
                        help='report the serial node only; never open it')
    args = parser.parse_args()
    if args.send is not None and args.no_open:
        parser.error('--no-open cannot be combined with --send')
    if args.send is not None and ('\r' in args.send or '\n' in args.send):
        parser.error('--send must contain one line without CR or LF')
    seen = watch(args.output, args.seconds, args.send, args.send_after,
                 ports=glob.escape(args.port) if args.port else PORTS,
                 ending=ENDINGS[args.ending], open_ports=not args.no_open,
                 baud=args.baud, dtr=args.dtr, rts=args.rts, hupcl=args.hupcl,
                 attach_existing=bool(args.port))
    raise SystemExit(0 if seen else 2)


if __name__ == '__main__':
    main()
