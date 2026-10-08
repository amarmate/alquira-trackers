// After analysis: fix what the stock analysis gets wrong about this compiler's MIPS16
// output. Safe to run twice: it only touches returns not yet marked and bytes that no
// function covers. The build runs it in both Ghidra runs, because code that run 2's
// re-analysis disassembles needs the same treatment.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.FlowOverride;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.Listing;

public class FixCode extends GhidraScript {
    private Listing listing;

    @Override
    public void run() throws Exception {
        listing = currentProgram.getListing();
        println("V24: jr a3 marked as return: " + markReturns());
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
}
