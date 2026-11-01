# Implementation Plan: Local Zone, Blocklist, Forwarder and Resolution Handler

**Branch**: `002-zone-forwarder` | **Date**: 2026-11-02 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-zone-forwarder/spec.md`

## Summary

Replace the SERVFAIL stub with real resolution: load the zone and blocklist files at startup into
two locked in-memory stores that fill the ZoneStore and Blocklist roles of
[001 contracts/interfaces.md](../001-parser-listener/contracts/interfaces.md), and install a
handler that applies the rows of contract.md § Responses in order — local zone (records, NODATA,
NXDOMAIN under a derived suffix, one-step CNAME, AA=1), blocked (built by the handler), cache
(placeholder until 003), and the upstream. The forwarder sends each query from a fresh
`secrets`-chosen source port with a fresh `secrets`-chosen ID, accepts only a reply from the
upstream with the same ID and question, retries over TCP on TC=1, and gives up with SERVFAIL when
one 2-second deadline for the whole exchange passes.

Approach: three new files under `dnsd/` (`zone.py`, `blocklist.py`, `forwarder.py`), standard
library only, plus a few lines in `__main__.py`. No change to `parser.py`, `listener.py` or any
001 interface.

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**: none (standard library only: `socket`, `secrets`, `threading`, `time`,
`ipaddress`, `sys`; plus `dnsd.parser` and `dnsd.listener` from 001)

**Storage**: in memory only; zone and blocklist files read once at startup, never written
(contract.md § Command line)

**Testing**: existing black-box suite, `pytest tests --impl .`; `ruff check dnsd`,
`bandit -r dnsd`. No new tests; `tests/` is not modified.

**Target Platform**: Linux (CI: ubuntu-latest), run as `python -m dnsd` from the repo root

**Project Type**: single-process network service (CLI entry point)

**Performance Goals**: every forwarded query answered within the 2 s budget plus local overhead
(tests allow 3.5 s, SC-004); a local or blocked answer needs no network I/O; startup with the
fixture files well within the harness's 5 s

**Constraints**: one 2 s deadline per upstream exchange including TCP retry (FR-018); no lock
held during network I/O and no store calls another store (001 concurrency rules 2 and 4); stores
expose exactly their role's methods (001 interfaces.md § 3); zero ruff/bandit findings

**Scale/Scope**: a home zone (tens to hundreds of records), a blocklist of up to tens of thousands
of entries, tens of concurrent queries; ~3 new source files, roughly 250–350 lines

All Technical Context items are known; no NEEDS CLARIFICATION remains. Design decisions are in
[research.md](research.md).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution v1.1.1.

| Principle | Check | Status |
|---|---|---|
| I. RFC 1035 authoritative | Zone lines follow the RFC 1035 master-file subset of contract.md; a trailing `;` comment is allowed because RFC 1035 5.1 allows it where the contract is silent (R-1); TCP retry uses RFC 1035 4.2.2 framing; RFC 4343 only for name matching and RFC 5452 only for the upstream ID/port, as contract.md cites them | Pass |
| II. contract.md binding | Spec and plan cite contract.md sections; unspecified points (trailing `#` starts a comment, malformed files, root suffix, ANY at a local name) are decided here, not added to the contract | Pass |
| III. Standard library only | Only stdlib modules listed above | Pass |
| IV. Requirement → test | Every FR keeps the test list of spec.md; acceptance = the 65 required tests (spec § Verification status, quickstart § 2). Startup-error handling has no test and is a plan decision, not an FR (spec Assumptions). No tests added or changed | Pass |
| V. Never crash | Loaders fail only at startup, before serving. At runtime the forwarder catches `OSError`/timeouts and returns `None` → SERVFAIL; `decode_message` never raises on upstream bytes; malformed or mismatched replies are ignored; the listener's FR-020 guard remains for defects | Pass |
| VI. Secure forwarding | Fresh `secrets` ID per query (including the TCP retry) and fresh `secrets` UDP source port per query; only replies with the matching ID (and the same question, from the connected upstream address) count; nothing configurable (R-7). Verified by `test_upstream_query_ids_are_random`, `test_upstream_source_ports_are_random`, `test_reply_with_wrong_id_is_ignored` | Pass |
| VII. Clean lint/scan | No `assert`, `random`, `try/except/pass` or `"0.0.0.0"` literal; blocked addresses built as `IPv4Address(0)`/`IPv6Address(0)`; `ruff check dnsd` and `bandit -r dnsd` in the tasks (R-10) | Pass |
| VIII. Simplicity | Three files as requested; two loader functions and two handler-side functions are the only names beyond the roles; no options, no cache logic, no custom exception types, no new shared types | Pass |
| IX. Module boundaries | zone, blocklist and forwarder are modules of Principle IX; stores have exactly their role's methods; shared types imported from `dnsd.parser`/`dnsd.listener`; only `__main__` imports the new modules ([contracts/modules.md](contracts/modules.md)); 001 interfaces unchanged | Pass |
| X. No self-merge | Johnny's code is reviewed by Daniel before merge; the 1.1.1 constitution amendment is approved in the same PR | Process |

**Post-design re-check (after Phase 1)**: Pass. The design added no class, option or file beyond
the planning input. The new public names (`load_zone`, `load_blocklist`, `make_handler`,
`exchange`) are module functions, not store methods, so the stores keep exactly their role's
methods. Two points for review: binding the UDP socket to `("", port)` is expected to pass bandit
(R-7 gives the fallback), and a zone record directly under the root makes every unmatched name
NXDOMAIN, as contract.md § Zone file implies (R-4 note).

## Project Structure

### Documentation (this feature)

```text
specs/002-zone-forwarder/
├── plan.md              # This file
├── research.md          # Phase 0: decisions and rationale
├── data-model.md        # Phase 1: store state, exchange values, handler responses
├── quickstart.md        # Phase 1: how to validate the feature
├── contracts/
│   └── modules.md       # Phase 1: public names of zone, blocklist, forwarder
├── checklists/
│   └── requirements.md  # from /speckit-specify
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
dnsd/
├── __init__.py      # unchanged
├── __main__.py      # changed: load_zone, load_blocklist (exit 1 on error), real stores, make_handler
├── parser.py        # unchanged (001)
├── listener.py      # unchanged (001); placeholders for cache and query log still used
├── zone.py          # new: ZoneStore (lookup, records, add, remove, make_record, value_text), load_zone
├── blocklist.py     # new: Blocklist (is_blocked, domains, add, remove), load_blocklist
└── forwarder.py     # new: exchange (UDP, TCP retry, 2 s deadline), make_handler

tests/               # existing black-box suite; not modified by this feature
```

**Structure Decision**: single package `dnsd/`, adding the three files above. Features 003 and
004 add `cache.py`, `querylog.py` and `api.py` and replace the two remaining placeholders in
`__main__.py`; they do not change the handler or these stores (spec SC-008).

## Complexity Tracking

No constitution violations; nothing to justify.
