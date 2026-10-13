> **Archived 26-10-11.** The current, reconciled account is [logicrom-core.md](../knowledge/logicrom-core.md). This note is kept as the dated record of the work; statements here may be superseded there.

# LogicROM license storage: offline findings, 2026-10-10

This investigation used existing files only. It did not reset, query, register,
flash or otherwise operate either device. It supersedes the suggestion that the
saved ordinary flash dumps can establish whether 412 has a stored license.

**Latest live result: blank license record, measured at 18:47:12 UTC.** The
reviewed `0xfc` helper returned with error 0, JEDEC `0x1660c8`, 133 commands,
and two identical 256-byte security passes, entirely `ff`. Status `0x021c`,
clocks and persistent controller settings were restored; all four full flash
reads matched the recovery baseline. Final verification completed at 18:48:14 UTC.
[Run and result](26-10-10-rom-extended-handler.md#security-read-through-this-arm--passed-at-184712-utc),
[journal](../../firmware/live/2026-10-10-logicrom-412-security-fc-1/operations.jsonl).
The traced all-`ff` reader path supplies length zero and the validator returns
14, so normal activation is a demonstrated prerequisite for this image. That
runtime return code was inferred from the pinned code, not captured live. No
activation, third-party contact or device reset/exit was attempted.

Earlier live follow-up: the authorized `secr` run at 16:32:44 UTC produced command echo,
zeros and readable SIM/GSM registration messages, but no security dump. Both the
initial and ABI-corrected returning RAM readers timed out. A direct ROM MMIO path
then stalled on JEDEC before sending any security read. Live reader entry points
are disabled until the SPI startup difference is understood. See the current
[measurement and reader audit](26-10-10-security-reader.md). The
[completed SPI startup comparison](26-10-10-spi-initialization-comparison.md)
found missing startup settings and ROM byte accesses in nominal word transfers;
neither is a demonstrated correction. A subsequent [SRAM-only return control](26-10-10-rom-jedec-probe.md)
also failed with no SPI access; JEDEC was not attempted, and 17:28:53 UTC recovery
verified the unchanged flash and restored controller/clocks. The findings below
remain the original offline trace; the latest live result above resolves its
blank-record condition.

## Findings

The installed diagnostic image contains the expected 16-byte `LROM_SDK_APPCODE`
and a nonzero application init pointer. Its bytes do not support an APPCODE
mismatch. Successful loader and descriptor checks alone do not establish that
the runtime selected or called the application.

The license gate is separate. Startup at `0x8823036e` calls `0x88233bcc`; a nonzero
result replaces the selected descriptor with the built-in descriptor at
`0x88244434` (`0x8823038e`). The selected init callback is called at `0x882303f2`.
There is also a module-selection check on the license-success path.

The previously missing validator can be reconstructed from the initialization
block copied from `0x882454a0` to `0x82300000`. The caller transforms the stored
key and IV, then AES-CBC decrypts 432 bytes at `0x82300110`. The recovered entry
at `0x82300144` requires a 48-byte decoded record, decrypts it, compares its
identity field against a value derived from the device UUID and IMEI, and checks
the serial with the core's Luhn routine. Observed return paths in the code:

| Return | Condition |
| --- | --- |
| 14 | Decoded input length is not 48 bytes |
| 13 | License decryption routine reports an error |
| 5 | Device identity retrieval fails |
| 6 | Identity comparison fails |
| 1 | Serial check fails |
| 0 | Checks succeed |

These are reconstructed code paths, not measured results from 412.

## The license is outside the ordinary flash dump

`0x88233bcc` asks `0x88232a84` for 96 bytes from record index 0. That reader maps
index 0 to address `0x1000` and calls the core vtable slot at offset `0x5ac`.
The vtable at `0x88204468` contains pointer `0x820011ed` in that slot.

The boot copy maps flash `0x8801b7e0–0x8801caf0` to RAM
`0x82000b00–0x82001e10`. Its routine at `0x820011ec` sends SPI opcode `0x48`,
three address bytes and one dummy byte, reading up to four bytes per transaction.
This agrees with `hal_SpiFlashSecurityRead` and `OPCODE_SECURITY_READ` in the
existing RDA SDK. Separate security program/erase routines use `0x42`/`0x44`.

**The address is in the SPI flash security registers, not main-array offset
`0x1000`, and not `/nvm`.** The saved 4 MiB main-array images do not include it.
Those images cannot distinguish an absent license from a present, rejected one.

If the first 96 security bytes are all `ff`, the reader clears the buffer and
returns zero bytes; the validator receives length zero and returns 14. That
would deterministically select the built-in console. The authorized security
read at 18:47:12 UTC measured exactly this all-`ff` condition on 412.

## Next experiment

This proposed capture sequence is historical. The successful independent
security read above has answered the blank-versus-present question; another
`secr` boot or helper run is unnecessary. Normal activation remains subject to
the user's no-Waybyte constraint. Continue USB/console diagnosis separately;
no activation workflow is authorized by this read-only measurement.

The built-in console already has a `secr` command, although its help list omits
it. The branch at `0x8823aedc` matches the literal at `0x882441f0`, calls the same
security reader for 256 bytes at `0x1000`, and prints a hex dump. This command
path reads the registers; it does not program or erase them.

First prepare a bounded capture that sends `secr\r` promptly on the next
authorized start of the existing installation. A complete 256-byte dump, ideally
repeated identically, answers whether the record is blank or present. Command
echo, NUL bytes or incomplete output do not answer that question. Ordinary core
startup can still write its filesystem; a console read is not a claim that the
whole boot changes no storage.

Prepared capture command (reviewed offline, not executed):

```sh
.venv/bin/python tools/logicrom_console.py \
  --output firmware/live/2026-10-10-logicrom-412-license-secr-1.jsonl \
  --seconds 120 --send secr --send-after 1 --ending cr \
  --baud 115200 --dtr on --rts on
```

Start the logger before the separately authorized core start. The existing
logger sends at most one command. This reuses the prior active capture's serial
settings and requires no firmware replacement. It does not supply or authorize
the device-start operation. An incomplete result ends this attempt; prepare the
independent reader instead of repeating long install/restore cycles.

If the broken console prevents a complete capture, prepare and audit a RAM-only
security reader offline before requesting its own device run. The existing
`--read-status` programmer command does not read security registers, and its
startup can set flash QE; do not describe it as an already qualified strictly
read-only substitute.

A blank record makes activation a demonstrated prerequisite for this LogicROM
image. Self-service `getlic` still uses Waybyte's service, so it must be reconciled
with the user's existing no-Waybyte constraint. A present record requires an
identity/validation investigation; presence alone does not prove acceptance.

Keep the 10-second USB timer as a separate diagnostic hypothesis. Enumeration and
data exchange do not prove timer cancellation: the traced transition to state 4
is on suspend. The live USB state at disconnect is still unmeasured. A timer
experiment may help console access, but cannot make a rejected license pass.

## Reproduction and artifacts

The pinned corrected core is
`firmware/live/2026-10-10-logicrom-offline/core-nvmfix.bin`, SHA-256
`aae113419a716f04defd2375e8ece913af67bf02c6159e7d682a72b7199c643a`.
The decoded validator SHA-256 is
`8287d3697273da63965d680c07f1ff67730e26161f1756e09bf3aceb88a6bc27`.

Run `python3 firmware/live/2026-10-10-logicrom-offline/extract-license-trace.py`
to reconstruct and check the code from the pinned core. It uses local OpenSSL
and GNU objdump, asserts the source and decoded hashes, and writes focused
disassemblies plus metadata under the adjacent `license-trace/` directory.
It performs no device I/O and creates no activation record or firmware patch.
