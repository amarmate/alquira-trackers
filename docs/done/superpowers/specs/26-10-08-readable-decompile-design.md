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
| Patching a device | binary patches built on B | gated on the flash-restore work in `26-10-08-flash-restore-spec.md`; not planned here |

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
strings in their bodies match the log lines captured in `26-10-08-firmware-analysis.md`
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

## 11. Amendments from planning and implementation (2026-10-08)

Found while writing and running the implementation plan
(`docs/done/superpowers/plans/26-10-08-readable-decompile.md`). Where this section and
sections 2, 5, 6, 8 or 9 disagree, this section holds. Everything here was read from the
backup or from the decompile it produced, unless marked **(unverified)**.

### 11.1 Memory map (replaces section 5)

The second-stage boot loader is the function at flash `0x3ebc` (`boot_LoaderEnter` in the
public SDK). Its copy loops give the ranges. It then write-protects the code ranges with
`hal_DbgPageProtectSetup(page, WRITE_TRIGGER, start, end)`, which is how text is told
from data. Text is loaded read-only, data writable.

| Run address | Flash source | Content | Evidence |
|---|---|---|---|
| `0x81c00280`–`0x81c00430` | `0x42e0`–`0x4490` | SRAM interrupt code | copy loop; protected page 6 |
| `0x81c00680`–`0x81c01ad0` | `0x29d0`–`0x3e20` | first-stage boot loader's own section | first stage's pool at flash `0x1460` |
| `0x81c01ad0`–`0x81c01f00` | `0x4490`–`0x48c0` | SRAM boot code | first stage's pool at flash `0xdc4`; protected page 7 |
| `0x81c01f00`–`0x81c01f80` | `0x48c0`–`0x4940` | SRAM boot data | copied with the row above, not protected |
| `0x81c01f80`–`0x81c08260` | `0x4940`–`0xac20` | SRAM text | copy loop; protected page 3 |
| `0x81c08260`–`0x81c089e0` | `0xac20`–`0xb3a0` | SRAM data | same copy loop; BSS from `0x81c089f0` |
| `0x82000100`–`0x82000e60` | `0x105b0`–`0x11310` | RAM boot code | first stage's pool at flash `0xdc4`; protected page 8 |
| `0x82000e60`–`0x82014d90` | `0x11310`–`0x25240` | RAM text | copy loop; protected page 2 |
| `0x82014d90`–`0x8201d5e0` | `0x25240`–`0x2da90` | RAM data | same copy loop |
| `0x8201d5e0`–`0x82050260` | `0x2d7860`, 123 KiB LZMA | code | see 11.2 |
| `0x82050260`–`0x820eab40` | `0x2f6300`, 375 KiB LZMA | mostly read-only data, some code | see 11.2 |
| `0x820eab40`–`0x82101e80` | `0x353f80`, 54 KiB LZMA | code | see 11.2 |
| `0x82101e80`–`0x82400000` | none | variables and BSS (cleared `0x82101f40`–`0x8223ab60`) | BSS loop; page 9 guards from `0x82400000`, so RAM is 4 MiB |
| `0x81e00000` | none | chip ROM, names only | see 11.4 |
| `0xa1a00000`–`0xa1a40000` | none | system registers, volatile | pool words |

The table at flash `0x1c4f8` that planning took for a copy table is an "is this a code
address" check. Its last entry, `0x882d76e0`, is the end of the flash image proper.

### 11.2 The packed RAM code is resolved (replaces the first item of section 9)

It is three LZMA streams with the standard `.lzma` header. The loaders at flash
`0x1620a4`, `0x162108` and `0x162170` each look up a segment, unpack it and check it:

| Segment | Flash | Destination | Unpacked | Checksum the firmware expects |
|---|---|---|---|---|
| 0 | `0x2d7860`–`0x2f62d2` | `0x8201d5e0` | `0x32c80` | `0x8a7ac17c` |
| 1 | `0x2f6300`–`0x353f52` | `0x82050260` | `0x9a8e0` | `0x76212f3e` |
| 2 | `0x353f80`–`0x36180e` | `0x820eab40` | `0x17340` | `0x25f19f18` |

