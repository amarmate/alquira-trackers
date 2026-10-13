"""Offline audit of the pinned ROM executor with a write-back stack model.

Runs selected MIPS16 USB caller, MIPS32 executor and 40-byte control instructions,
including delay slots. USB parsing and event transport are not CPU-emulated.
The write-back data cache is measured on 412: Cache_Control 0xa1a2b444 read
0x00000000 at 2026-10-10 18:07:40 UTC (Dcache_Inhibit clear). The remaining
model assumptions are a resident dirty caller line and discard-only invalidation.
Never opens USB, changes a payload, or enables a live execution path.
"""
import argparse
import json
from pathlib import Path
import struct

from rda_flash import ROM_SHA, sha

ROOT = Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / 'firmware/live/2026-10-10-logicrom-412-return-recovery-1/rom.bin'
CONTROL_PATH = ROOT / 'firmware/live/usb-programmer-build/rom-probe-2026-10-10/build/return.bin'
CONTROL_SHA = '90813fa73099e76bb82032c6b031e4269a0ae93e3bb6374c1fb69167344916c5'
SNAPSHOT_PATH = ROOT / 'firmware/live/2026-10-10-logicrom-412-cache-control-1/snapshot-before.json'
SNAPSHOT_SHA = 'f79fb4fa78179424acef0b36b0705a93ac13281c544caff00f3dfef6613e880a'
HOST_HEADER = ROOT / 'firmware/live/usb-programmer-build/sdk/soft/platform/chip/boot/include/boot_host.h'
ROM_BASE, EXECUTOR, HELPER = 0x81e00000, 0x81e002d0, 0xa1c01000
CONTEXT, RESULT, PRIVATE_SP = 0xa1c000a0, 0xa1c02000, 0xa1c04000
# Derived from ROM stack top minus Monitor (24), DoMonitoring (4416),
# HostUsbRecv (40), and USB parser (48) frames. Interrupts can add frames.
CALLER_SP, CALLER_RA, CALLER_S0 = 0x81c0ee4c, 0x81e0344b, 0x12120010
CALLBACK_RA = 0x81e03459
PARSER_RETURN, EVENT = 0x81e03673, 0x81e03169
ARGUMENT, VALUE = 0x13579bdf, 0x42505242
EXECUTOR_WORDS = (
    0x27bdffe8, 0xafbf0010, 0xafb00014, 0x3c0aa1c0, 0x8d4a00a8,
    0x3c09a1c0, 0x8d2900a4, 0x11400002, 0x03a08021, 0x0140e821,
    0x3c04a1c0, 0x8c8400ac, 0xbc000002, 0, 0x0120f809, 0,
    0x3c01a1c0, 0xac2200b0, 0x0200e821, 0x8fbf0010, 0x8fb00014,
    0x03e00008, 0x27bd0018,
)
CONTROL_WORDS = (
    0x3c08a1c0, 0x35082000, 0x3c095254, 0x35294e31, 0xad090000,
    0xad040004, 0x3c024250, 0x34425242, 0x03e00008, 0,
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Memory:
    """16-byte lines, cached KSEG0 stores, direct KSEG1 stores; no evictions.

    The model distinguishes writeback from invalidation. It intentionally
    assumes the small caller frame stays dirty until the executor's cache op.
    """
    def __init__(self, write_back):
        self.write_back = write_back
        self.ram, self.lines, self.dirty = {}, {}, set()
        self.discarded = []

    @staticmethod
    def physical(address):
        return address & 0x1fffffff

    def seed(self, address, value):
        address = self.physical(address)
        for n in range(4):
            self.ram[address + n] = value >> (8 * n) & 255

    def access(self, address):
        require(address % 4 == 0, f'Unaligned modeled access {address:#x}')
        require(0x01c00000 <= self.physical(address) <= 0x01c0fffc,
                f'Access outside internal SRAM {address:#x}')
        physical = self.physical(address)
        if self.write_back and address >> 29 == 4:
            base = physical & ~15
            if base not in self.lines:
                self.lines[base] = bytearray(self.ram.get(base + n, 0xcc) for n in range(16))
            return self.lines[base], physical - base, base
        return self.ram, physical, None

    def read(self, address):
        data, index, _ = self.access(address)
        if isinstance(data, dict):
            return sum(data.get(index + n, 0xcc) << (8 * n) for n in range(4))
        return int.from_bytes(data[index:index + 4], 'little')

    def store(self, address, value):
        data, index, base = self.access(address)
        for n in range(4):
            data[index + n] = value >> (8 * n) & 255
        if base is not None:
            self.dirty.add(base)

    def flush(self):
        for base in self.dirty:
            for n, value in enumerate(self.lines[base]):
                self.ram[base + n] = value
        self.dirty.clear()

    def invalidate(self):
        self.discarded.extend(sorted(self.dirty))
        self.lines.clear()
        self.dirty.clear()


def simulate(rom, control, *, write_back, flush_before_invalidate=False,
             context_sp=PRIVATE_SP, direct_callback=False, callback_enabled=True,
             uncached_caller=False, cmd_type=None):
    memory = Memory(write_back)
    caller_sp = CALLER_SP | (0x20000000 if uncached_caller else 0)
    frame_sp = caller_sp - 24
    # Distinct stale SRAM values make loss observable; these are not device data.
    memory.seed(frame_sp + 16, 0xdead0040)
    memory.seed(frame_sp + 20, 0xbad00010)
    if cmd_type is None:
        cmd_type = 0 if direct_callback else 0xff
    context = (cmd_type, HELPER, context_sp, ARGUMENT, 0,
               HELPER if direct_callback and callback_enabled else 0)
    for n, value in enumerate(context):
        memory.seed(CONTEXT + n * 4, value)
    memory.seed(RESULT, 0xcccccccc)
    memory.seed(RESULT + 4, 0xcccccccc)
    for n, stale in ((36, 0xbad00010), (40, 0xbad00011), (44, 0xdead0060)):
        memory.seed(caller_sp + n, stale)
    regs = [0] + [0x12120000 + n for n in range(1, 32)]
    original = list(regs)
    expected_ra = CALLBACK_RA if direct_callback else CALLER_RA
    expected_argument = CONTEXT if direct_callback else ARGUMENT
    regs[29], regs[31] = caller_sp + 48, PARSER_RETURN
    # Execute the real parser prologue and the execution branch, skipping packet
    # parsing. At 0x3466 skip parser continuation to its real return epilogue.
    pc, mode, redirect, steps, trace = 0x81e03218, 'MIPS16', None, 0, []
    condition = 0
    cache_ops = []
    helper_stores = []
    events = []
    helper_returned = False
    executor_state = None
    m16_regs = (16, 17, 2, 3, 4, 5, 6, 7)

    def read(address):
        if ROM_BASE <= address <= ROM_BASE + len(rom) - 4:
            return struct.unpack_from('<I', rom, address - ROM_BASE)[0]
        return memory.read(address)

    while True:
        if pc == 0x81e03220:
            pc = 0x81e03434
        elif pc == 0x81e03466:
            pc = 0x81e035d0
        if pc == EVENT & ~1 and mode == 'MIPS16':
            require(regs[4] in (0xff000004, 0xff000005), 'Unexpected ROM event')
            events.append(hex(regs[4]))
            # Transport is an ABI-preserving stub, without cache evictions. The
            # actual event's 56-byte frame and electrical behavior are not run.
            pc, mode = regs[31] & ~1, 'MIPS16' if regs[31] & 1 else 'MIPS32'
            for register in list(range(2, 16)) + [24, 25]:
                regs[register] = 0xdead0000 + register
            continue
        if HELPER <= pc < HELPER + len(control):
            code, base = control, HELPER
            require(mode == 'MIPS32' and pc % 4 == 0, 'Invalid helper ISA/alignment')
        elif mode == 'MIPS32' and EXECUTOR <= pc < EXECUTOR + 0x5c:
            code, base = rom, ROM_BASE
        elif mode == 'MIPS16' and any(lo <= pc < hi for lo, hi in (
                (0x81e03218, 0x81e03220), (0x81e03434, 0x81e03466),
                (0x81e035d0, 0x81e035dc))):
            code, base = rom, ROM_BASE
        else:
            break
        steps += 1
        require(steps <= 96, 'Unexpected executor/control loop')
        previous, redirect = redirect, None
        size = 2 if mode == 'MIPS16' else 4
        word = struct.unpack_from('<H' if size == 2 else '<I', code, pc - base)[0]
        if size == 2:
            rx = m16_regs[word >> 8 & 7]
            immediate = word & 255
            signed = immediate - 256 if immediate & 128 else immediate
            if word == 0x6500:
                pass
            elif word & 0xff00 == 0x6300:
                regs[29] += signed * 8
            elif word & 0xff00 == 0x6200:
                memory.store(regs[29] + immediate * 4, regs[31])
            elif word & 0xf800 == 0xd000:
                memory.store(regs[29] + immediate * 4, regs[rx])
            elif word & 0xf800 == 0x9000:
                regs[rx] = read(regs[29] + immediate * 4)
            elif word & 0xf800 == 0xb000:
                regs[rx] = read((pc & ~3) + immediate * 4)
            elif word & 0xf800 == 0x9800:
                ry = m16_regs[word >> 5 & 7]
                regs[ry] = read(regs[rx] + (word & 31) * 4)
            elif word & 0xf800 == 0x6800:
                regs[rx] = immediate
            elif word & 0xf800 == 0x7000:
                condition = regs[rx] ^ immediate
            elif word & 0xff00 in (0x6000, 0x6100):
                if (condition != 0) == (word & 0xff00 == 0x6100):
                    pc += 2 + signed * 2
                    continue
            elif word & 0xf800 == 0x2000:
                if regs[rx] == 0:
                    pc += 2 + signed * 2
                    continue
            elif word & 0xf800 == 0x1000:
                immediate = word & 0x7ff
                signed = immediate - 0x800 if immediate & 0x400 else immediate
                pc += 2 + signed * 2
                continue
            elif word & 0xf800 == 0x1800:
                second = struct.unpack_from('<H', code, pc - base + 2)[0]
                target = ((pc + 4) & 0xf0000000) | (
                    ((word & 31) << 21 | (word >> 5 & 31) << 16 | second) << 2)
                target_mode = 'MIPS32' if word & 0x400 else 'MIPS16'
                regs[31], size = (pc + 6) | 1, 4
                redirect = target, target_mode
                trace.append(dict(pc=hex(pc), target=hex(target | (target_mode == 'MIPS16')),
                                  instruction='jalx' if word & 0x400 else 'jal'))
            elif word & 0xf8ff in (0xe800, 0xe840):
                target = regs[rx]
                redirect = target & ~1, 'MIPS16' if target & 1 else 'MIPS32'
                if word & 0x40:
                    regs[31] = (pc + 4) | 1
                trace.append(dict(pc=hex(pc), target=hex(target),
                                  instruction='jalr' if word & 0x40 else 'jr'))
            else:
                raise ValueError(f'Unknown MIPS16 instruction {word:#x} at {pc:#x}')
        else:
            op, rs, rt, rd, fn = word >> 26, word >> 21 & 31, word >> 16 & 31, word >> 11 & 31, word & 63
            immediate = word & 65535
            signed = immediate - 65536 if immediate & 32768 else immediate
            if op == 0 and fn == 0 and word == 0:
                pass
            elif op == 0 and fn == 0x21:
                regs[rd] = regs[rs] + regs[rt]
            elif op == 0 and fn in (8, 9):
                target = regs[rs]
                redirect = target & ~1, 'MIPS16' if target & 1 else 'MIPS32'
                if fn == 9:
                    regs[rd] = pc + 8
                trace.append(dict(pc=hex(pc), target=hex(target), instruction='jalr' if fn == 9 else 'jr'))
            elif op == 4:
                if regs[rs] == regs[rt]:
                    redirect = (pc + 4 + signed * 4, mode)
            elif op == 9:
                regs[rt] = regs[rs] + signed
            elif op == 13:
                regs[rt] = regs[rs] | immediate
            elif op == 15:
                regs[rt] = immediate << 16
            elif op == 0x23:
                regs[rt] = read((regs[rs] + signed) & 0xffffffff)
            elif op == 0x2b:
                address = (regs[rs] + signed) & 0xffffffff
                memory.store(address, regs[rt])
                if base == HELPER:
                    helper_stores.append([hex(address), hex(regs[rt])])
            elif word == 0xbc000002:
                if flush_before_invalidate:
                    memory.flush()
                memory.invalidate()
                cache_ops.append(dict(pc=hex(pc), word=hex(word), modeled_operation='invalidate D-cache'))
            else:
                raise ValueError(f'Unknown MIPS32 instruction {word:#x} at {pc:#x}')
        regs = [value & 0xffffffff for value in regs]
        regs[0] = 0
        next_pc, next_mode = previous if previous is not None else (pc + size, mode)
        if base == HELPER and next_pc == (CALLBACK_RA & ~1 if direct_callback else 0x81e00310):
            helper_returned = True
        if pc == 0x81e00328:
            executor_state = dict(caller_ra_preserved=next_pc | (next_mode == 'MIPS16') == expected_ra,
                                  caller_s0_preserved=regs[16] == CALLER_S0,
                                  caller_sp_preserved=regs[29] == caller_sp)
        pc, mode = next_pc, next_mode
    ran_helper = not direct_callback or callback_enabled
    expected_value = 0 if direct_callback else VALUE
    if ran_helper:
        require(helper_returned and memory.read(RESULT) == 0x52544e31
                and memory.read(RESULT + 4) == expected_argument
                and memory.read(CONTEXT + 16) == expected_value,
                'Helper/result writes differ in model')
        require(helper_stores == [[hex(RESULT), '0x52544e31'], [hex(RESULT + 4), hex(expected_argument)]],
                'Helper touched unexpected memory')
    else:
        require(not helper_returned and not helper_stores and memory.read(RESULT) == 0xcccccccc,
                'Empty callback unexpectedly executed the helper')
    return dict(instructions=steps, helper_executed=ran_helper,
                helper_returned_to_expected_caller=helper_returned,
                entry_path='direct extended callback' if direct_callback else 'ROM executor',
                marker_and_argument_correct=ran_helper, context_return_value=hex(memory.read(CONTEXT + 16)),
                marker_argument=hex(memory.read(RESULT + 4)),
                final_target=hex(pc | (mode == 'MIPS16')), final_mode=mode,
                caller_ra_preserved=pc | (mode == 'MIPS16') == PARSER_RETURN,
                caller_s0_preserved=regs[16] == original[16],
                caller_s1_preserved=regs[17] == original[17],
                caller_sp_preserved=regs[29] == caller_sp + 48,
                executor_return_state=executor_state, modeled_usb_events=events,
                discarded_dirty_lines=[hex(line) for line in memory.discarded],
                cache_operations=cache_ops, control_transfers=trace)


def audit():
    rom, control = ROM_PATH.read_bytes(), CONTROL_PATH.read_bytes()
    require(len(rom) == 0x6000 and sha(rom) == ROM_SHA, 'Pinned ROM differs')
    require(sha(control) == CONTROL_SHA and control == struct.pack('<10I', *CONTROL_WORDS), 'Pinned control differs')
    executor = rom[0x2d0:0x32c]
    require(executor == struct.pack('<23I', *EXECUTOR_WORDS), 'Executor instruction sequence differs')
    # Pin MIPS16 call sites and literals rather than disassembling literal pools.
    expected_blocks = {
        0x3434: '76b4031b5a0c006575b4a09cff750461031fb40000650610',
        0x3458: '70b4011070b4031b5a0c0065',
        0x344c: '72b2609a0323209a40e90065',
    }
    for offset, expected in expected_blocks.items():
        require(rom[offset:offset + len(bytes.fromhex(expected))] == bytes.fromhex(expected),
                f'USB execution/return bytes differ at {ROM_BASE + offset:#x}')
    require(struct.unpack_from('<4I', rom, 0x360c) == (0xff000004, CONTEXT, 0xa1c000b4, 0xff000005),
            'USB event/context literals differ')
    require(struct.unpack_from('<I', rom, 0x3428)[0] == 0x0c5a1b03,
            'Unexpected event call encoding')
    # The chip-specific operation is operand 2, despite generic objdump's
    # "cache 0x0,2(zero)" formatting. FlushAll writes each way, then uses it.
    require(struct.unpack_from('<I', rom, 0x142c)[0] == 0xbc000002,
            'Flush-then-invalidate operation differs')
    require(tuple(struct.unpack_from('<4I', rom, 0x1020)) ==
            (0xbc000003, 0xbc000403, 0xbc000803, 0xbc000c03), 'D-cache writeback sequence differs')
    require(struct.unpack_from('<I', rom, 0x3a0)[0] == 0xbc000002, 'boot_InvalidDCache encoding differs')
    require(struct.unpack_from('<I', rom, 0x35c)[0] == 0x81c0fffc, 'ROM stack top is not cached KSEG0')
    require(rom.find(struct.pack('<I', 0xa1a2b444)) < 0 and rom.find(struct.pack('<I', 0x01a2b444)) < 0,
            'ROM image unexpectedly references Cache_Control')
    require(sha(SNAPSHOT_PATH.read_bytes()) == SNAPSHOT_SHA, 'Cache_Control snapshot differs')
    snapshot = json.loads(SNAPSHOT_PATH.read_text())
    require(snapshot['words']['cache_control'] == 0 and snapshot['decoded']['dcache_inhibit'] is False,
            'Measured Cache_Control on 412 is not all-clear')
    header = HOST_HEADER.read_text()
    ctx_end = header.index('} BOOT_HST_MONITOR_X_CTX_T;')
    ctx_block = header[header.rindex('typedef volatile struct', 0, ctx_end):ctx_end]
    fields = [ctx_block.index(name) for name in ('cmdType', 'pc;', 'sp;', 'param;', 'returnedValue;')]
    require(fields == sorted(fields), 'Monitor context field order differs in boot_host.h')
    executor_end = header.index('} BOOT_HST_EXECUTOR_T;')
    executor_block = header[header.rindex('typedef struct', 0, executor_end):executor_end]
    require(executor_block.index('hstMonitorXCtx;') < executor_block.index('hstMonitorExtendedHandler;'),
            'Extended handler no longer follows the monitor context in boot_host.h')
    require('BOOT_HST_MONITOR_X_EXT_CMD = 0xfc' in header, 'Named extended command differs in boot_host.h')
    usb_source = (ROOT / 'firmware/live/usb-programmer-build/sdk/soft/platform/chip/boot/8955/src/boot_usb_monitor.c').read_text()
    host_source = (ROOT / 'firmware/live/usb-programmer-build/sdk/soft/platform/chip/boot/8955/src/boot_host.c').read_text()
    start = usb_source.index('boot_HostUsbEvent(BOOT_HST_START_CMD_TREATMENT)')
    call = usb_source.index('boot_HstMonitorX();', start)
    end = usb_source.index('boot_HostUsbEvent(BOOT_HST_END_CMD_TREATMENT)', call)
    require('boot_FlushDCache' not in usb_source[start:end], 'USB execute path now flushes before the executor')
    flush = host_source.index('boot_FlushDCache(TRUE)')
    require(host_source.index('boot_HstMonitorX();', flush) > flush,
            'Debug-IRQ path no longer flushes before the executor')
    inner_switch = usb_source.index('switch(boot_HstMonitorXCtx.cmdType)')
    ext_check = usb_source.index('if (boot_HstMonitorExtendedHandler.')
    ext_call = usb_source.index('ExtendedCmdHandler)((VOID*)&boot_HstMonitorXCtx);')
    ext_end = usb_source.index('boot_HostUsbEvent(BOOT_HST_END_CMD_TREATMENT)', ext_call)
    require(inner_switch < ext_check < ext_call < ext_end, 'USB extended-handler arm shape differs')
    arm = usb_source[usb_source.rindex('case BOOT_HST_MONITOR_X_CMD:', 0, inner_switch):ext_end]
    require('boot_FlushDCache' not in arm and 'boot_InvalidDCache' not in arm,
            'Cache operation appeared in the USB execute/extended arm')
    require(arm.index('switch(boot_HstMonitorXCtx.cmdType)') < arm.index('boot_HstMonitorX();'),
            'Extended arm no longer dispatches on the context command')
    cases = []
    for name, kwargs, preserved in (
        ('flat-memory-control', dict(write_back=False), True),
        ('write-back-cached-caller', dict(write_back=True), False),
        ('write-back-caller-with-sp-zero', dict(write_back=True, context_sp=0), False),
        ('write-back-with-live-private-stack', dict(write_back=True, context_sp=0xa1c04000), False),
        ('hypothetical-flush-before-invalidation', dict(write_back=True, flush_before_invalidate=True), True),
        ('hypothetical-uncached-caller', dict(write_back=True, uncached_caller=True), True),
        ('direct-leaf-callback-candidate', dict(write_back=True, direct_callback=True), True),
        ('extended-command-0xfc', dict(write_back=True, direct_callback=True, cmd_type=0xfc), True),
        ('empty-direct-callback-control', dict(write_back=True, direct_callback=True, callback_enabled=False), True),
    ):
        result = simulate(rom, control, **kwargs)
        require(result['caller_ra_preserved'] == preserved and result['caller_s0_preserved'] == preserved,
                f'{name}: unexpected caller-state outcome')
        require(not preserved or result['caller_s1_preserved'], f'{name}: s1 restoration differs')
        require(result['caller_sp_preserved'] == preserved, f'{name}: stack restoration differs')
        require(result['modeled_usb_events'] == (['0xff000004', '0xff000005'] if preserved else ['0xff000004']),
                f'{name}: unexpected event sequence')
        if kwargs.get('direct_callback'):
            require(not result['cache_operations'],
                    f'{name}: unexpected cache operation on the extended/direct path')
            if kwargs.get('callback_enabled', True):
                require(result['marker_argument'] == hex(CONTEXT),
                        f'{name}: helper argument is not the context pointer')
        else:
            require([op['pc'] for op in result['cache_operations']] == ['0x81e00300'],
                    f'{name}: executor cache operation differs')
            require(result['marker_argument'] == hex(ARGUMENT), f'{name}: executor argument differs')
        cases.append(dict(name=name, passed=True, **result))
    inputs = {str(path.relative_to(ROOT)): sha(path.read_bytes()) for path in (
        ROM_PATH, CONTROL_PATH, SNAPSHOT_PATH, HOST_HEADER,
        ROOT / 'firmware/live/usb-programmer-build/sdk/soft/platform/chip/defs/8955_base.def',
        ROOT / 'firmware/live/usb-programmer-build/sdk/soft/platform/chip/boot/8955/src/boot_rom.S',
        ROOT / 'firmware/live/usb-programmer-build/sdk/soft/platform/chip/boot/8955/src/boot_irq_dispatch.c',
        ROOT / 'firmware/live/usb-programmer-build/sdk/soft/platform/chip/boot/8955/src/boot_usb_monitor.c',
        ROOT / 'firmware/live/usb-programmer-build/sdk/soft/platform/chip/boot/8955/src/boot_host.c',
    )}
    return dict(inputs=inputs, executor=hex(EXECUTOR), cache_instruction=hex(0xbc000002),
                cache_operation='boot_InvalidDCache (cache 2,0), not a writeback',
                writeback_operation='0xbc000003 per way, used by boot_FlushDCache',
                rom_stack_top='0x81c0fffc', stack_segment='KSEG0',
                context_segment='KSEG1 0xa1c000a0', helper_segment='KSEG1 0xa1c01000',
                caller_stack_estimate=hex(CALLER_SP), saved_ra_address=hex(CALLER_SP - 8),
                saved_s0_address=hex(CALLER_SP - 4), cases=cases,
                candidate_callback=hex(HELPER), candidate_return=hex(CALLBACK_RA),
                named_extended_command='0xfc',
                extended_handler_pointer='0xa1c000b4',
                extended_handler_argument=hex(CONTEXT),
                extended_handler_return='0x81e03459 (MIPS16)',
                extended_arm_cache_operations='none in source arm or byte-pinned dispatch',
                cache_control_measured='0x00000000 on 412 at 2026-10-10T18:07:40Z; Dcache_Inhibit clear',
                hardware_validated=False, live_requests_sent=0,
                limitations=[
                    'Write-back is measured on 412; a resident dirty line and discard-only invalidation remain model assumptions.',
                    'The executor saves ra eleven instructions before cache 2,0, with no call between them.',
                    'The D-cache inhibit bit is measured clear on 412. The stopped PC, Cause, and saved caller words were not measured.',
                    'The planted stale target is a model seed, not a PC observed on 412.',
                    'USB event bodies are ABI stubs. MIPS16 sites are byte-pinned and executed only on the included paths.',
                    'This identifies a reproducible ROM return hazard, not a proven stopping PC on 412.',
                    'The 0xfc extended arm is source-pinned, byte-pinned and modeled; it has not been sent to the device.',
                ])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = audit()
    output = json.dumps(report, indent=2) + '\n'
    if args.output:
        with args.output.open('x') as stream:
            stream.write(output)
    print(output, end='')
