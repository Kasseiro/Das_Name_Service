# Feature Specification: TTL-Respecting Cache

**Feature Branch**: `003-cache`

**Created**: 2026-11-02

**Status**: Draft

**Owner**: Johnny (module: cache; the startup change in `__main__.py`). Reviewer: Daniel
(constitution Principle X).

**Input**: User description:

> Feature: the TTL-respecting cache for dnsd. Builds on 001 and 002: a Cache store filling the
> cache role of specs/001-parser-listener/contracts/interfaces.md exactly (get, put), installed in
> ServerState by __main__.py in place of PlaceholderCache. The handler from 002 already calls get
> and put in the order of contract.md § Responses and must not change (002 SC-008). Import shared
> types from dnsd.parser and dnsd.listener; do not redefine them (Principle IX).
>
> Scope, per contract.md § Responses › Cache: positive caching (NOERROR with at least one answer
> record, cached for the lowest TTL in its answer section; until it expires the same question is
> answered from the cache); TTLs in a cached answer reduced by the time spent in the cache, to
> within one second; negative caching (NXDOMAIN or empty NOERROR cached only with an SOA in the
> authority section, for at most min(SOA TTL, SOA MINIMUM), RFC 2308; otherwise not cached);
> SERVFAIL and every other RCODE never cached. Case-insensitive matching and a size limit are
> unspecified by the contract; decide the simplest option and record it. Thread safety per 001
> interfaces.md concurrency rules (one lock, no I/O inside it).
>
> Out of scope: the query log and admin API (004), any change to the handler, zone, blocklist or
> forwarder. Verified by: tests/test_cache.py, plus the two cache tests 002 deferred to 003. Tests
> in test_cache.py that use the admin API (blocking/records takes effect, stats and log counters)
> are deferred to 004.

External behaviour is fixed by `contract.md`; this spec cites its sections and does not restate
them (Principle II). The Cache role (`get`, `put`), the message model, ServerState and the
concurrency rules are defined by [001 spec § Inter-module interfaces](../001-parser-listener/spec.md)
and [001 contracts/interfaces.md](../001-parser-listener/contracts/interfaces.md). How the handler
calls the cache is fixed by [002 spec FR-021, FR-023, FR-024](../002-zone-forwarder/spec.md). This
spec defines none of them again (Principle IX); it specifies only the behaviour behind `get` and
`put`.

## User Scenarios & Testing *(mandatory)*

The "users" of this feature are DNS clients on the home network, who get repeated answers faster
and without a trip to the upstream, and the operator, who expects answers to stay no longer than
their TTLs allow.

### User Story 1 - A repeated question is answered from the cache (Priority: P1)

A client asks for a name that is neither local nor blocked. The server forwards it once; while the
answer's TTL lasts, every repeat of the same question gets the same answer from the cache, over UDP
or TCP, and the upstream is not asked again.

**Why this priority**: this is the "TTL-respecting cache" of contract.md § Scope, Tier 2, and the
reason the feature exists.

**Independent Test**: with the fake upstream serving `cached.example.org. A 192.0.2.50` (TTL 300),
ask three times and check that all three replies match and the upstream saw one query; change the
upstream's answer and check the old one is still served.

**Acceptance Scenarios**:

1. **Given** the upstream answers `cached.example.org. A 192.0.2.50` with TTL 300, **When** a
   client asks three times, **Then** all three replies carry `192.0.2.50` and the upstream received
   exactly one query.
2. **Given** that answer is cached, **When** the upstream's answer changes to `192.0.2.51`,
   **Then** the next reply still carries `192.0.2.50`.
3. **Given** a cached answer, **When** a client asks again with a different query ID and the name in
   different letter case, **Then** the reply carries the new ID and the new question exactly as
   sent, and the cached addresses.
4. **Given** a cached answer, **When** a client asks over TCP, **Then** it gets the cached answer.
5. **Given** a cached answer with two records, **When** a client asks again, **Then** the reply is
   NOERROR, AA=0, RA=1, with both records.

---

### User Story 2 - Cached TTLs count down, and expired answers are fetched again (Priority: P1)

An answer served from the cache shows how much life it has left: each TTL is reduced by the time
the reply has spent in the cache. Once the lowest TTL in the answer section has run out, the next
question goes to the upstream again.

**Why this priority**: serving stale data, or data with an unchanged TTL that downstream caches
would keep too long, breaks the TTL contract (contract.md § Responses › Cache).

