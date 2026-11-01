---

description: "Task list for feature 002: local zone, blocklist, forwarder and resolution handler"
---

# Tasks: Local Zone, Blocklist, Forwarder and Resolution Handler

**Input**: Design documents from `specs/002-zone-forwarder/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/modules.md, quickstart.md

**Tests**: No test tasks are generated. The planning input forbids adding or modifying anything in
`tests/`. Verification uses the existing black-box suite (`pytest --impl=. ...`),
`ruff check dnsd` and `bandit -r dnsd`. The acceptance gate is the 65 required tests of spec.md
§ Verification status (quickstart § 2).

**Organization**: Tasks are grouped by user story (US1–US7 of spec.md). Three new files
(`dnsd/zone.py`, `dnsd/blocklist.py`, `dnsd/forwarder.py`) and one changed file
(`dnsd/__main__.py`); tasks on the same file are not `[P]`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story the task belongs to (US1–US7, from spec.md)
- Every task names its file path

## Rules that apply to every task (do not repeat per task)

- Standard library only (Principle III). Allowed imports: `socket`, `secrets`, `threading`,
  `time`, `ipaddress`, `sys`, `struct`, `contextlib`, plus `dnsd.parser` and `dnsd.listener`.
- Import every shared type (`Name`, `Question`, `ResourceRecord`, `A`, `AAAA`, `CNAME`, `Header`,
  `Message`, `decode_message`, `encode`, `type_from_text`, `TYPE_*`, `CLASS_IN`, RCODEs from
  `dnsd.parser`; `Query`, `Outcome`, `Handler`, `ServerState`, `Answer`, `NoData`, `NXDomain`,
  `NotLocal`, `Invalid` from `dnsd.listener`). Never redefine them (Principle IX).
- `ZoneStore` has exactly the six methods and `Blocklist` exactly the four methods of
  `specs/001-parser-listener/contracts/interfaces.md` § 3 (plus `__init__`); anything else is a
  module-level function or `_`-prefixed. Public module names are only those of
  `specs/002-zone-forwarder/contracts/modules.md`.
- Concurrency (001 interfaces.md § 3): each store has one private `threading.Lock`, taken for the
  whole body of every stateful method; inside it only in-memory work; return new lists or
  immutable values. The handler holds no lock.
- No `assert` (B101), no `try/except/pass` (B110; use `contextlib.suppress`), no `random` (B311),
  no `"0.0.0.0"` string literal (B104), no `logging`, no broad `except Exception` (research R-10).
  Errors go to `print("dnsd: ...", file=sys.stderr)`.
- No changes to `dnsd/parser.py`, `dnsd/listener.py`, `tests/`, `contract.md`. No prompt-log
  entries.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm the starting point

- [X] T001 From the repo root, confirm `ruff --version`, `bandit --version` and `pytest --version` run, and that the 11 stub-compatible 001 tests of `specs/001-parser-listener/quickstart.md` § 2 pass on the current `dnsd/` before any change (baseline; no file changes)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The zone store's record keeping, the zone file loader, a handler with its local branch,
and the entry point that installs them. Every black-box check of every story needs these.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T002 Create `dnsd/zone.py` with class `ZoneStore` (data-model § ZoneStore state): `__init__` creates `self._lock = threading.Lock()`, `self._by_name: dict[Name, list[ResourceRecord]] = {}` and `self._suffixes: set[Name] = set()`. Add a private `_recompute_suffixes()` (called with the lock held) that sets `self._suffixes = {n.parent() for n in self._by_name if n.labels}` (the root has no parent and is skipped). Implement `records()` (new flat list, insertion order per name), `add(record)` ("no two equal records under one name": if an equal record — `==`, which ignores TTL — is in the name's list, replace it at the same index; otherwise append; a new name → `_recompute_suffixes()`), `remove(name, rtype) -> int` (drop every record of that `rtype` at that name; "a key exists only while its list is non-empty": delete the key when the list empties and then recompute suffixes; return the count). Add `lookup(name, qtype)` returning `NotLocal()` for now (filled in by US1–US3). All four take the lock for their whole body
- [X] T003 Add `make_record(self, name_text, type_text, ttl, value_text) -> ResourceRecord | Invalid` and `value_text(self, record) -> str` to `ZoneStore` in `dnsd/zone.py` (FR-011, FR-012, research R-5); both are pure and take no lock. make_record: `Name.from_text(name_text)`; `type_from_text(type_text)` must be `TYPE_A`, `TYPE_AAAA` or `TYPE_CNAME` (case-insensitive via `type_from_text`), else `Invalid`; `ttl` must satisfy `type(ttl) is int` and "0–4294967295"; value: A → `ipaddress.IPv4Address(value_text)`, AAAA → `ipaddress.IPv6Address(value_text)` rejected if it has a `scope_id`, CNAME → `Name.from_text(value_text)`; then `ResourceRecord(name, rtype, CLASS_IN, ttl, rdata)`. Catch only `ValueError` (which covers `ipaddress.AddressValueError`) and return `Invalid(<short reason>)`. value_text: `str(record.rdata.address)` for A and AAAA, `record.rdata.target.to_text()` for CNAME
- [X] T004 Add module function `load_zone(path: str) -> ZoneStore` to `dnsd/zone.py` (FR-001, research R-1, R-3): open with `encoding="utf-8"`; per line (1-based number `n`): cut at the first `;`; skip if blank; `fields = line.split()` must have exactly 5 fields `name ttl class type value`; `name` must end with `.`; `ttl` must be `isascii() and isdigit()`; `class.upper() == "IN"`; then `make_record(name, type, int(ttl), value)` must not be `Invalid`; then `store.add(record)`. Any violation raises `ValueError(f"{path}:{n}: <reason>")`. Do not catch `OSError` or `UnicodeDecodeError`; they propagate to the caller
- [X] T005 [P] Create `dnsd/forwarder.py` with `make_handler(state: ServerState) -> Handler` (FR-020, FR-024, research R-8). The returned `handle(query: Query) -> Outcome` takes `question = query.message.questions[0]`, calls `state.zone.lookup(question.name, question.qtype)` and maps, per data-model § Handler responses: `Answer` → `Outcome(Message(Header(aa=True), answers=list(result.records)), "local", False)`; `NoData` → `Message(Header(aa=True))`, `"local"`, `False`; `NXDomain` → `Message(Header(aa=True, rcode=NXDOMAIN))`, `"local"`, `False`. For `NotLocal`, temporarily return `Outcome(Message(Header(rcode=SERVFAIL)), "error", False)` (replaced in T015 and T020)
- [X] T006 Change `dnsd/__main__.py` (contracts/modules.md § `dnsd.__main__`, research R-3, R-9): after `parse_args`, build the zone with `load_zone(args.zone)` inside `try/except (OSError, ValueError) as exc`, printing `f"dnsd: {exc}"` to stderr and calling `sys.exit(1)`; pass it to `ServerState` in place of `PlaceholderZoneStore()` and call `serve(state, make_handler(state))` instead of `serve(state, stub_handler)`. Remove the now-unused imports of `PlaceholderZoneStore` and `stub_handler` from `__main__.py` (they stay defined in `listener.py`). The blocklist slot keeps `PlaceholderBlocklist()` until T016

**Checkpoint**: `python -m dnsd` with the quickstart § 4 flags starts; every query gets SERVFAIL
(lookup is still `NotLocal`); `ruff check dnsd` is clean; the 11 001 gate tests still pass.

---

## Phase 3: User Story 1 - A client resolves a home-network name from the zone file (Priority: P1) 🎯 MVP

**Goal**: Names with records of the requested type get them, NOERROR, AA=1, with zone TTLs.

**Independent Test**: `nas.home.lan.` A/AAAA over UDP and TCP; `tabs.home.lan.` TTL 60; 40 records
for `big.home.lan.` (truncated on UDP, complete on TCP); case-insensitive names.

### Implementation for User Story 1

- [X] T007 [US1] In `ZoneStore.lookup` in `dnsd/zone.py`, implement row 1 of data-model § ZoneStore state › lookup: under the lock, `records = self._by_name.get(name)`; if `records` holds any record with `rtype == qtype`, return `Answer(tuple(those records))` (FR-004); otherwise fall through to `NotLocal()` for now. Name lookup is case-insensitive through `Name.__eq__`/`__hash__` (FR-005)
- [X] T008 [US1] Check US1: `pytest --impl=. tests/test_zone.py::test_a_record tests/test_zone.py::test_aaaa_record tests/test_zone.py::test_cname_record tests/test_zone.py::test_ttl_comes_from_the_zone_file tests/test_zone.py::test_several_records_with_one_name_and_type tests/test_zone.py::test_names_match_case_insensitively tests/test_zone.py::test_local_answer_over_tcp tests/test_listener.py::test_udp_response_over_512_bytes_is_truncated tests/test_listener.py::test_truncated_response_keeps_question_and_whole_records tests/test_listener.py::test_truncated_answer_is_complete_over_tcp tests/test_listener.py::test_edns_does_not_raise_udp_limit` — all pass. Fix code in `dnsd/zone.py` or `dnsd/forwarder.py` only

**Checkpoint**: US1 complete; local positive answers work over UDP and TCP.

---

## Phase 4: User Story 2 - Missing local names and types get authoritative negative answers (Priority: P1)

**Goal**: NODATA for a local name without the type; NXDOMAIN for undefined names under a local
zone suffix; everything else stays `NotLocal`.

**Independent Test**: `printer.home.lan. AAAA`, `nas.home.lan. TXT/MX` → NODATA, AA=1;
`missing.home.lan.`, `a.b.home.lan.`, `sub.nas.home.lan.` → NXDOMAIN, AA=1.

### Implementation for User Story 2

- [X] T009 [US2] In `ZoneStore.lookup` in `dnsd/zone.py`, add rows 3–5 of data-model § ZoneStore state › lookup: if `records` exists (non-empty) but has no record of `qtype` (and the CNAME row of T011 does not apply), return `NoData()` (FR-006); if the name has no records, walk `candidate = name`, then `candidate.parent()` while `candidate.labels` is non-empty, including the root at the end, and return `NXDomain()` as soon as a candidate is in `self._suffixes` (FR-007); otherwise `NotLocal()`
- [X] T010 [US2] Check US2: `pytest --impl=. tests/test_zone.py::test_nodata tests/test_zone.py::test_nxdomain_under_local_suffix` — all pass; re-run T008's command to confirm no regression

**Checkpoint**: US1 and US2 complete.

---

## Phase 5: User Story 3 - CNAMEs in the zone are followed one step (Priority: P2)

**Goal**: A query for an alias (type ≠ CNAME) gets the CNAME first, then the target's records of
that type if the target is local.

**Independent Test**: `files.home.lan.` A/AAAA (2 records, CNAME first), TXT (CNAME alone);
`ext.home.lan.` A (CNAME alone, AA=1).

### Implementation for User Story 3

- [X] T011 [US3] In `ZoneStore.lookup` in `dnsd/zone.py`, add row 2 of data-model § ZoneStore state › lookup, between "records of qtype" and `NoData`: if `qtype != TYPE_CNAME` and the name has CNAME records, return `Answer(tuple(cnames + [r for c in cnames for r in self._by_name.get(c.rdata.target, []) if r.rtype == qtype]))` (FR-008). One step only: never look at CNAMEs of the target. Nothing is sent upstream for an outside target
- [X] T012 [US3] Check US3: `pytest --impl=. tests/test_zone.py::test_cname_is_followed_inside_the_zone tests/test_zone.py::test_cname_to_local_target_without_the_requested_type tests/test_zone.py::test_cname_to_target_outside_the_zone` — all pass; re-run T008 and T010's commands

**Checkpoint**: The local zone (FR-004 – FR-008) is complete.

---

## Phase 6: User Story 4 - Blocked domains and their subdomains get the blocking response (Priority: P1)

**Goal**: Blocklist file loaded at startup; listed domains and their subdomains get the blocking
response; nothing blocked goes upstream; the harness probe `ads.example.com.` is blocked.

**Independent Test**: `test_blocklist.py` (10 required tests) and the five blocklist-dependent
listener tests.

### Implementation for User Story 4

- [ ] T013 [P] [US4] Create `dnsd/blocklist.py` with class `Blocklist` (data-model § Blocklist state, FR-013, FR-014, research R-6): `__init__` creates `self._lock = threading.Lock()` and `self._listed: dict[Name, None] = {}` ("listed entries in insertion order; first spelling kept"). `is_blocked(name)`: under the lock, check `name` and each ancestor via `parent()` down to and including the root against `self._listed`; return `True` on the first hit. `domains()`: `list(self._listed)`. `add(name)`: insert only if absent (idempotent; the first spelling stays). `remove(name) -> bool`: delete and return `True` if listed, else `False` (a subdomain of a listed entry is not listed). Every method takes the lock for its whole body
- [ ] T014 [US4] Add module function `load_blocklist(path: str) -> Blocklist` to `dnsd/blocklist.py` (FR-002, research R-2, R-3): open with `encoding="utf-8"`; per line (1-based `n`): cut at the first `#` (`line.split("#", 1)[0]`), which handles both whole-line and trailing comments, so `ads.example.com # ads` lists `ads.example.com`; skip if blank; `fields = line.split()` must be exactly one field, else `ValueError(f"{path}:{n}: expected one domain")`; `Name.from_text(fields[0])` (trailing dot optional, case kept), re-raising its `ValueError` as `ValueError(f"{path}:{n}: {exc}")`; then `store.add(name)`. `OSError` and `UnicodeDecodeError` propagate
- [ ] T015 [US4] In `make_handler` in `dnsd/forwarder.py`, handle `NotLocal` first with `state.blocklist.is_blocked(question.name)` (FR-021 rows 4–6, FR-022, research R-8): qtype `TYPE_A` → `answers=[ResourceRecord(question.name, TYPE_A, CLASS_IN, 60, A(IPv4Address(0)))]`; `TYPE_AAAA` → `[ResourceRecord(question.name, TYPE_AAAA, CLASS_IN, 60, AAAA(IPv6Address(0)))]`, both `Header()` (NOERROR, AA=0); any other type (including ANY) → `Message(Header(rcode=NXDOMAIN))`; all `Outcome(..., "blocked", False)`. Use `IPv4Address(0)` / `IPv6Address(0)`, never the string `"0.0.0.0"`. Not blocked → keep T005's temporary SERVFAIL for now
- [ ] T016 [US4] Change `dnsd/__main__.py`: build the blocklist with `load_blocklist(args.blocklist)` inside the same `try/except (OSError, ValueError)` as the zone (exit 1, `dnsd: <message>` on stderr), pass it to `ServerState` in place of `PlaceholderBlocklist()`, and drop the unused `PlaceholderBlocklist` import. Both files are loaded before `serve` is called (FR-003)
- [ ] T017 [US4] Check US4: `pytest --impl=. tests/test_blocklist.py --deselect tests/test_blocklist.py::test_file_yields_exactly_its_entries --deselect tests/test_blocklist.py::test_local_zone_wins_over_blocklist` — the three tests that query unblocked names (`test_parent_of_listed_domain_is_not_blocked`, `test_name_sharing_only_a_suffix_string_is_not_blocked`, `test_comment_lines_are_ignored`) pass already, because they only check that the reply is not a blocking response; all others must pass. Then `pytest --impl=. tests/test_listener.py::test_tcp_query_with_length_prefix tests/test_listener.py::test_tcp_closes_connection_where_udp_gives_no_reply tests/test_listener.py::test_query_with_opt_record_is_answered_without_one tests/test_listener.py::test_no_reply_to_packets_shorter_than_a_header tests/test_listener.py::test_no_reply_to_packets_with_qr_set` — all pass. Re-run T008, T010 and T012's commands

