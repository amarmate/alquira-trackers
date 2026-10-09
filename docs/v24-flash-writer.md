# V24 flash writer: operator guide

Status, 2026-10-09 Lisbon: `tools/rda_flash.py` has an audited host implementation and
offline fault tests. **It is pinned to the clean programmer build `c238911d…6c65`,
which started on 417 in a separately authorized start-only run:** READY 0.54 s
after execute, mailbox, flash layout and JEDEC `c8 60 16` at the pinned addresses,
and two full reads through the programmer identical to the pre-start read.
Physical RST restored vendor USB; the recovery reads differ only by the vendor
firmware's per-boot record. The unmodified SDK build `8a3ea625…9dd1` never reaches
READY and the writer now refuses it.
See [the run report](v24-programmer-start-2026-10-09.md).
A later [query run](v24-programmer-start-2026-10-09.md#query-run-1-the-first-mailbox-commands-answer-and-the-flash-reads-back-unchanged)
on 417 sent the writer's start-up check: PING on both mailbox slots and
GET_FINALIZE_INFO answered, and the flash read back unchanged.
A [write test](v24-programmer-start-2026-10-09.md#write-test-run-1-program-and-erase-work-and-the-flash-ends-as-it-started)
then programmed both ends of blank sector `0x3e0000` on 417 and erased it: both
commands worked and the flash ended identical to the pre-start read.
END has never been sent to a tracker, no used sector has been written and no
restore has been qualified. Original `1403167417` remains blocked in the writer; its gates
are unchanged. The flash variant and status registers are still unqualified.
The user reported on 2026-10-08 that five
spare units are on hand. One, `1403167412`, was connected on 2026-10-09: its factory
block gives IMEI `869214031674127`, whose digits 5-14 are the label's ID. Two backups
of two passes each are in `firmware/backup/` (`v24_1403167412_2026-10-09_a_flash.bin`
and `_b_`), all four passes identical, SHA-256 `b0250296…a2c4`. Its code,
`0x000000`-`0x360000`, is byte-identical to 417's, word 0 is `0xd9ef0045`, and block
`0x3e0000` is blank. Nothing has been written to it. The other four are untouched.
At 22:45 UTC the same day a forced warm reset did bring up the ROM monitor on the
original (`Coolsand Usb`, handshake answered); see
[Run B](v24-loader-audit-2026-10-08.md#run-b-forced-rom-entry-works-on-1403167417).
Statements below that ROM entry failed predate it.

The later [cached-ID and startup review](v24-cached-flash-id-review.md) identifies
the vendor's cached JEDEC bytes at `0x81c01f51..53`. The authorized four-byte read
at `0x81c01f50` succeeded at 17:29:58 UTC: `c8 60 16`, GigaDevice, 4 MiB,
writer ID `0x1660c8`. Exact part variant and current QE/status remain unverified.
Vendor and built-programmer
flash clock/config constants match (`9` and `0x291`), and both contain the
conditional QE write. Board photos are not a prerequisite for this identity read.

The implementation currently accepts live evidence only for a backed-up spare
experiment (`spare_writer_test`). There is no force override, automatic reset,
restart, chip erase, factory write or resume command. A JSON file is a local
review gate, not a measurement or proof of safety.

## Offline use now

Run from the repository root; these commands never import PyUSB or discover USB:

```sh
.venv/bin/python tools/rda_flash.py \
  --unit 1403167417 \
  --backup firmware/backup/v24_1403167417_2026-10-03_flash.bin \
  --image firmware/backup/v24_1403167417_2026-10-03_flash.bin

.venv/bin/python -m unittest discover -s tools -p test_rda_flash.py -v

.venv/bin/python tools/rda_lod_audit.py \
  firmware/live/usb-programmer-build/clean/artifacts/usb_8955_flsh_spi32m_ramrun_noclk_200ma.lod
```

The first example prints `OFFLINE_PLAN`, all image hashes, `sectors: []`,
`finalize_boot_magic: false` and `hardware_validated: false`. This is intentionally
a no-change example; it proves neither erase/program nor recovery. Add
`--current path/to/snapshot.bin` to compare another local snapshot with the target.
Without `--current`, the baseline backup is used as the current image.

All images must be exactly 4 MiB. The target must contain boot magic `0xd9ef0045`
and have exactly the backup's bytes in `[0x3fa000,0x400000)`. The current image must
also match that protected tail. Unit identity is physically confirmed by the
operator; a generic USB serial number does not establish it.

## What the writer does

The pinned LOD SHA-256 is
`c238911dc478363b1dffdebbffcc407e6e1b1b51ef5c53c9d90ca2fe8bff6c65`: the SDK's USB
programmer without its 104 MHz clock request and with the V24 charge current.
The [source/binary audit](v24-loader-audit-2026-10-08.md#host-writer-audit)
records protocol details for the unmodified build, and the
[re-pin review](v24-programmer-start-2026-10-09.md#writer-re-pinned-to-the-clean-build)
records what changed and what was checked again for this one.

Execution requires one device already in `Coolsand Usb` ROM mode. The writer
checks its handshake and full 24 KiB ROM hash, makes two matching full-flash reads,
and plans from those live bytes. A no-change result exits without loading code.
Otherwise it verifies the RAM load, starts the programmer and checks startup
events, fresh mailboxes, flash layout and the previously reviewed JEDEC identity.
This last check occurs **after startup** and cannot protect against startup QE
writes to an unidentified chip.

Changed non-boot sectors are erased/programmed first; sector zero is last.
Erase footprints are 64 KiB below `0x3f0000` and 4 KiB above it, stopping at
`0x3fa000`. Program chunks are 4 KiB, with complete RAM-buffer and sector readback.
The first boot word stays erased while sector zero is programmed. A complete
4 MiB comparison must pass before `FPC_END` writes that word; another complete
comparison follows. If sector zero is unchanged, `FPC_END` is not issued.
The tool leaves the device in the programmer; it does not reboot it.

The run directory must be new and inside gitignored `firmware/live/`. It contains
the source, unit backup, pre-startup and pre-write dumps, changed sectors' original
bytes, final readback, copied review reports and fsynced `operations.jsonl`.
No firmware bytes are printed. Plans contain unit IDs and hashes; keep redirected
plans and all qualification material under `firmware/live/` too.

Any failed transfer, device error, deadline or verification stops the run. The
tool does not retry destructive commands. Stopping the host cannot stop a device
already erasing, waiting for SPI completion or cycling RAM power. On failure,
retain the journal and power-state observations; do not automatically reset,
unplug or rerun. Recovery needs a reviewed entry/power procedure and fresh
readback. A successful write would still not prove cold recovery.

## Qualification evidence still needed

Do not create a passing qualification for the original from existing failure
logs, the simulator or this audit. First obtain a spare and follow the
[restore specification](v24-flash-restore-spec.md). Hardware experiments require
the separate decisions described there. There is no safe automatic command to
generate the missing hardware evidence today.

For each gate, create a local report with the physically confirmed unit ID,
date, procedure, actual observations, raw evidence paths and SHA-256 hashes,
reviewer and outcome. A report should identify limitations, not just say “pass”.

| Required report | How to obtain evidence and what a pass must establish |
| --- | --- |
| `two_matching_backups` | On the identified spare, capture two complete 4 MiB passes in stable vendor debug mode; compare bytes and hash them. Preserve both reads and the capture log, and bind the baseline hash to this physical unit. `rda_dump.py` compares two passes but saves only one; retain a second independently captured file and logs. The two historical original-unit backups differ in settings and are not interchangeable evidence for this gate. |
| `repeatable_rom_access` | Under an approved spare procedure, record repeated entry, sustained power, `Coolsand Usb` descriptors, handshake `0xff000001`, full ROM hash, stable reads and return/recovery observations. Record the number of trials and duration; one enumeration is insufficient. Diagnose the original's failed warm-entry attempt first; do not repeat it automatically. Warm ROM access does not prove blank-boot recovery. |
| `board_ram_power` | Match board PMD/GPIO, power rails, clocks and RAM to the build. Bound SRAM load/stack/BSS ownership, three 64 KiB external buffers, and startup writes at PSRAM offsets `0x3c0000..0x3c00ff` and `0x3fff00..0x3fffff`. Record measurements and a separately reviewed startup test on the spare, including absence of memory-failure/reset events. Do not run an unknown programmer to discover whether its RAM/power assumptions are safe. |
| `flash_chip_and_startup` | Establish the actual chip/JEDEC ID independently before launch, obtain its datasheet, and verify 4 MiB capacity, reset opcodes, status-register/QE semantics, protection bits, program pages and erase commands. Review PMD/clock/reset effects and the conditional status write. Preserve status observations before/after an approved spare startup. An unchanged array dump does not prove unchanged status registers. |
| `experiment_review` | Record the approved exact source hash, baseline, planned sectors and experiment. For a scratch test, prove the selected range is unused on that spare, specify a deterministic pattern and exact restoration procedure, and obtain the destructive-test decision. A blank sector alone is insufficient. Record whether sector zero is involved and the recovery route if the experiment fails. |

Hash the completed reports with `shasum -a 256 path/to/report.txt`. Assemble
`firmware/live/<spare-case>/qualification.json` using the schema below. Replace
every placeholder with measured or reviewed data; this example is deliberately
invalid and cannot enable execution. `flash_jedec_id` is a JSON integer containing
`manufacturer | type << 8 | capacity << 16`, with capacity byte 22 for 4 MiB.
Paths are relative to the qualification file's directory (absolute paths also work).

```json
{
  "schema": 1,
  "scope": "spare_writer_test",
  "unit": "PHYSICALLY-CONFIRMED-SPARE-ID",
  "backup_sha256": "BASELINE-SHA256",
  "source_sha256": "REVIEWED-TARGET-SHA256",
  "programmer_sha256": "c238911dc478363b1dffdebbffcc407e6e1b1b51ef5c53c9d90ca2fe8bff6c65",
  "rom_sha256": "3946ea195270620f0907997f96f32fbaa1e2ab405146235fef2afb5f3c4680d7",
  "flash_jedec_id": null,
  "evidence": {
    "two_matching_backups": {"path": "backups.txt", "sha256": "REPORT-SHA256", "result": "pending", "reviewed_by": ""},
    "repeatable_rom_access": {"path": "rom-access.txt", "sha256": "REPORT-SHA256", "result": "pending", "reviewed_by": ""},
    "board_ram_power": {"path": "board.txt", "sha256": "REPORT-SHA256", "result": "pending", "reviewed_by": ""},
    "flash_chip_and_startup": {"path": "flash.txt", "sha256": "REPORT-SHA256", "result": "pending", "reviewed_by": ""},
    "experiment_review": {"path": "experiment.txt", "sha256": "REPORT-SHA256", "result": "pending", "reviewed_by": ""}
  }
}
```

Each report must have `result: "pass"` and a named reviewer before the software
gate accepts it. Hash checking establishes file integrity, not truth: the tool
does not interpret reports, authenticate a reviewer, validate their linked raw
evidence or electrically identify the physical unit. A target change requires a
new experiment review and matching `source_sha256`.

With real reviewed files, check them **offline** by adding
`--qualification firmware/live/<spare-case>/qualification.json --check-qualification`
to the plan command for that spare and its reviewed image. There is no USB access.

Only after those gates and the hardware experiment decision are complete, the
same command may use `--execute` instead of `--check-qualification`, plus
`--lod firmware/live/usb-programmer-build/clean/artifacts/usb_8955_flsh_spi32m_ramrun_noclk_200ma.lod`
and `--journal firmware/live/<new-run-directory>`. Omit `--current`: execution
always reads the device. This is a future spare procedure, not an instruction to
flash the currently connected original. Do not run another tool holding USB at
the same time.
