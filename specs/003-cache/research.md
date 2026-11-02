# Research: TTL-Respecting Cache

Phase 0 decisions for [spec.md](spec.md). Each entry: decision, rationale, alternatives
considered. There were no NEEDS CLARIFICATION items in the Technical Context; these entries
record the choices the planning input left open or fixed.

## R-1: Storage and key

- **Decision**: one `dict[tuple[Name, int], _Entry]` keyed by `(name, qtype)`, as received from the
  handler. `_Entry` is a private frozen dataclass holding `rcode`, the three record sections as
  tuples, `stored` (a `time.monotonic()` value) and `lifetime` (whole seconds).
- **Rationale**: `Name.__eq__`/`__hash__` are already ASCII case-insensitive (001 interfaces.md
  § 1), so the dict gives the spec's case-insensitive matching (spec Assumptions, DC-3) with no
  extra code. Tuples make a stored entry immutable, so `get` only has to build new lists
  (001 concurrency rule 3).
- **Alternatives**: keying by `name.to_text().lower()` (duplicates what `Name` already does);
  storing the whole `Message` (its lists are mutable and its header is not needed, since the handler
  copies only the RCODE, 002 `_relayed`).

## R-2: Which replies are stored, and for how long (FR-003 – FR-005)

- **Decision**: a private pure function `_lifetime(reply) -> int` computed **before** taking the
  lock:
  - TC=1 (any RCODE): `0` (spec DC-4; checked first).
  - RCODE NOERROR with answers: `min(rr.ttl for rr in answers)`.
  - RCODE NXDOMAIN, or NOERROR with no answers: let `soas` be the authority records with
    `rtype == TYPE_SOA`; if none, `0`; otherwise `min(min(rr.ttl, rr.rdata.minimum) for rr in soas)`,
    further capped by `min(rr.ttl for rr in answers)` when the answer section is not empty
    (NXDOMAIN with answers, spec Edge Cases).
  - Any other RCODE: `0`.

  `put` stores the entry only when the lifetime is greater than 0; otherwise it returns without
  touching the dict (an uncacheable reply never removes a valid entry, spec Edge Cases).
- **Rationale**: one place decides cacheability; a lifetime of 0 doubles as "do not cache", so
  TTL-0 answers and missing SOAs fall out of the same rule. Computing it outside the lock keeps the
  locked section to a single dict assignment.
- **Alternatives**: storing a negative reply for a shorter time than the bound (the contract says
  "at most"; using the bound itself is simplest, spec DC-2); not caching negative replies at all
  (allowed by "may", but the spec scope includes negative caching).

## R-3: Ageing and expiry (FR-008, FR-009)

- **Decision**: `age = int(time.monotonic() - entry.stored)` (whole seconds, rounded down). An entry
  is expired when `age >= entry.lifetime`, which for a whole-number lifetime is the same as the
  exact elapsed time reaching it; `get` then deletes it and returns `None`. Otherwise every
  record in the three sections is returned as `dataclasses.replace(rr, ttl=max(rr.ttl - age, 0))`.
- **Rationale**: `time.monotonic` does not jump with the wall clock (spec Edge Cases). Rounding down
  gives TTL 300 right after caching and stays within one second of the exact remaining time
  (`test_cached_ttl_right_after_caching`, `test_cached_ttl_counts_down`). Expiry compares the
  integer age, so an entry with lifetime 1 is gone after 1 s; tests wait 2.3 s.
  `replace` re-runs `ResourceRecord.__post_init__`, and a TTL clamped to 0–original stays in the
  valid range.
- **Alternatives**: expiring on the exact float age (`elapsed >= lifetime`): for a whole-number
  lifetime `int(elapsed) >= lifetime` and `elapsed >= lifetime` are the same condition, so the two
  behave identically; the integer form is used because the same `age` also ages the TTLs. Rounding
  the age to nearest (would show TTLs up to half a second too low, and expire entries half a second
  early; no benefit).

## R-4: Records not aged

- **Decision**: every record is aged, including OPT pseudo-records in the additional section.
- **Rationale**: the listener removes OPT from every response (001 FR-015, `_without_opt`), so an
  aged OPT never reaches a client. Special-casing it would be dead code (Principle VIII).
- **Alternatives**: skip OPT (unneeded); strip OPT at `put` (duplicates the listener's job).

## R-5: Size limit and sweeping

- **Decision**: no size limit, no background sweep, no sweep inside `put`. Expired entries are
  removed only when `get` finds them (planning input; spec Assumptions).
- **Rationale**: simplest option the contract allows (contract.md § Responses › Cache leaves the
  size unspecified); a limit or sweeper would be an option or thread with no requirement behind it
  (Principle VIII). Memory grows with distinct cacheable questions; acceptable for a home network
  and noted for review.
- **Alternatives**: LRU with a fixed cap (`OrderedDict`), a periodic sweep thread, sweeping expired
  entries on every `put` (O(n) under the lock). All rejected for this feature.

## R-6: Locking (spec DC-1; FR-002 for the new lists)

- **Decision**: one private `threading.Lock` per `Cache`. `get` holds it for the lookup, expiry
  check, deletion and building the returned `Message` (pure in-memory work on tuples); `put`
  computes `_lifetime` and the tuples first, then holds it for the dict assignment only. No I/O, no
  logging, no call to another store under the lock.
- **Rationale**: 001 interfaces.md concurrency rules 1–3. The clock is read inside `get`'s lock so
  the age and the deletion decision see the same entry; reading `time.monotonic()` is not I/O.
- **Alternatives**: `RLock` (no re-entry needed); lock-free dict access relying on the GIL (rule 1
  requires the lock).

## R-7: Entry point

- **Decision**: `__main__.py` imports `Cache` from `dnsd.cache` and passes `Cache()` to
  `ServerState` in place of `PlaceholderCache()`, which is dropped from the import list. No other
  change.
- **Rationale**: spec FR-001; 002 contracts/modules.md § `dnsd.__main__`. `PlaceholderCache` stays
  defined in `listener.py` (no change to 001 code); it is simply no longer used by `__main__`.
- **Alternatives**: deleting `PlaceholderCache` from `listener.py` (a change to 001 code that the
  planning input forbids).

## R-8: Lint and scan (Principle VII)

- **Decision**: no `assert`, no `random`, no `try/except/pass`; type hints on public methods; the
  module imports only `dataclasses`, `threading`, `time` and `dnsd.parser` names (`Message`,
  `Header`, `Name`, `ResourceRecord`, `NOERROR`, `NXDOMAIN`, `TYPE_SOA`).
- **Rationale**: nothing here triggers ruff or bandit rules; checked by `ruff check dnsd` and
  `bandit -r dnsd` (quickstart § 1).
