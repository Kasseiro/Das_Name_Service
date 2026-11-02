---

description: "Task list for feature 003: TTL-respecting cache"
---

# Tasks: TTL-Respecting Cache

**Input**: Design documents from `specs/003-cache/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cache.md, quickstart.md

**Tests**: No test tasks are generated. The planning input forbids adding or modifying anything in
`tests/`. Verification uses the existing black-box suite (`pytest --impl=. ...`),
`ruff check dnsd` and `bandit -r dnsd`. The acceptance gate is the 17 required cache tests plus the
65 tests 002 requires (spec.md § Verification status; quickstart § 2, § 3).

**Organization**: Tasks are grouped by user story (US1–US5 of spec.md). One new file
(`dnsd/cache.py`) and one changed file (`dnsd/__main__.py`); tasks on the same file are not `[P]`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story the task belongs to (US1–US5, from spec.md)
- Every task names its file path

## Rules that apply to every task (do not repeat per task)

- Standard library only (Principle III). Allowed imports in `dnsd/cache.py`: `dataclasses`,
  `threading`, `time`, plus from `dnsd.parser`: `Header`, `Message`, `Name`, `ResourceRecord`,
  `NOERROR`, `NXDOMAIN`, `TYPE_SOA` (research R-8). Never redefine a shared type (Principle IX).
- `Cache` has exactly the two methods `get(self, name: Name, qtype: int) -> Message | None` and
  `put(self, name: Name, qtype: int, reply: Message) -> None` of
  `specs/001-parser-listener/contracts/interfaces.md` § 3, plus `__init__`. Everything else is
  `_`-prefixed (`_Entry`, `_lifetime`, `_aged`), per `specs/003-cache/contracts/cache.md`.
- Concurrency (001 interfaces.md § 3, spec DC-1; new lists: FR-002): one private `threading.Lock`; `get` and
  `put` each take it with `with self._lock:`; under the lock only in-memory work (no I/O, no
  logging, no call to another store). `get` returns a new `Message` with new lists.
- No `assert` (B101), no `try/except/pass` (B110), no `random`, no `logging`, no size limit, no
  sweep thread (research R-5, R-8).
- No changes to `dnsd/parser.py`, `dnsd/listener.py`, `dnsd/zone.py`, `dnsd/blocklist.py`,
  `dnsd/forwarder.py`, `tests/`, `contract.md`. No prompt-log entries.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the starting point

- [X] T001 From the repo root, confirm `ruff --version`, `bandit --version` and `pytest --version` run, and that the 65 required tests of `specs/002-zone-forwarder/quickstart.md` § 2 pass on the current `dnsd/` before any change (baseline; no file changes)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: An empty but correctly shaped cache, installed by the entry point. Every black-box
check of every story needs it.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T002 Create `dnsd/cache.py` (module docstring citing contract.md § Responses › Cache and spec 003) with a private frozen dataclass `_Entry` (data-model § `_Entry`): fields `rcode: int`, `answers: tuple[ResourceRecord, ...]`, `authority: tuple[ResourceRecord, ...]`, `additional: tuple[ResourceRecord, ...]`, `stored: float`, `lifetime: int`; and class `Cache` whose `__init__` sets `self._lock = threading.Lock()` and `self._entries: dict[tuple[Name, int], _Entry] = {}`. Add `get` returning `None` and `put` returning `None` (both filled in by US1), each with the signature of contracts/cache.md
- [X] T003 Change `dnsd/__main__.py` (contracts/cache.md § `dnsd.__main__`, research R-7): add `from dnsd.cache import Cache`, pass `Cache()` to `ServerState` in place of `PlaceholderCache()`, and remove `PlaceholderCache` from the `dnsd.listener` import list. Nothing else changes; `PlaceholderCache` stays defined in `dnsd/listener.py`

**Checkpoint**: `python -m dnsd` starts with the 002 quickstart flags; `ruff check dnsd` is clean;
the 65 002 tests still pass (the cache never hits yet).

---

## Phase 3: User Story 1 - A repeated question is answered from the cache (Priority: P1) 🎯 MVP

**Goal**: A positive NOERROR answer is stored and reused for the same question, over UDP and TCP.

**Independent Test**: `test_repeat_query_is_not_sent_upstream_again`,
`test_cached_answer_survives_a_change_upstream`, `test_cached_answer_keeps_response_shape`,
`test_cached_answer_carries_the_new_querys_id_and_question`, `test_cached_answer_over_tcp`.

### Implementation for User Story 1

- [X] T004 [US1] Add module function `_lifetime(reply: Message) -> int` to `dnsd/cache.py` (research R-2, data-model § Lifetime), positive branch only for now: if `reply.header.rcode == NOERROR` and `reply.answers` is not empty, return `min(rr.ttl for rr in reply.answers)`; otherwise return `0` (the negative branch is added in T010). It is pure and takes no lock
- [X] T005 [US1] Implement `Cache.put` in `dnsd/cache.py` (FR-003): compute `lifetime = _lifetime(reply)` **before** taking the lock; if `lifetime <= 0` return without touching `self._entries` ("A lifetime of 0 means `put` stores nothing and leaves any existing entry unchanged"); otherwise build `_Entry(reply.header.rcode, tuple(reply.answers), tuple(reply.authority), tuple(reply.additional), time.monotonic(), lifetime)` and, under the lock, assign `self._entries[(name, qtype)] = entry` (replacing any earlier entry)
- [X] T006 [US1] Implement `Cache.get` in `dnsd/cache.py` (FR-006, FR-007): under the lock, look up `self._entries.get((name, qtype))`; return `None` if absent; otherwise return `Message(Header(rcode=entry.rcode), [], list(entry.answers), list(entry.authority), list(entry.additional))` — header carries only the RCODE, no questions, new lists in stored order (data-model § Entry life cycle). Ageing and expiry are added in T008
- [X] T007 [US1] Run the five US1 tests named under Independent Test: `pytest --impl=. tests/test_cache.py -k "repeat_query or survives_a_change or keeps_response_shape or new_querys_id or over_tcp"`; all pass. Fix in `dnsd/cache.py` only

**Checkpoint**: repeated questions are answered from the cache (without expiry yet).

---

## Phase 4: User Story 2 - Cached TTLs count down, and expired answers are fetched again (Priority: P1)

**Goal**: Returned TTLs are reduced by whole seconds in the cache; entries expire after their
lifetime.

**Independent Test**: `test_cached_ttl_counts_down`, `test_cached_ttl_right_after_caching`,
`test_entry_lives_for_the_lowest_ttl_in_the_answer`, `test_expired_answer_is_fetched_again`,
`test_each_answer_expires_by_its_own_ttl`.

### Implementation for User Story 2

- [X] T008 [US2] In `dnsd/cache.py` add module function `_aged(records: tuple[ResourceRecord, ...], age: int) -> list[ResourceRecord]` returning `[dataclasses.replace(rr, ttl=max(rr.ttl - age, 0)) for rr in records]` (FR-008, research R-3, R-4: every record is aged, OPT included). Change `Cache.get`: under the lock, after finding the entry, compute `age = int(time.monotonic() - entry.stored)` (whole seconds, rounded down); if `age >= entry.lifetime`, `del self._entries[(name, qtype)]` and return `None` (FR-009); otherwise return the Message of T006 with each section built by `_aged(section, age)` instead of `list(section)`. Then run the five US2 tests: `pytest --impl=. tests/test_cache.py -k "ttl_counts_down or right_after_caching or lowest_ttl or fetched_again or own_ttl"`; all pass

**Checkpoint**: US1 and US2 tests pass together.

---

## Phase 5: User Story 3 - Each cache entry answers only its own question (Priority: P1)

**Goal**: A cached entry matches only the same name (ignoring ASCII case) and the same type.

**Independent Test**: `test_cache_is_per_type`, `test_cache_is_per_name`.

### Implementation for User Story 3

- [ ] T009 [US3] No code: the `(name, qtype)` dict key of T002/T005 gives FR-006, and DC-3 because `Name` equality and hash are ASCII case-insensitive (research R-1). Run `pytest --impl=. tests/test_cache.py -k "per_type or per_name or new_querys_id"`; all pass. If one fails, fix the key handling in `dnsd/cache.py` only (do not normalise names yourself)

**Checkpoint**: US1–US3 tests pass.

---

## Phase 6: User Story 4 - Failures and negative answers are not cached beyond what the contract allows (Priority: P1)

**Goal**: SERVFAIL and every other error RCODE are never stored; negative answers are stored only
with an SOA in the authority section, for at most min(SOA TTL, MINIMUM).

**Independent Test**: `test_nxdomain_without_soa_is_not_cached`,
`test_empty_noerror_without_soa_is_not_cached`,
`test_nxdomain_with_soa_is_cached_no_longer_than_ttl_and_minimum`,
`test_servfail_from_timeout_is_not_cached`, `test_error_reply_from_upstream_is_not_cached`.

### Implementation for User Story 4

- [ ] T010 [US4] Complete `_lifetime` in `dnsd/cache.py` (FR-004, FR-005, DC-4, research R-2, data-model § Lifetime): first, if `reply.header.tc` is set return `0` ("a truncated reply must not be served for its full TTL"; any RCODE); then keep the T004 positive branch; add — if `rcode == NXDOMAIN` or (`rcode == NOERROR` and `answers` empty): `soas = [rr for rr in reply.authority if rr.rtype == TYPE_SOA]`; if `soas` is empty return `0`; else `bound = min(min(rr.ttl, rr.rdata.minimum) for rr in soas)`; if `reply.answers` is not empty, `bound = min(bound, min(rr.ttl for rr in reply.answers))`; return `bound`. Every other RCODE (SERVFAIL, REFUSED, NOTIMP, FORMERR, …) returns `0`. Order the branches so `NOERROR` with answers takes the positive branch and `NXDOMAIN` with answers takes the negative one. An SOA in the answer section does not count. Call `min` only on non-empty sequences
- [ ] T011 [US4] Run the five US4 tests: `pytest --impl=. tests/test_cache.py -k "without_soa or with_soa or servfail_from_timeout or error_reply"`; all pass (the parametrised ones expand to 3 and 2 cases). Fix in `dnsd/cache.py` only

**Checkpoint**: all 17 required cache tests pass (quickstart § 2).

---

## Phase 7: User Story 5 - The cache plugs into the finished handler (Priority: P2)

**Goal**: Caching works without changing the handler, zone, blocklist or forwarder (002 SC-008).

**Independent Test**: quickstart § 5 scope check; the 5 tests deferred to 004 are re-run when 004
merges.

### Implementation for User Story 5

- [ ] T012 [US5] Scope and contract review of `dnsd/cache.py` and `dnsd/__main__.py` (FR-001, FR-002, SC-007, DC-1 – DC-4): `git diff --stat main -- dnsd/` lists only `dnsd/cache.py` and `dnsd/__main__.py`; `Cache`'s public methods are exactly `get` and `put` with the contracts/cache.md signatures; only `dnsd/__main__.py` imports `dnsd.cache`; (DC-1) one lock taken for the whole body of `get` and `put`, nothing under it does I/O, logging or calls another store, and `put` computes `_lifetime` and the tuples outside it; `get` returns new lists; (DC-2) a negative reply with an SOA is stored for exactly `min(SOA ttl, SOA minimum)` (capped by the lowest answer TTL if there are answers); (DC-3) the dict key is the `Name` value as passed, with no lower-casing or other normalisation; (DC-4) `_lifetime` returns 0 for a reply with `header.tc` set, before any RCODE branch. Fix in `dnsd/cache.py` / `dnsd/__main__.py` only

**Checkpoint**: All five user stories implemented and checked.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Gates required by the constitution and the spec's acceptance criteria

- [ ] T013 Run `ruff check dnsd` and `bandit -r dnsd` from the repo root and fix every finding in `dnsd/cache.py` or `dnsd/__main__.py` (Principle VII; zero findings)
- [ ] T014 Run the acceptance gate of `specs/003-cache/quickstart.md` § 2 (17 cache tests, 5 deselected) and § 3 (the 65 tests of 002): all pass, nothing skipped
- [ ] T015 Run the full suite `pytest tests --impl .` (quickstart § 4) and record every failing test: each must be one of the 5 tests spec.md § Verification status defers to 004, one of the 9 tests 002 defers to 004, or in `tests/test_admin_api.py`, and fail on a missing `/stats`, `/log`, `/records` or `/blocklist` (connection refused or 404 from the admin port), never on "dnsd exited" or "no response" from the DNS port. Report the list for the reviewer (constitution § Technical Constraints)
- [ ] T016 Re-read `dnsd/cache.py` against `specs/003-cache/contracts/cache.md` and 001 `contracts/interfaces.md` one last time: no public name beyond `Cache`, `get`, `put`; no unused imports or code; no size limit, sweep or option (Principle VIII, IX)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup; blocks every user story
- **US1 (Phase 3)**: depends on Phase 2
- **US2 (Phase 4)**: depends on US1 (extends the same `get`)
- **US3 (Phase 5)**: depends on US1 (checks the key used by `put`/`get`); can run before or after US2
- **US4 (Phase 6)**: depends on US1 (extends the same `_lifetime`); its `with_soa` test needs US2's expiry
- **US5 (Phase 7)**: depends on US1–US4
- **Polish (Phase 8)**: depends on all stories

### Within each phase

- Phase 2: T002 → T003 (T003 imports `dnsd.cache`, which T002 creates)
- Phase 3: T004 → T005 → T006 → T007
- Phase 6: T010 → T011

### Parallel Opportunities

- None. T003 depends on T002, and every other task edits or checks `dnsd/cache.py`, so all tasks
  run in order.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 Setup, Phase 2 Foundational
2. Phase 3 (US1): repeated questions answered from the cache
3. **STOP and VALIDATE**: the five US1 tests pass. This MVP is not shippable on its own: until
   US2, entries never expire, and contract.md § Responses › Cache forbids serving an answer past
   its TTL. (Until US4, negative replies are simply not stored, which the contract allows.)

### Incremental Delivery

1. Setup + Foundational → cache installed, never hits
2. US1 → hits for positive answers
3. US2 → TTL countdown and expiry (first shippable state)
4. US3 → key check
5. US4 → negative caching and error exclusion (all 17 required tests)
6. US5 + Polish → scope review, lint, full suite, reviewer list

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps a task to its user story for traceability
- Commit after each phase with `<type>(cache): <what changed>` and the `Prompt:` / `Spec:`
  trailers of README.md
- Stop at any checkpoint to validate the story on its own