**Checkpoint**: Local and blocked answers complete; the readiness probe is answered by the
blocklist; every remaining SERVFAIL comes from the not-yet-built forwarder.

---

## Phase 7: User Story 5 - Every other name is resolved by the upstream (Priority: P1)

**Goal**: Queries that are neither local nor blocked nor cached go to the upstream over UDP (TCP on
TC=1); its RCODE and three sections are relayed with AA=0; the cache is consulted and fed through
its role.

**Independent Test**: the relay tests of `test_forwarder.py` against the fake upstream, including
the TC=1 → TCP retry.

### Implementation for User Story 5

- [ ] T018 [US5] Add `exchange(upstream: tuple[str, int], question: Question) -> Message | None` to `dnsd/forwarder.py`, UDP path (FR-015 – FR-018, research R-7 steps 1–4 and 6, data-model § Upstream exchange): `deadline = time.monotonic() + 2.0` covering everything; bind an `AF_INET`/`SOCK_DGRAM` socket to `("", 1024 + secrets.randbelow(64512))`, on `OSError` close it and retry with a fresh port, "up to 5 bind attempts", then give up (`None`); `connect(upstream)`; send `encode(Message(Header(id=secrets.randbelow(65536), rd=True), [question]))`; loop: `remaining = deadline - time.monotonic()`, return `None` if `remaining <= 0`, `settimeout(remaining)`, `recv(65535)`; a datagram counts only if `decode_message(data)` is a `Message` with `header.qr` true, `header.id` equal to the sent ID and `questions == [question]`; otherwise ignore it and keep looping. Catch `OSError` (which includes `TimeoutError` and `ConnectionRefusedError`) around the whole exchange and return `None`. Use `with` so every socket is closed. Put the ID/port draws in one place each so a reviewer sees both come from `secrets` (Principle VI)
- [ ] T019 [US5] Add the TCP retry to `exchange` in `dnsd/forwarder.py` (FR-019, research R-7 step 5): if the counting UDP reply has `header.tc`, open `socket.create_connection(upstream, timeout=remaining)`, send the query again with a **new** `secrets.randbelow(65536)` ID as `struct.pack("!H", len(wire)) + wire`, read exactly 2 bytes of length then exactly that many bytes, setting `settimeout(deadline - time.monotonic())` before every `recv` (return `None` if not positive or on EOF); the reply counts under the same three checks as T018, and "One TCP reply only": if it does not count, return `None`. The TCP reply replaces the UDP one
- [ ] T020 [US5] In `make_handler` in `dnsd/forwarder.py`, replace T005/T015's temporary SERVFAIL for a name that is neither local nor blocked (FR-021 steps 3–4, FR-023, FR-024, research R-8): `cached = state.cache.get(question.name, question.qtype)`; if not `None` → `Outcome(Message(Header(rcode=cached.header.rcode), [], list(cached.answers), list(cached.authority), list(cached.additional)), "cached", False)`. Otherwise `reply = exchange(state.config.upstream, question)`; `None` → `Outcome(Message(Header(rcode=SERVFAIL)), "error", True)` and do **not** call `put`; a reply → `state.cache.put(question.name, question.qtype, reply)`, then `Outcome(Message(Header(rcode=reply.header.rcode), [], list(reply.answers), list(reply.authority), list(reply.additional)), "error" if reply.header.rcode == SERVFAIL else "forwarded", True)`. AA is always False on these paths
- [ ] T021 [US5] Check US5: `pytest --impl=. tests/test_forwarder.py::test_answer_is_relayed tests/test_forwarder.py::test_several_records_are_relayed tests/test_forwarder.py::test_other_types_are_relayed tests/test_forwarder.py::test_nxdomain_is_relayed tests/test_forwarder.py::test_authority_and_additional_are_relayed tests/test_forwarder.py::test_nxdomain_authority_is_relayed tests/test_forwarder.py::test_other_upstream_rcodes_are_relayed tests/test_forwarder.py::test_response_carries_the_clients_id_and_question tests/test_forwarder.py::test_forwarded_answer_over_tcp tests/test_forwarder.py::test_upstream_receives_the_question tests/test_forwarder.py::test_name_outside_every_local_suffix_is_forwarded tests/test_forwarder.py::test_blocked_names_are_not_forwarded tests/test_forwarder.py::test_truncated_upstream_reply_is_retried_over_tcp tests/test_forwarder.py::test_answer_fetched_over_tcp_is_truncated_for_a_udp_client tests/test_forwarder.py::test_client_udp_reply_never_exceeds_512_bytes tests/test_zone.py::test_local_names_are_not_forwarded tests/test_blocklist.py::test_parent_of_listed_domain_is_not_blocked tests/test_blocklist.py::test_name_sharing_only_a_suffix_string_is_not_blocked tests/test_blocklist.py::test_comment_lines_are_ignored` — all pass (the last three passed trivially in T017; now the names are really forwarded)

