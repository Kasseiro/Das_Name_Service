# Feature Specification: Wire Parser and UDP/TCP Listener

**Feature Branch**: `001-parser-listener` (spec directory; no branch hook is configured, so no branch was created)

**Created**: 2026-11-01

**Status**: Draft

**Owner**: Johnny (modules: parser, listener; also the shared-state container and `__main__.py`)

**Input**: User description:

> Feature: wire parser and UDP/TCP listener for dnsd. This feature comes first and defines the
> interfaces the other modules (zone, forwarder, cache, blocklist, querylog, api) build on.
> Command line per contract.md § Command line; listen on UDP and TCP; a slow query must not block
> other clients; parse and encode complete DNS messages with name compression on read; query
> handling per contract.md § Responses › Malformed and unusual queries, § Truncation, § TCP and the
> ID/question/QR/RA rules in § Responses; hand each valid query with the client address to one
> resolution handler (a stub answering SERVFAIL until the resolution modules exist); define the
> shared state and how the listener and admin API access it concurrently. Out of scope: local zone,
> forwarding, cache, blocklist, query log, admin API. Verified by tests/test_listener.py,
> tests/test_fuzz.py, tests/test_harness.py.

This spec is the single definition of the inter-module interfaces required by constitution
Principle IX (section **Inter-module interfaces** below). The zone + forwarder, cache and
blocklist + admin API specs reference it and do not redefine anything in it. External behaviour is
fixed by `contract.md`; this spec cites its sections and does not restate them (Principle II).

## Clarifications

### Session 2026-11-01

- Q1: No test covers invalid-flag rejection (FR-002 to FR-004) or "a slow query must not block
  other clients" (FR-007, FR-029). Add tests or drop the requirements? → Answer (option B): Drop invalid-flag
  validation and rejection (FR-003, FR-004 removed; FR-002 reduced to parsing): contract.md leaves
  it unspecified and argparse's default behaviour is enough. Keep FR-007 and FR-029; their test is
  pending, to be added to the suite by Daniel (test suite owner). This feature does not modify
  `tests/`.
- Q2: 9 named tests in `test_listener.py` / `test_fuzz.py` need blocklist or zone answers and cannot
  pass with the SERVFAIL stub. What is the acceptance gate? → Answer (option A): The feature is accepted when the 11
  stub-compatible tests pass; the other 9 are re-checked when the blocklist (004) and zone (002)
  features merge (see Verification status).

## User Scenarios & Testing *(mandatory)*

The "users" of this feature are DNS clients on the host, the operator who starts the server, and
the developers of the other modules, who build on the interfaces defined here.

### User Story 1 - A client gets a correctly framed reply to a valid query (Priority: P1)

A DNS client sends a well-formed query over UDP or TCP. The server parses it, passes it to the
resolution handler and sends back the handler's response with the query's ID and question, QR=1
and RA=1. In this feature the handler is a stub that answers SERVFAIL; once the resolution modules
exist, the same path carries real answers.

**Why this priority**: every other feature's answers travel through this path. Without it nothing
is observable.

