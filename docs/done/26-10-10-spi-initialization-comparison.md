> **Archived 26-10-11.** The current, reconciled account is [rom-flash-access.md](../knowledge/rom-flash-access.md). This note is kept as the dated record of the work; statements here may be superseded there.

# 412 SPI initialization comparison — offline, 2026-10-10

The comparison is complete. **The failed readers did not reproduce the working
programmer's startup, and the direct ROM path did not reproduce its MMIO access
width.** Neither difference is a demonstrated hardware fix. 412's license bytes
remain unmeasured.

This work used existing local files only. No USB device was opened, no device
command was sent, and neither disabled reader was re-enabled. The last hardware
state remains the [verified recovery at 16:57:05 UTC](26-10-10-security-reader.md):
412 waiting in ROM, diagnostic v2 installed, boot word blank, core/application
and its own factory/calibration tail intact.

## Evidence checked against the actual binaries

[audit_rda_spi_initialization.py](../../tools/audit_rda_spi_initialization.py) checks
six pinned evidence hashes, compares every loaded programmer LOD word against the
ELF, compares the SDK ROM's allocated bytes against the measured ROM, checks
compiled startup/receive instructions, and executes the ROM's actual short
`memcpy` path with delay slots. It imports no USB module and performs no device
I/O. The comparison passed **16 checks**.

- Working clean programmer ELF: `0f81ea0f…ada13a2`; LOD: `c238911d…bff6c65`.
  All **11,854 LOD words** equal their ELF bytes. This is the corrected programmer
  with the broken 104 MHz clock request removed and charging set to 200 mA.
- Measured ROM: `3946ea19…4680d7`. All **20,984 allocated SDK ROM bytes** match
  the saved read, including code, version and CRC. Padding between ELF sections
  is not part of that comparison.
- Corrected failed RAM payload: `444591d1…df12a1f`.
- Recovery controller snapshot: `6e2d3a1a…934af5`, 56 bytes.

Full hashes, checks and instruction traces are in the
[JSON report](../../firmware/live/2026-10-10-spi-initialization-comparison-final.json).
The existing programmer, helper payload and helper audit manifest were unchanged.
To repeat the comparison without writing a report:

```sh
.venv/bin/python tools/audit_rda_spi_initialization.py
```

## Controller config: the precise differences

Definitions are from the pinned SDK's 8955 `spi_flash.h`, confirmed against the
compiled `hal_SpiFlashOpen` at `0x81c038a0`. The recovered ROM state was measured;
the programmer column describes its compiled writes, rather than a saved live
register snapshot.

| `spi_config` field | Measured ROM `0x8a0` | Programmer `0x291` |
| --- | --- | --- |
| Quad main-array read, bit 0 | Off | On |
| WP/HOLD pin flags, bits 1/2 | Both clear | Both clear |
| Sample delay, bits 4–6 | 2 | 1 |
| Bypass start command, bit 7 | **On** | **On** |
| Divider, bits 8–15 | 8 | 2 |
| Quad command, bit 16 | Off | Off |
| Receive-size mode, bits 17–18 before transaction | 0 | 0 |

Bypass is already set in ROM; adding it is not a correction. Quad array reads are
distinct from command lane selection. The JEDEC command is single-line in both
implementations. A slower divider or a different sample delay can affect a
transaction, but these definitions do not prove why the host stopped receiving.

The failed ROM JEDEC attempt changed receive-size mode to 3, producing `0x608a0`,
and block size to `0x300`. Under the programmer's base config, the equivalent
JEDEC receive config would be `0x60291`. Both encode a three-byte receive using
the same controller framing. The RAM helper also preserved the original base
config while changing receive-size bits; it never established the HAL base config.

## The working programmer initializes clocks before its first JEDEC

The compiled order is more extensive than the call in `main()`:

1. `boot_MemInit` sets system frequency to 26 MHz, calls `boot_SysSetupPLL`
   at `0x81c00f7a`, then initializes ISPI, core voltage and external RAM.
2. `boot_SysSetupPLL` at `0x81c01640` unlocks sysCtrl. If PLL lock is absent it
   writes PLL control `0`, then `0x11`, waits for lock and enables fast output
   with bit 12. At `0x81c016a8` it writes **zero to `Sel_Clock` (`0xa1a00048`)**.
   That selects fast sources, including SPI flash: its slow-select bit 10 is clear.
   It then locks sysCtrl and restores the critical-section state.
3. Boot memory init writes `0x210` to **`0xa1a25014`** at `0x81c00fda`, a legacy
   controller setup carried in this build. The 8955 SPI register header and
   hardware XML name `0xa7fff000` as the SPI controller. The offline comparison
   has not established the legacy address's alias or necessity; do not add it
   to a new MMIO allowlist based solely on the source comment.
4. At `0x81c00fdc`, `memd_FlashOpen` calls `hal_SpiFlashOpen` from
   `0x81c05aa6`, **before `main()`**. SPI open writes `9` to `Cfg_Clk_SpiFlash`
   (`0xa1a000ac`), then `0x291` to `spi_config` (`0xa7fff014`). The clock selector
   chooses a nominal 156 MHz fast source; divider 2 gives nominal 78 MHz SPI.
5. SPI open sends flash reset-enable/reset `66/99`, waits 100 microseconds, reads
   JEDEC `9f`, reads SR2 `35` and conditionally sets QE through write-enable and
   status write. After PMD setup and watchdog close, `main()` calls it again at
   `0x81c02118`.

The obsolete 104 MHz `hal_SwRequestClk` is absent from this working startup.
It failed because its software clock object was uninitialized; reinstating that
request would reproduce an already resolved failure.