**Independent Test**: cache an answer with TTL 300, wait about 3 s, ask again and check the TTL
dropped by the elapsed time ±1 s; cache an answer with TTL 1, wait 2.3 s and check the upstream is
asked again.

**Acceptance Scenarios**:

1. **Given** an answer cached with TTL 300, **When** it is asked for again at once, **Then** its
   TTL is 300 or 299.
2. **Given** an answer cached with TTL 300, **When** it is asked for again about 3 s later,
   **Then** its TTL is 300 minus the elapsed time, within one second, and the upstream was not
   asked again.
3. **Given** an answer with TTL 1 in the answer section and a record with TTL 300 in the additional
   section, **When** 2.3 s pass and a client asks again, **Then** the upstream is asked again (the
   answer section's lowest TTL decides, not the other sections).
4. **Given** one name cached with TTL 1 and another with TTL 300, **When** 2.3 s pass and both are
   asked again, **Then** only the short-lived one is fetched again.

---

### User Story 3 - Each cache entry answers only its own question (Priority: P1)

A cached answer is reused only for the same name and the same type. A cached A answer never
answers an AAAA question, and a cached answer for one name never answers another name, a
subdomain, or a parent.

**Why this priority**: a cache that answers the wrong question returns wrong data, which is worse
than no cache.

**Independent Test**: cache an A answer, then ask for AAAA of the same name and A of other names,
and check every one is fetched from the upstream with its own answer.

**Acceptance Scenarios**:

1. **Given** `cached.example.org. A` is cached, **When** a client asks for its AAAA, **Then** the
   AAAA answer comes from the upstream, and A is still answered from the cache.
2. **Given** `cached.example.org. A` is cached, **When** a client asks `other.example.org. A` or
   `sub.cached.example.org. A`, **Then** each is forwarded and gets its own answer.

---

### User Story 4 - Failures and negative answers are not cached beyond what the contract allows (Priority: P1)

A SERVFAIL, from the upstream or from the server's own timeout, and any reply with an RCODE other
than NOERROR or NXDOMAIN, is never reused. A negative answer (NXDOMAIN, or NOERROR with no answer
records) is reused only when the upstream sent an SOA record with it, and never for longer than
that SOA record's TTL or MINIMUM field, whichever is lower.

**Why this priority**: caching a transient failure would keep a name broken after the upstream
recovers; caching a negative answer too long hides a name after it is created (contract.md
§ Responses › Cache, RFC 2308).

**Independent Test**: produce each kind of non-positive reply from the fake upstream, then switch
the upstream to a positive answer and check the next query gets it.

**Acceptance Scenarios**:

1. **Given** the upstream is silent and the server answers SERVFAIL, **When** the upstream
   recovers, **Then** the next query gets the upstream's answer.
2. **Given** the upstream answers SERVFAIL or REFUSED, **When** it starts answering normally,
   **Then** the next query gets the new answer.
3. **Given** the upstream answers NXDOMAIN, or NOERROR with an empty answer section, without an
   SOA record, **When** it starts answering with a record, **Then** the next query gets the record.
4. **Given** the upstream answers NXDOMAIN with an SOA record whose TTL and MINIMUM are (1, 1),
   (1, 300) or (300, 1), **When** 2.3 s pass and the upstream now has a record, **Then** the next
   query gets the record.

---

### User Story 5 - The cache plugs into the finished handler (Priority: P2)

The handler from 002 already asks the cache after the local zone and the blocklist, and offers it
every upstream reply that counts. Installing the real cache in place of the placeholder makes
caching work without changing the handler, the zone, blocklist or forwarder.

**Why this priority**: 002 SC-008 promised this; it keeps the feature limited to one module and
one line of start-up code.

**Independent Test**: review the diff (only the cache module and `__main__.py` change in `dnsd/`)
and run the whole suite.

**Acceptance Scenarios**:

1. **Given** the feature is merged, **When** the diff against `main` is reviewed, **Then** in
   `dnsd/` only the cache module (new) and `__main__.py` changed.
2. **Given** a name that is cached, **When** it is later blocked or given a local record (through
   the admin API of 004), **Then** the blocking or local answer wins (contract.md § Responses ›
   Cache: local zone and blocklist answers take precedence); verified when 004 merges.

---

### Edge Cases

- **Name in different letter case**: matches the cached entry (case-insensitive matching, see
  Assumptions and DC-3). The reply carries the client's question as sent, because the listener copies the
  question from the query (001).
- **Lowest answer TTL is 0**: the reply is relayed but not cached (its lifetime is zero).
- **A record TTL in the authority or additional section lower than the time spent in the cache**:
  served as 0, never negative or wrapped round.
- **NXDOMAIN with answer records** (e.g. a CNAME to a missing name): treated as negative, cached
  only with an SOA in the authority section (contract.md § Responses › Cache applies by RCODE).
  Its lifetime is also capped by its lowest answer TTL, so no answer record is served past its own
  TTL.
- **Truncated upstream reply (TC=1)** reaching `put` (a TCP retry reply that is itself truncated,
  002 Edge Cases): relayed to the client but not cached (DC-4), whatever its RCODE.
- **Several SOA records in the authority section**: the lowest min(TTL, MINIMUM) of all of them
  is the bound.
- **An SOA record in the answer section, none in the authority section**: does not count; the
  negative reply is not cached.
- **A put for a question that already has an entry** (two concurrent misses for the same question):
  the later cacheable reply replaces the entry; a later uncacheable reply leaves the entry alone.
- **Expired entry**: never returned by `get`; it is removed when `get` finds it expired.
- **Clock**: elapsed time is measured with a clock that does not jump when the wall clock is set,
  so a clock change neither expires entries early nor keeps them alive.
- **OPT record in an upstream reply's additional section**: stored as received; the listener
  removes OPT from every response (001), so it never reaches a client.
- **Query class**: the handler ignores the class (002 Assumptions), so the cache is keyed by name
  and type only, as contract.md § Responses › Cache says.

## Requirements *(mandatory)*

Each requirement lists the tests that verify it (Principle IV). Mark: **†** the test cannot pass
until feature 004 (query log + admin API) is merged. Unmarked tests are required for acceptance of
this feature. See **Verification status**.

### Functional Requirements

#### Cache store (001 contracts/interfaces.md § 3, Cache role)

- **FR-001**: The feature MUST provide a store filling the Cache role with exactly the two
  operations `get(name, qtype)` and `put(name, qtype, reply)` of 001 interfaces.md, and the entry
  point MUST install it in the ServerState in place of `PlaceholderCache`, before calling `serve`.
  Nothing else in the handler, zone, blocklist or forwarder modules changes (002 SC-008).
  *Tests*: `tests/test_cache.py::test_repeat_query_is_not_sent_upstream_again`,
  `tests/test_cache.py::test_cached_answer_over_tcp`
- **FR-002**: The store MUST have exactly the role's two methods, and `get` MUST return a new
  Message with new lists, so a caller cannot change a stored entry (001 interfaces.md concurrency
  rule 3). Locking is DC-1.
  *Tests*: `tests/test_cache.py::test_cached_answer_keeps_response_shape`,
  `tests/test_cache.py::test_repeat_query_is_not_sent_upstream_again`

#### What is cached (contract.md § Responses › Cache)

- **FR-003**: `put` MUST store a reply with RCODE NOERROR and at least one answer record for the
  lowest TTL in its answer section; a lowest TTL of 0 stores nothing. TTLs in the authority and
  additional sections do not affect the lifetime.
  *Tests*: `tests/test_cache.py::test_repeat_query_is_not_sent_upstream_again`,
  `tests/test_cache.py::test_cached_answer_survives_a_change_upstream`,
  `tests/test_cache.py::test_entry_lives_for_the_lowest_ttl_in_the_answer`
- **FR-004**: `put` MUST NOT store a reply with RCODE NXDOMAIN, or NOERROR with an empty answer
  section, unless its authority section holds an SOA record; when it does, the entry MUST NOT live
  longer than the lowest min(SOA TTL, SOA MINIMUM) over the SOA records in that section (RFC 2308).
  *Tests*: `tests/test_cache.py::test_nxdomain_without_soa_is_not_cached`,
  `tests/test_cache.py::test_empty_noerror_without_soa_is_not_cached`,
  `tests/test_cache.py::test_nxdomain_with_soa_is_cached_no_longer_than_ttl_and_minimum`
- **FR-005**: `put` MUST NOT store a reply with RCODE SERVFAIL or any RCODE other than NOERROR and
  NXDOMAIN. (A SERVFAIL built by the server itself never reaches `put`, 002 FR-023; the test checks
  the end-to-end result.)
  *Tests*: `tests/test_cache.py::test_servfail_from_timeout_is_not_cached`,
  `tests/test_cache.py::test_error_reply_from_upstream_is_not_cached`

#### What is returned (contract.md § Responses › Cache)

- **FR-006**: `get(name, qtype)` MUST return the stored reply only for the same name and the same
  question type; no other name (subdomain, parent, sibling) and no other type matches. How letter
  case is compared is DC-3.
  *Tests*: `tests/test_cache.py::test_cache_is_per_type`,
  `tests/test_cache.py::test_cache_is_per_name`
- **FR-007**: `get` MUST return the stored RCODE and all three record sections, in their stored
  order, as 001 interfaces.md specifies for the Cache role.
  *Tests*: `tests/test_cache.py::test_cached_answer_keeps_response_shape`,
  `tests/test_cache.py::test_cached_answer_survives_a_change_upstream`
- **FR-008**: In a reply returned by `get`, every record's TTL MUST be its stored TTL minus the
  whole seconds the reply has spent in the cache, never below 0, so it is correct to within one
  second.
  *Tests*: `tests/test_cache.py::test_cached_ttl_counts_down`,
  `tests/test_cache.py::test_cached_ttl_right_after_caching`
- **FR-009**: `get` MUST return nothing once an entry's lifetime (FR-003, FR-004) has passed, so the
  next query is forwarded again; each entry expires on its own lifetime.
  *Tests*: `tests/test_cache.py::test_expired_answer_is_fetched_again`,
  `tests/test_cache.py::test_each_answer_expires_by_its_own_ttl`,
  `tests/test_cache.py::test_entry_lives_for_the_lowest_ttl_in_the_answer`

#### Precedence and counters (contract.md § Responses › Cache, § Admin API; handled by 002's handler)

- **FR-010**: With the real cache installed, a cached name that is then blocked or given a local
  record MUST get the blocking or local answer at once, and cache hits and misses MUST show in
  `/stats` and `/log` as 002 FR-024 defines. Both follow from the unchanged 002 handler (it asks the
  zone and blocklist before the cache and reports `cached` / `upstream_asked`); this feature adds
  no code for them.
  *Tests*: `tests/test_cache.py::test_blocking_a_cached_name_takes_effect_immediately` †,
  `tests/test_cache.py::test_local_record_for_a_cached_name_takes_effect_immediately` †,
  `tests/test_cache.py::test_stats_count_misses_and_hits` †,
  `tests/test_cache.py::test_stats_count_a_miss_after_expiry` †,
  `tests/test_cache.py::test_cache_hit_is_logged_as_cached` †

### Design constraints *(binding; no test)*

- **DC-1**: The cache has one private lock, taken for the whole body of `get` and `put` (001
  interfaces.md concurrency rule 1). While holding it, the cache does in-memory work only: no
  socket or file I/O, no call to another store, no call back into caller code (rule 2). No test can
  observe either; both are checked in review, like 002 DC-1.
- **DC-2**: A negative reply with an SOA record (FR-004) is stored for exactly the bound FR-004
  gives, capped by its lowest answer TTL if it has answer records. The tests verify only the upper
  bound (that it is not kept longer) because no test in `tests/` observes that a negative answer is
  reused; the stored lifetime is checked in review.
- **DC-3**: Names match ASCII case-insensitively (RFC 4343): the cache keys on the `Name` value,
  whose equality and hash already ignore ASCII case, and does not normalise names itself (see
  Assumptions). No test can observe it: the fake upstream also ignores case, so a miss on a
  mixed-case repeat would still return the right addresses. Checked in review.
- **DC-4**: `put` does not store a reply with TC=1, so a truncated reply is never served for its
  full TTL. The forwarder normally replaces a truncated UDP reply with the TCP one (002 FR-019),
  but a TCP reply that itself has TC=1 is relayed as received (002 Edge Cases). No test sends one;
  checked in review.

### Key Entities *(include if feature involves data)*

All types are defined in 001 (message model, ServerState); this feature adds no shared type.

- **Cache entry**: one question (name, compared case-insensitively, and type) mapped to the reply
  as received from the upstream (RCODE and the three sections, TTLs as received), the time it was
  stored, and its lifetime (FR-003 or FR-004). Private to the cache module.

### Verification status

Same rule as 001 and 002 (constitution § Technical Constraints, v1.1.0): this feature is accepted
when the tests listed as required pass under `pytest tests --impl .`; deferred tests are re-checked
when 004 merges, and FR-010 counts as met only from then on (Principle IV).

The `server` and `upstream` fixtures are created for each test (`tests/conftest.py`), so every test
starts with an empty cache; tests in other suites that count upstream queries ask for distinct
names and are not affected by caching.

**Required for acceptance (003)** — 82 test functions:

- `tests/test_cache.py` (17 of 22): `test_repeat_query_is_not_sent_upstream_again`,
  `test_cached_answer_survives_a_change_upstream`, `test_cached_answer_keeps_response_shape`,
  `test_cached_ttl_counts_down`, `test_cached_ttl_right_after_caching`,
  `test_entry_lives_for_the_lowest_ttl_in_the_answer`,
  `test_cached_answer_carries_the_new_querys_id_and_question`, `test_cached_answer_over_tcp`,
  `test_cache_is_per_type`, `test_cache_is_per_name`, `test_expired_answer_is_fetched_again`,
  `test_each_answer_expires_by_its_own_ttl`, `test_nxdomain_without_soa_is_not_cached`,
  `test_empty_noerror_without_soa_is_not_cached`,
  `test_nxdomain_with_soa_is_cached_no_longer_than_ttl_and_minimum`,
  `test_servfail_from_timeout_is_not_cached`, `test_error_reply_from_upstream_is_not_cached`.
  This includes the two tests 002 deferred to 003 (`test_repeat_query_is_not_sent_upstream_again`,
  `test_servfail_from_timeout_is_not_cached`).
- No regression: the 65 tests 002 lists as required (002 § Verification status).

**Deferred to 004 (query log + admin API)** — 5 test functions:

| Test | Why it cannot pass before 004 |
|---|---|
| `tests/test_cache.py::test_blocking_a_cached_name_takes_effect_immediately` | uses `POST /blocklist` |
| `tests/test_cache.py::test_local_record_for_a_cached_name_takes_effect_immediately` | uses `POST /records` |
| `tests/test_cache.py::test_stats_count_misses_and_hits` | reads `/stats` |
| `tests/test_cache.py::test_stats_count_a_miss_after_expiry` | reads `/stats` |
| `tests/test_cache.py::test_cache_hit_is_logged_as_cached` | reads `/log` |

The first four were listed by 002 as "deferred to both 003 and 004"; with 003 merged they wait
only for 004. `test_stats_count_a_miss_after_expiry` is not named by 002 and is new here.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A question repeated any number of times within its answer's TTL reaches the upstream
  exactly once.
- **SC-002**: Every TTL in a cached answer is within one second of its stored TTL minus the time
  spent in the cache, and never negative.
- **SC-003**: 0 answers are served from the cache after their lifetime: an answer with a 1 s TTL is
  fetched from the upstream again 2.3 s later.
- **SC-004**: 0 SERVFAIL, REFUSED or other error replies, and 0 negative replies without an SOA
  record, are reused: after each, the next query reaches the upstream.
- **SC-005**: 0 cached answers are returned for a different name or type.
- **SC-006**: All 82 tests listed as required under Verification status pass.
- **SC-007**: The diff in `dnsd/` touches only the new cache module and `__main__.py`.

## Assumptions

- **Case-insensitive matching** (unspecified by contract.md § Responses › Cache): names match
  case-insensitively. It is the simplest option, because `Name` equality and hashing are already
  ASCII case-insensitive (001 interfaces.md § 1), and it matches the zone and blocklist (RFC 4343).
  The reply's question keeps the client's case because the listener copies it from the query.
  Recorded as DC-3 (checked in review), not as a tested requirement: no test can tell it apart from
  case-sensitive matching.
- **Size limit** (unspecified by contract.md § Responses › Cache): there is no limit and no
  background sweeping. An expired entry is removed when `get` finds it. This is the simplest option
  (Principle VIII); memory grows with the number of distinct cacheable questions asked within their
  TTLs, which is small for a home network. A limit would be a new option the contract does not
  require.
- **Time in the cache** is measured in whole seconds rounded down, from the moment `put` stored the
  reply, with a monotonic clock. Right after caching the TTL is unchanged; it is never more than
  one second off (contract.md: "to within one second").
- **Negative caching** stores a qualifying reply for exactly min(SOA TTL, SOA MINIMUM) (the "at
  most" bound of contract.md, used as the lifetime), so a repeated missing name is not forwarded
  again within that time (DC-2).
- The upstream reply passed to `put` is the one the handler relays (002 FR-023); the cache stores
  its RCODE and three sections as received. Of the rest of the header it reads only TC (DC-4); the
  handler and listener set everything else (001, 002).
- This feature does not modify `tests/`. Prompt-log entries (`docs/prompt-log.md`) are written by
  the user, as for 001 and 002.
