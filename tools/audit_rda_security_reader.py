"""Offline audit of the exact MIPS32 reader, including MMIO simulation.

The simulator is deliberately limited to this binary's instructions and rejects
unknown opcodes, memory stores, SPI commands, and calls. It is not hardware proof.
"""
import hashlib
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'firmware/live/usb-programmer-build/security-reader-2026-10-10/build'
BASE, RESULT, STOP = 0x81c00280, 0xa1c02000, 0x81e00310


def sha(b):
    return hashlib.sha256(b).hexdigest()


class Machine:
    def __init__(self, binary, security, jedec=0x1660c8, status=0x0200, busy_reads=0):
        self.code = binary
        self.security, self.jedec, self.status = security, jedec, status
        self.regs = [0] + [0x12120000 + n for n in range(1, 32)]
        self.regs[29] = 0xa1c04000
        self.regs[31] = STOP
        self.original = list(self.regs)
        self.mem = {RESULT + n: 0xcc for n in range(564)}
        self.spi = {1: 0x00000100, 5: 0x00000a05}
        self.spi_original = dict(self.spi)
        self.tx, self.commands = [], []
        self.sc, self.original_sc = 1, 1
        self.busy_reads = busy_reads
        self.pc, self.redirect, self.steps = BASE, None, 0
        self.minimum_sp = self.regs[29]

    def read(self, address, size=4):
        if address == 0xa1a01014:
            v, self.sc = self.sc, 0
            return v
        if 0xa7fff000 <= address <= 0xa7fff018:
            index = (address - 0xa7fff000) // 4
            if index == 3:
                if self.busy_reads:
                    self.busy_reads -= 1
                    return 1
                return 0
            return self.spi.get(index, 0)
        return sum(self.mem.get(address + n, 0xcc) << (8 * n) for n in range(size))

    def store(self, address, value, size=4):
        if address == 0xa1a01014:
            self.sc = value
            return
        if 0xa7fff000 <= address <= 0xa7fff018:
            index = (address - 0xa7fff000) // 4
            if index == 2:
                assert 0 <= value <= 255
                self.tx.append(value)
            elif index == 6:
                assert value == 3
                self.tx.clear()
            elif index == 0:
                assert not self.sc
                assert value & ~0xff00 == 0x10000
                cmd, count = (value >> 8) & 255, (self.spi[1] >> 8) & 511
                mode = (self.spi[5] >> 17) & 3
                assert mode == {1: 0, 3: 3, 4: 2}[count]
                if cmd == 0x48:
                    assert len(self.tx) == 4 and self.tx[-1] == 0 and count == 4
                    offset = int.from_bytes(bytes(self.tx[:3]), 'big') - 0x1000
                    assert 0 <= offset <= 252 and offset % 4 == 0
                    raw = self.security[offset:offset + 4]
                else:
                    assert not self.tx
                    offset = None
                    if cmd == 0x9f:
                        assert count == 3
                        raw = self.jedec.to_bytes(3, 'little')
                    elif cmd in (5, 0x35):
                        assert count == 1
                        raw = bytes([(self.status >> (0 if cmd == 5 else 8)) & 255])
                    else:
                        raise AssertionError(f'Forbidden SPI opcode {cmd:#x}')
                self.spi[4] = int.from_bytes(raw, 'little') << ((4 - count) * 8)
                self.commands.append((cmd, offset, count))
            elif index not in (1, 5):
                raise AssertionError(f'Forbidden SPI register store {index}')
            self.spi[index] = value
            return
        assert (RESULT <= address and address + size <= RESULT + 564
                or 0xa1c03e00 <= address and address + size <= 0xa1c04000), hex(address)
        for n in range(size):
            self.mem[address + n] = (value >> (n * 8)) & 255

    def run(self):
        while self.pc != STOP:
            assert BASE <= self.pc < BASE + len(self.code)
            self.steps += 1
            assert self.steps < 15000000
            pc = self.pc
            word = struct.unpack_from('<I', self.code, pc - BASE)[0]
            op, rs, rt, rd, shift, fn = (word >> 26, (word >> 21) & 31,
                                       (word >> 16) & 31, (word >> 11) & 31,
                                       (word >> 6) & 31, word & 63)
            imm = word & 65535
            signed = imm if imm < 32768 else imm - 65536
            old_redirect, self.redirect = self.redirect, None
            r = self.regs
            if op == 0:
                if fn == 0: r[rd] = r[rt] << shift
                elif fn == 2: r[rd] = r[rt] >> shift
                elif fn == 6: r[rd] = r[rt] >> (r[rs] & 31)
                elif fn == 8: self.redirect = r[rs]
                elif fn == 0x21: r[rd] = r[rs] + r[rt]
                elif fn == 0x23: r[rd] = r[rs] - r[rt]
                elif fn == 0x24: r[rd] = r[rs] & r[rt]
                elif fn == 0x25: r[rd] = r[rs] | r[rt]
                elif fn == 0x2b: r[rd] = int(r[rs] < r[rt])
                else: raise AssertionError(f'Unknown SPECIAL {fn:#x} at {pc:#x}')
            elif op in (2, 3):
                self.redirect = ((pc + 4) & 0xf0000000) | ((word & 0x3ffffff) << 2)
                if op == 3: r[31] = pc + 8
            elif op in (4, 5):
                if (r[rs] == r[rt]) == (op == 4):
                    self.redirect = pc + 4 + signed * 4
            elif op == 9: r[rt] = r[rs] + signed
            elif op == 12: r[rt] = r[rs] & imm
            elif op == 13: r[rt] = r[rs] | imm
            elif op == 15: r[rt] = imm << 16
            elif op == 0x23: r[rt] = self.read((r[rs] + signed) & 0xffffffff)
            elif op == 0x24: r[rt] = self.read((r[rs] + signed) & 0xffffffff, 1)
            elif op in (0x28, 0x2b):
                self.store((r[rs] + signed) & 0xffffffff, r[rt], 1 if op == 0x28 else 4)
            else: raise AssertionError(f'Unknown instruction {word:#x} at {pc:#x}')
            self.regs = [v & 0xffffffff for v in r]
            self.regs[0] = 0
            self.minimum_sp = min(self.minimum_sp, self.regs[29])
            self.pc = old_redirect if old_redirect is not None else pc + 4
        assert self.regs[29] == self.original[29]
        assert all(self.regs[n] == self.original[n] for n in range(16, 24))
        assert self.regs[30] == self.original[30]
        assert self.sc == self.original_sc
        assert self.spi[1] == self.spi_original[1] and self.spi[5] == self.spi_original[5]
        return bytes(self.mem[RESULT + n] for n in range(564))