The checksum routine (`0x8200e0c8`) is the POSIX `cksum` CRC. Computed over each
unpacked segment on the host it gives exactly those three values, so the unpack is
byte-exact. `SetupMemory.java` unpacks the segments with the LZMA library that ships
with Ghidra and loads them read-only: in the public SDK's linker script
(`compress_code_section_3264.ld`) these sections take only `.text` and `.rodata`.
That this firmware's script does the same is **(unverified)**; it is one SDK version
older and vendor-modified.

So the 576 KiB at `0x2d0000` is not audio. `0x290000`–`0x2d76e0` is a pointer table and
UI images; `0x2d7750` is the segment locator function; the packed code runs from
`0x2d7860` to `0x361892`; the flash is blank from there to `0x37a000`.

### 11.3 Import range and flash layout (changes section 5's first row)

The whole 4 MiB is imported, not `0x000000`–`0x290000`. The code points at a pointer
table at `0x290000` (175 pool words), at the packed segments, and at the settings and
factory areas; with the short import those references dangle.

| Flash | Loaded as |
|---|---|
| `0x000000`–`0x238720`, minus the load images above | code, read-only, executable |
| the load images of the copied sections | read-only, not executable: analysed there they would be a second, wrong copy of each function |
| `0x238720`–`0x362000` | data, read-only, not executable. Flash code ends at `0x238704`; with the string tables executable Ghidra finds "functions" in them |
| `0x362000`–`0x400000` | data, writable: file system, settings, calibration, factory block are rewritten at run time and must not read as constants |

### 11.4 ROM: the ELF is not needed (replaces the ROM row of section 5)

`firmware/live/2026-10-08-loader-audit/rda-rom.map` (saved by the loader audit) has
every ROM address the firmware calls as a symbol start: `memcpy`, `memset`, `strlen`,
`sprintf`, `atoi` and so on. Its ROM version, `0x51612152`, is the value read from this
chip. The ROM is a block with no bytes; the referenced addresses are named from the
committed `tools/ghidra/v24_names.rom.tsv`. One loose end: the first-stage boot loader's
pool at flash `0x148c` holds `0x51608222`, the version in the SDK's `u01` ROM
definition. What it is compared with is **(unverified)**.

### 11.5 Why the old export had no strings (corrects section 2)

Two causes, both needed. The flash block was writable, as section 2 says. And
`ExportC.java` never passed options to the decompiler, which then ignores read-only
memory altogether. The baseline also has 0 string literals, not 6: the six lines are
the character literal `'\"'`.

### 11.6 Function discovery (refines section 4's FixCode row)

`FixCode.java` runs in both Ghidra runs and creates functions in four places:

1. direct call targets where Ghidra had defined a data word instead of code;
2. MIPS16 code pointers found in any loaded memory (bit 0 set, 4-aligned target);
3. the frame idiom in bytes that are not code yet: `addiu sp,-N`, `sw ra` within eight
   instructions, and the matching `jr a3` with `addiu sp,+N` in its delay slot. The
   prologue alone matches 8 places in the string tables; the full idiom matches none
   and keeps 9,727 of 9,871 matches in flash code;
4. runs of code that Ghidra disassembled but left outside every function, when
   nothing falls or jumps into them. Without this about 107 KiB of code is absent
   from the export.

### 11.7 Name rule (refines section 6, source 1)

The identifier must contain an underscore and may follow leading whitespace
(`"\n set_url_port.url:%s"`). In the raw flash strings that gives 798 distinct leading
identifiers, 151 `sms_*` and 185 `*_handle`. A name is applied only when it is
one-to-one: one function prints the identifier and that function prints no other.

### 11.8 Build facts

- A stock headless import and analysis reproduces the baseline exactly (8,521
  functions). Run 1 takes about 9 minutes, run 2 a few; the build about 15.
- `analyzeHeadless` exits 0 when a script throws. The build checks for a completion
  line from every script instead.
- Ghidra creates stub functions at call targets in blocks without bytes, so those
  calls render as `FUN_…`/names, not `func_0x…`. The export reports "called functions
  with no code behind them" per block; after 11.2 that is the ROM only.
