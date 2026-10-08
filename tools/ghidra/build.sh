#!/bin/bash
# Rebuild the V24 decompile from the flash backup.
# Design: docs/superpowers/specs/2026-10-08-v24-readable-decompile-design.md
# Offline. Writes firmware/ghidra/ (project, logs) and firmware/decompiled/ (export);
# both are gitignored because they hold vendor code. Takes about 15 minutes.
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
    if ! "$GHIDRA_HOME/support/analyzeHeadless" "$PROJECT" v24 -scriptPath "$SCRIPTS" "$@" > "$log" 2>&1; then
        echo "build failed: Ghidra did not run to the end. Last lines of $log:" >&2
        tail -5 "$log" >&2
        exit 1
    fi
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

# The whole 4 MiB, not just the code: the code points at tables, settings and
# factory data that sit well past it, and the packed RAM code is in there too.
echo "run 1/2: import, memory map, analysis and code fixes (about 10 minutes)"
headless "$PROJECT/run1.log" -import "$ROOT/firmware/backup/$BACKUP_NAME" \
    -loader BinaryLoader -loader-baseAddr 0x88000000 -loader-blockName flash \
    -processor MIPS:LE:32:default -cspec default \
    -preScript SetupMemory.java -postScript FixCode.java
require "$PROJECT/run1.log" SetupMemory FixCode

echo "run 2/2: re-analysis, code fixes, names and export (a few minutes)"
headless "$PROJECT/run2.log" -process "$BACKUP_NAME" \
    -postScript FixCode.java -postScript ApplyNames.java "$OUT" -postScript ExportC.java "$OUT"
require "$PROJECT/run2.log" FixCode ApplyNames ExportC

echo
cat "$PROJECT/run1.log" "$PROJECT/run2.log" | sed -n 's/.*V24: \(.*\) (GhidraScript).*/\1/p' | grep -v ' done$'
python3 "$SCRIPTS/metrics.py" "$OUT"
