"""Offline instruction/allowlist audit for the staged returning ROM probes."""
import json
from pathlib import Path
import struct

from rda_flash import sha

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'firmware/live/usb-programmer-build/rom-probe-fc-2026-10-10/build'
ENTRY, RESULT, STACK, RETURN = 0xa1c01000, 0xa1c02000, 0xa1c04000, 0x81e00310
CONTEXT, PARSER_SP, PARSER_RETURN = 0xa1c000a0, 0x81c0ee4c, 0x81e03459
ARGUMENT, RETURN_VALUE = 0x13579bdf, 0x42505242
RETURN_WORDS = (0x3c08a1c0, 0x35082000, 0x3c095254, 0x35294e31,
                0xad090000, 0xad040004, 0x3c024250, 0x34425242,
                0x03e00008, 0)
JEDEC_SHA = 'd58e59d6312d888c1dff2da2708db89460e14fcf0246852e5f296bcfca23ed10'
SECURITY_SHA = '3c89fc6197af76e9cf2fb8f44a029f4d3e6baf19fef6d4df5223cfdeeb685dbb'
SECURITY_RESULT_SIZE = 20 * 4 + 512


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Machine:
    def __init__(self, binary, jedec=0x1660c8, argument=ARGUMENT, busy=0, post_busy=0,
                 extended=False, result_size=64, security=b'\xff' * 256, status=0x0200,
                 security_mode=False):
        self.binary = binary
        self.extended = extended
        self.result_size = result_size
        self.security = security
        self.status_value = status
        self.security_mode = security_mode
        self.tx = []
        self.security_offsets = []
        self.regs = [0] + [0x12120000 + n for n in range(1, 32)]
        self.mem = {RESULT + n: 0xcc for n in range(result_size)}
        if extended:
            # The 0xfc arm calls with a0 = &boot_HstMonitorXCtx on the parser's
            # KSEG0 stack; the argument lives at context word param (0xa1c000ac).
            self.regs[4], self.regs[29], self.regs[31] = CONTEXT, PARSER_SP, PARSER_RETURN
            for n, value in enumerate((0xfc, ENTRY, STACK, argument, 0, ENTRY)):
                for b in range(4):
                    self.mem[CONTEXT + n * 4 + b] = value >> (8 * b) & 255
        else:
            self.regs[4], self.regs[29], self.regs[31] = argument, STACK, RETURN
        self.return_address = PARSER_RETURN if extended else RETURN
        self.expected_sp = PARSER_SP if extended else STACK
        self.original = list(self.regs)
        self.spi = {4: 0x100, 0xc: 0x40a, 0x10: 0, 0x14: 0x8a0, 0x18: 0}
        self.sys = {0x44: 0x1011, 0x48: 0x5f16, 0xac: 2, 0: 0xa50000}
        self.jedec, self.busy, self.post_busy = jedec, busy, post_busy
        self.sc, self.commands, self.events, self.stores = 1, [], [], []
        self.pc, self.redirect, self.steps, self.minimum_sp = ENTRY, None, 0, STACK

    def read(self, address, size=4):
        if address == 0xa1a01014:
            require(size == 4, 'Forbidden SC byte access')
            value, self.sc = self.sc, 0
            return value
        if 0xa7fff000 <= address < 0xa7fff01c:
            require(size == 4, 'Forbidden SPI byte access')
            offset = address - 0xa7fff000
            require(offset in self.spi, 'Forbidden SPI load')
            if offset == 0xc and self.busy:
                self.busy -= 1
                return 1
            return self.spi[offset]
        if 0xa1a00000 <= address < 0xa1a000b0:
            require(size == 4, 'Forbidden sysCtrl byte access')
            require(address - 0xa1a00000 in self.sys, 'Forbidden sysCtrl load')
            return self.sys[address - 0xa1a00000]
        require(size in (1, 4), 'Forbidden load size')
        require(RESULT <= address and address + size <= RESULT + self.result_size
                or STACK - 512 <= address and address + size <= STACK
                or CONTEXT <= address and address + size <= CONTEXT + 24,
                f'Forbidden SRAM load {address:#x}')
        return sum(self.mem.get(address + n, 0xcc) << (8 * n) for n in range(size))

    def store(self, address, value, size=4):
        self.stores.append((address, value))
        if address == 0xa1a01014:
            require(size == 4 and value == 1, 'SC restoration differs')
            self.sc = value
        elif 0xa1a00000 <= address < 0xa1a000b0:
            require(size == 4, 'Forbidden sysCtrl byte store')
            offset = address - 0xa1a00000
            allowed = {0: {0xa50000, 0xa50001}, 0x48: {0x5f16, 0x5b16}, 0xac: {2, 9}}
            require(offset in allowed and value in allowed[offset], 'Forbidden sysCtrl store')
            if offset:
                require(self.sys[0] == 0xa50001, 'Protected clock store while locked')
            self.sys[offset] = value
        elif 0xa7fff000 <= address < 0xa7fff01c:
            require(size == 4, 'Forbidden SPI byte store')
            offset = address - 0xa7fff000
            if self.security_mode:
                if offset == 8:
                    require(0 <= value <= 255, 'Forbidden FIFO value')
                    self.tx.append(value)
                    self.spi[offset] = value
                    return
                allowed = {0: {0x19f00, 0x10500, 0x13500, 0x14800},
                           4: {0x100, 0x300, 0x400},
                           0x14: {0x8a0, 0x291, 0x60291, 0x40291}, 0x18: {3}}
                require(offset in allowed and value in allowed[offset], 'Forbidden SPI store/opcode')
                if offset == 0x18:
                    self.tx.clear()
                if offset == 0:
                    require(self.sc == 0, 'SPI command with IRQ enabled')
                    require(self.events == [0x53500001, 0x53500002], 'Missing pre-command checkpoint')
                    require(self.sys[0x48] == 0x5b16 and self.sys[0xac] == 9,
                            'SPI clock initialization missing')
                    cmd = (value >> 8) & 255
                    count = (self.spi[4] >> 8) & 511
                    mode = (self.spi[0x14] >> 17) & 3
                    require(mode == {1: 0, 3: 3, 4: 2}[count], 'Incorrect security framing')
                    if cmd == 0x48:
                        require(len(self.tx) == 4 and self.tx[-1] == 0 and count == 4,
                                'Incorrect security address phase')
                        offset_addr = int.from_bytes(bytes(self.tx[:3]), 'big') - 0x1000
                        require(0 <= offset_addr <= 252 and offset_addr % 4 == 0,
                                'Security address outside 0x1000-0x10fc')
                        raw = self.security[offset_addr:offset_addr + 4]
                        self.spi[0x10] = int.from_bytes(raw, 'little')
                        self.security_offsets.append(offset_addr)
                    else:
                        require(not self.tx, 'Unexpected FIFO bytes')
                        if cmd == 0x9f:
                            require(count == 3, 'Incorrect JEDEC count')
                            self.spi[0x10] = self.jedec << 8
                        elif cmd in (5, 0x35):
                            require(count == 1, 'Incorrect status count')
                            raw = (self.status_value >> (0 if cmd == 5 else 8)) & 255
                            self.spi[0x10] = raw << 24
                        else:
                            raise ValueError(f'Forbidden SPI opcode {cmd:#x}')
                    self.commands.append(value)
                    self.busy = self.post_busy
                self.spi[offset] = value
                return
            allowed = {0: {0x19f00}, 4: {0x100, 0x300}, 0x14: {0x8a0, 0x291, 0x60291}, 0x18: {3}}
            require(offset in allowed and value in allowed[offset], 'Forbidden SPI store/opcode')
            if offset == 0:
                require(not self.commands and self.sc == 0, 'Repeated command or IRQ enabled')
                require(self.spi[4] == 0x300 and self.spi[0x14] == 0x60291,
                        'Incorrect JEDEC framing')
                require(self.sys[0x48] == 0x5b16 and self.sys[0xac] == 9,
                        'SPI clock initialization missing')
                require(self.events == [0x53500001, 0x53500002], 'Missing pre-command checkpoint')
                self.commands.append(value)
                self.spi[0x10] = self.jedec << 8
                self.busy = self.post_busy
            self.spi[offset] = value
        else:
            require(size in (1, 4), 'Forbidden store size')
            require(RESULT <= address and address + size <= RESULT + self.result_size
                    or STACK - 512 <= address and address + size <= STACK,
                    f'Forbidden SRAM store {address:#x}')
            for n in range(size):
                self.mem[address + n] = (value >> (8 * n)) & 255

    def run(self):
        while self.pc != self.return_address:
            if self.pc == 0x81e03169:
                require(self.regs[4] in (0x53500001, 0x53500002, 0x53500003, 0x53500004),
                        'Forbidden event argument')
                self.events.append(self.regs[4])
                if STACK - 512 <= self.regs[29] <= STACK:
                    self.minimum_sp = min(self.minimum_sp, self.regs[29] - 112)
                self.pc, self.redirect = self.regs[31], None
                # ROM event behavior and ABI are modeled here; its full code is
                # separately reviewed against the pinned ROM, not simulated.
                for register in list(range(2, 16)) + [24, 25]:
                    self.regs[register] = 0xdead0000 + register
                continue
            require(ENTRY <= self.pc < ENTRY + len(self.binary), f'PC outside payload {self.pc:#x}')
            self.steps += 1
            require(self.steps < 4000000, 'Instruction guard exceeded')
            word = struct.unpack_from('<I', self.binary, self.pc - ENTRY)[0]
            op, rs, rt, rd, shift, fn = (word >> 26, (word >> 21) & 31,
                                       (word >> 16) & 31, (word >> 11) & 31,
                                       (word >> 6) & 31, word & 63)
            signed = (word & 65535) - (65536 if word & 32768 else 0)
            old_redirect, self.redirect = self.redirect, None
            r, pc = self.regs, self.pc
            if op == 0:
                if fn == 0: r[rd] = r[rt] << shift
                elif fn == 2: r[rd] = r[rt] >> shift
                elif fn == 6: r[rd] = r[rt] >> (r[rs] & 31)
                elif fn == 8: self.redirect = r[rs]
                elif fn == 0x21: r[rd] = r[rs] + r[rt]
                elif fn == 0x23: r[rd] = r[rs] - r[rt]
                elif fn == 0x24: r[rd] = r[rs] & r[rt]
                elif fn == 0x25: r[rd] = r[rs] | r[rt]
                elif fn == 0x26: r[rd] = r[rs] ^ r[rt]
                elif fn == 0x2b: r[rd] = int(r[rs] < r[rt])
                else: raise ValueError(f'Unknown instruction {word:#x}')
            elif op in (2, 3):
                self.redirect = ((pc + 4) & 0xf0000000) | ((word & 0x3ffffff) << 2)
                if op == 3: r[31] = pc + 8
            elif op in (4, 5):
                if (r[rs] == r[rt]) == (op == 4): self.redirect = pc + 4 + signed * 4
            elif op == 9: r[rt] = r[rs] + signed
            elif op == 12: r[rt] = r[rs] & (word & 65535)
            elif op == 13: r[rt] = r[rs] | (word & 65535)
            elif op == 15: r[rt] = (word & 65535) << 16
            elif op == 0x23: r[rt] = self.read((r[rs] + signed) & 0xffffffff)
            elif op == 0x24: r[rt] = self.read((r[rs] + signed) & 0xffffffff, 1)
            elif op == 0x28: self.store((r[rs] + signed) & 0xffffffff, r[rt] & 255, 1)
            elif op == 0x2b: self.store((r[rs] + signed) & 0xffffffff, r[rt])
            else: raise ValueError(f'Unknown instruction {word:#x}')
            self.regs = [value & 0xffffffff for value in r]
            self.regs[0] = 0
            if STACK - 512 <= self.regs[29] <= STACK:
                self.minimum_sp = min(self.minimum_sp, self.regs[29])
            self.pc = old_redirect if old_redirect is not None else pc + 4
        require(self.regs[29] == self.expected_sp and all(self.regs[n] == self.original[n]
                for n in list(range(16, 24)) + [30]), 'Callee-saved state differs')
        return bytes(self.mem[RESULT + n] for n in range(self.result_size))


