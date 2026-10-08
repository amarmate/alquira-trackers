# V24 cached flash identity and startup comparison — 2026-10-08

The user supplied another model's analysis. The findings below were checked
against local vendor decompilation, the pinned SDK sources and built-programmer
disassembly. No tracker command was sent in this review. The single cached-ID
read awaits the approval explicitly requested in the supplied procedure.

## Cached identity: verified read location

`firmware/decompiled/82000000.c`, `FUN_820004e4` at line 347, sends `0x9f`
through `FUN_82000418`, then stores these bytes:

| Address | Meaning |
| --- | --- |
| `0x81c01f50` | `checkirq`, initialized to zero |
| `0x81c01f51` | JEDEC manufacturer |
| `0x81c01f52` | JEDEC memory type |
| `0x81c01f53` | JEDEC capacity code; expected `0x16` for 4 MiB |
| `0x81c01f54` | High-performance opcode, `0xa3` only for manufacturer `0xef` |

One four-byte read starting at `0x81c01f50` obtains the first four rows.
It does not read the opcode byte or flash status/QE. This is a boot-cached ID,
not a new transaction with the SPI flash. A JEDEC result identifies a device
family; it may not uniquely establish package, voltage suffix or silicon revision.

The programmer's context at `0x81c076f0` instead has a raw ID at +4 and
manufacturer/type/capacity at +8/+9/+10. Do not use those offsets for vendor RAM,
or interpret the entire vendor four-byte word as the programmer ID. Construct
the writer's ID as `manufacturer | type << 8 | capacity << 16`.

`tools/rda_flash_identity.py` defaults to an offline plan. Its only device
memory request is the fixed frame `ad 00 07 ff 02 50 1f c0 81 03 f0`.
It verifies a single existing `1e04:0900` / `RDA Usb` interface, refuses queued
data, checks response framing/checksum, and logs the request, raw response and
decoded bytes in a new file under `firmware/live/`. It does not set USB
configuration, reset, retry the request, launch code or send SPI/memory writes.
Standard USB descriptor queries and bulk response reads accompany that request.
The read does not establish the physical unit's identity.

Offline verification checked the request against the existing word-read frame
builder, decoded synthetic data using the vendor offsets, and rejected truncated,
bad-header and bad-checksum replies. Synthetic data is not hardware evidence.

## Flash clock/config comparison: both constants match

Vendor `FUN_820008f8`, beginning at line 641, writes `9` to `0xa1a000ac`
and `0x291` to `0xa7fff014`.

The actual programmer disassembly at `0x81c04518` (`hal_SpiFlashOpen`) loads
`9` into `a3`, stores it at sysCtrl + `0xac`, adds `648` (`0x288`) to that
same value, and stores `657` (`0x291`) at spiFlash + `0x14`.

| Setting | Vendor | Built programmer |
| --- | --- | --- |
| `Cfg_Clk_SpiFlash` | `9` | `9` |
| Selected source clock | 156 MHz | 156 MHz |
| `spi_config` | `0x291` | `0x291` |
| Clock divider field | 2 | 2 |
| Nominal SPI flash clock | 78 MHz | 78 MHz |
| Sample-delay field | 1 | 1 |
| Quad-read / bypass-start-command | Both enabled | Both enabled |

The SDK's 8955 `sys_ctrl.h` maps value `9` to 156 MHz; `spi_flash.h`
decodes `0x291` as sample delay 1, divider 2, quad read and bypass start command.
The build target also selects `SPI_FLSH_78M`. These are programmed settings,
not measured clocks. The programmer's separate 104 MHz system-clock request
does not mean that its SPI flash clock is 104 MHz. Matching these two registers
does not establish all PMD, clock-source, RAM or startup behavior.

Both implementations reset with `0x66/0x99`, wait 100 microseconds, read status
2 (`0x35`), and conditionally write status registers to set QE if bit 1 is clear.
Both preserve the read status-1 byte when writing the two status bytes.
There is an ordering difference: the vendor reads/caches JEDEC after the QE
branch; the programmer reads/caches JEDEC before it. Their startup code is
therefore similar, not byte-identical.

The vendor's own initialization supports the inference that QE is already set.
It does not measure its current value or establish how the particular device's
QE state behaves across the programmer's flash reset. The previous framing that
this conditional write is unique to the programmer was too strong.

Programmer ELF SHA-256 rechecked:
`858fd6bd6308e9d61ab8ee188cef53e5d0b4ccf29a91edb41e673ee4ac3a99c7`.
LOD SHA-256 rechecked:
`8a3ea6257de0c4d584d9f04d8e19db73ee54d8eee0a47fc3ddcaebb2f8af9dd1`.
Sources and disassembly remain under `firmware/live/usb-programmer-build/`;
SDK commit is `b2b6287e8fa9a9f49b679a357b49beb1c31d821c`.

## ROM entry: shared destination, diagnosis still open

The 8955 SDK `boot_sector_chip.c:45` sets the force bit in `g_bootBootMode`
and calls `boot_Monitor()`. The boot-sector route and direct force-monitor reset
converge on the same ROM monitor, though their paths before that point differ.
The second attempt did not test an alternative USB-monitor implementation.

`boot_monitor.c:161` calls `boot_HostUsbClockEnable()` before `boot_UsbOpen()`
and before entering the loop that handles commands and the idle timeout.
The active implementation in `boot_usb_monitor.c:935` waits for PLL lock
without a timeout. `boot.h:28` sets the idle timeout to 30 seconds; that check
only runs once initialization reaches the monitor loop and requires valid flash
magic. Thus that timeout cannot recover an earlier PLL-lock hang.

Local filesystem timestamps place the reset at approximately 17:00:48 Lisbon
and the end of the last observation at 17:01:55. The retained polls cover
17:01:05–08 and 17:01:25–55, with no USB device reported. This is not a continuous
67-second capture, nor proof that control never returned to firmware. It shows
no observed successful USB recovery beyond the normal idle-timeout duration.

The saved 24 KiB ROM hash was rechecked as
`3946ea195270620f0907997f96f32fbaa1e2ab405146235fef2afb5f3c4680d7`,
the previously established SDK-ROM match. The PLL hang remains a hypothesis;
power loss, earlier stalls and unsuccessful later recovery are not separated
by these USB observations.

Host-port activity could provide useful positive evidence of execution, but
silent HST_TXD would not by itself prove power loss. In this source,
`BOOT_PROFILE_PULSE` is empty, and the host START event is emitted in response
to a command in the monitor loop; unsolicited progress events cannot be assumed.
The always-enabled debug-host monitor also differs from the optional UART monitor,
which requires `BOOT_MODE_UART_MONITOR_ENABLE`. Host-port access is a possible
recovery route, not yet a verified replacement for this board's USB path.

A later hardware diagnosis would need identified pads, correct electrical levels
and board-rail observations alongside host-port capture. No new reset is justified
by this source comparison. Erase/write/restore qualification remains pending on
a backed-up spare, and the existing writer's original-unit block is unchanged.