**Checkpoint**: Every row of contract.md § Responses is implemented (cache through its placeholder).

---

## Phase 8: User Story 6 - Forwarding resists spoofing and upstream failure (Priority: P1)

**Goal**: Random ID and source port per query; wrong-ID replies ignored; SERVFAIL within the
budget for a silent, spoofing or unreachable upstream; the server keeps working.

**Independent Test**: the randomness, wrong-ID, timeout and recovery tests of `test_forwarder.py`
and the fuzz stream.

### Implementation for User Story 6

- [ ] T022 [US6] Review `exchange` in `dnsd/forwarder.py` against constitution Principle VI and spec FR-016 – FR-018: both IDs (UDP and TCP retry) and the UDP source port come from `secrets` and are drawn fresh per call; none is stored, counted up, configurable or derived from the client's query; the deadline is set once at the start and every wait uses the remaining time (no per-`recv` fixed timeout that could add up past 2 s); non-matching or undecodable datagrams loop without resetting the deadline; every failure path returns `None`. Fix any deviation in `dnsd/forwarder.py`
- [ ] T023 [US6] Check US6: `pytest --impl=. tests/test_forwarder.py::test_upstream_query_ids_are_random tests/test_forwarder.py::test_upstream_source_ports_are_random tests/test_forwarder.py::test_reply_with_wrong_id_is_ignored tests/test_forwarder.py::test_reply_within_two_seconds_is_used tests/test_forwarder.py::test_servfail_when_upstream_is_silent tests/test_forwarder.py::test_servfail_over_tcp tests/test_forwarder.py::test_server_keeps_working_after_upstream_failure tests/test_fuzz.py::test_server_survives_fuzzing` — all pass
- [ ] T024 [US6] Manual check of an unreachable upstream (spec Edge Cases; no test covers it): start `python -m dnsd` with the quickstart § 4 flags but `--upstream 127.0.0.1:<a closed port>`, send a UDP query for `example.org. A`; expect SERVFAIL well within 2 s (ICMP port unreachable surfaces as `ConnectionRefusedError` on the connected socket) and nothing on stderr; then query `nas.home.lan. A` and `ads.example.com. A` and expect their normal answers. Scratch only; no file changes unless a fix is needed in `dnsd/forwarder.py`

