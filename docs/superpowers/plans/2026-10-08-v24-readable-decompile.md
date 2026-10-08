# V24 Readable Decompile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command rebuilds a Ghidra decompile of the V24 flash backup that shows strings, real returns, the RAM-resident code and function names.

**Architecture:** The C export is build output. `tools/ghidra/build.sh` checks the backup's sha256, then runs Ghidra headless twice: run 1 imports the flash, fixes the memory map before analysis and the code flow after it; run 2 re-analyses, applies names and exports. A small Python script measures the export against the spec's section 8 table. Knowledge that is not derivable from the image (names) lives in TSV files in git.

**Tech Stack:** Ghidra 12.1.4 headless (`brew --prefix ghidra`), OpenJDK 21 (`brew --prefix openjdk@21`), Ghidra scripts in Java, bash, Python 3 standard library with `unittest`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-08-v24-readable-decompile-design.md` (read section 11, the planning amendments, first: it corrects section 5).

**Status:** executed on 2026-10-08. The code blocks below are the plan as written; what was built differs where the execution record at the end says so. The scripts in `tools/ghidra/` and spec section 11 are current, this file is history.

## Global Constraints

- Offline only. Nothing is sent to a tracker and nothing is written to flash.
- Input is `firmware/backup/v24_1403167417_2026-10-03_flash.bin`, sha256 `c63a447aff0e3b457bda4cb7a049d3c2bfcb049b555f0d1398dc41b67a9982bd`. The build refuses any other bytes.
- Import: raw binary, flash `0x000000`–`0x290000` at base `0x88000000`, language `MIPS:LE:32:default`, compiler spec `default`.
- Generated and gitignored: `firmware/ghidra/` (project, logs) and `firmware/decompiled/` (export). Never `git add` anything under `firmware/`.
- Tracked: `tools/ghidra/*.sh`, `*.java`, `*.py`, `*.tsv`, and `tools/test_ghidra_metrics.py`.
- Ghidra scripts are Java. Every script prints `V24: <ScriptName> done` as its last line; numbers for the build report are printed as `V24: ...`.
- Any failing step stops the build with a non-zero exit.
- Mac only (Apple Silicon). No Windows tools.
- Out of scope: types and structs, hand cleanup, register names, patches, device access.

## Facts established while planning

Measured on the backup on 2026-10-08. They replace the estimates in spec section 5.

| Fact | Evidence |
|---|---|
| A stock headless import and analysis reproduces the baseline exactly: 8,521 functions, in 8 min 51 s | scratch run of the command in Task 2 |
| The context register for MIPS16 is `ISA_MODE` | scratch run |
| Boot copy loop: SRAM `0x81c01ad0` from flash `0x4490`–`0x4940`; RAM `0x82000100` from flash `0x105b0`–`0x11310`; BSS `0x81c089e0`–`0x81c089f0` and `0x82101f30`–`0x82101f40` | constant pool at flash `0xdc4`–`0xdf8` |
| Text ranges: RAM `0x82000e60`–`0x82014d90`, SRAM `0x81c01f80`–`0x81c08260`; the same table holds `0x88000000` and `0x882d76e0` | table at flash `0x1c4f8`–`0x1c50c` |
| The linear image continues past the boot copy: 137 of 232 RAM call targets and 24 of 32 SRAM call targets in the text ranges land on `addiu sp,-N`; the misses start with pool loads (leaf functions) | scored against the old export's `func_0x…` targets |
| The linear RAM image ends at flash `0x2da90` (run `0x8201d5e0`): zero padding, then flash code | bytes at `0x2da80`; old export's first function at `0x8802daa4` |
| 209 call targets lie at `0x8201d620` and above (not 161 from `0x82020000`); only 3 of the 48 below `0x82020000` hit a prologue under the linear mapping | same scoring |
| All 24 ROM call targets are symbol starts in `firmware/live/2026-10-08-loader-audit/rda-rom.map` (`memcpy`, `strlen`, `sprintf`, …). That map's ROM version `0x51612152` is the value read from this chip | loader audit doc, line 124; match script in Task 6 |
| Leading identifiers with an underscore in the flash strings: 798 distinct, 151 `sms_*`, 185 `*_handle` | regex in Task 6 run over the raw strings |

## Review Focus

1. **Wrong or missing backup.** A different file under the backup's name must stop the build before Ghidra starts. Test: Task 2, step 5.
2. **A script throws inside Ghidra.** `analyzeHeadless` exits 0 anyway; the build must still fail. Test: Task 6, step 8 (a names row that is not a function start).
3. **Malformed names row** (wrong column count, bad address). Must fail with file and line. Test: Task 6, step 8.
4. **Functions with no bytes** (ROM stubs). Must appear in the index and not count as decompile failures. Test: Task 6, step 7.
5. **Two builds from the same input differ.** The export must be byte-identical. Test: Task 7, step 4.

---

### Task 1: Metrics script

**Files:**
- Create: `tools/ghidra/metrics.py`
- Test: `tools/test_ghidra_metrics.py`

**Interfaces:**
- Produces: `read_export(path) -> str` (one file, or a directory, of which only files named `<8 hex digits>.c` are read), `measure(text) -> dict` with keys `functions`, `named`, `string_literals`, `unrecovered_returns`, `decompile_failed`, `missing_targets`, `missing_by_region`, `spot_check_missing`. CLI: `python3 tools/ghidra/metrics.py <export dir or file>`.
- Consumes: the export format `// ---- <name> @ <8 hex digits> ----` before every function.

- [ ] **Step 1: Write the failing test**

`tools/test_ghidra_metrics.py`:

```python
"""Checks for the decompile metrics (design spec section 8) on a hand-written export.

Run: .venv/bin/python -m unittest discover -s tools -p 'test_*.py'
"""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent / 'ghidra'))
from metrics import measure, read_export  # noqa: E402

FIRST = '''// ---- FUN_88000400 @ 88000400 ----

void FUN_88000400(void)
{
  code *UNRECOVERED_JUMPTABLE;
  func_0x81e015f0(4);
  func_0x81c01be8();
  func_0x8200031c();
  func_0x82020000();
  (*UNRECOVERED_JUMPTABLE)();
  (*UNRECOVERED_JUMPTABLE)();
}

'''
SECOND = '''// ---- sms_apn_handle @ 881b4f3c ----

void sms_apn_handle(char *param_1)
{
  FUN_88000400("sms_apn_handle error");
  FUN_88000400("sms_apn_handle error");
  FUN_88000400("say \\"hi\\"", '"');
  func_0x81e015f0(4);
}

// ---- thunk_FUN_88000400 @ 881b5000 ----
// DECOMPILE FAILED: timeout
'''


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.result = measure(FIRST + SECOND)

    def test_counts_functions_and_names(self):
        self.assertEqual(self.result['functions'], 3)
        self.assertEqual(self.result['named'], 1)

    def test_string_literals_are_distinct_and_survive_quotes(self):
        self.assertEqual(self.result['string_literals'], 2)

    def test_unrecovered_counts_bodies_not_occurrences(self):
        self.assertEqual(self.result['unrecovered_returns'], 1)

    def test_failed_decompiles(self):
        self.assertEqual(self.result['decompile_failed'], 1)

    def test_missing_targets_by_region(self):
        self.assertEqual(self.result['missing_targets'], 4)
        self.assertEqual(self.result['missing_by_region'],
                         {'rom': 1, 'sram': 1, 'ram': 1, 'ram_packed': 1})

    def test_spot_check_lists_absent_names(self):
        self.assertEqual(self.result['spot_check_missing'],
                         ['get_apn_handle', 'set_url_port'])

    def test_reads_only_the_build_files_of_a_directory_in_address_order(self):
        with tempfile.TemporaryDirectory() as folder:
            pathlib.Path(folder, '881b0000.c').write_text(SECOND)
            pathlib.Path(folder, '88000000.c').write_text(FIRST)
            pathlib.Path(folder, 'index.tsv').write_text('not C\n')
            pathlib.Path(folder, 'v24_code.c').write_text(FIRST)
            self.assertEqual(read_export(folder), FIRST + SECOND)

    def test_reads_a_single_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder, 'v24_code.c')
            path.write_text(FIRST)
            self.assertEqual(read_export(path), FIRST)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `.venv/bin/python -m unittest discover -s tools -p 'test_ghidra_metrics.py'`
Expected: `ModuleNotFoundError: No module named 'metrics'`

- [ ] **Step 3: Write the implementation**

`tools/ghidra/metrics.py`:

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest discover -s tools -p 'test_*.py'`
Expected: all tests pass, including the existing `test_rda_config` and `test_tracker_ui` tests.

- [ ] **Step 5: Check the script against the known baseline**

Run: `python3 tools/ghidra/metrics.py firmware/decompiled/v24_code.c`
Expected, from spec section 2: `functions 8521`, `named functions 0`, `bodies with UNRECOVERED_JUMPTABLE 2777`, `call targets with no function 518 (ram 248, ram_packed 209, rom 24, sram 37)`, `failed to decompile 0`, a single-digit string literal count. A different number means the metric is wrong, not the export: fix the script before going on.

- [ ] **Step 6: Commit**

```bash
git add tools/ghidra/metrics.py tools/test_ghidra_metrics.py
git commit -m "Add metrics for the V24 decompile export"
```

---

### Task 2: Build script and split export, with no fixes yet

This is the control build: the pipeline must reproduce the baseline numbers before anything is changed.

**Files:**
- Create: `tools/ghidra/build.sh`
- Modify: `tools/ghidra/ExportC.java` (whole file)
- Modify: `.gitignore`

**Interfaces:**
- Produces: `firmware/decompiled/<address>.c` (one per 64 KiB, name is the first address of the 64 KiB window as 8 hex digits), `firmware/decompiled/index.tsv` with header `address	name	name_source	size	file	callers`, logs `firmware/ghidra/run1.log` and `run2.log`. `build.sh` has two helpers later tasks extend: `headless <log> <analyzeHeadless args…>` and `require <log> <ScriptName>…`.
- Consumes: `metrics.py` from Task 1.

- [ ] **Step 1: Ignore the generated folders**

Append to `.gitignore`:

```
# Generated by tools/ghidra/build.sh. Both hold vendor code.
firmware/ghidra/
firmware/decompiled/
```

Run: `git check-ignore firmware/ghidra/x firmware/decompiled/v24_code.c`
Expected: both paths are printed.

- [ ] **Step 2: Rewrite the export script**

`tools/ghidra/ExportC.java`:

```java
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
```

- [ ] **Step 3: Write the build script**

`tools/ghidra/build.sh` (then `chmod +x tools/ghidra/build.sh`):

```bash
#!/bin/bash
# Rebuild the V24 decompile from the flash backup.
# Design: docs/superpowers/specs/2026-10-08-v24-readable-decompile-design.md
# Offline. Writes firmware/ghidra/ (project, logs) and firmware/decompiled/ (export);
# both are gitignored because they hold vendor code. Takes about 25 minutes.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKUP_NAME="v24_1403167417_2026-10-03_flash.bin"
SCRIPTS="$ROOT/tools/ghidra"
PROJECT="$ROOT/firmware/ghidra"
OUT="$ROOT/firmware/decompiled"

# Names are keyed by address, so they are only valid for this exact image.
if ! (cd "$ROOT/firmware/backup" && grep " $BACKUP_NAME\$" SHA256SUMS | shasum -a 256 -c -); then
    echo "build refused: firmware/backup/$BACKUP_NAME does not match SHA256SUMS" >&2
    exit 1
fi

GHIDRA_HOME="${GHIDRA_HOME:-$(brew --prefix ghidra)/libexec}"
export JAVA_HOME="${JAVA_HOME:-$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home}"

rm -rf "$PROJECT"
mkdir -p "$PROJECT" "$OUT"
# Only our own output: the folder may hold files a person put there.
rm -f "$OUT"/[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f].c \
      "$OUT/index.tsv" "$OUT/name_candidates.tsv"

headless() {  # headless <log> <analyzeHeadless arguments...>
    local log="$1"; shift
    "$GHIDRA_HOME/support/analyzeHeadless" "$PROJECT" v24 -scriptPath "$SCRIPTS" "$@" > "$log" 2>&1
}

# analyzeHeadless exits 0 even when a script throws, so every script prints
# "V24: <name> done" as its last line and we insist on seeing it.
require() {  # require <log> <script name>...
    local log="$1"; shift
    local script
    for script in "$@"; do
        if ! grep -q "V24: $script done" "$log"; then
            echo "build failed: $script did not finish. From $log:" >&2
            grep -n 'ERROR\|Exception' "$log" | grep -v 'Invalid PNG\|Invalid GIF' | head -20 >&2 || true
            exit 1
        fi
    done
}

echo "run 1/2: import and analysis (about 10 minutes)"
headless "$PROJECT/run1.log" -import "$ROOT/firmware/backup/$BACKUP_NAME" \
    -loader BinaryLoader -loader-baseAddr 0x88000000 -loader-length 0x290000 -loader-blockName flash \
    -processor MIPS:LE:32:default -cspec default

echo "run 2/2: re-analysis and export (about 15 minutes)"
headless "$PROJECT/run2.log" -process "$BACKUP_NAME" \
    -postScript ExportC.java "$OUT"
require "$PROJECT/run2.log" ExportC

echo
cat "$PROJECT/run1.log" "$PROJECT/run2.log" | sed -n 's/.*V24: \(.*\) (GhidraScript).*/\1/p' | grep -v ' done$'
python3 "$SCRIPTS/metrics.py" "$OUT"
```

- [ ] **Step 4: Run the control build**

Run: `tools/ghidra/build.sh`
Expected: exit 0; `functions` within a few of 8,521; `bodies with UNRECOVERED_JUMPTABLE` near 2,777; `call targets with no function` near 518; `failed to decompile 0`; `named functions 0`. Run 2 re-analyses a program that run 1 already analysed, so small differences from the baseline are possible: record them. `ls firmware/decompiled | head` shows `88000000.c`, `88030000.c`, … and `index.tsv`.

Then confirm run 2 really re-analyses: `grep -c 'ANALYZING all memory and code' firmware/ghidra/run2.log` prints `1`.

- [ ] **Step 5: Test that a wrong backup is refused (Review Focus 1)**

Build a scratch tree whose backup has the right name and wrong bytes. `ROOT` is derived from the script's location, so the copy checks the scratch tree:

```bash
T="$(mktemp -d)"
mkdir -p "$T/tools/ghidra" "$T/firmware/backup"
cp tools/ghidra/build.sh "$T/tools/ghidra/"
cp firmware/backup/SHA256SUMS "$T/firmware/backup/"
head -c 4194304 /dev/zero > "$T/firmware/backup/v24_1403167417_2026-10-03_flash.bin"
"$T/tools/ghidra/build.sh"; echo "exit=$?"; ls "$T/firmware"
```

Expected: `v24_1403167417_2026-10-03_flash.bin: FAILED`, `build refused: …`, `exit=1`, and `ls` shows only `backup` (no `ghidra`, so Ghidra never started). Repeat after `rm "$T/firmware/backup/"*.bin`, and again after emptying `SHA256SUMS`: `build refused` and `exit=1` both times.

- [ ] **Step 6: Commit**

```bash
git add .gitignore tools/ghidra/build.sh tools/ghidra/ExportC.java
git commit -m "Add a reproducible Ghidra build for the V24 decompile"
```

---

### Task 3: Memory map

**Files:**
- Create: `tools/ghidra/SetupMemory.java`
- Modify: `tools/ghidra/build.sh` (run 1)

**Interfaces:**
- Produces: memory blocks `boot_sram`, `sram_boot`, `sram_text`, `sram_data`, `ram_boot`, `ram_text`, `ram_data` (initialised, at run addresses), `img_<name>` (the same bytes at their flash address, not executable), `sram_low`, `sram_bss`, `rom`, `ram_low`, `ram_packed`, `ram_bss`, `sysreg` (uninitialised). Later scripts rely on two properties: code lives only in initialised executable blocks, and `rom` and `ram_packed` have no bytes.

- [ ] **Step 1: Write the script**

`tools/ghidra/SetupMemory.java`:

```java
// Before analysis: make Ghidra's memory look like the running firmware's.
// The flash image alone hides two things. Flash is read-only, and until Ghidra knows
// that the decompiler will not show string and pool constants. And boot copies part of
// the image to RAM and SRAM, where the rest of the firmware calls it.
// Bounds come from the firmware's own tables: the boot copy loop's constant pool at
// flash 0xdc4 and the text-range table at flash 0x1c4f8 (design spec, section 11).
import ghidra.app.script.GhidraScript;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;
import java.io.ByteArrayInputStream;

