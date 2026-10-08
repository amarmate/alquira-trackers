// After analysis: fix what the stock analysis gets wrong about this compiler's MIPS16
// output. Safe to run twice: it only touches returns not yet marked and bytes that no
// function covers. The build runs it in both Ghidra runs, because code that run 2's
// re-analysis disassembles needs the same treatment.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressOutOfBoundsException;
import ghidra.program.model.address.AddressRange;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.address.AddressIterator;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.FlowOverride;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryAccessException;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.RefType;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceManager;
import java.math.BigInteger;

public class FixCode extends GhidraScript {
    private Memory mem;
    private Listing listing;
    private FunctionManager functions;
    private int blockedByData;

    @Override
    public void run() throws Exception {
        mem = currentProgram.getMemory();
        listing = currentProgram.getListing();
        functions = currentProgram.getFunctionManager();

        int before = functions.getFunctionCount();
        int fromCalls = functionsAtCallTargets();
        int fromPointers = functionsAtCodePointers();
        int fromPrologues = functionsAtPrologues();
        int fromLooseCode = functionsAtUncoveredCode();
        // Last, so the code just disassembled is covered too.
        int returns = markReturns();

        println("V24: functions before " + before + ", created at call targets " + fromCalls
                + ", at code pointers " + fromPointers + ", at uncovered prologues " + fromPrologues
                + ", at code outside any function " + fromLooseCode);
        println("V24: function starts skipped because data is defined there: " + blockedByData);
        println("V24: jr a3 marked as return: " + returns);
        println("V24: instruction bytes outside any function: " + uncoveredCode().getNumAddresses());
        println("V24: FixCode done");
    }

    // The epilogue reloads the return address into a3 and ends with `jr a3`
    // (bytes 00 ef). Ghidra only treats `jr ra` as a return, so without this every
    // such function ends in an "unrecovered jump table".
    private int markReturns() throws Exception {
        int marked = 0;
        for (Instruction instruction : listing.getInstructions(true)) {
            monitor.checkCancelled();
            if (instruction.getLength() != 2 || instruction.getFlowOverride() == FlowOverride.RETURN) continue;
            byte[] bytes = instruction.getBytes();
            if (bytes[0] == 0x00 && (bytes[1] & 0xff) == 0xef && instruction.getMnemonicString().equals("jr")) {
                instruction.setFlowOverride(FlowOverride.RETURN);
                marked++;
            }
        }
        return marked;
    }

    // A call target that never became code: Ghidra defined data there first, because
    // the boot loader also writes to that address when it copies the section.
    private int functionsAtCallTargets() throws Exception {
        int made = 0;
        Register isaMode = currentProgram.getProgramContext().getRegister("ISA_MODE");
        ReferenceManager references = currentProgram.getReferenceManager();
        for (MemoryBlock block : mem.getBlocks()) {
            if (!isCodeBlock(block)) continue;
            AddressIterator targets = references.getReferenceDestinationIterator(
                    new AddressSet(block.getStart(), block.getEnd()), true);
            while (targets.hasNext()) {
                monitor.checkCancelled();
                Address target = targets.next();
                if (listing.getInstructionContaining(target) != null) continue;
                for (Reference reference : references.getReferencesTo(target)) {
                    Instruction caller = listing.getInstructionAt(reference.getFromAddress());
                    if (caller == null || reference.getReferenceType() != RefType.UNCONDITIONAL_CALL) continue;
                    // jal keeps the caller's instruction set, jalx switches it.
                    BigInteger mode = currentProgram.getProgramContext().getValue(isaMode, caller.getAddress(), false);
                    boolean callerMips16 = mode != null && mode.testBit(0);
                    if (create(target, callerMips16 != caller.getMnemonicString().equals("jalx"))) made++;
                    break;
                }
            }
        }
        return made;
    }

    // Handlers are reached through tables of pointers, which the analysis does not
    // follow. A MIPS16 code pointer has bit 0 set and functions are 4-aligned, so a
    // table entry ends in binary 01. The prologue check keeps out pointers to odd
    // addresses inside strings.
    private int functionsAtCodePointers() throws Exception {
        int made = 0;
        for (MemoryBlock block : mem.getBlocks()) {
            if (!block.isInitialized()) continue;
            byte[] bytes = new byte[(int) block.getSize()];
            block.getBytes(block.getStart(), bytes);
            for (int offset = 0; offset + 4 <= bytes.length; offset += 4) {
                monitor.checkCancelled();
                long word = (bytes[offset] & 0xffL) | (bytes[offset + 1] & 0xffL) << 8
                        | (bytes[offset + 2] & 0xffL) << 16 | (bytes[offset + 3] & 0xffL) << 24;
                if ((word & 3) != 1) continue;
                Address target = toAddr(word - 1);
                if (!isCodeBlock(mem.getBlock(target)) || !mips16Prologue(target)) continue;
                // A word inside an instruction is code that happens to look like a pointer.
                if (listing.getInstructionContaining(block.getStart().add(offset)) != null) continue;
                if (create(target, true)) made++;
            }
        }
        return made;
    }