def main():
    binary = (BUILD / 'security_reader.bin').read_bytes()
    elf = (BUILD / 'security_reader.elf').read_bytes()
    assert elf[:7] == b'\x7fELF\x01\x01\x01'
    assert struct.unpack_from('<I', elf, 24)[0] == BASE
    assert 0 < len(binary) < 0x2000 - 0x280 and len(binary) % 4 == 0
    reserved = set(range(11, 16)) | set(range(18, 24)) | {30}
    for offset in range(0, len(binary), 4):
        word = struct.unpack_from('<I', binary, offset)[0]
        op = word >> 26
        rs, rt, rd = (word >> 21) & 31, (word >> 16) & 31, (word >> 11) & 31
        used = ({rs, rt, rd} if op == 0 else {rs, rt}
                if op not in (2, 3) else set())
        assert not used & reserved, (hex(BASE + offset), used & reserved)
    checks = []
    for label, record, jedec, status, error, busy in (
        ('blank', b'\xff' * 256, 0x1660c8, 0x0200, 0, 0),
        ('present', bytes(range(256)), 0x1660c8, 0x021c, 0, 0),
        ('busy-controller', bytes(range(256)), 0x1660c8, 0x0200, 0, 7),
        ('wrong-chip', b'\xff' * 256, 0x123456, 0x0200, 2, 0),
        ('flash-write-enabled', b'\xff' * 256, 0x1660c8, 0x0202, 4, 0),
        ('busy-timeout', b'\xff' * 256, 0x1660c8, 0x0200, 1, 2000000),
    ):
        machine = Machine(binary, record, jedec, status, busy)
        raw = machine.run()
        words = struct.unpack_from('<13I', raw)
        assert words[:4] == (0x53454352, 1, 3 if error else 2, error)
        assert machine.regs[2] == error
        if not error:
            assert words[7:9] == (256, 256)
            assert raw[52:308] == raw[308:564] == record
            reads = [entry for entry in machine.commands if entry[0] == 0x48]
            assert reads == [(0x48, offset, 4) for _ in range(2) for offset in range(0, 256, 4)]
            assert words[5:7] == (status, status)
        else:
            assert not any(entry[0] == 0x48 for entry in machine.commands)
        checks.append(dict(name=label, passed=True, instructions=machine.steps,
                           spi_transactions=len(machine.commands), return_error=error,
                           maximum_stack_bytes=machine.original[29] - machine.minimum_sp))
    audit = dict(payload_sha256=sha(binary), source_sha256=sha(
        (ROOT / 'firmware/logicrom/security_reader.c').read_bytes()),
        elf_sha256=sha(elf), entry=hex(BASE), result=hex(RESULT), result_bytes=564,
        stack='0xa1c04000', reduced_register_binary_check=True,
        stack_max_observed=max(check['maximum_stack_bytes'] for check in checks),
        spi_opcodes=[0x9f, 5, 0x35, 0x48],
        offline_binary_checks_passed=True, hardware_tested=False, checks=checks,
        limitation='MMIO behavior modeled from SDK; hardware behavior still unmeasured')
    (BUILD / 'audit.json').write_text(json.dumps(audit, indent=2) + '\n')
    print(json.dumps(audit, indent=2))


if __name__ == '__main__':
    main()
