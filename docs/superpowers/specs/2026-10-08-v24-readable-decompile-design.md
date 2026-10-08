# V24 readable decompile: design (2026-10-08)

Goal: understand the vendor firmware well enough to patch it, starting with the command
parser and the settings store. This spec covers the first sub-project only: a
reproducible Ghidra build that turns the flash backup into a decompile with strings,
correct returns, the missing code mapped, and function names.

Everything here is offline. Nothing is sent to a tracker and nothing is written to flash.

## 1. Decomposition

| Sub-project | Content | Spec |
|---|---|---|
| **A. Readable decompile** | reproducible build, input fixes, automatic names | this document |
| B. Command parser and settings store | hand cleanup (types, structs, names), verified against live logs and captures; pure logic lifted into host-runnable code with tests | written after A, because its shape depends on what A shows |
| C. Later subsystems | server link, GPS and power, pin map | one spec each, as needed |
| Patching a device | binary patches built on B | gated on the flash-restore work in `v24-flash-restore-spec.md`; not planned here |

## 2. What is wrong with the current export

`firmware/decompiled/v24_code.c` (350,726 lines, 8,521 functions) came from a raw-binary
import of flash `0x000000`–`0x290000` at base `0x88000000`, language
`MIPS:LE:32:default`, default auto-analysis, Ghidra 12.1.4. Measured on that file and on
the 2026-10-03 backup (sha256 `c63a447a…`):

| Problem | Evidence | Cause |
|---|---|---|
| No strings | 6 string literals; the code holds 8,010 constant-pool words pointing at 3,060 distinct printable strings | the flash block is writable, so the decompiler will not treat pool words as constants |
| Returns shown as `(*UNRECOVERED_JUMPTABLE)()` | 2,777 function bodies; 2,782 of the 2,784 sites are the MIPS16 instruction `jr a3` (`0xEF00`) | this compiler returns through `a3`; Ghidra does not recognise it |
| Calls into code that was never decompiled | 518 distinct `func_0x…` targets: 457 in RAM `0x82…`, 37 in internal SRAM `0x81c0…`, 24 in chip ROM `0x81e0…` | only the flash-address view was loaded |
| Missed functions | about 12,000 `jr a3` byte patterns against 8,521 functions | functions reached only through handler tables are not discovered |
| No names | all functions are `FUN_…` | 742 distinct function names lead the log strings (151 `sms_*`, 184 `*_handle`) and are unused |

## 3. Approach

Treat the C export as build output. Fix the Ghidra program (memory map, flags, flow,
names) with scripts and regenerate. Names and other knowledge live in a text file in git.

Rejected:

- **Post-process the C text** (substitute pool constants, rewrite the return idiom). Quick,
  but cosmetic: function boundaries, missing code and cross-references stay wrong, and the
  decompiler never gets to simplify with the constants.
- **Work in the Ghidra GUI and keep the project as the source of truth.** Good for
  browsing, but the project is a binary database: not diffable, not in git, and a wrong
  import setting means starting over. The generated project stays openable in the GUI.

## 4. Build

One command, `tools/ghidra/build.sh`. It refuses to run unless the backup matches the
sha256 in `firmware/backup/SHA256SUMS`, then runs Ghidra headless and prints the metrics
in section 8. Any step that fails stops the build with a non-zero exit.

| File | Role |
|---|---|
| `tools/ghidra/build.sh` | checksum check, the Ghidra runs, metrics |
| `tools/ghidra/SetupMemory.java` | before analysis: flash read-only, add the blocks in section 5 |
| `tools/ghidra/FixCode.java` | after analysis: mark `jr a3` as a return; create functions at code-pointer table entries and at prologues in bytes no function covers |
| `tools/ghidra/ApplyNames.java` | names from log strings, then `v24_names.tsv` on top |
| `tools/ghidra/ExportC.java` | exists; changed to write one file per 64 KiB of address space plus an index |
| `tools/ghidra/v24_names.tsv` | hand-maintained names, in git |

Scripts are Java because the existing one is and Java scripts run headless with no extra
setup. Ghidra runs twice: import, fix and analyse; then name and export. Changes made by
scripts are only re-analysed after the run that made them.

Generated and gitignored: the Ghidra project in `firmware/ghidra/` and the export in
`firmware/decompiled/`. The current project sits in another session's temp folder and is
not reused.

## 5. Memory map to load