    // Bytes that are not code yet: look for the non-leaf frame idiom itself.
    private int functionsAtPrologues() throws Exception {
        int made = 0;
        for (MemoryBlock block : mem.getBlocks()) {
            if (!isCodeBlock(block)) continue;
            Address last = block.getEnd().subtract(20);
            for (Address a = block.getStart(); a.compareTo(last) < 0; a = a.add(4)) {
                monitor.checkCancelled();
                if (mips16Prologue(a) && create(a, true)) made++;
            }
        }
        return made;
    }

    // Code that Ghidra disassembled but left outside every function never reaches the
    // export. If nothing falls or jumps into such a run, it is a function of its own:
    // one reached through a pointer the analysis could not follow, or dead code.
    // (Jump tables would break this rule by leaving case blocks unreferenced, but
    // this compiler's output has none left unrecovered once the returns are fixed.)
    private int functionsAtUncoveredCode() throws Exception {
        int made = 0;
        for (AddressRange run : uncoveredCode()) {
            monitor.checkCancelled();
            Address start = run.getMinAddress();
            if (listing.getInstructionAt(start) == null || onlyNops(run)) continue;
            Instruction before = listing.getInstructionBefore(start);
            if (before != null && start.equals(before.getFallThrough())) continue;
            boolean jumpedTo = false;
            for (Reference reference : currentProgram.getReferenceManager().getReferencesTo(start)) {
                jumpedTo |= reference.getReferenceType().isJump();
            }
            if (!jumpedTo && createFunction(start, null) != null) made++;
        }
        return made;
    }

    // Alignment padding between functions is disassembled as nops.
    private boolean onlyNops(AddressRange run) {
        for (Instruction instruction : listing.getInstructions(new AddressSet(run), true)) {
            if (!instruction.getMnemonicString().equals("nop")) return false;
        }
        return true;
    }

    private static boolean isCodeBlock(MemoryBlock block) {
        return block != null && block.isInitialized() && block.isExecute();
    }

    // The whole frame idiom of a non-leaf function: `addiu sp,-N` (0x63 with a negative
    // immediate), `sw ra,M(sp)` (0x62xx) within eight instructions, and further on the
    // matching epilogue, `jr a3` with `addiu sp,+N` in its delay slot. Measured on the
    // image: prologue and `sw ra` alone match 8 places in the string tables, the full
    // idiom matches none there and keeps 98.5% of the matches in code. Leaf functions
    // do not match and are left to the call-reference analysis.
    private boolean mips16Prologue(Address a) {
        try {
            int first = mem.getShort(a) & 0xffff;
            if ((first & 0xff80) != 0x6380) return false;
            boolean savesRa = false;
            for (int k = 1; k <= 8 && !savesRa; k++) {
                savesRa = (mem.getShort(a.add(2 * k)) & 0xff00) == 0x6200;
            }
            if (!savesRa) return false;
            int release = 0x6300 | (0x100 - (first & 0xff));
            for (int k = 2; k < 4096; k++) {
                if ((mem.getShort(a.add(2 * k)) & 0xffff) == 0xef00
                        && (mem.getShort(a.add(2 * k + 2)) & 0xffff) == release) {
                    return true;
                }
            }
            return false;
        } catch (MemoryAccessException | AddressOutOfBoundsException e) {
            return false;
        }
    }

    private boolean create(Address entry, boolean mips16) throws Exception {
        if (functions.getFunctionContaining(entry) != null) return false;
        if (listing.getInstructionAt(entry) == null) {
            if (listing.getInstructionContaining(entry) != null) return false;
            Data data = listing.getDefinedDataContaining(entry);
            if (data != null) {
                // Ghidra types four code bytes that look like an address as a pointer, and
                // defines a word wherever the boot copy loop writes. Those are cleared.
                // A string or a table is longer than a word and stays.
                if (data.getLength() > 4 || !data.getAddress().equals(entry)) {
                    blockedByData++;
                    return false;
                }
                clearListing(data.getAddress(), data.getMaxAddress());
            }
            // Ghidra decodes MIPS32 unless told otherwise.
            Register isaMode = currentProgram.getProgramContext().getRegister("ISA_MODE");
            currentProgram.getProgramContext().setValue(isaMode, entry, entry,
                    mips16 ? BigInteger.ONE : BigInteger.ZERO);
            if (!disassemble(entry)) return false;
        }
        return createFunction(entry, null) != null;
    }

    private AddressSet uncoveredCode() throws Exception {
        AddressSet code = new AddressSet();
        for (Instruction instruction : listing.getInstructions(true)) {
            code.add(instruction.getMinAddress(), instruction.getMaxAddress());
        }
        AddressSet covered = new AddressSet();
        for (Function f : functions.getFunctions(true)) {
            covered.add(f.getBody());
        }
        return code.subtract(covered);
    }
}
