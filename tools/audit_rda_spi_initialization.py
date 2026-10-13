"""Compare the failed 412 readers with the pinned programmer, entirely offline.

Reads saved evidence and ELF/LOD files only; never imports USB or operates a
device. A passing report verifies the comparison, not a hardware correction.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from audit_rda_security_reader import Machine
from rda_lod_audit import audit as audit_lod

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / 'firmware/live'
PROGRAMMER = LIVE / 'usb-programmer-build/clean/artifacts'
ROM_ELF = LIVE / ('usb-programmer-build/clean/sdk/soft/platform/chip/rom/'
                  '8955/lib/mem_bridge_rom_CHIP.elf')
RECOVERY = LIVE / '2026-10-10-logicrom-412-security-recovered-1'
HELPER = LIVE / 'usb-programmer-build/security-reader-2026-10-10/build/security_reader.bin'
PINNED = {
    PROGRAMMER / 'usb_8955_flsh_spi32m_ramrun_noclk_200ma.elf':
        '0f81ea0fcd763333d49da4794de981265ef6bac2c3a68597ef8da4638ada13a2',
    PROGRAMMER / 'usb_8955_flsh_spi32m_ramrun_noclk_200ma.lod':
        'c238911dc478363b1dffdebbffcc407e6e1b1b51ef5c53c9d90ca2fe8bff6c65',
    ROM_ELF: '9d91a6ebb1af6533413101b6a7da37289fb04d50d3d97a3d91e992357e767483',
    RECOVERY / 'rom.bin':
        '3946ea195270620f0907997f96f32fbaa1e2ab405146235fef2afb5f3c4680d7',
    RECOVERY / 'controller.bin':
        '6e2d3a1a7537529a2b02e5e35cac97b92b94518ec6122c28972c3f7d55934af5',
    HELPER: '444591d19fafc0db085cee0f568897af7d4a1b23afa63b12b37d2a358df12a1f',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Elf:
    def __init__(self, data):
        require(data[:7] == b'\x7fELF\x01\x01\x01', 'Expected ELF32 little endian')
        header = struct.unpack_from('<16sHHIIIIIHHHHHH', data)
        require(header[2] == 8 and header[11] == 40, 'Expected MIPS section table')
        self.sections = []
        for number in range(header[12]):
            section = struct.unpack_from('<10I', data, header[6] + number * 40)
            if section[1] == 1 and section[2] & 2:  # allocated PROGBITS only
                contents = data[section[4]:section[4] + section[5]]
                require(len(contents) == section[5], 'Truncated ELF section')
                self.sections.append((section[3], contents))

    def read(self, address, count):
        for base, contents in self.sections:
            offset = address - base
            if 0 <= offset and offset + count <= len(contents):
                return contents[offset:offset + count]
        raise ValueError(f'Address absent from ELF: {address:#x}+{count:#x}')

    def physical_word(self, address):
        matches = []
        for base, contents in self.sections:
            offset = address - (base & 0x1fffffff)
            if 0 <= offset and offset + 4 <= len(contents):
                matches.append(contents[offset:offset + 4])
        require(len(matches) == 1, f'Ambiguous/missing ELF word: {address:#x}')
        return struct.unpack('<I', matches[0])[0]


def decode_config(value):
    return dict(raw=hex(value), quad_array_read=bool(value & 1),
                write_protect_pin=bool(value & 2), hold_pin=bool(value & 4),
                sample_delay=(value >> 4) & 7,
                bypass_start_command=bool(value & 0x80),
                divider=(value >> 8) & 255,
                quad_command=bool(value & 0x10000),
                receive_size_mode=(value >> 17) & 3)


def trace_short_memcpy(rom, destination, source, contents):
    """Execute the pinned ROM's actual short-copy MIPS32 path, including slots.

    Records CPU access widths. Does not model the SPI bus's reaction to them.
    The instruction subset deliberately rejects anything outside this path.
    """
    require(0 < len(contents) < 16, 'Only the ROM short-copy path is modeled')
    registers = [0] * 32
    registers[4:7] = [destination, source, len(contents)]
    registers[29], registers[31] = 0xa1c08000, 0x12345678
    memory = {source + n: byte for n, byte in enumerate(contents)}
    reads, writes = [], []
    pc, redirect, steps = 0x81e03b10, None, 0
    while pc != 0x12345678:
        steps += 1
        require(steps < 200, 'ROM memcpy did not return')
        instruction = struct.unpack_from('<I', rom, pc - 0x81e00000)[0]
        op = instruction >> 26
        rs, rt, rd = (instruction >> 21) & 31, (instruction >> 16) & 31, (instruction >> 11) & 31
        immediate = instruction & 65535
        signed = immediate if immediate < 32768 else immediate - 65536
        next_redirect, redirect = redirect, None
        r = registers
        if op == 0:
            fn = instruction & 63
            if fn == 0:
                r[rd] = r[rt] << ((instruction >> 6) & 31)
            elif fn == 8:
                redirect = r[rs]
            elif fn == 0x21:
                r[rd] = r[rs] + r[rt]
            else:
                raise ValueError(f'Unmodeled memcpy instruction {instruction:#x}')
        elif op in (4, 5):
            if (r[rs] == r[rt]) == (op == 4):
                redirect = pc + 4 + signed * 4
        elif op == 9:
            r[rt] = r[rs] + signed
        elif op == 11:
            r[rt] = int(r[rs] < (signed & 0xffffffff))
        elif op in (0x23, 0x24):
            address, size = (r[rs] + signed) & 0xffffffff, 4 if op == 0x23 else 1
            require(all(address + n in memory for n in range(size)), 'Unmapped memcpy load')
            r[rt] = sum(memory[address + n] << (8 * n) for n in range(size))
            if source <= address < source + len(contents):
                reads.append(dict(address=hex(address), bytes=size, instruction=hex(pc)))
        elif op in (0x28, 0x2b):
            address, size = (r[rs] + signed) & 0xffffffff, 1 if op == 0x28 else 4
            require(destination <= address and address + size <= destination + len(contents)
                    or 0xa1c07f00 <= address and address + size <= 0xa1c08004,
                    'Unexpected memcpy store destination')
            for n in range(size):
                memory[address + n] = (r[rt] >> (8 * n)) & 255
            if destination <= address < destination + len(contents):
                writes.append(dict(address=hex(address), bytes=size,
                                   value=hex(r[rt] & ((1 << (size * 8)) - 1)), instruction=hex(pc)))
        else:
            raise ValueError(f'Unmodeled memcpy instruction {instruction:#x}')
        registers = [value & 0xffffffff for value in r]
        registers[0] = 0
        pc = next_redirect if next_redirect is not None else pc + 4
    require(bytes(memory[destination + n] for n in range(len(contents))) == contents,
            'ROM copy content differs')
    require(registers[2] == destination and registers[29] == 0xa1c08000,
            'ROM copy return state differs')
    return dict(instructions=steps, reads=reads, writes=writes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, help='Create a new JSON file; never overwrite')
    args = parser.parse_args()
    evidence = {}
    for path, expected in PINNED.items():
        data = path.read_bytes()
        require(hashlib.sha256(data).hexdigest() == expected, f'Pinned evidence differs: {path}')
        evidence[str(path.relative_to(ROOT))] = expected
    elf_path = PROGRAMMER / 'usb_8955_flsh_spi32m_ramrun_noclk_200ma.elf'
    lod_path = PROGRAMMER / 'usb_8955_flsh_spi32m_ramrun_noclk_200ma.lod'
    programmer, rom_elf = Elf(elf_path.read_bytes()), Elf(ROM_ELF.read_bytes())
    rom = (RECOVERY / 'rom.bin').read_bytes()
    checks = []
    compared = 0
    for address, data in rom_elf.sections:
        require(0x81e00000 <= address and address + len(data) <= 0x81e06000, 'Unexpected ROM section')
        require(rom[address - 0x81e00000:address - 0x81e00000 + len(data)] == data,
                'SDK ROM section differs from measured ROM')
        compared += len(data)
    checks.append(dict(name='SDK ROM allocated bytes equal measured ROM', bytes=compared))
    lod = audit_lod(lod_path)
    address, words = None, 0
    for line in lod_path.read_text().splitlines():
        line = line.strip()
        if line.startswith('@'):
            address = int(line[1:], 16)
        elif line and not line.startswith('#'):
            require(programmer.physical_word(address) == int(line, 16), 'LOD/ELF word mismatch')
            address += 4
            words += 1
    require(words * 4 == lod['payload_bytes'], 'LOD word count differs')
    checks.append(dict(name='Entire pinned LOD equals allocated ELF bytes', words=words))

    # These anchors are from the compiled instructions, not just source macros.
    anchors = (
        (0x81c038a0, '2fb3fa632fb2096f0b620ad109d0006da0f0ecdb80f2084fe5da',
         'SPI open stores 9 at sysCtrl+ac, then 0x291 at spiFlash+14'),
        (0x81c0395c, '0000a0a100f0ffa7', 'SPI open base-address literals'),
        (0x81c038ba, 'c567031a5a0c666c006dc567031a5a0c996c031a3705646c006dc5679f6c031af70c036f',
         'SPI open resets 66/99, waits 100 microseconds and reads JEDEC'),
        (0x81c016a4, 'a0a1063c4800c0ac', 'PLL setup stores zero to Sel_Clock'),
        (0x81c00f7a, '031e900560da', 'boot memory init calls PLL setup'),
        (0x81c00fd0, '14b200f2106b031a130460da031aa8168267',
         'boot memory init writes legacy controller setup and calls memd_FlashOpen'),
        (0x81c01020, '1450a2a1', 'legacy controller address is a1a25014'),
        (0x81c05aa6, '031a280e0467', 'memd_FlashOpen calls SPI open before main'),
        (0x81c033f4, '27b2036fe6da', 'receive routine clears FIFOs with a word store'),
        (0x81c03454, 'ff6801480dea403240db', 'receive routine constructs and word-stores single-line command'),
        (0x81c03490, '00f0ffa7ff00feff000002000000040000000600fffff9ff',
         'receive routine base, block mask and receive-mode constants'),
    )
    for address, contents, name in anchors:
        require(programmer.read(address, len(bytes.fromhex(contents))) == bytes.fromhex(contents), name)
        checks.append(dict(name=name, address=hex(address)))
    require(rom[0x34a4:0x34ac] == bytes.fromhex('031fc40e8399c4a9'), 'ROM normal write memcpy call differs')
    require(rom[0x30ba:0x30be] == bytes.fromhex('031fc40e'), 'ROM read reply memcpy call differs')
    checks.append(dict(name='ROM reads and ordinary writes both call memcpy'))

    write_trace = trace_short_memcpy(rom, 0xa7fff000, 0xa1c09000, struct.pack('<I', 0x19f00))
    read_trace = trace_short_memcpy(rom, 0xa1c09000, 0xa7fff00c, struct.pack('<I', 0x40a))
    require([item['bytes'] for item in write_trace['writes']] == [1] * 4, 'Expected byte stores')
    require([item['bytes'] for item in read_trace['reads']] == [1] * 4, 'Expected byte loads')
    checks.append(dict(name='Actual ROM four-byte memcpy uses four byte accesses',
                       write_trace=write_trace, read_trace=read_trace))

    controller = struct.unpack('<14I', (RECOVERY / 'controller.bin').read_bytes())
    require(controller[1] == 0x100 and controller[5] == 0x8a0 and not controller[3] & 1,
            'Recovered controller differs')
    # Demonstrate the old simulator's limitation without modifying its manifest.
    model_results = []
    for config in (0x8a0, 0x291):
        machine = Machine(HELPER.read_bytes(), b'\xff' * 256)
        machine.spi[5] = config
        machine.spi_original[5] = config
        result = machine.run()
        require(struct.unpack_from('<4I', result) == (0x53454352, 1, 2, 0), 'Old model result differs')
        model_results.append(dict(config=hex(config), simulated_success=True,
                                  transactions=len(machine.commands), restored=machine.spi[5] == config))
    checks.append(dict(name='Old helper model accepts both configs; it cannot validate initialization',
                       results=model_results))
    report = dict(
        scope='OFFLINE COMPARISON ONLY; no device access', checks_passed=len(checks), checks=checks,
        evidence=evidence, rom_config=decode_config(controller[5]),
        programmer_config=decode_config(0x291),
        programmer_spi_clock=dict(selector_address='0xa1a000ac', selector=9,
                                  fast_source_hz=156000000, divider=2, nominal_spi_hz=78000000,
                                  source_select_address='0xa1a00048', slow_select_bit=10,
                                  boot_PLL_setup_writes=0),
        measured_rom_clock_registers=None,
        hardware_fix_validated=False, license_state='unmeasured',
        limitations=[
            'Bus byte-enable/command-latching behavior is unmeasured; memcpy trace is CPU behavior only.',
            'The RAM helper uses word stores but omits SPI source/config startup; stopping PC is unknown.',
            'Working startup also resets the flash and may write nonvolatile QE; copying it is not read-only.',
            'Finite CPU loops cannot bound a stalled MMIO bus access.',
        ],
        next_measurement=dict(operations='handshake and fixed memory reads only',
                              registers=['0xa1a00004', '0xa1a00038', '0xa1a0003c',
                                         '0xa1a00044', '0xa1a00048', '0xa1a000ac',
                                         '0xa7fff000..0xa7fff004', '0xa7fff00c..0xa7fff034',
                                         '0xa1c001d8'],
                              note='Inspect live SPI clock/reset and ROM USB-context ownership before another command probe.'),
    )
    output = json.dumps(report, indent=2) + '\n'
    if args.report:
        with args.report.open('x') as file:
            file.write(output)
    print(output, end='')


if __name__ == '__main__':
    main()