**Checkpoint**: All forwarding requirements verified, including Principle VI.

---

## Phase 9: User Story 7 - Features 003 and 004 plug into finished stores and handler (Priority: P2)

**Goal**: The stores and handler need no change when 003 and 004 replace the remaining
placeholders and add the admin API.

**Independent Test**: review against 001 interfaces.md and contracts/modules.md; the tests deferred
to 003/004 can only be run when those merge.

### Implementation for User Story 7

- [ ] T025 [US7] Review `dnsd/zone.py` and `dnsd/blocklist.py` against 001 `contracts/interfaces.md` § 3: `ZoneStore` public methods are exactly `lookup, records, add, remove, make_record, value_text` and `Blocklist` exactly `is_blocked, domains, add, remove`, with those signatures; each stateful method takes the store's own lock for its whole body and does no I/O or call to another store inside it; `records()`/`domains()` return new lists; `Answer.records` is a tuple. Check by hand in a Python shell (scratch, not committed): `make_record("added.home.lan", "a", 120, "192.168.1.99")` is a record (no trailing dot, lowercase type accepted); `make_record("x.", "MX", 60, "10 x.")`, `make_record("x.", "A", -1, "1.2.3.4")`, `make_record("x.", "A", True, "1.2.3.4")`, `make_record("x.", "AAAA", 60, "fe80::1%eth0")` are `Invalid`; `value_text` gives `"192.168.1.10"`, `"fd00::10"`, `"nas.home.lan."`; adding the same record twice with a new TTL leaves one record with the new TTL; `remove` of the last record under `other.lan.` makes `missing.other.lan.` `NotLocal`. Fix in `dnsd/zone.py` / `dnsd/blocklist.py` only
- [ ] T026 [US7] Review `dnsd/forwarder.py` against FR-021 – FR-025 and DC-1: stores are reached only through `state` (`state.zone`, `state.blocklist`, `state.cache`, `state.config.upstream`); the handler never calls `state.stats` or `state.log`; it sets only `rcode`, `aa` and the three sections (no `id`, `qr`, `ra`, `tc`, `rd`, questions); every section list is new; no lock is held. Confirm `dnsd/listener.py` and `dnsd/parser.py` are unchanged (`git diff --stat dnsd/listener.py dnsd/parser.py` is empty) and that only `dnsd/__main__.py` imports `dnsd.zone`, `dnsd.blocklist` and `dnsd.forwarder`

