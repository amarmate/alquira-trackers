# docs

Three folders, grouped by what a note is for.

| Folder | Holds | Naming |
| --- | --- | --- |
| `knowledge/` | Living reference: what is known, reconciled. Update in place. | `name.md`, no date |
| `in-process/` | Open work: the working summary, plans, trial histories still being added to. | `YY-MM-DD-name.md` |
| `done/` | Finished work, kept as the dated record. Do not update; supersede in `knowledge/`. | `YY-MM-DD-name.md` |

A note moves from `in-process/` to `done/` when its question is answered, and its lasting
findings are folded into a `knowledge/` doc. Archived notes carry a banner pointing at the
doc that replaced them. The date is the day the note was started.

## knowledge/

| Doc | Answers |
| --- | --- |
| [logicrom-core](knowledge/logicrom-core.md) | What the LogicROM 0.5.1 core does on the V24: app handoff and license gate, the 10 s USB timer, the console, reset paths, what is measured and what is not. |
| [rom-flash-access](knowledge/rom-flash-access.md) | How to enter the ROM monitor, load the RAM programmer, write and restore flash, run a returning helper, and what failed on the way. |
| [firmware-analysis](knowledge/firmware-analysis.md) | The vendor firmware: USB command channel, flash map, stored settings, command keywords, the Ghidra decompile. |
| [tracker-intel](knowledge/tracker-intel.md) | The vendor's SMS and TCP protocol, SIM requirements, setup procedure, frame examples. |
| [pin-map](knowledge/pin-map.md) | Which RDA8955 pin does what on the V24 board. |

## in-process/

- [26-10-10-agents-summary](in-process/26-10-10-agents-summary.md): current state, experiment ledger, traps, open questions. Read first.
- [26-10-11-battery-route-plan](in-process/26-10-11-battery-route-plan.md): the 30-days-on-battery plan.
- [26-10-09-logicrom-trial](in-process/26-10-09-logicrom-trial.md): the Logicrom trial history on spare 412.
- [26-10-10-tracker-app-skeleton](in-process/26-10-10-tracker-app-skeleton.md): offline tracker app design (parked with Logicrom).