public class SetupMemory extends GhidraScript {
    private static final long FLASH = 0x88000000L;
    private Memory mem;

    @Override
    public void run() throws Exception {
        mem = currentProgram.getMemory();
        mem.getBlock(toAddr(FLASH)).setPermissions(true, false, true);

        // Text is read-only so pool constants show; data must stay writable, or the
        // decompiler would fold the initial value of every global into the code.
        //     name         run address  flash    length   write  execute
        copied("boot_sram", 0x81c00680L, 0x029d0, 0x01450, true,  true);
        copied("sram_boot", 0x81c01ad0L, 0x04490, 0x004b0, true,  true);
        copied("sram_text", 0x81c01f80L, 0x04940, 0x062e0, false, true);
        copied("sram_data", 0x81c08260L, 0x0ac20, 0x00780, true,  false);
        copied("ram_boot",  0x82000100L, 0x105b0, 0x00d60, true,  true);
        copied("ram_text",  0x82000e60L, 0x11310, 0x13f30, false, true);
        copied("ram_data",  0x82014d90L, 0x25240, 0x08850, true,  false);

        // No bytes, but a block gives globals and call targets a stable label.
        //    name          start        length     execute
        blank("sram_low",   0x81c00000L, 0x000680,  false);
        blank("sram_bss",   0x81c089e0L, 0x007620,  false);
        blank("rom",        0x81e00000L, 0x010000,  true);   // named from the ROM map
        blank("ram_low",    0x82000000L, 0x000100,  false);
        blank("ram_packed", 0x8201d5e0L, 0x0e4950,  true);   // unpacked at boot, spec section 9
        blank("ram_bss",    0x82101f30L, 0x2fe0d0,  false);  // to the end of 4 MiB
        blank("sysreg",     0xa1a00000L, 0x040000,  false).setVolatile(true);

        for (MemoryBlock block : mem.getBlocks()) {
            if (block.getName().startsWith("flash")) {
                block.setName(String.format("flash_%06x", block.getStart().getOffset() - FLASH));
            }
            println("V24: block " + block.getName() + " " + block.getStart() + "-" + block.getEnd()
                    + " " + (block.isWrite() ? "w" : "-") + (block.isExecute() ? "x" : "-")
                    + (block.isInitialized() ? "" : " (no bytes)"));
        }
        println("V24: SetupMemory done");
    }