**Checkpoint**: All seven user stories implemented and checked.

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: Gates required by the constitution and the spec's acceptance criteria

- [ ] T027 Run `ruff check dnsd` and `bandit -r dnsd` from the repo root and fix every finding in `dnsd/` (Principle VII; zero findings). If bandit flags the `("", port)` bind (B104), do not suppress it; instead, in `exchange` in `dnsd/forwarder.py`, `connect()` a throwaway `AF_INET`/`SOCK_DGRAM` socket to the upstream (sends nothing), read the local address with `getsockname()[0]`, close it, and bind the query socket to `(that address, 1024 + secrets.randbelow(64512))` (research R-7 lint note)
- [ ] T028 Manual check of startup errors (research R-3, quickstart § 4): with scratch files outside the repo, confirm exit status 1, one `dnsd: ...` line on stderr and no bound socket for: a missing `--zone` path; a missing `--blocklist` path; a zone line `nas.home.lan. 300 IN MX 10 x.` (`<path>:1:` in the message); a zone line without a trailing dot on the name; a blocklist line `ads example.com`. Also confirm a zone file with a trailing `; comment` after a record and a blocklist line `ads.example.com # ads` both load and that `ads.example.com.` is then blocked. Fix in `dnsd/zone.py`, `dnsd/blocklist.py` or `dnsd/__main__.py` only
- [ ] T029 Run the acceptance gate of `specs/002-zone-forwarder/quickstart.md` § 2 (six suites, nine deselected tests): all 65 tests pass, nothing skipped
- [ ] T030 Run the full suite `pytest tests --impl .` (quickstart § 3) and record every failing test: each must be in `tests/test_cache.py` or `tests/test_admin_api.py` (the cache and admin API suites, verified with 003 and 004), or one of the 9 tests spec.md § Verification status defers to 004 from the six 002 suites, and fail on a missing cache, `/stats`, `/log`, `/records` or `/blocklist` (connection refused or 404 from the admin port, or an uncached repeat), never on "dnsd exited" or "no response" from the DNS port. Report the list for the reviewer (constitution § Technical Constraints)
- [ ] T031 Re-read `dnsd/zone.py`, `dnsd/blocklist.py`, `dnsd/forwarder.py` and `dnsd/__main__.py` against `specs/002-zone-forwarder/contracts/modules.md` and 001 `contracts/interfaces.md` one last time: no public name beyond those contracts except `_`-prefixed helpers; no unused imports or code; no leftover temporary SERVFAIL from T005/T015 (Principle VIII, IX). `stub_handler`, `PlaceholderZoneStore` and `PlaceholderBlocklist` stay in `dnsd/listener.py` on purpose, unused after this feature: `listener.py` is 001 code and is not changed (research R-9)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup; blocks every user story
- **US1 (Phase 3)**: depends on Phase 2
- **US2 (Phase 4)**: depends on US1 (extends the same `lookup`)
- **US3 (Phase 5)**: depends on US2 (inserts a row into `lookup` between US1's and US2's rows)
- **US4 (Phase 6)**: depends on Phase 2 only; T013 can start right after Phase 2. Its checks
  (T017) re-run the US1–US3 commands, so run them after those phases