| Run address | Source | Evidence | Status |
|---|---|---|---|
| `0x88000000` flash | backup `0x000000`–`0x290000` | loaded today | change to read-only |
| `0x81c00000` internal SRAM | flash from `0x29c0` | 26 of 37 call targets land on a function prologue; next best offset scores 7 | linear copy; length to be read from the boot code |
| `0x82000000` RAM | flash from `0x104b0`, to about `0x2da00` | 141 of 296 call targets below `0x82020000` land on a prologue; next best offset scores 16 of 120. Ghidra's first flash-address function after this area is at `0x2daa4` | linear copy; exact end to be read from the boot code |
| `0x82020000`–`0x82101ccc` RAM | not stored uncompressed (best linear offset: 16 of 161, noise) | string `USR_INIT: Decompress Task`; the SDK has `compress_3264` linker scripts; flash `0x2d0000`–`0x360000` is 576 KiB at entropy 8.0 | **unresolved**, see section 9 |
| `0x81e00000` chip ROM | SDK `soft/platform/chip/rom/8955/lib/mem_bridge_rom_CHIP.elf` and `.map` | 24 call targets | **unverified** that this ELF is the internal ROM and matches the chip revision |
| remaining RAM, SRAM, register space | uninitialised blocks | 25,007 pool words point at `0x82…`, 7,600 at `0xa0…`–`0xa2…` | gives globals and registers stable labels |

The boot routine's constant pool at flash `0x1470`–`0x1560` holds section addresses
(`0x81c01ad0`, `0x88003e20`, `0x82000000`, `0x82000010`); reading that routine gives the
exact copy table.

## 6. Names

Sources 1 to 3 run in order and only name functions that have no name yet. Source 4
overrides all of them.

1. **Log strings.** A string starting with `identifier.`, `identifier:`, `identifier,`
   or `identifier ` names the function that references it, when all strings carrying
   that identifier are referenced by one single function. Otherwise nothing is applied
   and the candidates go into the build report.
2. **SDK source**, only if needed. After step 1, measure how many callees of the
   `sms_*_handle` functions are still unnamed. If most are, match firmware strings
   against string literals in the public SDK (`cherryding1/RDA8955_W17.44_IDH`, 2,256 C
   files; the firmware is branch W17.40, so matching is by string, not by bytes) and take
   the enclosing function's name. Results are written to a generated
   `tools/ghidra/v24_names.sdk.tsv`, which is committed so the SDK checkout is not needed
   to build.
3. **ROM symbols** from the ELF in section 5, if it verifies.
4. **`v24_names.tsv`.** Columns: address, name, source, evidence. A row whose address
   is not a function start fails the build.

## 7. Output

`firmware/decompiled/<start address>.c`, one per 64 KiB of address space, and
`firmware/decompiled/index.tsv`: address, name, name source, size, file, caller count.
The index is how a function is found by name. Splitting by module is left to
sub-project B, where it is needed.

## 8. How we know it worked

`build.sh` prints these after every build. Baseline is the current export.

| Metric | Baseline | Expected |
|---|---|---|
| distinct string literals in the export | 6 lines contain one | about 3,000 |
| function bodies containing `UNRECOVERED_JUMPTABLE` | 2,777 | a few dozen at most, each a real jump table or tail call |
| distinct call targets with no function | 518 | 0 for SRAM and for RAM below `0x82020000`; ROM and the 161 targets from `0x82020000` up are reported separately |
| functions | 8,521 | higher; code bytes not covered by any function are reported |
| named functions | 0 | several hundred, out of 742 candidate names |
| functions that fail to decompile | 0 | 0 |

A result far from the expected column means the fix did not work and is investigated
before the next step.

Spot check: `sms_apn_handle`, `get_apn_handle` and `set_url_port` exist by name, and the
strings in their bodies match the log lines captured in `v24-firmware-analysis.md`
section 9.

## 9. Open questions and risks

- **RAM code from `0x82020000` up.** Probably compressed in flash and unpacked at boot
  **(unverified)**. Once strings are visible, the function referencing
  `USR_INIT: Decompress Task` shows the source address and algorithm; the SDK source is
  the reference. If it unpacks with a small host script, the result is loaded as a block
  at its run address. If not, the 161 targets stay as named externals and the gap is
  recorded in the build report. The `sms_*` strings are referenced from flash-address
  code, so sub-project B does not depend on this.