ROM's compiled `boot_HostUsbClockEnable` (`0x81e02fe8–3010`) powers the PLL, waits
for lock and enables fast output for USB. **It does not write `Sel_Clock` or
`Cfg_Clk_SpiFlash`.** USB responsiveness therefore establishes neither the selected
SPI source nor its divider input. Main-array reads demonstrate a functioning
array-read path; they do not establish the host command path.

The retained ROM evidence has no sysCtrl clock/reset snapshot. The actual
`Sel_Clock`, `Cfg_Clk_SpiFlash`, SPI clock-enable and SPI reset state at the failed
transaction are unknown. A blanket claim that the PLL was off is unsupported.
So is a claim that writing `0x291` alone will fix it.

Copying `hal_SpiFlashOpen` wholesale would add flash reset and possibly a
nonvolatile QE write. It is not a strictly storage-immutable replacement reader.

## Direct ROM “word writes” actually use byte stores

The ordinary ROM USB decoder at `0x81e034a4` calls `memcpy`, regardless of the
request's word-access encoding. Read-reply generation at `0x81e030ba` also calls
`memcpy`. The mask-ROM implementation at `0x81e03b10` chooses its byte-copy loop
for **every size below 16 bytes**, including an aligned four-byte request.

Executing those actual instructions offline for the nominal JEDEC command
`0x19f00` produces four stores from `0x81e03cb4`:

| CPU destination | Store width | Value |
| --- | --- | --- |
| `0xa7fff000` | 1 byte (`sb`) | `0x00` |
| `0xa7fff001` | 1 byte (`sb`) | `0x9f` |
| `0xa7fff002` | 1 byte (`sb`) | `0x01` |
| `0xa7fff003` | 1 byte (`sb`) | `0x00` |

The nominal four-byte controller-status read likewise performs four `lbu`
accesses, at `0xa7fff00c–0f`. The working HAL and RAM helper use aligned `sw/lw`
accesses. Thus sending command `82` does not ensure an atomic word MMIO store.
The prior SDK-source review established the call to `memcpy`, but incorrectly
treated its four-byte operation as equivalent to the HAL store.

Whether this peripheral honors byte enables, replicates byte data or triggers
on each store is not measured. Partial or repeated command latching is a possible
failure mechanism, not an observed bus trace. Do not describe the direct run as
isolating an otherwise identical HAL receive sequence. It only establishes that
ROM stopped answering after the nominal JEDEC submission.

A longer ROM write is not a safe way to force its word-copy path: it would span
neighboring live registers, including command/FIFO/config. No such workaround
was prepared or tried.

This finding cannot explain the RAM helper by itself; its MMIO accesses are
already word-sized. The helper's stopping instruction was not recovered before
RST, and the post-RST random result bytes cannot identify its progress.

## What the earlier simulator proves, and what it omits

The previous helper simulator validates the compiled CPU path, ABI, framing,
data order and permitted destinations. It synthesizes a response when a valid
command is stored; it does not model the SPI clock source, sampling, reset mode,
MMIO bus completion or flash reset requirements.

Running the exact same corrected payload under that model with base config
`0x8a0` **and** `0x291` succeeds in both cases: 133 transactions and restored
config. That result exposes the model's limitation. It cannot distinguish the
failed ROM initialization from the working HAL initialization and cannot qualify
a config change as a fix.

Likewise, a finite busy loop bounds instruction execution only while its MMIO
loads complete. A stuck bus load/store can prevent the timeout handler and return
path from running. The earlier busy-timeout scenario modeled a responding status
register that keeps reporting busy, not an unresponsive bus transaction.

## Concrete next measurement

**Subsequent outcome:** this snapshot was captured, and the SRAM-only return
control failed before any JEDEC probe was attempted. Recovery verification at
17:28:53 UTC passed. See [staged outcomes](26-10-10-rom-jedec-probe.md);
the sequence below is retained as the original plan, not a pending hardware retry.

Before another SPI command, capture a **handshake-and-memory-read-only** ROM
snapshot of the following fixed words, in a fresh evidence directory:

| Address | Purpose |
| --- | --- |
| `0xa1a00004` | Sys reset bits; SPI reset bit 23 |
| `0xa1a00038`, `0xa1a0003c` | Other-clock mode/enable state; SPI clock bits 19/20 |
| `0xa1a00044`, `0xa1a00048` | PLL control, lock indication and SPI source selection |
| `0xa1a000ac` | Selected SPI fast-source frequency |
| `0xa7fff000–0xa7fff034` | Controller baseline; compare the existing 56-byte snapshot |
| `0xa1c001d8` | ROM USB-context pointer; establish live stack/buffer ownership |

Avoid reading the SC critical-section register (`0xa1a01014`), whose read changes
interrupt state. Prefer controller ranges `0xa7fff000–004` and `0xa7fff00c–034`
to omit FIFO data (`spi_data_fifo_wo`, offset 8). The earlier 56-byte baseline
included that port; a new capture need not access it again.

The pointer check matters before placing another returning helper: ROM owns a
`0x1114`-byte USB context on its stack, while the working programmer replaces that
context and runs without returning. Its success alone does not qualify the
returning helper's result/stack placement.

After those values are known, a candidate diagnostic should establish the required
volatile SPI source/config using true word MMIO, record a checkpoint before and
after **one JEDEC read**, and restore exact saved settings if accesses complete.
It should first demonstrate SRAM-only execution/return and allocation separation.
Adding flash reset, QE setting or security-register reads at that stage would
combine unresolved variables. This is a reviewable next design, not a runnable
or hardware-qualified correction. Both failed live reader entry points remain
disabled.