    // A section the firmware runs from RAM. The bytes are loaded at the run address and
    // stay visible in flash as "img_<name>", not executable: analysed there they would
    // become a second, wrong copy of every function.
    private void copied(String name, long run, long flashOffset, long length,
                        boolean write, boolean execute) throws Exception {
        byte[] bytes = new byte[(int) length];
        mem.getBytes(toAddr(FLASH + flashOffset), bytes);
        MemoryBlock image = carve(FLASH + flashOffset, length);
        image.setName("img_" + name);
        image.setPermissions(true, false, false);
        MemoryBlock block = mem.createInitializedBlock(name, toAddr(run),
                new ByteArrayInputStream(bytes), length, monitor, false);
        block.setPermissions(true, write, execute);
    }

    // Split the flash block so that [start, start + length) is a block of its own.
    private MemoryBlock carve(long start, long length) throws Exception {
        MemoryBlock block = mem.getBlock(toAddr(start));
        if (block.getStart().getOffset() != start) {
            mem.split(block, toAddr(start));
            block = mem.getBlock(toAddr(start));
        }
        if (block.getEnd().getOffset() != start + length - 1) {
            mem.split(block, toAddr(start + length));
            block = mem.getBlock(toAddr(start));
        }
        return block;
    }

    private MemoryBlock blank(String name, long start, long length, boolean execute) throws Exception {
        MemoryBlock block = mem.createUninitializedBlock(name, toAddr(start), length, false);
        block.setPermissions(true, true, execute);
        return block;
    }
}
```

- [ ] **Step 2: Wire it into run 1**

In `tools/ghidra/build.sh`, change the run 1 block to:

```bash
echo "run 1/2: import, memory map and analysis (about 10 minutes)"
headless "$PROJECT/run1.log" -import "$ROOT/firmware/backup/$BACKUP_NAME" \
    -loader BinaryLoader -loader-baseAddr 0x88000000 -loader-length 0x290000 -loader-blockName flash \
    -processor MIPS:LE:32:default -cspec default \
    -preScript SetupMemory.java
