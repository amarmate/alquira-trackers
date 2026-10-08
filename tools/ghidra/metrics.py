"""Measure a V24 decompile export against the design spec's section 8 table.

Run: python3 tools/ghidra/metrics.py firmware/decompiled
Also accepts the old single-file export, which is how the baseline was checked.
"""
import pathlib
import re
import sys

HEADER = re.compile(r'^// ---- (\S+) @ ([0-9a-f]{8}) ----$', re.M)
DEFAULT_NAME = re.compile(r'^(thunk_)?FUN_[0-9a-f]{8}$')
# Char literals go first: '"' would otherwise open a string that never closes.
CHAR = re.compile(r"'(?:[^'\\\n]|\\.)'")
STRING = re.compile(r'"(?:[^"\\\n]|\\.)*"')
MISSING = re.compile(r'\bfunc_0x([0-9a-f]{8})\b')
OUR_FILE = re.compile(r'[0-9a-f]{8}\.c')

# Where a call with no function behind it points. Bounds match SetupMemory.java.
# ram_packed is code the firmware unpacks at boot: no bytes for it in the backup.
REGIONS = [
    ('sram', 0x81c00000, 0x81d00000),
    ('rom', 0x81e00000, 0x81f00000),
    ('ram', 0x82000000, 0x8201d5e0),
    ('ram_packed', 0x8201d5e0, 0x83000000),
]
SPOT_CHECK = ('sms_apn_handle', 'get_apn_handle', 'set_url_port')


def read_export(path):
    path = pathlib.Path(path)
    if not path.is_dir():
        return path.read_text(errors='replace')
    # Only the build's own files: the folder may hold other C a person put there.
    files = sorted(f for f in path.glob('*.c') if OUR_FILE.fullmatch(f.name))
    return ''.join(f.read_text(errors='replace') for f in files)


def region(address):
    for name, start, end in REGIONS:
        if start <= address < end:
            return name
    return 'other'


def measure(text):
    parts = HEADER.split(text)  # [preamble, name, address, body, name, address, body, ...]
    names = parts[1::3]
    bodies = parts[3::3]
    missing = {int(address, 16) for address in MISSING.findall(text)}
    by_region = {}
    for address in missing:
        by_region[region(address)] = by_region.get(region(address), 0) + 1
    return {
        'functions': len(names),
        'named': sum(not DEFAULT_NAME.match(name) for name in names),
        'string_literals': len(set(STRING.findall(CHAR.sub("''", text)))),
        'unrecovered_returns': sum('UNRECOVERED_JUMPTABLE' in body for body in bodies),
        'decompile_failed': sum('DECOMPILE FAILED' in body for body in bodies),
        'missing_targets': len(missing),
        'missing_by_region': by_region,
        'spot_check_missing': [name for name in SPOT_CHECK if name not in names],
    }


def main():
    if len(sys.argv) != 2:
        sys.exit('usage: metrics.py <export directory or file>')
    result = measure(read_export(sys.argv[1]))
    regions = ', '.join(f'{name} {count}' for name, count in sorted(result['missing_by_region'].items()))
    absent = result['spot_check_missing']
    print(f"functions                          {result['functions']}")
    print(f"named functions                    {result['named']}")
    print(f"distinct string literals           {result['string_literals']}")
    print(f"bodies with UNRECOVERED_JUMPTABLE  {result['unrecovered_returns']}")
    print(f"failed to decompile                {result['decompile_failed']}")
    print(f"call targets with no function      {result['missing_targets']} ({regions})")
    print(f"spot check                         {'missing: ' + ', '.join(absent) if absent else 'ok'}")


if __name__ == '__main__':
    main()
