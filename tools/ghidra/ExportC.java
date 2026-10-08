// Decompile every function: one C file per 64 KiB of address space, plus index.tsv,
// which is how a function is found by name.
// Why 64 KiB: one 9 MB file is unusable in an editor, and module boundaries are not
// known yet, so the split follows addresses and promises nothing more.
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Listing;
import java.io.File;
import java.io.FileWriter;
import java.io.PrintWriter;

public class ExportC extends GhidraScript {
    @Override
    public void run() throws Exception {
        File dir = new File(getScriptArgs()[0]);
        Listing listing = currentProgram.getListing();
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        int exported = 0, failed = 0, withoutCode = 0;
        String file = null;
        PrintWriter c = null;
        try (PrintWriter index = new PrintWriter(new FileWriter(new File(dir, "index.tsv")))) {
            index.println("address\tname\tname_source\tsize\tfile\tcallers");
            // Address order, so each C file is opened once.
            for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
                monitor.checkCancelled();
                String row = f.getEntryPoint() + "\t" + f.getName() + "\t" + nameSource(f) + "\t";
                int callers = f.getCallingFunctions(monitor).size();
                // ROM functions are named stubs with no bytes behind them: index, don't decompile.
                if (listing.getInstructionAt(f.getEntryPoint()) == null) {
                    index.println(row + "0\t\t" + callers);
                    withoutCode++;
                    continue;
                }
                String wanted = String.format("%08x.c", f.getEntryPoint().getOffset() & ~0xffffL);
                if (!wanted.equals(file)) {
                    if (c != null) c.close();
                    file = wanted;
                    c = new PrintWriter(new FileWriter(new File(dir, file)));
                }
                DecompileResults result = decompiler.decompileFunction(f, 60, monitor);
                c.println("// ---- " + f.getName() + " @ " + f.getEntryPoint() + " ----");
                if (result.decompileCompleted()) {
                    c.println(result.getDecompiledFunction().getC());
                } else {
                    failed++;
                    c.println("// DECOMPILE FAILED: " + result.getErrorMessage());
                }
                index.println(row + f.getBody().getNumAddresses() + "\t" + file + "\t" + callers);
                exported++;
            }
        } finally {
            if (c != null) c.close();
            decompiler.dispose();
        }
        println("V24: exported " + exported + " functions (" + failed + " failed to decompile, "
                + withoutCode + " without code) to " + dir);
        println("V24: ExportC done");
    }

    // ApplyNames records where a name came from at the start of the function comment.
    private static String nameSource(Function f) {
        String comment = f.getComment();
        if (comment == null || !comment.startsWith("name from ")) return "";
        int end = comment.indexOf(':');
        return end < 0 ? "" : comment.substring("name from ".length(), end);
    }
}