- **US5 (Phase 7)**: depends on US4 (T020 replaces the temporary branch after the blocked branch of
  T015; the US5 checks need the probe to be blocked)
- **US6 (Phase 8)**: depends on US5 (reviews and checks the finished `exchange`)
- **US7 (Phase 9)**: depends on US1–US6
- **Polish (Phase 10)**: depends on all stories

### Within each phase

- Phase 2: T002 → T003 → T004; T005 in parallel with T002–T004 (imports only listener/parser types); T006 after T004
  and T005
- Phase 6: T013 → T014 → T016; T015 after T013 (needs only the role); T017 last
- Phase 7: T018 → T019; T020 after T018; T021 last
- Phase 8: T022 → T023 → T024

### Parallel Opportunities

- T005 (`dnsd/forwarder.py`) with T003–T004 (`dnsd/zone.py`)
- T013–T014 (`dnsd/blocklist.py`) with Phases 3–5 (`dnsd/zone.py`)
- T018–T019 (`exchange`) can be written alongside Phase 6 once T015 is in, since T020 is the only
  step that joins them in the handler

---

## Parallel Example: User Story 4 alongside the local zone

```bash
# Developer A (dnsd/zone.py):
Task: "T007 lookup row 1", "T009 NODATA / NXDOMAIN", "T011 CNAME"

# At the same time (dnsd/blocklist.py):
Task: "T013 Blocklist store", "T014 load_blocklist"
```

