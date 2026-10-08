"""Offline structural audit of an RDA RAM programmer LOD; never opens USB.

Only physical internal-SRAM load records are accepted. This does not establish
startup safety, external RAM compatibility, or flash-chip support.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def audit(path):
    raw = path.read_bytes()
    memory = {}
    address = None
    expected = None
    checksum = 0
    for number, line in enumerate(raw.decode('ascii').splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if line.startswith('#checksum='):
            if expected is not None:
                raise ValueError('Multiple checksums')
            expected = int(line.split('=', 1)[1], 16)
        elif re.fullmatch(r'@[0-9a-fA-F]{8}', line):
            address = int(line[1:], 16)
            if address % 4:
                raise ValueError(f'Unaligned address at line {number}')
        elif re.fullmatch(r'[0-9a-fA-F]{8}', line) and address is not None:
            if expected is not None:
                raise ValueError('Data after checksum')
            if not 0x01c00000 <= address < 0x01c10000:
                raise ValueError(f'Non-internal-SRAM load at {address:#x}')
            if address in memory:
                raise ValueError(f'Overlapping load at {address:#x}')
            memory[address] = int(line, 16)
            checksum = (checksum + memory[address]) & 0xffffffff
            address += 4
        else:
            raise ValueError(f'Unexpected LOD syntax at line {number}')
    if not memory or expected is None or checksum != expected:
        raise ValueError('Missing data/checksum or checksum mismatch')
    intervals = []
    for address in sorted(memory):
        if intervals and intervals[-1][1] == address:
            intervals[-1][1] += 4
        else:
            intervals.append([address, address + 4])
    context = [memory.get(0x01c000a0 + i * 4) for i in range(6)]
    if any(value is None for value in context):
        raise ValueError('Incomplete monitor execution context')
    if (context[1] & 0x1ffffffe) not in memory:
        raise ValueError('Entry point is not in loaded SRAM')
    # Find the ABI marker in loaded data; report, never assume a fixed address.
    markers = []
    for address in sorted(memory):
        if memory[address] == 0xfb05fa01:
            words = [memory.get(address + 4 * i) for i in range(15)]
            markers.append(dict(physical=hex(address), words=[hex(x) if x is not None else None for x in words]))
    return dict(file=path.name, sha256=hashlib.sha256(raw).hexdigest(),
                file_bytes=len(raw), payload_bytes=4 * len(memory),
                checksum=hex(checksum), intervals=[[hex(a), hex(b)] for a, b in intervals],
                execution_context=[hex(x) for x in context], protocol_maps=markers,
                status='STRUCTURAL_AUDIT_ONLY_NOT_DEVICE_VALIDATION')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('lod', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.lod), indent=2))