**Independent Test**: start the server with the five documented flags, send a query over UDP and
over TCP, and check that the reply parses, echoes ID and question (with the name's case kept), and
has QR and RA set.

**Acceptance Scenarios**:

1. **Given** the server is running, **When** a client sends a valid query over UDP with ID 0x1234,
   **Then** it receives one reply with ID 0x1234, the identical question section, QR=1 and RA=1.
2. **Given** the server is running, **When** a client sends the query `SuB.aDs.ExAmPlE.cOm. A`,
   **Then** the reply's question bytes are identical to the query's, including letter case.
3. **Given** the server is running, **When** a client sends a length-prefixed query over TCP,
   **Then** the reply is preceded by a two-byte length equal to the reply's size.
4. **Given** only the stub handler is installed, **When** any valid query arrives, **Then** the
   reply has RCODE SERVFAIL.

---

### User Story 2 - Malformed and hostile input never takes the server down (Priority: P1)

Untrusted bytes arrive on the DNS port: short packets, responses, unsupported opcodes, broken
names, compression loops, random garbage. The server reacts as contract.md § Responses › Malformed
and unusual queries prescribes and keeps answering everyone else.

**Why this priority**: one bad packet must not stop name resolution for the host (Principle V).

**Independent Test**: send each malformed packet class over UDP and TCP and check the reaction
(no reply / connection closed / bare FORMERR / bare NOTIMP); then run the seeded 2000-packet fuzz
stream and check that the server never exits and still answers a valid query.

**Acceptance Scenarios**:

1. **Given** the server is running, **When** a UDP packet of 0–11 bytes arrives, **Then** no reply
   is sent and the server keeps answering valid queries.
2. **Given** the server is running, **When** a packet with QR=1 arrives, **Then** no reply is sent
   (UDP) or the connection is closed without data (TCP).
3. **Given** the server is running, **When** a query with opcode 1, 2 or 15 arrives, **Then** the
   reply is a bare 12-byte NOTIMP header (contract.md § Responses › Malformed and unusual queries).
4. **Given** the server is running, **When** a query with QDCOUNT ≠ 1, or with a question that
   cannot be parsed (cut short, label over 63 bytes, name over 255 bytes, looping or out-of-packet
   compression pointer), arrives, **Then** the reply is a bare 12-byte FORMERR header.
5. **Given** the server is running, **When** the fuzz stream of seed 1035 is sent, **Then** the
   process never exits and every canary query is answered.

---

### User Story 3 - Large answers are truncated on UDP and complete on TCP (Priority: P2)

A response that does not fit in 512 bytes is sent over UDP as a truncated message with TC=1 so the
client retries over TCP, where it gets the whole answer. EDNS in the query changes nothing.

**Why this priority**: required by contract.md § Truncation; it only matters once answers can be
large (local zone, forwarder), but the mechanism belongs to the listener.

**Independent Test**: query a name with 40 A records over UDP (with and without an EDNS OPT
record) and over TCP.

**Acceptance Scenarios**:

1. **Given** a handler response that encodes to more than 512 bytes, **When** it is sent over UDP,
   **Then** the datagram is at most 512 bytes, has TC=1, keeps the question and contains only whole
   records.
2. **Given** the same response, **When** it is sent over TCP, **Then** it is complete and TC=0.
3. **Given** a query carrying an OPT record advertising a 4096-byte payload, **When** it is answered
   over UDP, **Then** the 512-byte limit still applies and the response carries no OPT record.

---

### User Story 4 - The operator starts the server from the documented command line (Priority: P2)

The operator runs `python -m dnsd` with the five flags of contract.md § Command line, and the
server starts answering on the `--listen` address. Invalid command lines are unspecified by
contract.md and get the argument parser's default handling.

**Why this priority**: the test harness and every user start the server this way.

**Independent Test**: start with the five valid flags and send a query.

**Acceptance Scenarios**:

1. **Given** five valid flags, **When** the server starts, **Then** it answers a UDP query on the
   `--listen` address within 5 seconds.

---

### User Story 5 - A slow query does not hold up other clients (Priority: P2)

While one query waits on the upstream (up to the 2-second budget of contract.md § Responses ›
Forwarded queries), other clients' queries over UDP and TCP are received and answered without
waiting for it.

**Why this priority**: a resolver that serialises queries stalls every client behind one slow
upstream. The mechanism belongs to the listener even though slow handlers only appear once the
forwarder exists.

**Independent Test**: make the upstream delay its reply by 1.5 s, send a query that is forwarded,
and while it is outstanding send a query that is answered locally; the second must be answered
well before the first.

**Acceptance Scenarios**:

1. **Given** a query whose handler call takes 1.5 s, **When** another client sends a query whose
   handler returns immediately, **Then** that client is answered within 0.5 s.
2. **Given** a TCP client that connects and sends nothing, **When** other clients query over UDP
   and TCP, **Then** they are answered normally, and the idle connection is closed after the idle
   timeout.

---

### User Story 6 - Module developers build on one set of interfaces (Priority: P1)

The developers of zone, forwarder, cache, blocklist, querylog and api use the message model, the
resolution-handler interface and the shared-state objects defined here, without redefining them
or reaching into another module's internals.

**Why this priority**: three developers work in parallel; this is the integration contract
(Principle IX). It must exist before the other specs are planned.

**Independent Test**: `/speckit-analyze` and review of the other three specs find no type, field,
operation or concurrency rule that this spec does not define, and none that contradicts it.

**Acceptance Scenarios**:

1. **Given** an upstream reply with compressed names in the answer, authority and additional
   sections, **When** the forwarder decodes it with the parser and the listener re-encodes it,
   **Then** the client receives the same records (verified by the forwarder tests listed under
   FR-024).
2. **Given** an upstream NXDOMAIN reply with an SOA record in the authority section, **When** the
   cache inspects the decoded reply, **Then** it can read the SOA record's TTL and MINIMUM.
3. **Given** the admin API adds a blocklist domain, **When** a query for that domain arrives
   immediately afterwards, **Then** the handler sees the change.

---

### Edge Cases

- **Query with trailing bytes or extra sections**: only the header and the first question are
  read; answer/authority/additional counts and any bytes after the question are ignored, including
  records that would not parse and an OPT record (contract.md § Responses › Malformed and unusual
  queries).
- **All four counts 65535 with one question**: QDCOUNT ≠ 1 → bare FORMERR.
- **Opcode ≠ 0 and QDCOUNT ≠ 1 together**: checks run in the order of FR-008, so the reply is
  NOTIMP.
- **Compression pointer in the question pointing into the header**: allowed if the referenced
  bytes form a valid name within the packet and no pointer loops; the response's question is
  written out uncompressed with the same labels.
- **Name exactly 255 bytes** (wire length including length octets and root): valid. 256: FORMERR.
- **Label of exactly 63 bytes**: valid. A label-length byte with the top bits `01` or `10`
  (reserved, RFC 1035 4.1.4): question cannot be parsed → FORMERR.
- **Query for type ANY, a type with no mnemonic, or a class other than IN**: valid query, passed to
  the handler unchanged (class handling is unspecified by contract.md and is not checked here).
- **TCP length prefix of 0–11**: the message is shorter than a header → the connection is closed
  without reply.
- **TCP client sends a length prefix and fewer bytes than announced, then waits**: the connection is
  closed when the idle timeout expires; other clients are unaffected.
- **TCP client closes before the reply is written**: the write failure is ignored; the query is
  still counted (FR-031), because it was answered.
- **Handler raises an unexpected error or returns something that is not an Outcome**: the listener
  answers SERVFAIL (FR-020) and keeps serving.
- **Response that does not fit in 65535 bytes over TCP** (possible only when an upstream reply that
  used compression grows when re-encoded): the listener answers SERVFAIL instead (FR-017).
- **Many slow queries at once**: each is handled independently; any limit on in-flight queries is a
  plan decision and is not specified by contract.md.
- **Invalid command line, or `--listen` and `--admin` naming the same address and port**:
  unspecified by contract.md; no requirement (FR-003 and FR-004 were removed in clarification).
- **UDP datagram larger than 512 bytes from a client**: accepted and parsed like any other query.

## Requirements *(mandatory)*

Each requirement lists the tests that verify it (Principle IV). Tests marked **†** also depend on
another feature (zone, forwarder, cache, blocklist or admin API) and cannot pass while only the
stub handler (FR-019) is installed. Every test outside `test_listener.py`, `test_fuzz.py` and
`test_harness.py` is of this kind. See **Verification status** below.

### Functional Requirements

#### Command line (contract.md § Command line)

- **FR-001**: The server MUST start as `python -m dnsd` and accept the five flags `--listen`,
  `--admin`, `--zone`, `--blocklist` and `--upstream` in the form of contract.md § Command line.
  *Tests*: `tests/test_harness.py::test_server_starts_with_documented_flags`
- **FR-002**: `--listen`, `--admin` and `--upstream` MUST be split into an address and a port at the
  last `:`, and `--zone` and `--blocklist` kept as paths, giving the Config entity. This feature only
  parses these values; the admin API, zone, blocklist and forwarder features use them. A missing,
  unknown or malformed flag is not a requirement: contract.md leaves it unspecified, and the
  argument parser's default behaviour applies (see Clarifications).
  *Tests*: `tests/test_harness.py::test_server_starts_with_documented_flags`
- **FR-003**: *Removed in clarification (Q1): validation and rejection of invalid flag values.*
- **FR-004**: *Removed in clarification (Q1): required exit behaviour when a socket cannot be bound.*

#### Transport (contract.md § Command line, § TCP)

- **FR-005**: The server MUST receive queries on UDP and on TCP at the `--listen` address, and MUST
  start answering only after all startup loading (zone file, blocklist file) is complete.
  *Tests*: `tests/test_harness.py::test_server_starts_with_documented_flags`,
  `tests/test_listener.py::test_tcp_query_with_length_prefix` †
- **FR-006**: Over TCP every message MUST be read and written with a two-byte big-endian length
  prefix (RFC 1035 4.2.2). The server answers the first query on a connection and then closes it.
  A connection that has not delivered a complete message within an idle timeout (a few seconds;
  value chosen in the plan) is closed.
  *Tests*: `tests/test_listener.py::test_tcp_query_with_length_prefix` †,
  `tests/test_listener.py::test_tcp_formerr`, `tests/test_listener.py::test_tcp_notimp`
- **FR-007**: The handling of one query, including a handler call that takes up to the contract's
  2-second upstream budget, MUST NOT delay the receiving or answering of other queries over UDP or
  TCP, from the same or other clients. A stalled TCP connection MUST NOT delay other clients.
  *Tests*: pending: slow-upstream test (Daniel). No test in `tests/` covers this yet; Daniel, as
  test suite owner, adds it (see Clarifications). This feature does not modify `tests/`.

#### Query intake (contract.md § Responses › Malformed and unusual queries)

- **FR-008**: Each received message MUST be classified in this order, and the first matching rule
  applies:
  1. fewer than 12 bytes → no reply (TCP: close the connection);
  2. QR=1 → no reply (TCP: close the connection);
  3. opcode ≠ 0 → bare NOTIMP reply (FR-010);
  4. QDCOUNT ≠ 1 → bare FORMERR reply;
  5. the question cannot be parsed (FR-021 limits) → bare FORMERR reply;
  6. otherwise → valid query, passed to the resolution handler (FR-018).
  *Tests*: `tests/test_listener.py::test_no_reply_to_packets_shorter_than_a_header` †,
  `tests/test_listener.py::test_no_reply_to_packets_with_qr_set` †,
  `tests/test_listener.py::test_tcp_closes_connection_where_udp_gives_no_reply` †,
  `tests/test_listener.py::test_notimp_for_other_opcodes`,
  `tests/test_listener.py::test_formerr`, `tests/test_listener.py::test_tcp_formerr`,
  `tests/test_listener.py::test_tcp_notimp`
- **FR-009**: For a valid query, only the header and the single question MUST be read. Answer,
  authority and additional records in a query, including an OPT record, and any bytes after the
  question MUST be ignored and MUST NOT cause FORMERR.
  *Tests*: `tests/test_listener.py::test_query_with_opt_record_is_answered_without_one` †,
  `tests/test_listener.py::test_edns_does_not_raise_udp_limit` †
- **FR-010**: A FORMERR or NOTIMP reply MUST be exactly 12 bytes: the query's ID, QR=1, the query's
  opcode and RD bit (RFC 1035 4.1.1), AA=0, TC=0, RA=1, Z=0, the RCODE, and all four counts zero.
  *Tests*: `tests/test_listener.py::test_formerr`,
  `tests/test_listener.py::test_notimp_for_other_opcodes`, `tests/test_listener.py::test_tcp_formerr`,
  `tests/test_listener.py::test_tcp_notimp`
- **FR-011**: No input received on the DNS port MUST crash, hang or stop the server, and an error
  while handling one message MUST NOT affect the handling of others (Principle V).
  *Tests*: `tests/test_fuzz.py::test_server_survives_fuzzing` †,
  `tests/test_listener.py::test_no_reply_to_packets_shorter_than_a_header` †

#### Response finalisation (contract.md § Responses)

- **FR-012**: Every response to a valid query MUST carry the query's ID.
  *Tests*: `tests/test_listener.py::test_response_echoes_id`
- **FR-013**: Every response to a valid query MUST carry exactly the query's question: same name
  labels with their letter case, same type, same class.
  *Tests*: `tests/test_listener.py::test_response_echoes_question`,
  `tests/test_listener.py::test_response_preserves_case_of_question_name`
- **FR-014**: Every response MUST have QR=1 and RA=1, opcode 0 and the query's RD bit, whatever the
  handler set.
  *Tests*: `tests/test_listener.py::test_qr_set_on_every_response`,
  `tests/test_listener.py::test_ra_set_on_every_response`
- **FR-015**: No response MUST carry an OPT record: the listener removes any record of type OPT (41)
  from the handler's response before encoding.
  *Tests*: `tests/test_listener.py::test_query_with_opt_record_is_answered_without_one` †
- **FR-016**: Over UDP, a response whose encoding exceeds 512 bytes MUST be replaced by its header
  (same ID, flags and RCODE, TC=1) and question, with answer, authority and additional sections
  empty and their counts zero. The handler's TC bit is ignored; the listener alone sets TC.
  *Tests*: `tests/test_listener.py::test_udp_response_over_512_bytes_is_truncated` †,
  `tests/test_listener.py::test_truncated_response_keeps_question_and_whole_records` †,
  `tests/test_listener.py::test_edns_does_not_raise_udp_limit` †,
  `tests/test_forwarder.py::test_client_udp_reply_never_exceeds_512_bytes` †,
  `tests/test_forwarder.py::test_answer_fetched_over_tcp_is_truncated_for_a_udp_client` †
- **FR-017**: Over TCP, TC MUST never be set and the full response MUST be sent. If the encoding
  exceeds 65535 bytes, the listener MUST send a SERVFAIL response (FR-020 form) instead.
  *Tests*: `tests/test_listener.py::test_truncated_answer_is_complete_over_tcp` †

#### Resolution handler (see **Inter-module interfaces › Resolution handler**)

- **FR-018**: Each valid query MUST be passed exactly once, together with the client's address, to
  the single resolution handler installed at startup, and the handler's response MUST be finalised
  (FR-012 to FR-017) and sent to that client over the transport the query arrived on.
  *Tests*: `tests/test_admin_api.py::test_stats_queries_counts_udp_and_tcp` †,
  `tests/test_admin_api.py::test_log_limit_larger_than_log_returns_everything` †
- **FR-019**: Until the zone, forwarder, cache and blocklist features are implemented, the installed
  handler MUST be a stub that returns, for every query, an Outcome with RCODE SERVFAIL, empty
  sections, result `error` and `upstream_asked` false. The stub is replaced, not extended, by the
  real handler of the zone + forwarder feature.
  *Tests*: `tests/test_harness.py::test_server_starts_with_documented_flags`
- **FR-020**: If the handler raises an error or returns something other than an Outcome, the
  listener MUST answer SERVFAIL (query ID and question, QR=1, RA=1, empty sections), record the
  query as result `error` with `upstream_asked` false, report the error on standard error, and keep
  serving.
  *Tests*: `tests/test_fuzz.py::test_server_survives_fuzzing` †

#### Message model (see **Inter-module interfaces › Message model**)

- **FR-021**: The parser MUST decode names with RFC 1035 4.1.4 compression and MUST reject, without
  reading out of bounds: a label over 63 bytes, a name over 255 bytes, a reserved label type, a
  pointer outside the message, a pointer loop, and a name that runs past the end of the message.
  *Tests*: `tests/test_listener.py::test_formerr`, `tests/test_fuzz.py::test_server_survives_fuzzing` †
- **FR-022**: The parser MUST decode a complete message — header, questions, answer, authority and
  additional records — and encode a Message back to wire format, with every length and offset
  checked before it is read. A record whose RDLENGTH runs past the end of the message, or whose
  structured RDATA (FR-023) does not exactly fill RDLENGTH, makes the message malformed.
  *Tests*: `tests/test_forwarder.py::test_answer_is_relayed` †,
  `tests/test_forwarder.py::test_several_records_are_relayed` †,
  `tests/test_forwarder.py::test_authority_and_additional_are_relayed` †
- **FR-023**: RDATA MUST be held in structured form for A (an IPv4 address), AAAA (an IPv6 address),
  CNAME, NS and PTR (a name), MX (preference and exchange name) and SOA (MNAME, RNAME, SERIAL,
  REFRESH, RETRY, EXPIRE, MINIMUM). Names inside RDATA MUST be decompressed on read, so that the
  record re-encodes correctly in another message. RDATA of every other type MUST be kept as the
  raw bytes received and re-encoded unchanged.
  *Tests*: `tests/test_forwarder.py::test_other_types_are_relayed` †,
  `tests/test_forwarder.py::test_nxdomain_authority_is_relayed` †,
  `tests/test_cache.py::test_nxdomain_with_soa_is_cached_no_longer_than_ttl_and_minimum` †
- **FR-024**: Every record MUST expose its owner name, type, class and TTL (an unsigned 32-bit value
  as received) so that the cache can take the lowest answer TTL and the SOA TTL and MINIMUM.
  *Tests*: `tests/test_cache.py::test_entry_lives_for_the_lowest_ttl_in_the_answer` †,
  `tests/test_cache.py::test_nxdomain_with_soa_is_cached_no_longer_than_ttl_and_minimum` †,
  `tests/test_forwarder.py::test_authority_and_additional_are_relayed` †
- **FR-025**: The parser MUST convert between type codes and mnemonics for A (1), NS (2), CNAME (5),
  SOA (6), PTR (12), MX (15), TXT (16), AAAA (28), OPT (41) and ANY (255), in both directions and
  case-insensitively from text; every other code is written `TYPEn` (contract.md § Admin API ›
  /log).
  *Tests*: `tests/test_admin_api.py::test_log_entry_fields` †,
  `tests/test_admin_api.py::test_log_type_without_mnemonic` †
- **FR-026**: The parser MUST convert between names and their text form: labels joined by `.`
  with a trailing `.` (the root is `.`), with `.`, `\` and bytes outside printable ASCII written as
  `\DDD` (RFC 1035 5.1); from text, a trailing dot is optional and letter case is kept.
  *Tests*: `tests/test_admin_api.py::test_log_entry_fields` †,
  `tests/test_admin_api.py::test_blocklist_accepts_names_in_any_form` †

#### Shared state (see **Inter-module interfaces › Shared state**)

- **FR-027**: At startup the entry point MUST create exactly one ServerState and give the same
  instance to the listener, the resolution handler and the admin API. No module keeps a second copy
  of any store.
  *Tests*: `tests/test_admin_api.py::test_post_blocklist_takes_effect_immediately`,
  `tests/test_admin_api.py::test_posted_record_resolves`
- **FR-028**: Every store operation MUST be atomic with respect to every other operation on the same
  store, from any number of concurrent queries and admin API requests: a reader sees the state
  before or after a change, never part of it, and a change is visible to every operation that
  starts after it returns (contract.md § Admin API: "changes take effect immediately").
  *Tests*: `tests/test_admin_api.py::test_post_blocklist_takes_effect_immediately`,
  `tests/test_admin_api.py::test_delete_blocklist_unblocks_immediately`,
  `tests/test_admin_api.py::test_posted_record_resolves`,
  `tests/test_cache.py::test_blocking_a_cached_name_takes_effect_immediately`,
  `tests/test_cache.py::test_local_record_for_a_cached_name_takes_effect_immediately`
- **FR-029**: No store operation may wait on network I/O or call into another store, so a handler
  waiting on the upstream never holds up an admin API request or another query.
  *Tests*: pending: slow-upstream test (Daniel), as FR-007.
- **FR-030**: Store operations MUST return copies or immutable values; no caller can change a store
  except through its operations (Principle IX).
  *Tests*: `tests/test_admin_api.py::test_get_records_lists_zone_file_records`,
  `tests/test_admin_api.py::test_get_blocklist_lists_file_entries`

#### Accounting (contract.md § Admin API › /stats, › /log)

- **FR-031**: For every valid query whose Outcome the listener receives (or replaces under FR-020),
  the listener MUST — and nothing else may — increment `queries`, increment `blocked` if the result
  is `blocked`, `cache_hits` if it is `cached` and `cache_misses` if `upstream_asked` is true, and
  append one log entry with the query's arrival time, the client's IP address, the question name
  and type, and the result. Input that got no reply, FORMERR or NOTIMP MUST change no counter and
  add no log entry.
  *Tests*: `tests/test_admin_api.py::test_stats_queries_counts_udp_and_tcp` †,
  `tests/test_admin_api.py::test_stats_queries_ignores_uncounted_input` †,
  `tests/test_admin_api.py::test_log_ignores_uncounted_input` †,
  `tests/test_admin_api.py::test_log_entry_fields` †,
  `tests/test_admin_api.py::test_stats_blocked_counts_blocking_responses` †,
  `tests/test_cache.py::test_stats_count_misses_and_hits` †

### Key Entities *(include if feature involves data)*

- **Config**: the five parsed command-line values: `listen`, `admin` and `upstream` as
  (IPv4 address, port); `zone_path` and `blocklist_path`. Immutable after startup.
- **Message, Header, Question, Name, ResourceRecord**: the parsed form of a DNS message (see
  **Message model**).
- **Query / Outcome**: what the listener gives the resolution handler and what it gets back (see
  **Resolution handler**).
- **ServerState** with its stores **ZoneStore**, **Blocklist**, **Cache**, **Stats** and
  **QueryLog**: the server's only mutable state (see **Shared state**).
- **LogEntry**: one query-log line: `time`, `client`, `name`, `type`, `result`
  (contract.md § Admin API › /log).

### Inter-module interfaces *(normative; constitution Principle IX)*

The names below are the interface vocabulary for all specs. The plan of this feature turns them
into concrete signatures in its `contracts/` directory; that file and this section must agree, and
changing either is an amendment of this spec.

#### Message model (module: parser)

- **Name**: a sequence of labels, each 1–63 bytes, as received (letter case preserved); total wire
  length at most 255. Two names are equal when their labels are equal ignoring ASCII case
  (RFC 4343). Operations: equality, `parent()` (first label removed), `is_subdomain_of(other)`
  (whole-label suffix match, a name being a subdomain of itself), `to_text()` / `from_text()`
  (FR-026).
- **Header**: `id` (0–65535), `qr`, `aa`, `tc`, `rd`, `ra` (booleans), `opcode` (0–15),
  `z` (0–7), `rcode` (0–15). Section counts are not stored; they are taken from the section
  lengths when encoding.
- **Question**: `name` (Name), `qtype` (0–65535), `qclass` (0–65535).
- **ResourceRecord**: `name` (Name), `rtype`, `rclass` (0–65535), `ttl` (0–4294967295), `rdata`.
  `rdata` is one of: `A(address)`, `AAAA(address)`, `CNAME(target)`, `NS(host)`, `PTR(target)`,
  `MX(preference, exchange)`, `SOA(mname, rname, serial, refresh, retry, expire, minimum)`, or
  `Raw(bytes)` for every other type. Records are compared by name, type, class and rdata; TTL is
  not part of identity.
- **Message**: `header`, `questions`, `answers`, `authority`, `additional` (ordered lists).
- **Operations**:
  - `decode_query(bytes) → Short | IsResponse | NotImp(header) | FormErr(header) | Query(Message)`:
    the classification of FR-008, rules 1–6 in that order. Reads the header and, only for rule 5,
    the one question; never reads the answer, authority or additional sections.
  - `decode_message(bytes) → Message | Malformed`: reads every section (used by the forwarder for
    upstream replies). Fails as a whole; never returns a partial message.
  - `encode(Message) → bytes`: writes the message; names MAY be compressed on write. Never fails
    for a Message built from decoded data or from the constructors above.
  - `type_to_text(code)` / `type_from_text(text)` (FR-025).

#### Resolution handler (modules: listener → zone/forwarder)

- **Query**: the decoded query Message (one question; answer, authority, additional empty) and the
  `client` as (IP address text, port).
- **Outcome**: `response` (Message), `result` (one of `local`, `blocked`, `cached`, `forwarded`,
  `error`, as in contract.md § Admin API › /log) and `upstream_asked` (true when the handler sent
  the query to the upstream, whatever came back).
- **Contract**: `handle(query) → Outcome`, a blocking call. It is called concurrently for different
  queries and may take up to the contract's 2-second upstream budget. The handler sets the
  response's RCODE, AA and the three record sections. The listener owns ID, question, QR, RA,
  opcode, RD, TC, OPT removal, truncation, transport, counters and log (FR-012 to FR-017, FR-031);
  whatever the handler puts there is overwritten.
- **Installation**: exactly one handler, built at startup from the ServerState; the zone + forwarder
  feature provides the real one, which consults ZoneStore, Blocklist and Cache in the order of
  contract.md § Responses.

#### Shared state (module: listener holds the container; each store belongs to its module)

`ServerState` holds `config` (Config) and one instance of each store below. Operations follow
FR-028 to FR-030. Names given to operations are Name values; the admin API converts text with
`Name.from_text` and the record helpers below.

| Store | Owner module | Operations | Used by |
|---|---|---|---|
| **ZoneStore** | zone | `lookup(name, qtype) → Answer(records) \| NoData \| NXDomain \| NotLocal`; `records() → list`; `add(record)` (adds, or replaces the TTL of an identical record); `remove(name, rtype) → count removed`; `make_record(name_text, type_text, ttl, value_text) → ResourceRecord \| Invalid`; `value_text(record) → str` | handler; api; zone-file loader |
| **Blocklist** | blocklist | `is_blocked(name) → bool`; `domains() → list of Name`; `add(name)` (idempotent); `remove(name) → bool` (listed entries only) | handler; api; blocklist-file loader |
| **Cache** | cache | `get(name, qtype) → cached Message sections with TTLs reduced by age \| none`; `put(name, qtype, reply Message)` (stores only if contract.md § Responses › Cache allows) | handler |
| **Stats** | listener | `record(outcome)` (FR-031 increments); `snapshot() → {queries, blocked, cache_hits, cache_misses}` read as one consistent set | listener; api |
| **QueryLog** | querylog | `append(LogEntry)`; `recent(limit) → list of LogEntry, newest first`; keeps at least the 1000 most recent | listener; api |

Semantics of `lookup`, `is_blocked`, `get`/`put` and the API conversions are defined by the
cited contract.md sections and by the specs of the owner modules; their signatures and the
concurrency rules are defined here. Until a store's feature is implemented, the entry point fills
its slot with an empty placeholder that has the same operations.

### Verification status

**Acceptance gate (decided in clarification, Q2)**: this feature is accepted when the 11
stub-compatible tests below pass under `pytest tests --impl .` with only the stub handler installed.
The other 9 named tests are re-checked when the features they depend on merge; the requirements
they verify count as met only from then on (Principle IV).

**Stub-compatible (11), required for acceptance of this feature:**

- `tests/test_harness.py::test_server_starts_with_documented_flags`
- `tests/test_listener.py::test_response_echoes_id`
- `tests/test_listener.py::test_response_echoes_question`
- `tests/test_listener.py::test_response_preserves_case_of_question_name`
- `tests/test_listener.py::test_qr_set_on_every_response`
- `tests/test_listener.py::test_ra_set_on_every_response`
- `tests/test_listener.py::test_tcp_formerr`
- `tests/test_listener.py::test_tcp_notimp`
- `tests/test_listener.py::test_formerr`
- `tests/test_listener.py::test_notimp_for_other_opcodes`
- `tests/test_listener.py::test_truncated_response_keeps_question_and_whole_records` (passes
  trivially with the stub, since nothing is truncated; re-checked with the zone feature, 002)

**Deferred (9), re-checked when the named feature merges:**

| Test | Needs | Why it cannot pass with the stub |
|---|---|---|
| `tests/test_listener.py::test_tcp_query_with_length_prefix` | blocklist (004) | expects NOERROR `0.0.0.0` |
| `tests/test_listener.py::test_tcp_closes_connection_where_udp_gives_no_reply` | blocklist (004) | follow-up query expects NOERROR |
| `tests/test_listener.py::test_query_with_opt_record_is_answered_without_one` | blocklist (004) | expects NOERROR `0.0.0.0` |
| `tests/test_listener.py::test_no_reply_to_packets_shorter_than_a_header` | blocklist (004) | follow-up query expects NOERROR |
| `tests/test_listener.py::test_no_reply_to_packets_with_qr_set` | blocklist (004) | follow-up query expects NOERROR |
| `tests/test_fuzz.py::test_server_survives_fuzzing` | blocklist (004) | canary expects `0.0.0.0` |
| `tests/test_listener.py::test_udp_response_over_512_bytes_is_truncated` | zone (002) | needs the 40-record answer for `big.home.lan.` |
| `tests/test_listener.py::test_truncated_answer_is_complete_over_tcp` | zone (002) | needs the 40-record answer for `big.home.lan.` |
| `tests/test_listener.py::test_edns_does_not_raise_udp_limit` | zone (002) | needs the 40-record answer for `big.home.lan.` |

**Pending (not yet in `tests/`):** the slow-upstream test for FR-007 and FR-029, to be added by
Daniel as test suite owner. It is not part of this feature's acceptance gate, and this feature does
not modify `tests/`.

Tests named in FR lists that belong to other suites (`test_admin_api.py`, `test_forwarder.py`,
`test_cache.py`) are checked when their own features merge.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Across the 2000-packet fuzz stream of seed 1035, the server never exits and answers
  every one of the 20 canary queries correctly.
- **SC-002**: 100% of replies to valid queries carry the query's ID and question (letter case
  included), QR=1 and RA=1, over both UDP and TCP.
- **SC-003**: 0 UDP replies exceed 512 bytes; every truncated reply parses as a complete message.
- **SC-004**: While one query is waiting 1.5 s on the upstream, a query from another client that
  needs no upstream is answered within 0.5 s.
- **SC-005**: Started with valid flags, the server answers its first query within 5 seconds.
- **SC-006**: The zone + forwarder, cache and blocklist + admin API specs reference the message
  model, resolution handler and shared state of this spec and define none of them again
  (checked by `/speckit-analyze` and in review).

## Assumptions

- Addresses on the command line have the `<address>:<port>` form of contract.md and the test
  harness. Handling of any other command line is left to the argument parser's defaults (argparse:
  missing or unknown flags exit with status 2 and a usage message); no further validation is
  specified (Principle VIII, Q1).
- The server closes a TCP connection after answering its first query; contract.md § TCP leaves
  further queries unspecified.
- A truncated UDP reply carries no records at all (contract.md § Truncation allows "none"); the
  question alone always fits, since a name is at most 255 bytes.
- Names may be compressed on write but need not be; decompression on read is required.
- Responses for classes other than IN, and bytes after the last counted section, are unspecified by
  contract.md and not checked.
- Startup loading of the zone and blocklist files belongs to the zone and blocklist features; until
  they exist, this feature does not open those files.
- The query log placeholder installed before the querylog feature exists keeps no entries; nothing
  reads it until the admin API exists.
- Constitution Principle IX's module list is used as is: `parser` (message model), `listener`
  (transport, query intake, response finalisation, Stats, ServerState container), plus
  `__main__.py` (command line and startup).