## Parallel Example: User Story 5

```bash
# dnsd/forwarder.py, exchange():
Task: "T018 UDP exchange with secrets ID/port and one 2 s deadline"
Task: "T019 TCP retry on TC=1"
# then the handler:
Task: "T020 cache get/put and forward branch with the Q1 result rule"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 Setup, Phase 2 Foundational
2. Phase 3 US1 → STOP and validate with T008: local names answer authoritatively, and the three
   001 tests that needed `big.home.lan.` pass

### Incremental Delivery

1. + US2, US3 → the whole local zone (FR-004 – FR-008)
2. + US4 → blocklist; the five blocklist-dependent 001 listener tests pass, and the probe stops
   reaching the upstream
3. + US5 → forwarding; every row of contract.md § Responses works
4. + US6 → Principle VI and failure handling verified; fuzz stream passes
5. + US7, Polish → reviews, ruff/bandit clean, 65-test gate green, deferred failures listed, then
   review by Daniel (Principle X), together with the constitution 1.1.1 amendment

---

## Notes

- `[P]` tasks touch different files and have no unfinished dependencies
- T005 and T015 leave a temporary SERVFAIL branch that T020 replaces; T031 checks none is left
- Manual checks (T024, T025, T028) use scratch scripts or a Python shell outside the repo; nothing
  from them is committed
- The 9 deferred tests of the six 002 suites, and the parts of `test_cache.py` and
  `test_admin_api.py` that need a cache or the admin API, stay red until 003 and 004 merge (spec
  § Verification status); that is expected, not a defect of this feature
