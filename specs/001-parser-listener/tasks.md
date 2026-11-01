---

description: "Task list for feature 001: wire parser and UDP/TCP listener"
---

# Tasks: Wire Parser and UDP/TCP Listener

**Input**: Design documents from `specs/001-parser-listener/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/interfaces.md, quickstart.md

**Tests**: No test tasks are generated. The spec (Clarifications Q1/Q2, plan § Testing) forbids
adding or modifying anything in `tests/`. Verification uses the existing black-box suite
(`pytest --impl=. ...`), `ruff check dnsd` and `bandit -r dnsd`. The acceptance gate is the 11
stub-compatible tests listed in spec.md § Verification status.

**Organization**: Tasks are grouped by user story so each story can be implemented and checked on
its own. Only four source files exist (`dnsd/__init__.py`, `dnsd/__main__.py`, `dnsd/parser.py`,
`dnsd/listener.py`), so most tasks in one phase touch the same file and are **not** `[P]`.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story the task belongs to (US1–US6, from spec.md)
- Every task names its file path

## Rules that apply to every task (do not repeat per task)

- Standard library only (Principle III). Allowed imports: `dataclasses`, `struct`, `ipaddress`,
  `socketserver`, `socket`, `threading`, `argparse`, `time`, `sys`, `contextlib`, `typing`,
  `collections.abc`.
- Signatures, class names, field names and field order MUST match
  `specs/001-parser-listener/contracts/interfaces.md` exactly; that file is binding for 002–004.
- No `assert` (bandit B101), no `try/except/pass` (B110; use `contextlib.suppress`), no `random`
  (B311), no literal `0.0.0.0` (B104), no `logging` module. Errors go to
  `print("dnsd: ...", file=sys.stderr)` (research R-11, R-12).
- Public parser functions never raise on any input (Principle V, research R-6).
- No new files beyond the four above; no changes under `tests/` or to `contract.md`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Package skeleton and tool environment

- [ ] T001 Create the package marker `dnsd/__init__.py` as an empty file (plan § Project Structure)
- [ ] T002 [P] Install the test/lint tools with `pip install -r tests/requirements.txt` from the repo root and confirm `ruff --version`, `bandit --version` and `pytest --version` run (quickstart § Prerequisites); no repo file changes

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The message model, encoder, name reader and every shared interface type. All user
stories depend on these.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Message model — `dnsd/parser.py`

- [ ] T003 Create `dnsd/parser.py` with the module-level constants exactly as in contracts/interfaces.md § 1: `TYPE_A, TYPE_NS, TYPE_CNAME, TYPE_SOA, TYPE_PTR = 1, 2, 5, 6, 12`; `TYPE_MX, TYPE_TXT, TYPE_AAAA, TYPE_OPT, TYPE_ANY = 15, 16, 28, 41, 255`; `CLASS_IN = 1`; `NOERROR, FORMERR, SERVFAIL, NXDOMAIN, NOTIMP = 0, 1, 2, 3, 4`
- [ ] T004 Add `Name` to `dnsd/parser.py` as `@dataclass(frozen=True, eq=False)` with field `labels: tuple[bytes, ...]` (data-model § Name): `__post_init__` raises `ValueError` unless "each label 1–63 bytes; `sum(len(l) + 1) + 1 ≤ 255`; `()` is the root"; `__eq__`/`__hash__` compare the labels lowercased in ASCII only (`bytes.lower()`, RFC 4343) and return `NotImplemented` for non-Name; `parent()` returns the name with the first label removed and raises `ValueError` for the root; `is_subdomain_of(other)` is a whole-label suffix match, true for itself, true for every name against the root
- [ ] T005 Add `Name.to_text()` and `Name.from_text(text)` to `dnsd/parser.py` (FR-026, data-model § Name): to_text joins labels with `.` and appends a trailing `.`; root is `"."`; bytes `0x21`–`0x7E` other than `.` and `\` are written as-is, every other byte as `\DDD` (three decimal digits). from_text accepts `\DDD` and `\X` escapes, an optional trailing dot, `"."` as root, keeps letter case, and raises `ValueError` for an empty string, an empty label, a bad escape or a T004 limit violation
- [ ] T006 Add `Header` and `Question` frozen dataclasses to `dnsd/parser.py` with the fields, order and defaults of contracts/interfaces.md § 1 (`id, qr, opcode, aa, tc, rd, ra, z, rcode`, all defaulting to 0/False). `Header.__post_init__` raises `ValueError` unless "`id` 0–65535, `opcode` 0–15, `z` 0–7, `rcode` 0–15". `Question.__post_init__` raises `ValueError` unless `qtype` and `qclass` are 0–65535
- [ ] T007 Add RDATA dataclasses `A`, `AAAA`, `CNAME`, `NS`, `PTR`, `MX`, `SOA`, `Raw`, the alias `RData = A | AAAA | CNAME | NS | PTR | MX | SOA | Raw`, and `ResourceRecord(name, rtype, rclass, ttl=field(compare=False), rdata)` to `dnsd/parser.py` (contracts § 1, data-model § ResourceRecord / § RDATA types). Validation in `__post_init__` raising `ValueError`: `A.address` is `IPv4Address`, `AAAA.address` is `IPv6Address`; `MX.preference` 0–65535; SOA `serial, refresh, retry, expire, minimum` "each 0–4294967295"; `Raw.data` is `bytes` "≤ 65535 bytes"; `rtype`/`rclass` 0–65535; `ttl` "0–4294967295"; rdata class must match rtype: "`A` ↔ 1, `NS` ↔ 2, `CNAME` ↔ 5, `SOA` ↔ 6, `PTR` ↔ 12, `MX` ↔ 15, `AAAA` ↔ 28, `Raw` ↔ any other type (including TXT and OPT)". Note: `ttl` has no default but precedes `rdata`; use `field(compare=False)` without a default as the contract shows, which is valid because no earlier field has a default
- [ ] T008 Add `Message` (`header`, then `questions`, `answers`, `authority`, `additional` as `list` with `field(default_factory=list)`) and the decode result classes `Short`, `IsResponse`, `NotImp(header)`, `FormErr(header)`, `Malformed` as frozen dataclasses to `dnsd/parser.py` (contracts § 1, data-model § Decode results)
- [ ] T009 Add `type_to_text(code)` and `type_from_text(text)` to `dnsd/parser.py` (FR-025): mnemonics A=1, NS=2, CNAME=5, SOA=6, PTR=12, MX=15, TXT=16, AAAA=28, OPT=41, ANY=255; any other code → `f"TYPE{code}"`; from_text is case-insensitive, also accepts `TYPEn` with n in 0–65535, and raises `ValueError` otherwise

### Wire helpers — `dnsd/parser.py`

- [ ] T010 Add the private exception `_ParseError(Exception)` and `_read_name(data: bytes, offset: int) -> tuple[Name, int]` to `dnsd/parser.py` (FR-021, research R-6): returns the name and the offset just after it in the original byte stream (after the first pointer if one was followed). Check every index against `len(data)` before reading; follow `0b11` pointers only to offsets `< len(data)`, keep a set of visited pointer targets and fail on revisit (loop); fail on label types `0b01`/`0b10`, on a label > 63 bytes, on total wire length (sum of label lengths + length octets + root) > 255, and on a name running past the end. Every failure raises `_ParseError`
- [ ] T011 Add `encode(message: Message) -> bytes` to `dnsd/parser.py` (contracts § 1, research R-5): 12-byte header packed with `struct` (`!HHHHHH`; flags `qr<<15 | opcode<<11 | aa<<10 | tc<<9 | rd<<8 | ra<<7 | z<<4 | rcode`; counts from `len()` of the four lists); names written uncompressed (length-prefixed labels + `0x00`); questions as name + `!HH`; records as name + `!HHIH` (type, class, ttl, rdlength) + rdata. RDATA: A → `address.packed` (4 bytes), AAAA → `address.packed` (16), CNAME/NS/PTR → the name, MX → `!H` preference + exchange name, SOA → mname + rname + `!IIIII`, Raw → `data` unchanged. Must not raise for any Message whose parts passed their `__post_init__` checks

### Shared interface types — `dnsd/listener.py`

- [ ] T012 Create `dnsd/listener.py` with `Result = Literal["local", "blocked", "cached", "forwarded", "error"]` and frozen dataclasses `Query(message, client)`, `Outcome(response, result, upstream_asked)`, `Config(listen, admin, upstream, zone_path, blocklist_path)`, `LogEntry(time, client, name, type, result)`, `Answer(records: tuple[ResourceRecord, ...])`, `NoData`, `NXDomain`, `NotLocal`, `Invalid(reason: str)`, and `Handler = Callable[[Query], Outcome]`, field names/types/order exactly as contracts/interfaces.md §§ 2–3 (depends on T008)
- [ ] T013 Add `Stats` to `dnsd/listener.py` (data-model § Stats, FR-031, research R-2): four int counters `queries`, `blocked`, `cache_hits`, `cache_misses` starting at 0, one private `threading.Lock`; `record(outcome)` under the lock does `queries += 1`, `blocked += 1` if `outcome.result == "blocked"`, `cache_hits += 1` if `outcome.result == "cached"`, `cache_misses += 1` if `outcome.upstream_asked`; `snapshot()` returns a new `dict` with keys `"queries", "blocked", "cache_hits", "cache_misses"` read under the lock
- [ ] T014 Add the four stateless placeholder stores to `dnsd/listener.py` with exactly the method signatures of contracts/interfaces.md § 3 › Store operations (data-model § Placeholder stores): `PlaceholderZoneStore` (`lookup` → `NotLocal()`; `records` → `[]`; `add` does nothing; `remove` → `0`; `make_record` → `Invalid("no zone support")`; `value_text` → `""`), `PlaceholderBlocklist` (`is_blocked` → `False`; `domains` → `[]`; `add` does nothing; `remove` → `False`), `PlaceholderCache` (`get` → `None`; `put` does nothing), `PlaceholderQueryLog` (`append` does nothing; `recent` → `[]`). No locks (no state)
- [ ] T015 Add `ServerState` (frozen dataclass: `config, zone, blocklist, cache, stats, log`, in that order, contracts § 3) and `stub_handler(query: Query) -> Outcome` returning `Outcome(Message(Header(rcode=SERVFAIL)), "error", False)` (FR-019) to `dnsd/listener.py`

**Checkpoint**: `python -c "import dnsd.parser, dnsd.listener"` succeeds; `ruff check dnsd` is clean.

---

## Phase 3: User Story 1 - A client gets a correctly framed reply to a valid query (Priority: P1) 🎯 MVP

**Goal**: A valid UDP or TCP query reaches the (stub) handler and the client gets back a reply with
the query's ID and exact question bytes, QR=1, RA=1, RCODE SERVFAIL; TCP replies carry a 2-byte
length prefix. Counting and logging happen for every such query.

**Independent Test**: Start `python -m dnsd` with the five flags, send a query over UDP and over
TCP, check ID, question (case kept), QR, RA, SERVFAIL (quickstart § 4).

### Implementation for User Story 1

- [ ] T016 [US1] Add `decode_query(data: bytes)` to `dnsd/parser.py` (FR-008, FR-009, research R-6): rule 1 `len(data) < 12` → `Short()`; unpack the header; rule 2 QR=1 → `IsResponse()`; rule 3 opcode ≠ 0 → `NotImp(header)`; rule 4 QDCOUNT ≠ 1 → `FormErr(header)`; rule 5 read one question with `_read_name` + 4 bytes `!HH` (bounds-checked), any `_ParseError` → `FormErr(header)`; rule 6 → `Message(header, [question])` with the other three lists empty. Never read the answer/authority/additional sections or trailing bytes. Wrap the body so no exception escapes (catch `_ParseError`, `struct.error`, `ValueError`). The header used for NotImp/FormErr must be constructible from any 12 bytes (all fields are in range by bit width)
- [ ] T017 [US1] Add `_finalise(query: Message, response: Message) -> Message` to `dnsd/listener.py` (FR-012–FR-014, research R-8): header = `dataclasses.replace(response.header, id=query.header.id, qr=True, opcode=0, rd=query.header.rd, ra=True, tc=False, z=0)` (handler keeps `aa` and `rcode`); `questions = list(query.questions)`; `answers`, `authority`, `additional` copied as new lists from the response
- [ ] T018 [US1] Add `_account(state: ServerState, query: Query, outcome: Outcome, arrival: float) -> None` to `dnsd/listener.py` (FR-031, research R-11): `state.stats.record(outcome)` then `state.log.append(LogEntry(time=arrival, client=query.client[0], name=q.name.to_text(), type=type_to_text(q.qtype), result=outcome.result))` where `q = query.message.questions[0]`. Called only for valid queries, never for Short/IsResponse/NotImp/FormErr
- [ ] T019 [US1] Add `_process(data: bytes, client: tuple[str, int], tcp: bool, state: ServerState, handler: Handler) -> bytes | None` to `dnsd/listener.py`: take `arrival = time.time()`, call `decode_query`; for a `Message`, build `Query(message, client)`, call `handler(query)`, finalise with T017, `_account` (T018) **before** returning, and return `encode(finalised)`; return `None` for every non-Message result (US2 fills in the error branches). Hold no lock anywhere in this function (contracts § 3 rule 4)
- [ ] T020 [US1] Add the UDP side to `dnsd/listener.py` (research R-1, R-12): a `socketserver.BaseRequestHandler` subclass whose `handle()` takes `data, sock = self.request`, calls `_process(data, self.client_address, False, ...)` and, if bytes are returned, sends them with `sock.sendto(reply, self.client_address)` inside `contextlib.suppress(OSError)`; a `ThreadingUDPServer` subclass with `daemon_threads = True`, `allow_reuse_address = True`, `max_packet_size = 65535`, and attributes `state` and `handler` that the request handler reads via `self.server`
- [ ] T021 [US1] Add the TCP side to `dnsd/listener.py` (FR-006, research R-7): request handler computes `deadline = time.monotonic() + 5.0` at accept; a helper `_recv_exact(sock, n, deadline) -> bytes | None` loops `sock.settimeout(remaining)` + `recv`, returning `None` on timeout, EOF, `OSError` or `remaining <= 0`; read 2-byte big-endian length, then exactly that many bytes; call `_process(..., True, ...)`; if bytes are returned send `struct.pack("!H", len(reply)) + reply` with `sendall` inside `contextlib.suppress(OSError)`; then return so the connection closes (one query per connection). `ThreadingTCPServer` subclass with `daemon_threads = True`, `allow_reuse_address = True`, and `state`/`handler` attributes
- [ ] T022 [US1] Add `serve(state: ServerState, handler: Handler) -> None` to `dnsd/listener.py` (contracts § 4, research R-1): bind the TCP and UDP servers on `state.config.listen`; run the TCP server's `serve_forever` in a `threading.Thread(daemon=True)`; run the UDP server's `serve_forever` in the calling thread
- [ ] T023 [P] [US1] Create `dnsd/__main__.py` (FR-001, FR-002, FR-027, research R-10, data-model § Process): `argparse` with five `required=True` options `--listen`, `--admin`, `--upstream` (`type=` a function doing `host, _, port = text.rpartition(":")` and returning `(host, int(port))`) and `--zone`, `--blocklist` (`str`); build `Config(listen, admin, upstream, zone_path, blocklist_path)`, one `ServerState(config, PlaceholderZoneStore(), PlaceholderBlocklist(), PlaceholderCache(), Stats(), PlaceholderQueryLog())`, then `serve(state, stub_handler)`. Guard with `if __name__ == "__main__":` calling a `main()` function. No other validation; do not open the zone or blocklist files (spec Assumptions)
- [ ] T024 [US1] Verify US1: run `pytest --impl=. tests/test_harness.py::test_server_starts_with_documented_flags tests/test_listener.py::test_response_echoes_id tests/test_listener.py::test_response_echoes_question tests/test_listener.py::test_response_preserves_case_of_question_name tests/test_listener.py::test_qr_set_on_every_response tests/test_listener.py::test_ra_set_on_every_response` and the two dnspython one-liners of `specs/001-parser-listener/quickstart.md` § 4; all must pass/print SERVFAIL with QR RD RA. Fix code in `dnsd/` only

**Checkpoint**: MVP. A client gets a correctly framed SERVFAIL over UDP and TCP.

---

## Phase 4: User Story 2 - Malformed and hostile input never takes the server down (Priority: P1)

**Goal**: Each malformed class gets the reaction of FR-008 (no reply / close / bare FORMERR / bare
NOTIMP), handler failures become SERVFAIL, and no input stops the server.

**Independent Test**: Send short, QR=1, opcode 1/2/15, QDCOUNT ≠ 1 and broken-name packets over UDP
and TCP; then run the fuzz test and check it fails only on the canary's expected answer.

### Implementation for User Story 2

- [ ] T025 [US2] Add `_bare_reply(header: Header, rcode: int) -> bytes` to `dnsd/listener.py` (FR-010, research R-8): `encode(Message(Header(id=header.id, qr=True, opcode=header.opcode, rd=header.rd, ra=True, rcode=rcode)))`, i.e. exactly 12 bytes with AA=0, TC=0, Z=0 and all four counts zero
- [ ] T026 [US2] Extend `_process` in `dnsd/listener.py`: `NotImp(h)` → `_bare_reply(h, NOTIMP)`; `FormErr(h)` → `_bare_reply(h, FORMERR)`; `Short`/`IsResponse` → `None` (UDP: no reply; TCP: T021 closes the connection without data). None of these call `_account` (FR-031)
- [ ] T027 [US2] Add `_call_handler(handler: Handler, query: Query) -> Outcome` to `dnsd/listener.py` and use it in `_process` (FR-020): call the handler inside `try/except Exception`; on an exception, or a return value that is not an `Outcome` instance, print `dnsd: handler error: ...` to stderr and return `Outcome(Message(Header(rcode=SERVFAIL)), "error", False)`; the result is then finalised and accounted like any Outcome
- [ ] T028 [US2] Wrap the body of both request handlers' `handle()` in `dnsd/listener.py` in one `try/except Exception` that prints `dnsd: error handling message from <client>: <exc>` to stderr and sends nothing (FR-011, research R-11), so a defect while handling one message never stops the server thread or affects others
- [ ] T029 [US2] Verify US2: run `pytest --impl=. tests/test_listener.py::test_formerr tests/test_listener.py::test_notimp_for_other_opcodes tests/test_listener.py::test_tcp_formerr tests/test_listener.py::test_tcp_notimp` (must pass); then run `pytest --impl=. tests/test_fuzz.py tests/test_listener.py::test_no_reply_to_packets_shorter_than_a_header tests/test_listener.py::test_no_reply_to_packets_with_qr_set tests/test_listener.py::test_tcp_closes_connection_where_udp_gives_no_reply` and confirm these deferred tests fail only on the expected answer (`rcode=SERVFAIL` instead of NOERROR `0.0.0.0`), never with "server exited" or "no answer" (quickstart § 3). Fix code in `dnsd/` only

**Checkpoint**: US1 and US2 both work; the server survives hostile input.

---

## Phase 5: User Story 6 - Module developers build on one set of interfaces (Priority: P1)

**Goal**: The full-message decoder used by the forwarder and cache exists, and every name in
contracts/interfaces.md is importable with the exact signature given.

**Independent Test**: A decode → encode → decode round trip of a reply with compressed names in all
three record sections and an NXDOMAIN + SOA authority returns equal records with readable TTL and
MINIMUM; an import check finds every contract name.

### Implementation for User Story 6

- [ ] T030 [US6] Add `_read_rdata(data: bytes, offset: int, rtype: int, rdlength: int) -> RData` to `dnsd/parser.py` (FR-022, FR-023, research R-6): first check `offset + rdlength <= len(data)`; A requires `rdlength == 4` → `A(IPv4Address(bytes))`; AAAA requires `rdlength == 16` → `AAAA(IPv6Address(bytes))`; CNAME/NS/PTR read one name with `_read_name` (decompressed against the whole message); MX `!H` + name; SOA two names + `!IIIII`; for these, the parsed end offset must equal `offset + rdlength` exactly, else `_ParseError`; every other type → `Raw(data[offset:offset + rdlength])`
- [ ] T031 [US6] Add `decode_message(data: bytes) -> Message | Malformed` to `dnsd/parser.py` (FR-022, contracts § 1): read the header (fewer than 12 bytes → Malformed), then QDCOUNT questions and ANCOUNT/NSCOUNT/ARCOUNT records (name via `_read_name`, `!HHIH` bounds-checked, rdata via T030), building a `ResourceRecord` for each. Any `_ParseError`, `struct.error` or `ValueError` → `Malformed()`; never a partial message; bytes after the last counted section are ignored. Does not apply the FR-008 query rules (QR=1 is expected here)
- [ ] T032 [US6] Verify the interface contract: run a throwaway check from the repo root (not committed, e.g. a scratch script outside `dnsd/` and `tests/`) that (a) imports every name in contracts/interfaces.md §§ 1–4 from `dnsd.parser` / `dnsd.listener` and compares `dataclasses.fields()` names/order and `inspect.signature` of each function/method against the contract, (b) builds a reply with dnspython (`tests/requirements.txt`, allowed outside `dnsd/`) with compressed names in answer, authority and additional plus an NXDOMAIN reply with an SOA in authority, runs `decode_message` → `encode` → `decode_message`, and checks records are equal, TTLs preserved, and `rdata.minimum` readable, (c) feeds `decode_message` and `decode_query` 10 000 random byte strings and confirms neither raises. Fix any mismatch in `dnsd/` (never in the contract without amending spec.md)

**Checkpoint**: Features 002–004 can be planned against a working parser and stable interfaces.

---

## Phase 6: User Story 3 - Large answers are truncated on UDP and complete on TCP (Priority: P2)

**Goal**: No UDP reply exceeds 512 bytes (TC=1, header + question only), TCP replies are complete
with TC=0 (or SERVFAIL above 65535 bytes), and no reply ever carries an OPT record.

**Independent Test**: With the stub handler, `test_truncated_response_keeps_question_and_whole_records`
passes; the three 40-record tests are deferred to 002 (spec § Verification status). A scratch
handler that returns 40 A records shows a ≤ 512-byte TC=1 UDP reply and a complete TCP reply.

### Implementation for User Story 3

- [ ] T033 [US3] Extend `_finalise` in `dnsd/listener.py` to drop every record with `rtype == TYPE_OPT` from `answers`, `authority` and `additional` (FR-015, data-model lifecycle "drop OPT")
- [ ] T034 [US3] Extend `_process` in `dnsd/listener.py` for size limits (FR-016, FR-017, research R-8): after `wire = encode(finalised)`, if UDP and `len(wire) > 512` → `encode(Message(replace(finalised.header, tc=True), list(finalised.questions)))` (same ID, flags and RCODE, sections empty); if TCP and `len(wire) > 65535` → print a note to stderr and encode the FR-020 SERVFAIL form instead (`_finalise(query, Message(Header(rcode=SERVFAIL)))`) and account it as `Outcome(..., "error", False)`. Accounting (`_account`) happens once per query, with the Outcome actually answered. The handler's TC bit is always ignored (T017 sets `tc=False`)
- [ ] T035 [US3] Verify US3: run `pytest --impl=. tests/test_listener.py::test_truncated_response_keeps_question_and_whole_records` (must pass); then with a temporary local edit of `stub_handler` in `dnsd/listener.py` returning 40 `A` records for any query (reverted before commit), check with dnspython that a UDP reply is ≤ 512 bytes with TC=1 and the question, a UDP query with a 4096-byte EDNS OPT still gets ≤ 512 bytes and no OPT, and a TCP reply has all 40 records and TC=0. Confirm `git diff dnsd/listener.py` shows no leftover test edit

**Checkpoint**: Truncation and OPT rules hold; real 40-record checks resume when 002 merges.

---

## Phase 7: User Story 4 - The operator starts the server from the documented command line (Priority: P2)

**Goal**: `python -m dnsd` with the five contract.md flags answers on `--listen` within 5 s;
anything else gets argparse's default handling.

**Independent Test**: Start with the five valid flags and send a query; start with a missing flag
and observe usage + exit status 2.

### Implementation for User Story 4

- [ ] T036 [US4] Verify `dnsd/__main__.py` (built in T023) against FR-001/FR-002 and research R-10: `--listen 127.0.0.1:5353` yields `("127.0.0.1", 5353)` (split at the **last** `:`); `--zone`/`--blocklist` are kept as given strings and not opened; `python -m dnsd --listen 127.0.0.1:5353` prints argparse usage and exits 2; `--listen 127.0.0.1:abc` exits 2 via the `ValueError` from `int()`; with valid flags the first UDP query is answered within 5 s (SC-005, `tests/test_harness.py::test_server_starts_with_documented_flags`). Fix `dnsd/__main__.py` only if a check fails

**Checkpoint**: Operator-facing startup matches contract.md § Command line.

---

## Phase 8: User Story 5 - A slow query does not hold up other clients (Priority: P2)

**Goal**: A handler call of up to 2 s, or a stalled TCP connection, never delays other UDP/TCP
clients; idle TCP connections close after 5 s.

**Independent Test**: With a temporary 1.5 s handler for one name, a concurrent query for another
name is answered within 0.5 s (SC-004); an idle TCP connection is closed after 5 s while other
queries answer immediately (quickstart § 4). The official test is pending (Daniel).

### Implementation for User Story 5

- [ ] T037 [US5] Review `dnsd/listener.py` against FR-007, FR-028, FR-029 and contracts § 3 › Concurrency rules: both servers set `daemon_threads = True`; `_process`, `_call_handler` and both request handlers hold no lock while calling the handler, a socket or a store; `Stats` takes only its own lock and does in-memory work inside it; the TCP deadline is one 5 s deadline per connection (not per `recv`). Fix any violation in `dnsd/listener.py`
- [ ] T038 [US5] Verify US5: with a temporary local edit of `stub_handler` in `dnsd/listener.py` that sleeps 1.5 s when the question name is `slow.test.` (reverted before commit), send a UDP query for `slow.test.` and, while it is outstanding, UDP and TCP queries for `fast.test.`; both fast replies must arrive within 0.5 s. Run the quickstart § 4 idle-TCP one-liner and confirm it prints `b'' 5` while other queries answer immediately. Confirm `git diff dnsd/listener.py` shows no leftover test edit

**Checkpoint**: All six user stories are implemented and checked.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Gates required by the constitution and the spec's acceptance criteria

- [ ] T039 Run `ruff check dnsd` and `bandit -r dnsd` from the repo root and fix every finding in `dnsd/` (Principle VII; zero findings required)
- [ ] T040 Run the acceptance gate, the 11 stub-compatible tests of `specs/001-parser-listener/quickstart.md` § 2 (`pytest --impl=. tests/test_harness.py::test_server_starts_with_documented_flags ... tests/test_listener.py::test_truncated_response_keeps_question_and_whole_records`); all must pass with nothing skipped
- [ ] T041 Run `pytest --impl=. tests/test_listener.py tests/test_fuzz.py` and record which of the 9 deferred tests fail and why; each must fail only on the expected answer (quickstart § 3), never on "server exited" or "no answer"
- [ ] T042 [P] Re-read `dnsd/parser.py` and `dnsd/listener.py` against contracts/interfaces.md one last time: no public name, field or method beyond the contract except the documented placeholders, private `_`-prefixed helpers and the server/request-handler classes (Principle VIII, IX); remove anything unused
- [ ] T043 [P] Add the `S-NNN` entry for this `/speckit-tasks` call (and later the implement prompts) to `docs/prompt-log.md` in the existing format (constitution § Development Workflow); commits use `<type>(<module>): <what changed>` with `Prompt:` and `Spec:` trailers (README.md)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup; blocks every user story
- **US1 (Phase 3)**: depends on Phase 2; it creates `serve()` and `dnsd/__main__.py`, which every
  black-box check in later phases needs to start the server
- **US2 (Phase 4)**: depends on US1 (extends `_process` and the request handlers)
- **US6 (Phase 5)**: depends on Phase 2 only (`_read_name`, `encode`, model types); T030–T031 can
  be done in parallel with Phases 3–4 if someone else edits `dnsd/listener.py` meanwhile, since they
  touch only `dnsd/parser.py` (after T016 is merged, to avoid conflicts in the same file)
- **US3 (Phase 6)**: depends on US1 (edits `_finalise` and `_process`)
- **US4 (Phase 7)**: depends on US1 (T023)
- **US5 (Phase 8)**: depends on US1 and US2 (reviews the finished request handlers)
- **Polish (Phase 9)**: depends on all stories

### Within each phase

- Phase 2: T003 → T004 → T005; T006–T009 after T004; T010 after T004/T008; T011 after T007/T008;
  T012 after T008; T013–T015 after T012
- Phase 3: T016 → T017 → T018 → T019 → T020/T021 → T022; T023 in parallel with T016–T022
  (different file, imports only contract names); T024 last
- Phase 4: T025 → T026 → T027 → T028 → T029
- Phase 5: T030 → T031 → T032

### Parallel Opportunities

- T002 with T001
- T023 (`dnsd/__main__.py`) with T016–T022 (`dnsd/parser.py`, `dnsd/listener.py`)
- Phase 5 parser work (T030, T031) with Phase 4/6 listener work (T025–T028, T033–T034)
- T042 with T043

---

## Parallel Example: User Story 1

```bash
# Developer A (dnsd/parser.py, then dnsd/listener.py):
Task: "T016 Add decode_query to dnsd/parser.py"
Task: "T017–T022 finalise, account, _process, UDP/TCP servers, serve() in dnsd/listener.py"