def audit():
    return_binary = (BUILD / 'return.bin').read_bytes()
    jedec_binary = (BUILD / 'jedec.bin').read_bytes()
    jedec_fc_binary = (BUILD / 'jedec-fc.bin').read_bytes()
    security_fc_binary = (BUILD / 'security-fc.bin').read_bytes()
    require(return_binary == struct.pack('<10I', *RETURN_WORDS), 'Return probe words differ')
    require(sha(jedec_binary) == JEDEC_SHA, 'Executor-arm JEDEC build does not reproduce the pinned artifact')
    require(sha(security_fc_binary) == SECURITY_SHA, 'Security-fc build differs from pinned artifact')
    cases = []
    control = Machine(return_binary)
    result = control.run()
    require(result[:8] == struct.pack('<2I', 0x52544e31, ARGUMENT), 'Return marker differs')
    require(control.regs[2] == RETURN_VALUE and not control.commands and not control.events,
            'Return control behavior differs')
    require(control.stores == [(RESULT, 0x52544e31), (RESULT + 4, ARGUMENT)],
            'Return control performs more than two SRAM stores')
    cases.append(dict(name='return', passed=True, instructions=control.steps, bytes=len(return_binary)))
    reserved = set(range(11, 16)) | set(range(18, 24)) | {30}
    for label, binary in (('jedec', jedec_binary), ('jedec-fc', jedec_fc_binary),
                          ('security-fc', security_fc_binary)):
        for offset in range(0, len(binary), 4):
            word = struct.unpack_from('<I', binary, offset)[0]
            op = word >> 26
            registers = {(word >> 21) & 31, (word >> 16) & 31}
            if op == 0: registers.add((word >> 11) & 31)
            if op in (2, 3): registers = set()
            require(not registers & reserved, f'Reserved register in {label} at {ENTRY + offset:#x}')
    scenarios = (
        ('jedec-success', {}, 0, 1), ('wrong-jedec', {'jedec': 0x123456}, 7, 1),
        ('wrong-argument', {'argument': 0}, 1, 0),
        ('temporary-busy', {'busy': 7}, 0, 1),
        ('busy-before-command', {'busy': 100000}, 2, 0),
        ('busy-after-command', {'post_busy': 100000}, 6, 1),
    )
    for name, kwargs, error, command_count in scenarios:
        model = Machine(jedec_binary, **kwargs)
        result = struct.unpack('<16I', model.run())
        require(result[:4] == (0x4a454443, 1, 4, error), f'{name}: result differs')
        require(model.regs[2] == error and len(model.commands) == command_count, f'{name}: return differs')
        require(result[6:10] == result[10:14], f'{name}: register restoration differs')
        require(model.sc == 1 and model.sys[0] == 0xa50000, f'{name}: lock/IRQ differs')
        cases.append(dict(name=name, passed=True, instructions=model.steps,
                          events=[hex(value) for value in model.events],
                          commands=command_count, maximum_stack_bytes=STACK - model.minimum_sp))
    for name, kwargs, error, command_count in scenarios:
        model = Machine(jedec_fc_binary, extended=True, **kwargs)
        result = struct.unpack('<16I', model.run())
        require(result[:4] == (0x4a454443, 1, 4, error), f'fc-{name}: result differs')
        require(model.regs[2] == error and len(model.commands) == command_count, f'fc-{name}: return differs')
        require(result[6:10] == result[10:14], f'fc-{name}: register restoration differs')
        require(model.sc == 1 and model.sys[0] == 0xa50000, f'fc-{name}: lock/IRQ differs')
        require(not any(PARSER_SP - 4096 <= address < PARSER_SP + 64 for address, _ in model.stores),
                f'fc-{name}: store reached the parser stack')
        cases.append(dict(name='fc-' + name, passed=True, arm='0xfc extended', instructions=model.steps,
                          events=[hex(value) for value in model.events],
                          commands=command_count, maximum_stack_bytes=STACK - model.minimum_sp,
                          entry_stack=hex(PARSER_SP), stack_restored=True))
    blank, present = b'\xff' * 256, bytes(range(256))
    security_scenarios = (
        ('security-blank', dict(security=blank), 0, 133),
        ('security-present', dict(security=present, status=0x021c), 0, 133),
        ('security-temporary-busy', dict(security=present, busy=7), 0, 133),
        ('security-wrong-argument', dict(argument=0), 1, 0),
        ('security-wrong-jedec', dict(jedec=0x123456), 4, 1),
        ('security-wel-set', dict(status=0x0202), 6, 3),
        ('security-busy-before-command', dict(busy=100000), 2, 0),
        ('security-busy-during-read', dict(post_busy=100000), 3, 1),
    )
    for name, kwargs, error, command_count in security_scenarios:
        model = Machine(security_fc_binary, extended=True, result_size=SECURITY_RESULT_SIZE,
                        security_mode=True, **kwargs)
        raw = model.run()
        result = struct.unpack('<20I', raw[:80])
        first, second = raw[80:336], raw[336:592]
        require(result[:4] == (0x53454352, 2, 4, error), f'fc-{name}: result differs')
        require(model.regs[2] == error and len(model.commands) == command_count, f'fc-{name}: return differs')
        require(result[12:16] == result[16:20], f'fc-{name}: register restoration differs')
        require(model.sc == 1 and model.sys[0] == 0xa50000, f'fc-{name}: lock/IRQ differs')
        require(not any(PARSER_SP - 4096 <= address < PARSER_SP + 64 for address, _ in model.stores),
                f'fc-{name}: store reached the parser stack')
        if not error:
            expected = kwargs.get('security', blank)
            require(result[4] == 0x1660c8 and result[5] == result[6] == kwargs.get('status', 0x0200),
                    f'fc-{name}: jedec/status differs')
            require(result[7:9] == (256, 256) and result[10] == 133, f'fc-{name}: counts differs')
            require(first == second == expected, f'fc-{name}: security data differs')
            require(model.security_offsets == [offset for _ in range(2) for offset in range(0, 256, 4)],
                    f'fc-{name}: security addresses differs')
        else:
            require(not model.security_offsets or error == 7, f'fc-{name}: unexpected security reads')
        cases.append(dict(name='fc-' + name, passed=True, arm='0xfc extended', instructions=model.steps,
                          events=[hex(value) for value in model.events],
                          commands=command_count, maximum_stack_bytes=STACK - model.minimum_sp,
                          entry_stack=hex(PARSER_SP), stack_restored=True,
                          security_bytes=len(first) + len(second)))
    sources = {name: sha((ROOT / 'firmware/logicrom' / name).read_bytes()) for name in
               ('rom_return_probe.S', 'rom_jedec_entry.S', 'rom_jedec_probe.c',
                'rom_security_entry.S', 'rom_security_probe.c', 'rom_probe.ld', 'build_rom_probe.sh')}
    report = dict(entry=hex(ENTRY), result=hex(RESULT), stack=hex(STACK), argument=hex(ARGUMENT),
                  return_sha256=sha(return_binary), jedec_sha256=sha(jedec_binary),
                  jedec_fc_sha256=sha(jedec_fc_binary), security_fc_sha256=sha(security_fc_binary),
                  result_bytes=64, security_result_bytes=SECURITY_RESULT_SIZE,
                  extended_arm=dict(context=hex(CONTEXT), parser_stack=hex(PARSER_SP),
                                    parser_return=hex(PARSER_RETURN),
                                    argument_source='boot_HstMonitorXCtx.param at 0xa1c000ac',
                                    note='The 0xfc arm does not switch sp; the entry stub switches to the private stack.'),
                  sources=sources, cases=cases, reduced_register_check=True,
                  hardware_validated=False,
                  limitations=['SPI MMIO/clock responses modeled; a stalled bus access is not bounded.',
                               'ROM USB event implementation reviewed, modeled as an ABI-preserving call.',
                               'The jedec-fc entry/stack behavior is modeled; only the return and JEDEC controls are hardware-validated.',
                               'The security-fc helper is modeled only; its license bytes are unmeasured.'])
    (BUILD / 'audit.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    print(json.dumps(audit(), indent=2))
