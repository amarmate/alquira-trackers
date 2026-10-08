// Name functions. Order matters: log strings first, and only where the name is not a
// guess; then ROM symbols; then v24_names.tsv, which overrides everything.
// Every name records where it came from at the start of the function comment, so a
// wrong name can be traced and the index can show the source.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressOutOfBoundsException;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryAccessException;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.SourceType;
import java.io.File;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class ApplyNames extends GhidraScript {
    // A log line usually starts with the name of the function that prints it, often
    // after a newline ("\n set_url_port.url:%s"). The underscore keeps ordinary words
    // ("error ", "Send ") from becoming names.
    private static final Pattern LEAD =
            Pattern.compile("^\\s*([A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+)[.:, ]");

    private Memory mem;
    private FunctionManager functions;

    @Override
    public void run() throws Exception {
        mem = currentProgram.getMemory();
        functions = currentProgram.getFunctionManager();
        File out = new File(getScriptArgs()[0]);
        File here = new File(getSourceFile().getParentFile().getAbsolutePath());

        namesFromLogStrings(new File(out, "name_candidates.tsv"));
        println("V24: names from the ROM map: " + applyTsv(new File(here, "v24_names.rom.tsv"), true));
        println("V24: names from v24_names.tsv: " + applyTsv(new File(here, "v24_names.tsv"), false));
        reportSmsCallees();
        println("V24: ApplyNames done");
    }

    private void namesFromLogStrings(File candidatesFile) throws Exception {
        Map<String, Set<Function>> printers = new TreeMap<>();  // identifier -> functions that print it
        Map<String, String> example = new HashMap<>();
        for (Function f : functions.getFunctions(true)) {
            monitor.checkCancelled();
            for (Instruction instruction : currentProgram.getListing().getInstructions(f.getBody(), true)) {
                for (Reference reference : instruction.getReferencesFrom()) {
                    // Either straight to the string, or to the pool word that points at it.
                    String text = stringAt(reference.getToAddress());
                    if (text == null) text = stringAt(pointerAt(reference.getToAddress()));
                    if (text == null) continue;
                    Matcher lead = LEAD.matcher(text);
                    if (!lead.find()) continue;
                    printers.computeIfAbsent(lead.group(1), k -> new HashSet<>()).add(f);
                    example.putIfAbsent(lead.group(1), text.strip().replace("\n", "\\n").replace("\r", "\\r"));
                }
            }
        }
        // Apply a name only when it is one-to-one: one function prints the identifier,
        // and that function prints no other identifier. Everything else is a helper,
        // a shared tag or a copy-pasted message, and goes to the candidates file.
        Map<Function, List<String>> claims = new HashMap<>();
        for (Map.Entry<String, Set<Function>> entry : printers.entrySet()) {
            if (entry.getValue().size() == 1) {
                claims.computeIfAbsent(entry.getValue().iterator().next(), k -> new ArrayList<>()).add(entry.getKey());
            }
        }
        int applied = 0;
        try (PrintWriter candidates = new PrintWriter(new FileWriter(candidatesFile))) {
            candidates.println("identifier\tfunctions\texample");
            for (Map.Entry<String, Set<Function>> entry : printers.entrySet()) {
                String identifier = entry.getKey();
                Function only = entry.getValue().size() == 1 ? entry.getValue().iterator().next() : null;
                if (only != null && claims.get(only).size() == 1
                        && only.getSymbol().getSource() == SourceType.DEFAULT) {
                    only.setName(identifier, SourceType.ANALYSIS);
                    only.setComment("name from log: " + example.get(identifier));
                    applied++;
                    continue;
                }
                List<String> addresses = new ArrayList<>();
                for (Function f : entry.getValue()) addresses.add(f.getEntryPoint().toString());
                addresses.sort(null);
                candidates.println(identifier + "\t" + String.join(",", addresses) + "\t" + example.get(identifier));
            }
        }
        println("V24: names from log strings: " + applied + " applied, "
                + (printers.size() - applied) + " ambiguous (see name_candidates.tsv)");
    }

    private String stringAt(Address a) {
        if (a == null) return null;
        StringBuilder text = new StringBuilder();
        try {
            for (int k = 0; k < 400; k++) {
                int c = mem.getByte(a.add(k)) & 0xff;
                if (c == 0) return text.length() >= 4 ? text.toString() : null;
                if (c != '\n' && c != '\r' && c != '\t' && (c < 0x20 || c > 0x7e)) return null;
                text.append((char) c);
            }
        } catch (MemoryAccessException | AddressOutOfBoundsException e) {
            // not readable memory: not a string
        }
        return null;
    }

    private Address pointerAt(Address a) {
        try {
            return toAddr(mem.getInt(a) & 0xffffffffL);
        } catch (MemoryAccessException | AddressOutOfBoundsException e) {
            return null;
        }
    }

    // rom: the block has no bytes, so a function exists there only if we create it,
    // and only the addresses this firmware references are worth creating.
    private int applyTsv(File tsv, boolean rom) throws Exception {
        int applied = 0, line = 0;
        for (String row : Files.readAllLines(tsv.toPath())) {
            line++;
            if (row.isBlank() || row.startsWith("#")) continue;
            String where = tsv.getName() + ":" + line + ": ";
            String[] column = row.split("\t", -1);
            if (column.length != 4) {
                throw new IllegalArgumentException(where + "expected 4 tab-separated columns, found " + column.length);
            }
            Address address;
            try {
                address = toAddr(Long.parseLong(column[0].replaceFirst("^0x", ""), 16));
            } catch (NumberFormatException e) {
                throw new IllegalArgumentException(where + "bad address '" + column[0] + "'");
            }
            Function f = functions.getFunctionAt(address);
            if (f == null && rom) {
                if (!currentProgram.getReferenceManager().hasReferencesTo(address)) continue;
                // A ROM symbol the firmware reads instead of calls is a table, not a function.
                if (currentProgram.getListing().getDefinedDataContaining(address) != null) {
                    createLabel(address, column[1], true);
                    println("V24: ROM symbol used as data, labelled only: " + column[1]);
                    continue;
                }
                f = functions.createFunction(column[1], address, new AddressSet(address), SourceType.IMPORTED);
            }
            if (f == null) {
                throw new IllegalArgumentException(where + column[0] + " is not a function start");
            }
            f.setName(column[1], SourceType.USER_DEFINED);
            f.setComment("name from " + column[2] + ": " + column[3]);
            applied++;
        }
        return applied;
    }

    // Spec section 6, source 2: matching against the SDK source is only worth doing
    // if the SMS handlers still call mostly anonymous functions.
    private void reportSmsCallees() throws Exception {
        Set<Function> callees = new HashSet<>();
        for (Function f : functions.getFunctions(true)) {
            if (f.getName().startsWith("sms_") && f.getName().endsWith("_handle")) {
                callees.addAll(f.getCalledFunctions(monitor));
            }
        }
        long unnamed = callees.stream().filter(c -> c.getSymbol().getSource() == SourceType.DEFAULT).count();
        println("V24: callees of sms_*_handle still unnamed: " + unnamed + " of " + callees.size());
    }
}