require "$PROJECT/run1.log" SetupMemory
```

- [ ] **Step 3: Build and compare with the control build**

Run: `tools/ghidra/build.sh`
Expected:
- the block list shows the seven copied blocks, seven `img_…` blocks, seven blocks with no bytes, and `flash_…` blocks covering the rest;
- `distinct string literals` goes from single digits to roughly 3,000;
- `call targets with no function`: `sram 0`, `ram 0`; `rom` 24 and `ram_packed` about 209 remain;
- `functions` is higher than the control build (RAM and SRAM code is now decompiled);
- `failed to decompile 0`.

If `sram` or `ram` is not 0, list the leftovers with `grep -ohE 'func_0x(81c|820)[0-9a-f]+' firmware/decompiled/*.c | sort -u | head -40` and check each against the block bounds before changing anything: a target in `ram_boot` or `sram_boot` that is MIPS32 code, or one just past a block end, means a bound in the table is wrong.

- [ ] **Step 4: Check the bounds against the firmware's own code**

The table in Step 1 was read from raw pool words. Now read the code that uses them: find the function that references the text-range table.

Run: `grep -ln '0x82014d90\|0x81c08260\|0x882d76e0' firmware/decompiled/*.c` and read the functions that match.
Expected: the function shows what the four ranges are for (checksum, copy or unpack). Record the finding in spec section 11. If it shows a bound that differs from the table in `SetupMemory.java`, correct the table, rebuild, and repeat Step 3.

- [ ] **Step 5: Commit**

```bash
git add tools/ghidra/SetupMemory.java tools/ghidra/build.sh docs/superpowers/specs/2026-10-08-v24-readable-decompile-design.md
git commit -m "Load the RAM-resident code and mark flash read-only in the V24 build"
```

---

### Task 4: Returns

**Files:**
- Create: `tools/ghidra/FixCode.java`
- Modify: `tools/ghidra/build.sh` (run 1 and run 2)

**Interfaces:**
- Produces: `FixCode.java` with `markReturns()`; safe to run more than once. Task 5 adds function discovery to the same file.

- [ ] **Step 1: Write the script**

`tools/ghidra/FixCode.java`:

```java
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
```

- [ ] **Step 2: Wire it into both runs**

In `tools/ghidra/build.sh`, run 1 becomes:

```bash
echo "run 1/2: import, memory map, analysis and code fixes (about 10 minutes)"
headless "$PROJECT/run1.log" -import "$ROOT/firmware/backup/$BACKUP_NAME" \
    -loader BinaryLoader -loader-baseAddr 0x88000000 -loader-length 0x290000 -loader-blockName flash \
    -processor MIPS:LE:32:default -cspec default \
    -preScript SetupMemory.java -postScript FixCode.java
require "$PROJECT/run1.log" SetupMemory FixCode
```

and run 2 becomes:

```bash
echo "run 2/2: re-analysis, code fixes and export (about 15 minutes)"
headless "$PROJECT/run2.log" -process "$BACKUP_NAME" \
    -postScript FixCode.java -postScript ExportC.java "$OUT"
require "$PROJECT/run2.log" FixCode ExportC
```

- [ ] **Step 3: Build and measure**

Run: `tools/ghidra/build.sh`
Expected: `jr a3 marked as return` prints twice, a few thousand in run 1 and a small number in run 2; `bodies with UNRECOVERED_JUMPTABLE` falls from about 2,777 to a few dozen at most; `failed to decompile 0`.

- [ ] **Step 4: Look at what is left**

Run: `grep -c UNRECOVERED_JUMPTABLE firmware/decompiled/*.c | grep -v ':0$' | head -20`, then read five of the remaining bodies.
Expected: each is a real jump table (`switch`) or a tail call through a register. If hundreds remain and they are ordinary returns, the flow override is not enough (spec section 9): stop, read the P-code of one such function in the Ghidra GUI (`ghidraRun`, open `firmware/ghidra/v24.gpr`), and decide between a call fixup in the compiler spec and re-creating the affected functions. Do not go on to Task 5 until the number is explained.

- [ ] **Step 5: Commit**

```bash
git add tools/ghidra/FixCode.java tools/ghidra/build.sh
git commit -m "Treat jr a3 as a return in the V24 build"
```

---

### Task 5: Missed functions

**Files:**
- Modify: `tools/ghidra/FixCode.java` (whole file)

**Interfaces:**
- Produces: `FixCode.java` that also creates functions at MIPS16 code pointers and at uncovered prologues, and prints `V24: instruction bytes outside any function: N`.

- [ ] **Step 1: Replace the script**

`tools/ghidra/FixCode.java`:

```java
// After analysis: fix what the stock analysis gets wrong about this compiler's MIPS16
// output. Safe to run twice: it only touches returns not yet marked and bytes that no
// function covers. The build runs it in both Ghidra runs, because code that run 2's
// re-analysis disassembles needs the same treatment.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressOutOfBoundsException;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.FlowOverride;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryAccessException;
import ghidra.program.model.mem.MemoryBlock;
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
        int fromPointers = functionsAtCodePointers();
        int fromPrologues = functionsAtPrologues();
        // Last, so the code just disassembled is covered too.
        int returns = markReturns();

        println("V24: functions before " + before + ", created at code pointers " + fromPointers
                + ", at uncovered prologues " + fromPrologues);
        println("V24: prologues skipped because Ghidra defined data there: " + blockedByData);
        println("V24: jr a3 marked as return: " + returns);
        println("V24: instruction bytes outside any function: " + bytesOutsideFunctions());
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
                if (create(target)) made++;
            }
        }
        return made;
    }

    // Whatever is still not in a function: look for the non-leaf prologue itself.
    private int functionsAtPrologues() throws Exception {
        int made = 0;
        for (MemoryBlock block : mem.getBlocks()) {
            if (!isCodeBlock(block)) continue;
            Address last = block.getEnd().subtract(20);
            for (Address a = block.getStart(); a.compareTo(last) < 0; a = a.add(4)) {
                monitor.checkCancelled();
                if (mips16Prologue(a) && create(a)) made++;
            }
        }
        return made;
    }

    private static boolean isCodeBlock(MemoryBlock block) {
        return block != null && block.isInitialized() && block.isExecute();
    }

    // `addiu sp,-N` (0x63 with a negative immediate) followed within eight instructions
    // by `sw ra,N(sp)` (0x62xx). Both together are rare in data; leaf functions do not
    // match and are left to the call-reference analysis.
    private boolean mips16Prologue(Address a) {
        try {
            if ((mem.getShort(a) & 0xff80) != 0x6380) return false;
            for (int k = 1; k <= 8; k++) {
                if ((mem.getShort(a.add(2 * k)) & 0xff00) == 0x6200) return true;
            }
            return false;
        } catch (MemoryAccessException | AddressOutOfBoundsException e) {
            return false;
        }
    }

    private boolean create(Address entry) throws Exception {
        if (functions.getFunctionContaining(entry) != null) return false;
        if (listing.getInstructionAt(entry) == null) {
            if (listing.getInstructionContaining(entry) != null) return false;
            if (listing.getDefinedDataContaining(entry) != null) {
                blockedByData++;
                return false;
            }
            // Without this Ghidra would decode the bytes as MIPS32.
            Register isaMode = currentProgram.getProgramContext().getRegister("ISA_MODE");
            currentProgram.getProgramContext().setValue(isaMode, entry, entry, BigInteger.ONE);
            if (!disassemble(entry)) return false;
        }
        return createFunction(entry, null) != null;
    }

    private long bytesOutsideFunctions() throws Exception {
        AddressSet code = new AddressSet();
        for (Instruction instruction : listing.getInstructions(true)) {
            code.add(instruction.getMinAddress(), instruction.getMaxAddress());
        }
        AddressSet covered = new AddressSet();
        for (Function f : functions.getFunctions(true)) {
            covered.add(f.getBody());
        }
        return code.subtract(covered).getNumAddresses();
    }
}
```

- [ ] **Step 2: Build and measure**

Run: `cp firmware/decompiled/index.tsv "${TMPDIR:-/tmp}/v24-index-before.tsv" && tools/ghidra/build.sh`
Expected: `functions` rises by a few thousand towards the roughly 12,000 `jr a3` sites; run 2's FixCode line shows only a few new functions (run 1 already found them); `failed to decompile` stays 0 or very close; `bodies with UNRECOVERED_JUMPTABLE` stays in the dozens; `instruction bytes outside any function` is printed.

- [ ] **Step 3: Check the new functions are real**

Pick ten functions created by this step: `comm -13 <(cut -f1 "${TMPDIR:-/tmp}/v24-index-before.tsv" | sort) <(cut -f1 firmware/decompiled/index.tsv | sort) | sort -R | head -10`. Read each in its C file.
Expected: ordinary function bodies with a return. If several are garbage (`halt_baddata()`, bodies of a few bytes, decompile failures in `run2.log`), tighten `mips16Prologue` rather than accept them: the count of false functions matters more than the count of functions. If `prologues skipped because Ghidra defined data there` is in the hundreds, look at three of those addresses before deciding whether the data definitions are wrong.

- [ ] **Step 4: Commit**

```bash
git add tools/ghidra/FixCode.java
git commit -m "Find V24 functions reached only through pointer tables"
```

---

### Task 6: Names

**Files:**
- Create: `tools/ghidra/ApplyNames.java`
- Create: `tools/ghidra/v24_names.tsv`
- Create: `tools/ghidra/v24_names.rom.tsv` (generated once, committed)
- Modify: `tools/ghidra/build.sh` (run 2)

**Interfaces:**
- Consumes: the `rom` block from Task 3; `nameSource()` in `ExportC.java` reads the comment this script writes.
- Produces: function names; a function comment that starts `name from <source>: <evidence>`; `firmware/decompiled/name_candidates.tsv` with header `identifier	functions	example`; TSV format `address<TAB>name<TAB>source<TAB>evidence`, `#` starts a comment line.

- [ ] **Step 1: Generate the ROM names file**

The ROM map is in the gitignored loader-audit folder; the names file is committed so the build does not need it.

```bash
python3 - <<'EOF'
import re
text = open('firmware/live/2026-10-08-loader-audit/rda-rom.map').read()
symbols = {}
for address, name in re.findall(r'^\s+0x(?:ffffffff)?(81e[0-9a-f]{5})\s+([A-Za-z_]\w*)\s*$', text, re.M):
    symbols.setdefault(int(address, 16) & ~1, name)   # bit 0 only marks MIPS16
rows = ['# RDA8955 chip ROM symbols. Generated on 2026-10-08 from the SDK ROM map',
        '# (rda-rom.map, ROM version 0x51612152, the version read from this chip).',
        '# All 24 ROM addresses the firmware calls are symbol starts in this map.',
        '# address\tname\tsource\tevidence']
rows += [f'0x{address:08x}\t{name}\trom\trda-rom.map' for address, name in sorted(symbols.items())]
open('tools/ghidra/v24_names.rom.tsv', 'w').write('\n'.join(rows) + '\n')
print(len(symbols), 'symbols')
EOF
awk -F'\t' '$2=="memcpy" || $2=="strlen" || $2=="sprintf"' tools/ghidra/v24_names.rom.tsv
```

Expected: `119 symbols`; `memcpy` at `0x81e03b10`, `strlen` at `0x81e04480`, `sprintf` at `0x81e051a0`.

- [ ] **Step 2: Create the hand-maintained names file**

`tools/ghidra/v24_names.tsv`:

```
# Hand-maintained function names for the V24 firmware (backup sha256 c63a447a...).
# Applied last: a row here overrides every automatic name.
# A row whose address is not a function start fails the build.
# address	name	source	evidence
0x88039f54	uat_transSetCallback	traced	docs/v24-firmware-analysis.md section 9, SDK name
```

(Tabs between columns. Addresses are without the MIPS16 bit.)

- [ ] **Step 3: Write the script**

`tools/ghidra/ApplyNames.java`:

```java
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
    // A log line usually starts with the name of the function that prints it. The
    // underscore keeps ordinary words ("error ", "Send ") from becoming names.
    private static final Pattern LEAD =
            Pattern.compile("^([A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+)[.:, ]");

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
```

- [ ] **Step 4: Wire it into run 2**

In `tools/ghidra/build.sh`, run 2 becomes:

```bash
echo "run 2/2: re-analysis, code fixes, names and export (about 15 minutes)"
headless "$PROJECT/run2.log" -process "$BACKUP_NAME" \
    -postScript FixCode.java -postScript ApplyNames.java "$OUT" -postScript ExportC.java "$OUT"
require "$PROJECT/run2.log" FixCode ApplyNames ExportC
```

- [ ] **Step 5: Build and measure**

Run: `tools/ghidra/build.sh`
Expected: `named functions` several hundred; `names from the ROM map: 24`; `names from v24_names.tsv: 1`; `call targets with no function` now shows `rom 0`; `spot check ok`.

- [ ] **Step 6: Spot check against the captured logs**

Run: `awk -F'\t' '$2 ~ /^(sms_apn_handle|get_apn_handle|set_url_port|uat_transSetCallback|memcpy)$/' firmware/decompiled/index.tsv`, then read `sms_apn_handle` in the file the index names.
Expected: five rows with sources `log`, `log`, `log`, `traced`, `rom`; the body of `sms_apn_handle` contains the string `sms_apn_handle.apn:%s,%s,%s,%s.` and its address is `881b4f3c`, the APN handler traced by hand in `docs/v24-firmware-analysis.md` section 9. A different address means the log-string rule named a helper: investigate before trusting any other name.

- [ ] **Step 7: Check ROM stubs are indexed, not decompiled (Review Focus 4)**

Run: `awk -F'\t' '$3=="rom"' firmware/decompiled/index.tsv | head -3; ls firmware/decompiled | grep -c '^81e'`
Expected: rows with size `0`, an empty file column and a caller count above 0; the `ls` count is `0` (no C file for the ROM range); `failed to decompile` is unchanged from Task 5.

- [ ] **Step 8: Test that bad names rows fail loudly (Review Focus 2 and 3)**

Run only the names step, read-only, against a scratch copy of the scripts with a bad row, so the real project and names file are untouched:

```bash
T="$(mktemp -d)"; cp tools/ghidra/*.java tools/ghidra/*.tsv "$T/"
printf '0x88039f58\tnot_a_start\ttest\tmid-function address\n' >> "$T/v24_names.tsv"
GH="$(brew --prefix ghidra)/libexec/support/analyzeHeadless"
export JAVA_HOME="$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home"
"$GH" firmware/ghidra v24 -process v24_1403167417_2026-10-03_flash.bin -noanalysis -readOnly \
    -scriptPath "$T" -postScript ApplyNames.java "$T" > "$T/log" 2>&1
grep -c 'V24: ApplyNames done' "$T/log"; grep -o 'v24_names.tsv:[0-9]*: .*is not a function start' "$T/log"
```

Expected: `0`, then `v24_names.tsv:6: 0x88039f58 is not a function start`. `build.sh`'s `require` fails the build on exactly that missing `done` line. Repeat with a three-column row (`printf '0x88039f54\tx\ty\n'`) in a fresh scratch copy: expect `expected 4 tab-separated columns, found 3`.

- [ ] **Step 9: Commit**

```bash
git add tools/ghidra/ApplyNames.java tools/ghidra/v24_names.tsv tools/ghidra/v24_names.rom.tsv tools/ghidra/build.sh
git commit -m "Name V24 functions from log strings, the ROM map and a names file"
```

---

### Task 7: Close the open questions and write down the result

**Files:**
- Modify: `docs/superpowers/specs/2026-10-08-v24-readable-decompile-design.md` (section 11)
- Modify: `docs/v24-firmware-analysis.md` (flash map row for `0x2d0000`, new section on the decompile)
- Delete: `firmware/decompiled/v24_code.c` (untracked, superseded)

- [ ] **Step 1: Decide on SDK name matching (spec section 6, source 2)**

Read the `callees of sms_*_handle still unnamed: U of N` line from the last build.
Rule: if `U / N` is above one half, SDK matching is needed and gets its own short plan, written against the list of unnamed callees. Otherwise it is not done. Record the two numbers and the decision in spec section 11.

- [ ] **Step 2: Find out how the packed RAM code gets there (spec section 9)**

Run: `grep -ln 'Decompress Task' firmware/decompiled/*.c`, read the function that prints it and the functions it calls; then the function found in Task 3 step 4 that holds `0x882d76e0`.
Record in spec section 11: the flash address and length of the packed data, the destination range, and the algorithm, each marked verified or unverified. Rule: if the algorithm is one the Python standard library unpacks (`zlib`, `lzma`) or the SDK has its source and a port is under about a hundred lines, unpacking gets its own short plan; the unpacked bytes would be loaded as one more `copied`-style block. If not, the `ram_packed` targets stay unresolved and the count stays in the build report. Either way, sub-project B is not blocked.

- [ ] **Step 3: Update the analysis doc**

In `docs/v24-firmware-analysis.md`: correct the `0x2d0000` flash map row with what Step 2 found (keep **(unverified)** on anything not shown by code), and add a section "11. Decompile" with: the build command, where the output is, how to find a function (`index.tsv`), the final metrics table (baseline against result), and what remains unresolved.

- [ ] **Step 4: Check the build is reproducible (Review Focus 5)**

```bash
FIRST="$(mktemp -d)"; cp firmware/decompiled/*.tsv firmware/decompiled/[0-9a-f]*.c "$FIRST/"
tools/ghidra/build.sh
diff -rq -x v24_code.c "$FIRST" firmware/decompiled && echo identical
```

Expected: `identical`. If files differ, look at one difference: a varying variable name or ordering inside one function is a decompiler timing effect (note it in the analysis doc); a differing function list is a bug in the scripts and must be fixed.

- [ ] **Step 5: Remove the old export**

The spec replaces the single-file export with the split one. Check first that nothing but the old export is being removed: `ls -la firmware/decompiled | grep -v '^.*[0-9a-f]\{8\}\.c$'` shows `index.tsv`, `name_candidates.tsv` and `v24_code.c` only.

Run: `rm firmware/decompiled/v24_code.c && python3 tools/ghidra/metrics.py firmware/decompiled`
Expected: the same numbers as the last build, and `functions` equals `tail -n +2 firmware/decompiled/index.tsv | awk -F'\t' '$5!=""' | wc -l`.

- [ ] **Step 6: Run all tests and commit**

Run: `.venv/bin/python -m unittest discover -s tools -p 'test_*.py'`
Expected: all pass.

```bash
git add docs/superpowers/specs/2026-10-08-v24-readable-decompile-design.md docs/v24-firmware-analysis.md
git commit -m "Record the V24 decompile results and what stays unresolved"
```

---

## Execution record (2026-10-08)

Executed inline in one session. Tasks 3 to 6 were each verified by a full build of exactly that task's files, run in parallel in scratch trees; the final working-tree build is byte-identical to the scratch build of Task 6.

Final build: 16,300 functions, 685 named plus 38 ROM functions, 3,233 distinct string literals, 0 functions ending in an unrecovered jump table, 0 decompile failures.

Decisions taken during execution, in order. Each ends with what it costs if it is wrong.

- **Setup.** no separate worktree — the build's inputs (firmware/backup, tools/) are untracked files in this working directory and the only branch is claude/gracious-planck-w7hw73 — cost if wrong: commits land on the session branch next to the spec, as the spec commit already did.
- **Setup.** start implementation without a plan-review stop — the user said "go ahead and start implementation" before the plan existed — cost if wrong: the user reads the plan after the fact; everything is offline and generated output is gitignored.
- **Task 3.** import the whole 4 MiB flash, not 0x000000–0x290000 as spec section 5 says — 175 pool words in the code point into a pointer table at flash 0x290000 (941 pointers in its first 8 KiB) and 40-odd into the settings and factory areas, all of which dangle with the short import; 0x290000–0x360000 is loaded read-only non-executable (flash_data), 0x360000–0x400000 writable non-executable (flash_store, rewritten at run time) — cost if wrong: analysis spends time on 1.4 MiB of data and may define junk strings there; no code can be created in it.
- **Task 3.** rom block is read+execute, not writable — it is ROM; the plan's blank() made every blank block writable — cost if wrong: none, the block has no bytes.
- **Task 3.** verify tasks 3-6 with four parallel builds in scratch trees (each holds that task's exact tools/ghidra state; build.sh derives ROOT from its own location) instead of four sequential builds in the working tree — same script, same input, 12 minutes instead of 45 — cost if wrong: a scratch-tree result could differ from a working-tree build; Task 7's reproducibility check compares the two.
- **Task 3.** ExportC passes DecompileOptions to the decompiler — plan defect: without options the decompiler ignores read-only memory, so even with flash read-only every string came out as PTR_s_… (0 literals in the scratch preview, 3052 with options) — cost if wrong: none, these are Ghidra's GUI defaults.
- **Task 3.** the packed-RAM and ROM gaps are reported by ExportC as "called functions with no code behind them" per block, not by the metrics script's func_0x count — Ghidra creates stub functions at call targets in blocks without bytes, so those calls no longer render as func_0x… — cost if wrong: none; the stubs appear in index.tsv with size 0 and can be named.
- **Task 3.** build.sh header says 15 minutes, not 25 — measured: run 1 is 9 min, run 2 under 2 min in the control build.
- **Task 6.** the log-string rule allows leading whitespace before the identifier — "\n set_url_port.url:%s" is how this firmware writes many log lines, and the spec's own spot check name was missed without it — cost if wrong: a few more names from strings that merely mention an identifier first.
- **Task 6.** a ROM symbol that the firmware references as data (g_BootHostUsbFixPtr) gets a label, not a function — createFunction throws on defined data — cost if wrong: none.
- **Task 3.** SetupMemory table corrected to the boot loader's code — adds sram_irq, splits sram_boot at 0x81c01f00 into text and data, makes sram_boot and ram_boot read-only — the plan's table was read from raw pool words; plan step 4 says to correct it from the code — cost if wrong: a mutable global in a block marked read-only would be shown as a constant.
- **Task 3.** flash from 0x238720 is data (flash_data to 0x362000 read-only, flash_store beyond writable) — flash code ends at 0x238704 (last return idiom at 0x2386bc, pool to 0x238704); with the string tables executable Ghidra's own analysis created junk functions there (0x8824ab68, 0x88256558, ...) — cost if wrong: code past 0x238720 would only be found through calls (the segment locator at 0x882d7750 is, and was).
- **Task 3.** unpack the three LZMA segments in SetupMemory and load them at 0x8201d5e0, 0x82050260 and 0x820eab40 as read-only executable blocks — spec section 9 says to load the result if a small script unpacks it; the plan deferred it to a later plan before the facts were in. Evidence: the loaders at flash 0x1620a4/0x162108/0x162170 name source, destination and length; each segment has a standard .lzma header whose length field matches; Python's lzma and Ghidra's bundled org.tukaani.xz both unpack to exactly those lengths; 155 of the 209 old call targets land on addiu sp,-N; the SDK linker script puts only .text and .rodata in these sections. Unverified: the firmware's own checksum over each segment (function at 0x880439c4, algorithm not identified) — cost if wrong: none found; a wrong unpack would not produce prologues at call targets.
- **Task 5.** mips16Prologue also requires the matching epilogue (jr a3 with addiu sp,+N in the delay slot, within 8 KiB) — the plan's rule matched 8 places in the string tables; the full idiom matches none and keeps 9727 of 9871 matches in code — cost if wrong: about 1.5% of non-leaf functions reached only by pointer are left to other discovery.
- **Task 5.** FixCode clears a word-sized data definition that sits exactly on a function start, and creates functions at direct call targets that have no code — Ghidra typed the first four bytes of 31 real functions as pointers, and defined data at 0x81c01f80 (called twice) because the boot loader writes there — cost if wrong: a real 4-byte datum at an address that also passes the prologue test or is a direct call target would be turned into code.
- **Task 5.** FixCode also makes a function of every run of disassembled code that no function covers and that nothing falls or jumps into — 106,710 instruction bytes (1,130 runs) were outside every function in the preview and so absent from the export; most start with a prologue whose epilogue releases the frame in two steps, which the strict prologue rule rejects; the step created 1,045 functions and left 6,118 bytes — cost if wrong: if Ghidra had mis-disassembled data, it now shows up as a junk function instead of staying invisible; unrecovered jump tables would be split into fragments, but the preview has none (0 bodies with UNRECOVERED_JUMPTABLE).
- **Task 3.** metrics region renamed ram_packed -> ram_overlay (0x8201d5e0-0x82101e80), and names Ghidra makes up (caseD_1, thunk_EXT_FUN_...) no longer count as named — both test-first (RED then GREEN) — cost if wrong: none.
- **Task 6.** v24_names.tsv starts with four rows, not one — boot_LoaderEnter, hal_DbgPageProtectSetup and hal_DbgPageProtectEnable were identified against the SDK's boot_loader.c while checking the memory map — cost if wrong: three wrong names, each with its evidence in the row.
- **Task 7.** SDK name matching is not started, although 107 of the 202 callees of sms_*_handle are unnamed (53%, just over the plan's one-half trigger) — 106 unnamed callees appear in the handlers' bodies, one (0x881b9304, the log printf) is called by all 128 handlers, 74 by exactly one handler, and nearly all sit at 0x881a....-0x881b...., the vendor's application code, which the public RDA SDK does not contain; SDK matching would name platform functions, not these — cost if wrong: platform callees stay FUN_... until sub-project B names them by hand or a later plan matches the SDK.
- **Task 7.** step 2's "unpacking gets its own short plan" is void — done in Task 3 (see that ruling).

Not done, by decision: SDK name matching (see the Task 7 decision above).