- **The `jr a3` override may not be enough** for the decompiler to drop the indirect-call
  rendering. The metric in section 8 decides; the fallback is a call fixup in the
  compiler spec.
- **Prologue-based function discovery can create false functions** in data. Limit it to
  bytes no function covers, and watch the decompile-failure count.
- **A log string can sit in a helper**, not in the function it names. Rule 1 in section 6
  limits this; the source column keeps guesses traceable.
- **The export contains vendor code.** It stays out of git along with the Ghidra project.

## 10. Out of scope

Types and structs, hand cleanup, peripheral register names, any patch, any device
access, and a source tree that compiles.

## 11. Amendments from planning (2026-10-08)

Measured on the backup while writing the implementation plan
(`docs/superpowers/plans/2026-10-08-v24-readable-decompile.md`). Where this section and
sections 5, 6 or 8 disagree, this section holds.

**Memory map (replaces the estimates in section 5).** The offsets in section 5 are
right; the bounds below are exact and come from two tables in the image.

| Run address | Flash source | Content | Evidence |
|---|---|---|---|
| `0x81c00680`–`0x81c01ad0` | `0x29d0`–`0x3e20` | boot loader's SRAM section | copy loop pool at flash `0x1460` |
| `0x81c01ad0`–`0x81c01f80` | `0x4490`–`0x4940` | SRAM, copied by the boot loop | pool at flash `0xdc4` |
| `0x81c01f80`–`0x81c08260` | `0x4940`–`0xac20` | SRAM text | range table at flash `0x1c4f8`; 24 of 32 call targets on a prologue |
| `0x81c08260`–`0x81c089e0` | `0xac20`–`0xb3a0` | SRAM data, then BSS | BSS bounds in the pool at `0xdc4`; `0x8800b3a0` is referenced from flash |
| `0x82000100`–`0x82000e60` | `0x105b0`–`0x11310` | RAM, copied by the boot loop | pool at flash `0xdc4` |
| `0x82000e60`–`0x82014d90` | `0x11310`–`0x25240` | RAM text | range table at flash `0x1c4f8`; 137 of 232 call targets on a prologue, the misses are leaf functions |
| `0x82014d90`–`0x8201d5e0` | `0x25240`–`0x2da90` | RAM data | zero padding at flash `0x2da80`, flash code from `0x2da90` |
| `0x8201d5e0`–`0x82101f30` | not stored uncompressed | code unpacked at boot | 209 call targets from `0x8201d620` up; BSS starts at `0x82101f30` |

What copies the two text ranges, and what the `0x882d76e0` entry in the same table
means, is **unverified**: the plan reads that code once it is decompiled (Task 3).
The text ranges are loaded read-only, the data ranges writable.

**The packed range starts at `0x8201d5e0`, not `0x82020000`.** It holds 209 of the 518
missing call targets, not 161. Section 8's "0 for RAM below `0x82020000`" becomes "0 for
RAM below `0x8201d5e0`" (248 targets).

**The image bytes are also hidden at their flash address.** Left executable there, the
RAM code would be analysed a second time at the wrong address. The build carves those
flash ranges into non-executable blocks.

**ROM: the ELF is not needed.** `firmware/live/2026-10-08-loader-audit/rda-rom.map`
(saved by the loader audit) has every one of the 24 ROM call targets as a symbol start:
`memcpy`, `memset`, `strlen`, `sprintf`, `atoi` and so on. Its ROM version, `0x51612152`,
is the value read from this chip. The ROM is loaded as a block with no bytes and the
referenced addresses are named from a committed `tools/ghidra/v24_names.rom.tsv`. One
loose end: the boot loader's pool at flash `0x148c` holds `0x51608222`, the version in
the SDK's `u01` ROM definition. What the boot loader compares it with is **unverified**.

**Name rule (section 6, source 1).** The identifier must contain an underscore. That is
the rule that reproduces the counts in section 2: 798 distinct leading identifiers in
the raw flash strings, 151 `sms_*` and 185 `*_handle`. A name is applied only when it is
one-to-one: one function prints the identifier and that function prints no other.

**Build facts.** A stock headless import and analysis reproduces the baseline exactly
(8,521 functions) and takes about 9 minutes on this Mac, so a full build is about 25.
`analyzeHeadless` exits 0 when a script throws; the build checks for a completion line
from every script instead.