# Developer B, at the same time (dnsd/__main__.py):
Task: "T023 Create dnsd/__main__.py with argparse, Config, ServerState, serve(state, stub_handler)"
```

## Parallel Example: User Story 6 alongside User Story 2

```bash
Task: "T030–T031 _read_rdata and decode_message in dnsd/parser.py"
Task: "T025–T028 bare replies, handler guard, per-message try/except in dnsd/listener.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 Setup, Phase 2 Foundational
2. Phase 3 US1 → STOP and validate with T024: the server answers framed SERVFAIL over UDP and TCP
   (6 of the 11 gate tests pass)

### Incremental Delivery

1. + US2 → the 4 FORMERR/NOTIMP gate tests pass; fuzzing does not kill the server (10 of 11)
2. + US6 → decode_message and the full interface exist; 002–004 can start
3. + US3 → truncation/OPT rules (`test_truncated_response_keeps_question_and_whole_records`: 11 of 11)
4. + US4, US5 → command-line and concurrency checks
5. Polish → ruff/bandit clean, acceptance gate green, then review by Daniel (Principle X)

---

## Notes

- `[P]` tasks touch different files and have no unfinished dependencies
- Temporary handler edits in T035 and T038 are for local checks only and must not be committed
- 9 tests stay red until features 002 (zone) and 004 (blocklist) merge; that is expected
  (spec § Verification status), not a defect of this feature
- Commit after each task or logical group, following the README commit format
