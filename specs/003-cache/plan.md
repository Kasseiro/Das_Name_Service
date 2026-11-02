# Implementation Plan: TTL-Respecting Cache

**Branch**: `003-cache` | **Date**: 2026-11-02 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-cache/spec.md`

## Summary

Replace `PlaceholderCache` with a real store filling the Cache role of
[001 contracts/interfaces.md](../001-parser-listener/contracts/interfaces.md): `put` keeps an
upstream reply for its lifetime (the lowest answer TTL for a positive NOERROR answer; the lowest
min(SOA TTL, MINIMUM) for a negative answer with an SOA in the authority section; never for any
other reply), and `get` returns it with every TTL reduced by the whole seconds spent in the cache,
until the lifetime passes.

Approach: one new file, `dnsd/cache.py`: a dict keyed by `(Name, qtype)` (case-insensitive
through `Name` equality), one `threading.Lock`, `time.monotonic` for ageing, expired entries
removed when `get` finds them, no size limit. `__main__.py` installs `Cache()` in place of
`PlaceholderCache()`. No change to `parser.py`, `listener.py`, `zone.py`, `blocklist.py` or
`forwarder.py`.

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**: none (standard library only: `dataclasses`, `threading`, `time`; plus
`dnsd.parser` from 001)

**Storage**: in memory only; nothing persists across restarts

**Testing**: existing black-box suite, `pytest tests --impl .`; `ruff check dnsd`,
`bandit -r dnsd`. No new tests; `tests/` is not modified.

**Target Platform**: Linux (CI: ubuntu-latest), run as `python -m dnsd` from the repo root

**Project Type**: single-process network service (CLI entry point)

**Performance Goals**: `get` and `put` are O(size of the reply) with no I/O; a cache hit answers
without any network round trip

**Constraints**: exactly the role's two methods (001 interfaces.md § 3); one lock, in-memory work
only while held (001 concurrency rules 1–3); no change to the handler (002 SC-008); zero ruff/bandit
findings

**Scale/Scope**: a home network's distinct questions within their TTLs (hundreds to low
thousands of entries); one new file of roughly 70–90 lines, two changed lines in `__main__.py`

All Technical Context items are known; no NEEDS CLARIFICATION remains. Design decisions are in
[research.md](research.md).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution v1.1.1.

| Principle | Check | Status |
|---|---|---|
| I. RFC 1035 authoritative | RFC 2308 used only for the negative-caching bound and RFC 4343 only for name matching, as contract.md § Responses › Cache and § Zone file cite them | Pass |
| II. contract.md binding | Spec and plan cite contract.md § Responses › Cache; the two unspecified points (case, size) are decided in spec Assumptions and research R-1, R-5, not added to the contract | Pass |
| III. Standard library only | `dataclasses`, `threading`, `time` only | Pass |
| IV. Requirement → test | FR-001 – FR-010 keep the test lists of spec.md; acceptance = the 17 required cache tests plus the 65 of 002 (quickstart § 2, § 3). DC-1 – DC-4 (locking, negative lifetime, case-insensitive matching, TC=1 not stored) are review-checked constraints, not FRs, because no test can observe them. No tests added or changed | Pass |
| V. Never crash | `get`/`put` work only on already-decoded `Message` values; `max(…, 0)` keeps aged TTLs valid for `ResourceRecord`; a missing key or empty section raises nothing (`min` is called only on non-empty sequences); the listener's FR-020 guard remains for defects | Pass |
| VI. Secure forwarding | Not touched. Only replies the forwarder accepted (matching ID and question) reach `put` (002 FR-017, FR-023), so the cache cannot be filled by spoofed datagrams | Pass |
| VII. Clean lint/scan | No `assert`, `random`, `try/except/pass` (research R-8); `ruff check dnsd` and `bandit -r dnsd` in quickstart § 1 | Pass |
| VIII. Simplicity | One class with the role's two methods, one private entry type and two private helpers; no size limit, sweeper, option or new shared type (research R-5) | Pass |
| IX. Module boundaries | `cache` is a Principle IX module; `Cache` has exactly the role's methods; shared types imported from `dnsd.parser`; only `__main__` imports `dnsd.cache` ([contracts/cache.md](contracts/cache.md)); 001 interfaces unchanged | Pass |
| X. No self-merge | Johnny's code is reviewed by Daniel before merge | Process |

**Post-design re-check (after Phase 1)**: Pass. The design added nothing beyond the planning
input: one file, one public class with two methods, private `_Entry`, `_lifetime` and `_aged`.
Points for review: the unbounded dict (research R-5: entries for questions never asked again
after expiry stay in memory) and DC-1 – DC-4 (spec § Design constraints; not observable by tests).
After `/speckit-analyze`, a reply with TC=1 is no longer cached (spec DC-4, research R-2).

## Project Structure

### Documentation (this feature)

```text
specs/003-cache/
├── plan.md              # This file
├── research.md          # Phase 0: decisions and rationale
├── data-model.md        # Phase 1: cache state, entry, lifetime, life cycle
├── quickstart.md        # Phase 1: how to validate the feature
├── contracts/
│   └── cache.md         # Phase 1: public names of dnsd.cache, __main__ change
├── checklists/
│   └── requirements.md  # from /speckit-specify
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
dnsd/
├── __init__.py      # unchanged
├── __main__.py      # changed: Cache() in place of PlaceholderCache()
├── parser.py        # unchanged (001)
├── listener.py      # unchanged (001); PlaceholderCache stays defined but unused by __main__
├── zone.py          # unchanged (002)
├── blocklist.py     # unchanged (002)
├── forwarder.py     # unchanged (002); the handler already calls cache.get / cache.put
└── cache.py         # new: Cache (get, put); private _Entry, _lifetime, _aged

tests/               # existing black-box suite; not modified by this feature
```

**Structure Decision**: single package `dnsd/`, adding `cache.py`. Feature 004 adds
`querylog.py` and `api.py` and replaces the last placeholder in `__main__.py`.

## Complexity Tracking

No constitution violations; nothing to justify.
