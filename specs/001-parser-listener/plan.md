# Implementation Plan: Wire Parser and UDP/TCP Listener

**Branch**: `001-parser-listener` | **Date**: 2026-11-01 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-parser-listener/spec.md`

## Summary

Build the DNS wire layer and the network front end of dnsd: a parser that decodes and encodes
complete RFC 1035 messages (name decompression on read, structured RDATA for A, AAAA, CNAME, NS,
PTR, MX, SOA, raw bytes otherwise), and a listener that serves UDP and TCP on the `--listen`
address, classifies each message per FR-008, hands valid queries to a single resolution handler
(a SERVFAIL stub in this feature), finalises and frames the response (ID, question, QR/RA,
OPT removal, 512-byte UDP truncation, TCP length prefix) and does all counting and logging.
It also fixes the inter-module interfaces (message model, Query/Outcome/handler, ServerState
and its five stores) as concrete Python signatures in [contracts/interfaces.md](contracts/interfaces.md),
which features 002–004 build on.

Approach: four files under `dnsd/`, standard library only. Frozen dataclasses for the message
model; `socketserver.ThreadingUDPServer` / `ThreadingTCPServer` with daemon threads for
concurrency; each stateful store owns one `threading.Lock`; errors printed to stderr.

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**: none (standard library only: `dataclasses`, `struct`, `ipaddress`,
`socketserver`, `socket`, `threading`, `argparse`, `time`, `sys`, `contextlib`)

**Storage**: N/A (all state in memory; zone and blocklist files are read by features 002/004)

**Testing**: existing black-box suite, `pytest tests --impl .` (pytest + dnspython, in `tests/`
only); `ruff check dnsd`, `bandit -r dnsd`. No new tests; `tests/` is not modified.

**Target Platform**: Linux (CI: ubuntu-latest), run as `python -m dnsd` from the repo root

**Project Type**: single-process network service (CLI entry point)

**Performance Goals**: answer a query within 5 s of startup (SC-005); a 1.5 s handler call must not
delay another client by more than 0.5 s (SC-004, design goal DG-1); survive 2000 fuzz packets paced at 2 ms (SC-001)

**Constraints**: UDP responses ≤ 512 bytes (SC-003); TCP responses ≤ 65535 bytes; no lock held
during network I/O or across stores (FR-028, design goal DG-2); zero ruff/bandit findings (Principle VII)

**Scale/Scope**: one local host's resolver; tens of concurrent queries at most; ~4 source files

All Technical Context items are known; no NEEDS CLARIFICATION remains. Design decisions are
recorded in [research.md](research.md).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Status |
|---|---|---|
| I. RFC 1035 authoritative | Wire format, compression (4.1.4), TCP framing (4.2.2), header bits (4.1.1) and name text form (5.1) follow RFC 1035; RFC 4343 only for name equality, as contract.md cites it | Pass |
| II. contract.md binding | Plan cites contract.md sections; no behaviour beyond them. Unspecified points (TCP after first answer, idle timeout, truncation content) are decided in research.md, not added to the contract | Pass |
| III. Standard library only | Only stdlib modules listed above; no new dependency anywhere | Pass |
| IV. Requirement → test | Every FR keeps its test list from spec.md; acceptance gate is the 11 stub-compatible tests (spec § Verification status). FR-007/FR-029 have no test yet, so they are non-normative design goals DG-1/DG-2 until the slow-upstream test lands. No tests added or changed | Pass |
| V. Never crash | Parser bounds-checks every read and never raises on input; listener wraps each message in one `try/except Exception` that prints to stderr; handler errors become SERVFAIL (FR-020); TCP reads have a 5 s deadline | Pass |
| VI. Secure forwarding | Not in scope (forwarder, 002). Nothing here fixes or exposes upstream IDs/ports | N/A |
| VII. Clean lint/scan | No `assert`, no `except: pass` (use `contextlib.suppress`), no `random`, no hard-coded bind-all address; checked with `ruff check dnsd` and `bandit -r dnsd` | Pass |
| VIII. Simplicity | Four files as requested; no frameworks, no logging framework, no protocols/ABCs, no options beyond the five flags; no compression on write; no in-flight limit. Every type traces to an FR or the spec's interface section | Pass |
| IX. Module boundaries | parser = message model; listener = transport, intake, finalisation, Stats, ServerState and the shared interface types; stores owned by zone/blocklist/cache/querylog replace the placeholders in 002–004 without changing signatures | Pass |
| X. No self-merge | Johnny's code is reviewed by Daniel before merge | Process |

**Post-design re-check (after Phase 1)**: Pass. The design added no class, option or file beyond
the spec. Two design points (research.md R-3, R-9) were accepted and spec.md § Inter-module
interfaces amended to match: `decode_query`'s rule-6 result is the `Message` itself, and the zone
result types (`Answer`, `NoData`, `NXDomain`, `NotLocal`, `Invalid`) and `LogEntry` are defined in
`dnsd/listener.py` so that the placeholders can return them before the zone and querylog modules
exist.

## Project Structure

### Documentation (this feature)

```text
specs/001-parser-listener/
├── plan.md              # This file
├── research.md          # Phase 0: decisions and rationale
├── data-model.md        # Phase 1: entities, fields, validation, lifecycles
├── quickstart.md        # Phase 1: how to validate the feature
├── contracts/
│   └── interfaces.md    # Phase 1: binding Python signatures for 002–004
├── checklists/
│   └── requirements.md  # from /speckit-specify
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
dnsd/
├── __init__.py      # empty package marker
├── __main__.py      # argparse (five flags → Config), build ServerState and handler, call listener.serve
├── parser.py        # Name, Header, Question, ResourceRecord, RDATA types, Message,
│                    # decode_query, decode_message, encode, type_to_text/type_from_text,
│                    # TYPE_* / CLASS_IN / RCODE constants
└── listener.py      # Config, Query, Outcome, LogEntry, zone result types, Stats, ServerState,
                     # placeholder stores, stub_handler, UDP/TCP servers, serve()

tests/               # existing black-box suite; not modified by this feature
```

**Structure Decision**: single package `dnsd/` with exactly the four files above. Features 002–004
add `zone.py`, `forwarder.py`, `cache.py`, `blocklist.py`, `querylog.py`, `api.py` and change
`__main__.py` to install their stores and handler; they do not change `parser.py`/`listener.py`
signatures without amending spec.md.

## Complexity Tracking

No constitution violations; nothing to justify.
