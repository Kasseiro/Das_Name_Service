# Feature Specification: Local Zone, Blocklist, Forwarder and Resolution Handler

**Feature Branch**: `002-zone-forwarder`

**Created**: 2026-11-02

**Status**: Draft

**Owner**: Johnny (modules: zone, blocklist, forwarder; the resolution handler; the startup
changes in `__main__.py`). Reviewer: Daniel (constitution Principle X).

**Input**: User description:

> Feature: local zone, forwarder and the real resolution handler for dnsd. Builds on feature 001:
> use the message model, Query/Outcome/Handler, ServerState and the store roles from
> specs/001-parser-listener/contracts/interfaces.md; import shared types from dnsd.listener and do
> not redefine them (Principle IX). Scope: zone file loading per contract.md § Zone file, at
> startup, before the server answers (FR-005 of 001); a ZoneStore filling the zone role exactly as
> interfaces.md defines it, including the operations the admin API will use (records, add, remove,
> make_record, value_text); local answers per contract.md § Responses and § Zone file (records,
> NODATA, NXDOMAIN under a local zone suffix, CNAME handling, AA=1); forwarder per contract.md
> § Responses › Forwarded queries (random query ID and source port per query from `secrets`,
> Principle VI; only replies with a matching ID count; 2 s budget; TCP retry on TC=1; SERVFAIL on
> timeout or failure); the real resolution handler that replaces `stub_handler`, applying the rows
> of contract.md § Responses top to bottom (local zone, blocked, cache, forward), building the
> blocked responses itself and calling the blocklist and cache roles through ServerState (until
> features 003 and 004 replace their placeholders, those branches never fire); Outcome `result`
> and `upstream_asked` set correctly for every path. Out of scope: the cache store's logic (003),
> the blocklist store, query log store and admin API (004). Verified by tests/test_zone.py,
> tests/test_forwarder.py and the three deferred 001 tests that need big.home.lan.

Scope as changed in clarification (see Clarifications): the blocklist store and blocklist file
loading are part of this feature; 004 keeps only the query log store and the admin API.

External behaviour is fixed by `contract.md`; this spec cites its sections and does not restate
them (Principle II). Every interface used here — the message model, Query / Outcome / Handler,
ServerState, the store roles, the ZoneStore result types (`Answer`, `NoData`, `NXDomain`,
`NotLocal`, `Invalid`) and the concurrency rules — is defined by
[001 spec § Inter-module interfaces](../001-parser-listener/spec.md) and
[001 contracts/interfaces.md](../001-parser-listener/contracts/interfaces.md). This spec defines
none of them again (Principle IX); it specifies only the behaviour behind them.

## Clarifications

### Session 2026-11-02

- Q1: Is an upstream reply with RCODE SERVFAIL, relayed to the client, logged as `forwarded` or
  `error`? → Answer (option A): `error`. Every response that goes out with RCODE SERVFAIL has
  result `error`, whether the upstream or the server produced it (contract.md § Admin API › /log:
  `"error"` (SERVFAIL)). `upstream_asked` stays true, so it still counts as a cache miss (FR-025).
- Scope change: Johnny builds every feature, so the Blocklist store moves from 004 into this
  feature: blocklist file loading at startup per contract.md § Blocklist file, and a store filling
  the Blocklist role of 001 interfaces.md (`is_blocked`, `domains`, `add`, `remove`). 004 keeps
  only the query log store and the admin API. Consequence for verification: the harness's
  readiness probe (`ads.example.com. A`) is now blocked instead of forwarded, so the tests that
  count upstream queries exactly become verifiable here, including the two Principle VI tests;
  the manual random-ID/port check is dropped (see Verification status).

## User Scenarios & Testing *(mandatory)*

The "users" of this feature are DNS clients on the home network, the operator who writes the zone
and blocklist files, and the developers of features 003 and 004, who plug the cache store into the
handler built here and expose the zone and blocklist stores through the admin API.

### User Story 1 - A client resolves a home-network name from the zone file (Priority: P1)

The operator lists the home network's hosts in the zone file. A client asks for one of them and
gets the records from the file, marked authoritative, without the query leaving the host.

**Why this priority**: answering local names is Tier 1 of contract.md § Scope and the main reason
the server exists.

**Independent Test**: start the server with `tests/fixtures/zone.txt`, query `nas.home.lan.` for A
and AAAA over UDP and TCP, and check the records, TTLs and AA=1.

**Acceptance Scenarios**:

1. **Given** the fixture zone, **When** a client asks `nas.home.lan. A`, **Then** the reply is
   NOERROR, AA=1, with the single record `192.168.1.10`, TTL 300.
2. **Given** the fixture zone, **When** a client asks `tabs.home.lan. A` (a tab-separated line
   with TTL 60), **Then** the record is returned with TTL 60.
3. **Given** 40 A records for `big.home.lan.`, **When** a client asks over TCP, **Then** all 40
   are returned; over UDP the reply is truncated with TC=1 (contract.md § Truncation).
4. **Given** the fixture zone, **When** a client asks `NAS.HOME.LAN.`, **Then** it gets the same
   records as for `nas.home.lan.`, and the question keeps the client's letter case.

---

### User Story 2 - Missing local names and types get authoritative negative answers (Priority: P1)

A client asks for a type a local name does not have, or for a name under a local zone suffix that
does not exist. The server answers NODATA or NXDOMAIN itself, authoritatively, and never forwards
the query.

**Why this priority**: forwarding private names leaks them upstream and gives wrong answers; the
contract makes these answers authoritative.

**Independent Test**: query `printer.home.lan. AAAA`, `nas.home.lan. MX`, `missing.home.lan. A`,
`sub.nas.home.lan. TXT`, and check RCODE, empty answer, AA=1 and that the upstream received
nothing.

**Acceptance Scenarios**:

1. **Given** `printer.home.lan.` has only an A record, **When** a client asks for AAAA, **Then**
   the reply is NOERROR with an empty answer and AA=1.
2. **Given** `home.lan.` is a local zone suffix, **When** a client asks `missing.home.lan.` or
   `a.b.home.lan.` for any type, **Then** the reply is NXDOMAIN with an empty answer and AA=1.
3. **Given** no record name ends in `other.lan.`, **When** a client asks `other.lan. A` or
   `lan. A`, **Then** the query is forwarded (neither is under a local zone suffix).

---

### User Story 3 - CNAMEs in the zone are followed one step (Priority: P2)

A local alias points at another name. A client asking for an address of the alias gets the CNAME
and, if the target is local, the target's records of the requested type in the same reply.

**Why this priority**: aliases are common in a home zone; contract.md § Zone file fixes the shape
of the answer.

**Independent Test**: query `files.home.lan.` (CNAME to `nas.home.lan.`) for A, AAAA, TXT and
CNAME, and `ext.home.lan.` (CNAME to a name outside the zone) for A.

**Acceptance Scenarios**:

1. **Given** `files.home.lan. CNAME nas.home.lan.`, **When** a client asks `files.home.lan. A`,
   **Then** the answer is the CNAME record first, then `nas.home.lan. A 192.168.1.10`, AA=1.
2. **Given** the same alias, **When** a client asks for TXT, **Then** the answer is the CNAME
   record alone, NOERROR, AA=1.
3. **Given** `ext.home.lan. CNAME www.example.org.`, **When** a client asks for A, **Then** the
   answer is the CNAME record alone, AA=1, and the target is not resolved upstream.
4. **Given** the same alias, **When** a client asks for type CNAME, **Then** the answer is the
   CNAME record alone.

---

### User Story 4 - Blocked domains and their subdomains get the blocking response (Priority: P1)

The operator lists ad and tracker domains in the blocklist file. A client asking for one of them,
or for any name below it, gets the blocking response of contract.md § Responses, and the query
never reaches the upstream.

**Why this priority**: blocking is the main Tier 2 feature a household notices, and it is the
only row of contract.md § Responses between the local zone and the upstream.

**Independent Test**: start the server with `tests/fixtures/blocklist.txt`; query
`ads.example.com.`, `sub.ads.example.com.`, `ADS.EXAMPLE.COM.` and `dotted.example.net.` for A,
AAAA and TXT; query `example.com.`, `xads.example.com.` and the commented-out names; check the
responses and that only the unblocked names reached the upstream.

**Acceptance Scenarios**:

1. **Given** `ads.example.com` is listed, **When** a client asks for its A record, **Then** the
   reply is NOERROR, `0.0.0.0`, TTL 60, AA=0; for AAAA it is `::`, TTL 60; for TXT, MX, CNAME, NS
   or ANY it is NXDOMAIN with an empty answer.
2. **Given** the same entry, **When** a client asks `a.b.c.ads.example.com. A`, **Then** it is
   blocked; **When** it asks `example.com. A` or `xads.example.com. A`, **Then** the query is
   forwarded.
3. **Given** an entry written `UPPER.Example.NET` and one written `dotted.example.net.`, **When**
   a client asks `upper.example.net. A` or `sub.dotted.example.net. A`, **Then** both are blocked.
4. **Given** the lines `# commented.example.org` and `   # indented-comment.example.org`,
   **When** a client asks for those names, **Then** they are forwarded, not blocked.

---

### User Story 5 - Every other name is resolved by the upstream (Priority: P1)

A client asks for a name that is neither local nor blocked nor cached. The server forwards it to
the `--upstream` resolver and relays the reply's RCODE and all three record sections, with AA=0.

**Why this priority**: without it the server resolves nothing but home-network names
(contract.md § Scope, Tier 1).

**Independent Test**: with the fake upstream serving canned answers, query names of several
types and check that answer, authority and additional sections and the RCODE arrive unchanged.

**Acceptance Scenarios**:

1. **Given** the upstream answers `www.example.org. A 192.0.2.1`, **When** a client asks for it,
   **Then** it gets that record, NOERROR, AA=0.
2. **Given** the upstream answers NXDOMAIN with an SOA in the authority section, **When** a client
   asks, **Then** it gets NXDOMAIN and the same SOA record.
3. **Given** the upstream answers REFUSED, SERVFAIL or NOTIMP, **When** a client asks, **Then** it
   gets that RCODE.
4. **Given** the upstream reply has TC=1 over UDP, **When** a client asks over TCP, **Then** the
   server repeats the query over TCP and the client gets the complete 40-record answer.

---

### User Story 6 - Forwarding resists spoofing and upstream failure (Priority: P1)

Each upstream query uses a fresh random ID and source port; replies with the wrong ID are
ignored; a silent or broken upstream turns into SERVFAIL within the time budget, and the server
keeps working.

**Why this priority**: constitution Principle VI and contract.md § Responses › Forwarded queries;
predictable queries make cache poisoning practical.

**Independent Test**: forward 20 queries carrying the same client ID and inspect the IDs and
source ports the upstream saw; set the upstream to `silent` and `wrong_id` and check for SERVFAIL
within 3.5 s.

**Acceptance Scenarios**:

1. **Given** 20 forwarded queries all sent with client ID 0x0707, **When** the upstream records
   them, **Then** their IDs and source ports are neither repeated, nor counted up, nor copied from
   the client.
2. **Given** the upstream replies only with a wrong ID, **When** a client asks, **Then** it gets
   SERVFAIL and no answer records.
3. **Given** the upstream never replies, **When** a client asks over UDP or TCP, **Then** it gets
   SERVFAIL with its own ID, RA=1, within 3.5 s of asking.
4. **Given** the upstream delays its reply by 1 s, **When** a client asks, **Then** it gets the
   upstream's answer.
5. **Given** a SERVFAIL caused by a silent upstream, **When** the upstream recovers, **Then** the
   next forwarded, local and blocked queries are answered normally.

---

### User Story 7 - Features 003 and 004 plug into finished stores and handler (Priority: P2)

The handler already applies the rows of contract.md § Responses in order and calls the cache; the
zone and blocklist stores already provide the operations the admin API needs. When 003 replaces
the cache placeholder and 004 adds the query log and admin API, their behaviour appears without
changing the handler or these stores.

**Why this priority**: the handler is the single place where the row order is decided, and the
stores are the single place where records and blocked domains live; doing both once here keeps
003 and 004 limited to their own modules.

**Independent Test**: review and `/speckit-analyze`; after 003 and 004 merge, their tests pass
without changes to the zone, blocklist or forwarder modules or the handler.

**Acceptance Scenarios**:

1. **Given** a name both in the local zone and blocked, **When** a client asks, **Then** it gets
   the local answer (contract.md § Responses: first matching row).
2. **Given** a cache store holding a reply, **When** the same question arrives, **Then** the
   cached reply is returned with result `cached` and the upstream is not asked.
3. **Given** the admin API adds or removes a record or a blocklist domain, **When** the next query
   arrives, **Then** the handler sees the change.

---

### Edge Cases

- **Zone file lines**: comment lines starting with `;`, blank lines, and fields separated by any
  mix of spaces and tabs are handled per contract.md § Zone file. A comment after a record on the
  same line, a missing class field, and lines with other types or classes are not in the contract;
  their handling is a plan decision (see Assumptions).
- **Duplicate lines in the zone file**: identical records (same name, type, value) are stored once;
  the later TTL wins (the same rule as `add`).
- **Blocklist file lines**: comment lines (first non-blank character `#`, including indented
  ones) and blank lines are skipped; leading and trailing whitespace around an entry is ignored. A
  `#` later in a line is unspecified by contract.md § Blocklist file; the plan treats it as the
  start of a comment, so `ads.example.com # ads` lists `ads.example.com` (research R-2).
- **Duplicate blocklist entries**, including the same domain in different case or with and
  without a trailing dot: listed once (the same rule as `add`).
- **Blocklist entry that is not a valid name** (label over 63 bytes, empty label): not specified
  by contract.md; like a malformed zone line, the server reports it on standard error and exits
  with status 1 before serving (research R-3).
- **Blocklist entry for the root or a top-level name** (e.g. `test`): matched like any other entry
  by whole labels; `test` would block every name under `test.`.
- **Blocked name that is also a local zone name or under a local suffix**: the local zone answers
  (contract.md § Responses: first matching row); the blocklist is not consulted.
- **Removing a subdomain of a listed domain**: `remove` returns false; the subdomain stays blocked
  (contract.md § Admin API › /blocklist).
- **CNAME target is itself a CNAME**: only one step is followed; the answer is the first CNAME
  plus any records of the requested type at its target (none, if the target has only a CNAME).
- **Query type ANY at a local name**: answered from the zone like any other type (NODATA unless a
  record of type 255 exists, which it cannot), AA=1. contract.md defines ANY only for blocked
  names; this choice is recorded as an assumption.
- **Query for a local zone suffix itself** (e.g. `home.lan.` with no records of its own):
  unspecified by contract.md § Zone file; answered NXDOMAIN, AA=1 (it is under its own suffix).
- **Name below a local name** (`sub.nas.home.lan.`): it is under the suffix `home.lan.` and has no
  records, so NXDOMAIN.
- **Local name added under a new suffix through the admin API** (004): the suffix becomes local at
  once; removing the last record under it makes it non-local again (contract.md § Zone file).
- **Class other than IN in a query**: unspecified; the handler ignores the class.
- **Upstream reply that does not parse, or parses but carries a non-matching ID**: ignored; the
  server keeps waiting within the budget and answers SERVFAIL if nothing better arrives.
- **Several replies to one upstream query** (e.g. a spoofed one first): the first matching reply
  counts; others are ignored.
- **Upstream reply over 512 bytes on UDP**: unspecified by contract.md; it is accepted and decoded
  like any reply (the listener then truncates it for a UDP client).
- **TCP retry after TC=1 fails, is refused, or times out**: SERVFAIL within the same 2 s budget.
- **Upstream TCP reply that itself has TC=1**: used as received.
- **Upstream unreachable** (ICMP port unreachable, network error): SERVFAIL, at the latest when the
  2 s budget ends.
- **Upstream reply with RCODE SERVFAIL**: relayed as received, result `error` (Q1).
- **Upstream reply larger than the listener can send over TCP**: handled by the listener (001
  FR-017), not here.

## Requirements *(mandatory)*

Each requirement lists the tests that verify it (Principle IV). Marks: **‡** the test cannot pass
until feature 003 (cache) is merged; **†** it cannot pass until feature 004 (query log + admin
API) is merged; **‡†** it needs both. Unmarked tests are required for acceptance of this feature.
See **Verification status**.

### Functional Requirements

#### Startup loading (contract.md § Command line, § Zone file, § Blocklist file)

- **FR-001**: At startup the server MUST read the file named by `--zone` once, in the format of
  contract.md § Zone file, and load every record into the ZoneStore; fields are split on any
  amount of whitespace, comment and blank lines are skipped, and every record of the same name and
  type is kept.
  *Tests*: `tests/test_zone.py::test_a_record`, `tests/test_zone.py::test_aaaa_record`,
  `tests/test_zone.py::test_cname_record`, `tests/test_zone.py::test_ttl_comes_from_the_zone_file`,
  `tests/test_zone.py::test_several_records_with_one_name_and_type`,
  `tests/test_admin_api.py::test_get_records_lists_zone_file_records` †
- **FR-002**: At startup the server MUST read the file named by `--blocklist` once, in the format
  of contract.md § Blocklist file, and load every entry into the Blocklist store: comment lines
  (first non-blank character `#`) and blank lines are skipped, a trailing `# …` after an entry is
  also a comment (research R-2), and entries are accepted with or without a trailing dot and in
  any case.
  *Tests*: `tests/test_blocklist.py::test_blocked_a`,
  `tests/test_blocklist.py::test_comment_lines_are_ignored`,
  `tests/test_blocklist.py::test_entry_with_trailing_dot_blocks`,
  `tests/test_blocklist.py::test_names_match_case_insensitively`,
  `tests/test_blocklist.py::test_file_yields_exactly_its_entries` †,
  `tests/test_admin_api.py::test_get_blocklist_lists_file_entries` †
- **FR-003**: Both files MUST be loaded completely before the listener starts answering
  (001 FR-005).
  *Tests*: `tests/test_harness.py::test_server_starts_with_documented_flags`,
  `tests/test_listener.py::test_tcp_query_with_length_prefix`

#### Local answers (contract.md § Responses rows 1–3, § Zone file)

- **FR-004**: A query for a name that has records MUST be answered with every record of the
  requested type, NOERROR, AA=1, each with the TTL from the zone (contract.md § Responses, row 1).
  *Tests*: `tests/test_zone.py::test_a_record`, `tests/test_zone.py::test_aaaa_record`,
  `tests/test_zone.py::test_cname_record`, `tests/test_zone.py::test_ttl_comes_from_the_zone_file`,
  `tests/test_zone.py::test_several_records_with_one_name_and_type`,
  `tests/test_zone.py::test_local_answer_over_tcp`,
  `tests/test_listener.py::test_udp_response_over_512_bytes_is_truncated`,
  `tests/test_listener.py::test_truncated_response_keeps_question_and_whole_records`,
  `tests/test_listener.py::test_truncated_answer_is_complete_over_tcp`,
  `tests/test_listener.py::test_edns_does_not_raise_udp_limit`
- **FR-005**: Zone names MUST match case-insensitively (contract.md § Zone file, RFC 4343).
  *Tests*: `tests/test_zone.py::test_names_match_case_insensitively`
- **FR-006**: A query for a name that has records, but none of the requested type and no CNAME,
  MUST get NODATA: NOERROR, empty answer, AA=1 (contract.md § Responses, row 2).
  *Tests*: `tests/test_zone.py::test_nodata`,
  `tests/test_zone.py::test_deleted_record_no_longer_resolves` †
- **FR-007**: The local zone suffixes MUST be derived from the current record set as contract.md
  § Zone file › Local zone suffix defines, recomputed whenever the set changes (zone file load and
  `add` / `remove`). A query for a name with no records that is a subdomain of a local zone suffix
  MUST get NXDOMAIN, empty answer, AA=1 (contract.md § Responses, row 3). A name under no suffix
  is not local and goes on to the next row.
  *Tests*: `tests/test_zone.py::test_nxdomain_under_local_suffix`,
  `tests/test_forwarder.py::test_name_outside_every_local_suffix_is_forwarded`,
  `tests/test_zone.py::test_api_record_creates_a_local_suffix` †,
  `tests/test_zone.py::test_deleting_the_last_record_removes_the_suffix` †
- **FR-008**: A query with a type other than CNAME for a name that has a CNAME record MUST be
  answered as contract.md § Zone file › CNAME prescribes: the CNAME record first, followed by the
  target's records of the requested type when the target has records in the local zone; otherwise
  the CNAME record alone. NOERROR, AA=1. Only one CNAME step is followed, and the target is never
  resolved upstream.
  *Tests*: `tests/test_zone.py::test_cname_is_followed_inside_the_zone`,
  `tests/test_zone.py::test_cname_to_local_target_without_the_requested_type`,
  `tests/test_zone.py::test_cname_to_target_outside_the_zone`
- **FR-009**: A query answered under FR-004 to FR-008 MUST NOT be sent to the upstream.
  *Tests*: `tests/test_zone.py::test_local_names_are_not_forwarded`

#### ZoneStore operations (001 contracts/interfaces.md § 3, ZoneStore role)

- **FR-010**: The ZoneStore MUST provide the six operations of the ZoneStore role with the
  signatures of 001 interfaces.md and follow its concurrency rules 1–3. Their behaviour:
  `lookup` gives the FR-004 to FR-008 classification as `Answer` / `NoData` / `NXDomain` /
  `NotLocal`; `records()` returns every stored record (zone file and added) as a new list;
  `add(record)` stores a record, or replaces only the TTL of an identical one (name, type, class,
  rdata), so it is stored once; `remove(name, rtype)` removes every record with that name and type
  and returns the count. Changes are visible to the next `lookup` (contract.md § Admin API:
  "changes take effect immediately").
  *Tests*: `tests/test_admin_api.py::test_get_records_lists_zone_file_records` †,
  `tests/test_admin_api.py::test_post_record_duplicate_replaces_ttl` †,
  `tests/test_admin_api.py::test_delete_record_removes_every_record_of_that_name_and_type` †,
  `tests/test_admin_api.py::test_posted_record_resolves` †,
  `tests/test_zone.py::test_deleted_record_no_longer_resolves` †
- **FR-011**: `make_record(name_text, type_text, ttl, value_text)` MUST build a class-IN record or
  return `Invalid(reason)`, reading and writing no state. It returns `Invalid` when the name is not
  a valid name, the type is not A, AAAA or CNAME (matched case-insensitively), the TTL is not
  0–4294967295, or the value is not, respectively, an IPv4 address, an IPv6 address or a valid
  name (contract.md § Admin API › /records). The name accepts the forms of contract.md § Admin
  API › Names.
  *Tests*: `tests/test_admin_api.py::test_post_records_bad_body_is_400` †,
  `tests/test_admin_api.py::test_post_record` †
- **FR-012**: `value_text(record)` MUST return the record's value in zone-file form: the IPv4
  address in dotted form, the IPv6 address in its compressed text form, or the CNAME target with a
  trailing dot (contract.md § Admin API › /records).
  *Tests*: `tests/test_admin_api.py::test_get_records_lists_zone_file_records` †,
  `tests/test_admin_api.py::test_record_fields` †

#### Blocklist store (contract.md § Blocklist file; 001 contracts/interfaces.md § 3, Blocklist role)

- **FR-013**: `is_blocked(name)` MUST return true exactly when the name equals a listed entry or
  is a subdomain of one, matching by whole labels and ignoring ASCII case (contract.md § Blocklist
  file, RFC 4343).
  *Tests*: `tests/test_blocklist.py::test_subdomain_of_listed_domain_is_blocked`,
  `tests/test_blocklist.py::test_parent_of_listed_domain_is_not_blocked`,
  `tests/test_blocklist.py::test_name_sharing_only_a_suffix_string_is_not_blocked`,
  `tests/test_blocklist.py::test_names_match_case_insensitively`,
  `tests/test_blocklist.py::test_entry_with_trailing_dot_blocks`
- **FR-014**: The Blocklist store MUST provide the four operations of the Blocklist role with the
  signatures of 001 interfaces.md and follow its concurrency rules 1–3. Their behaviour:
  `domains()` returns every listed entry (file and added) as a new list; `add(name)` lists a
  domain, idempotently, so a domain is listed once whatever its case; `remove(name)` removes a
  listed entry and returns true, or returns false when the name is not itself listed (a subdomain
  of a listed entry stays blocked). Changes are visible to the next `is_blocked` (contract.md
  § Admin API › /blocklist).
  *Tests*: `tests/test_admin_api.py::test_post_blocklist` †,
  `tests/test_admin_api.py::test_post_blocklist_duplicate` †,
  `tests/test_admin_api.py::test_post_blocklist_takes_effect_immediately` †,
  `tests/test_admin_api.py::test_delete_blocklist` †,
  `tests/test_admin_api.py::test_delete_blocklist_unblocks_immediately` †,
  `tests/test_admin_api.py::test_delete_blocklist_entry_loaded_from_file` †,
  `tests/test_admin_api.py::test_delete_blocklist_twice_is_404` †,
  `tests/test_admin_api.py::test_delete_blocklist_subdomain_of_listed_is_404` †,
  `tests/test_admin_api.py::test_blocklist_accepts_names_in_any_form` †

#### Forwarder (contract.md § Responses › Forwarded queries)

- **FR-015**: A query that reaches the last row of contract.md § Responses MUST be sent to the
  `--upstream` address over UDP with the client's question, and the upstream reply's RCODE and
  answer, authority and additional sections MUST be returned unchanged, with AA=0.
  *Tests*: `tests/test_forwarder.py::test_answer_is_relayed`,
  `tests/test_forwarder.py::test_several_records_are_relayed`,
  `tests/test_forwarder.py::test_other_types_are_relayed`,
  `tests/test_forwarder.py::test_nxdomain_is_relayed`,
  `tests/test_forwarder.py::test_authority_and_additional_are_relayed`,
  `tests/test_forwarder.py::test_nxdomain_authority_is_relayed`,
  `tests/test_forwarder.py::test_other_upstream_rcodes_are_relayed`,
  `tests/test_forwarder.py::test_response_carries_the_clients_id_and_question`,
  `tests/test_forwarder.py::test_forwarded_answer_over_tcp`,
  `tests/test_forwarder.py::test_upstream_receives_the_question`
- **FR-016**: Every query sent to the upstream, including the TCP retry of FR-019, MUST carry a
  16-bit ID drawn fresh from `secrets`; every UDP query MUST be sent from a source port drawn fresh
  from `secrets` (constitution Principle VI, contract.md § Responses › Forwarded queries,
  RFC 5452). Neither is fixed, sequential, reused deliberately or copied from the client, and
  neither is configurable.
  *Tests*: `tests/test_forwarder.py::test_upstream_query_ids_are_random`,
  `tests/test_forwarder.py::test_upstream_source_ports_are_random`. These tests see only UDP
  queries; the rule for the TCP-retry ID is checked by review (tasks T022), not by a test.
- **FR-017**: An upstream reply MUST count only if it decodes as a message and its ID matches the
  ID of the query sent; any other datagram is ignored and the server keeps waiting (Principle VI).
  *Tests*: `tests/test_forwarder.py::test_reply_with_wrong_id_is_ignored`
- **FR-018**: The whole upstream exchange, including any TCP retry, MUST finish within 2 seconds
  of the forwarder starting it. If no counting reply arrives in that time, or the exchange fails
  in any other way, the handler MUST return SERVFAIL with empty sections, and the server keeps
  serving (Principle V).
  *Tests*: `tests/test_forwarder.py::test_reply_within_two_seconds_is_used`,
  `tests/test_forwarder.py::test_servfail_when_upstream_is_silent`,
  `tests/test_forwarder.py::test_servfail_over_tcp`,
  `tests/test_forwarder.py::test_server_keeps_working_after_upstream_failure`
- **FR-019**: If the counting UDP reply has TC=1, the query MUST be repeated over TCP to the same
  upstream address (RFC 1035 4.2.2 framing), and the TCP reply used instead; it too counts only
  under FR-017. A failed TCP attempt gives SERVFAIL (FR-018).
  *Tests*: `tests/test_forwarder.py::test_truncated_upstream_reply_is_retried_over_tcp`,
  `tests/test_forwarder.py::test_answer_fetched_over_tcp_is_truncated_for_a_udp_client`,
  `tests/test_forwarder.py::test_client_udp_reply_never_exceeds_512_bytes`

#### Resolution handler (contract.md § Responses; 001 § Inter-module interfaces › Resolution handler)

- **FR-020**: The feature MUST provide the real handler as a function `(ServerState) -> Handler`,
  and the entry point MUST install it in place of `stub_handler`, with the real ZoneStore and
  Blocklist stores in the ServerState, after loading both files (FR-003) and before calling
  `serve` (001 interfaces.md § 2, § 4). The cache and query log slots keep their placeholders
  until 003 and 004.
  *Tests*: `tests/test_harness.py::test_server_starts_with_documented_flags`,
  `tests/test_zone.py::test_a_record`, `tests/test_blocklist.py::test_blocked_a`,
  `tests/test_forwarder.py::test_answer_is_relayed`
- **FR-021**: For each query the handler MUST try the rows of contract.md § Responses top to
  bottom and apply the first that matches: (1) the ZoneStore's `lookup` (rows 1–3); (2) when it
  returns `NotLocal`, the Blocklist's `is_blocked` (rows 4–6); (3) otherwise the Cache's `get`;
  (4) otherwise the forwarder (row 7). Stores are reached only through the ServerState the handler
  was built from.
  *Tests*: `tests/test_forwarder.py::test_name_outside_every_local_suffix_is_forwarded`,
  `tests/test_forwarder.py::test_blocked_names_are_not_forwarded`,
  `tests/test_blocklist.py::test_parent_of_listed_domain_is_not_blocked`,
  `tests/test_blocklist.py::test_local_zone_wins_over_blocklist` †,
  `tests/test_cache.py::test_repeat_query_is_not_sent_upstream_again` ‡,
  `tests/test_cache.py::test_blocking_a_cached_name_takes_effect_immediately` ‡†,
  `tests/test_cache.py::test_local_record_for_a_cached_name_takes_effect_immediately` ‡†
- **FR-022**: For a blocked name the handler MUST build the response itself as contract.md
  § Responses rows 4–6 prescribe: for type A one record `0.0.0.0`, for AAAA one record `::`, each
  class IN, TTL 60, owned by the question name, NOERROR; for every other type (including ANY)
  NXDOMAIN with an empty answer. AA=0, and nothing goes upstream.
  *Tests*: `tests/test_blocklist.py::test_blocked_a`, `tests/test_blocklist.py::test_blocked_aaaa`,
  `tests/test_blocklist.py::test_blocked_other_types`,
  `tests/test_blocklist.py::test_blocked_over_tcp`,
  `tests/test_blocklist.py::test_subdomain_of_listed_domain_is_blocked`,
  `tests/test_forwarder.py::test_blocked_names_are_not_forwarded`,
  `tests/test_listener.py::test_tcp_query_with_length_prefix`,
  `tests/test_listener.py::test_query_with_opt_record_is_answered_without_one`,
  `tests/test_listener.py::test_tcp_closes_connection_where_udp_gives_no_reply`,
  `tests/test_listener.py::test_no_reply_to_packets_shorter_than_a_header`,
  `tests/test_listener.py::test_no_reply_to_packets_with_qr_set`,
  `tests/test_fuzz.py::test_server_survives_fuzzing`
- **FR-023**: A cached reply returned by the Cache's `get` MUST be sent with its RCODE and
  sections as returned, AA=0. After a counting upstream reply (FR-017, FR-019), the handler MUST
  pass it to the Cache's `put` with the question's name and type; the cache decides what to keep
  (003). A SERVFAIL built by the server itself (FR-018) MUST NOT be passed to `put`.
  *Tests*: `tests/test_cache.py::test_repeat_query_is_not_sent_upstream_again` ‡,
  `tests/test_cache.py::test_servfail_from_timeout_is_not_cached` ‡
- **FR-024**: Every Outcome MUST set `result` and `upstream_asked` as follows (Q1):

  | Path | `result` | `upstream_asked` |
  |---|---|---|
  | local zone (FR-004 – FR-008) | `local` | false |
  | blocked (FR-022) | `blocked` | false |
  | cache hit (FR-023) | `cached` | false |
  | upstream reply relayed (FR-015, FR-019), RCODE other than SERVFAIL | `forwarded` | true |
  | upstream reply relayed with RCODE SERVFAIL | `error` | true |
  | SERVFAIL built by the server after asking the upstream (FR-018) | `error` | true |

  *Tests*: `tests/test_zone.py::test_local_queries_are_logged_as_local` †,
  `tests/test_zone.py::test_local_queries_leave_cache_counters_alone` †,
  `tests/test_forwarder.py::test_forwarded_query_is_logged_as_forwarded` †,
  `tests/test_forwarder.py::test_servfail_is_logged_as_error` †,
  `tests/test_admin_api.py::test_stats_blocked_counts_blocking_responses` †,
  `tests/test_admin_api.py::test_stats_blocked_queries_leave_cache_counters_alone` †,
  `tests/test_cache.py::test_stats_count_misses_and_hits` ‡†,
  `tests/test_cache.py::test_cache_hit_is_logged_as_cached` ‡†
- **FR-025**: The handler MUST set only the parts of the response it owns (001 interfaces.md § 2:
  RCODE, AA and the three record sections) and MUST NOT call `Stats.record` or `QueryLog.append`.
  *Tests*: `tests/test_listener.py::test_response_echoes_id`,
  `tests/test_listener.py::test_ra_set_on_every_response`,
  `tests/test_forwarder.py::test_response_carries_the_clients_id_and_question`,
  `tests/test_admin_api.py::test_stats_queries_counts_udp_and_tcp` † (a handler that also counted
  would make each query count twice)

### Design constraints *(binding; no test)*

- **DC-1**: The handler holds no lock while calling a store or the network. This is
  001 contracts/interfaces.md § 3, concurrency rule 4, kept as a binding design constraint for this
  feature in the same way 001 keeps rule 2 (001 spec § Shared state). No test in `tests/` can
  observe it, so it is not a functional requirement (Principle IV); it is checked in review
  (tasks T026).

### Key Entities *(include if feature involves data)*

All types are defined in 001 (message model, Query, Outcome, ServerState, ZoneStore result types);
this feature adds no shared type.

- **Zone record**: a ResourceRecord of type A, AAAA or CNAME, class IN, loaded from the zone file
  or added through the ZoneStore. Identity is name (case-insensitive), type, class and value; TTL
  is not part of identity.
- **Local zone suffix**: the parent of a stored record name (contract.md § Zone file). Derived,
  never stored on its own; follows the record set.
- **Blocklist entry**: a listed domain, as a Name, loaded from the blocklist file or added
  through the Blocklist store. Identity ignores case; it blocks itself and every subdomain.
- **Upstream exchange**: one forwarded question: the random ID and source port, the 2 s deadline,
  the optional TCP retry, and its result (a counting reply, or failure).

### Verification status

Same rule as 001 (constitution § Technical Constraints, v1.1.0): this feature is accepted when the
tests listed as required pass under `pytest tests --impl .`; deferred tests are re-checked when the
feature they need merges, and the requirements they verify count as met only from then on
(Principle IV).

With the blocklist in this feature, the harness's readiness probe (`ads.example.com. A`,
`tests/conftest.py::PROBE_NAME`) is answered by the blocklist and never forwarded, so every test
that counts upstream queries exactly is verifiable here. The two Principle VI tests (FR-016) are
required, and no manual random-ID/port check is needed.

**Required for acceptance (002)** — 65 test functions: 45 from the zone, forwarder and blocklist
suites, and all 20 in `test_listener.py`, `test_fuzz.py` and `test_harness.py`:

- `tests/test_zone.py` (13 of 18): `test_a_record`, `test_aaaa_record`, `test_cname_record`,
  `test_ttl_comes_from_the_zone_file`, `test_several_records_with_one_name_and_type`,
  `test_names_match_case_insensitively`, `test_local_answer_over_tcp`,
  `test_cname_is_followed_inside_the_zone`, `test_cname_to_local_target_without_the_requested_type`,
  `test_cname_to_target_outside_the_zone`, `test_nodata`, `test_nxdomain_under_local_suffix`,
  `test_local_names_are_not_forwarded`
- `tests/test_forwarder.py` (22 of 24): `test_answer_is_relayed`, `test_several_records_are_relayed`,
  `test_other_types_are_relayed`, `test_nxdomain_is_relayed`,
  `test_authority_and_additional_are_relayed`, `test_nxdomain_authority_is_relayed`,
  `test_response_carries_the_clients_id_and_question`, `test_forwarded_answer_over_tcp`,
  `test_upstream_receives_the_question`, `test_name_outside_every_local_suffix_is_forwarded`,
  `test_blocked_names_are_not_forwarded`, `test_reply_within_two_seconds_is_used`,
  `test_servfail_when_upstream_is_silent`, `test_reply_with_wrong_id_is_ignored`,
  `test_server_keeps_working_after_upstream_failure`, `test_servfail_over_tcp`,
  `test_client_udp_reply_never_exceeds_512_bytes`,
  `test_truncated_upstream_reply_is_retried_over_tcp`,
  `test_answer_fetched_over_tcp_is_truncated_for_a_udp_client`,
  `test_upstream_query_ids_are_random`, `test_upstream_source_ports_are_random`,
  `test_other_upstream_rcodes_are_relayed`
- `tests/test_blocklist.py` (10 of 12): `test_blocked_a`, `test_blocked_aaaa`,
  `test_blocked_other_types`, `test_blocked_over_tcp`,
  `test_subdomain_of_listed_domain_is_blocked`, `test_parent_of_listed_domain_is_not_blocked`,
  `test_name_sharing_only_a_suffix_string_is_not_blocked`, `test_comment_lines_are_ignored`,
  `test_entry_with_trailing_dot_blocks`, `test_names_match_case_insensitively`
- All 9 tests 001 deferred (its § Verification status), which now pass here:
  - needing the blocklist: `tests/test_listener.py::test_tcp_query_with_length_prefix`,
    `tests/test_listener.py::test_tcp_closes_connection_where_udp_gives_no_reply`,
    `tests/test_listener.py::test_query_with_opt_record_is_answered_without_one`,
    `tests/test_listener.py::test_no_reply_to_packets_shorter_than_a_header`,
    `tests/test_listener.py::test_no_reply_to_packets_with_qr_set`,
    `tests/test_fuzz.py::test_server_survives_fuzzing`
  - needing `big.home.lan.`: `tests/test_listener.py::test_udp_response_over_512_bytes_is_truncated`,
    `tests/test_listener.py::test_truncated_answer_is_complete_over_tcp`,
    `tests/test_listener.py::test_edns_does_not_raise_udp_limit`
- No regression: the 11 stub-compatible 001 tests (one of them,
  `tests/test_listener.py::test_truncated_response_keeps_question_and_whole_records`, now gets its
  full check against the 40-record answer) and `tests/test_harness.py`.

With this, all 20 tests in `test_listener.py`, `test_fuzz.py` and `test_harness.py` are required;
001 has no deferred tests left.

**Deferred to 004 (query log + admin API)** — 9 test functions from the 002 suites:

| Test | Why it cannot pass before 004 |
|---|---|
| `tests/test_zone.py::test_api_record_creates_a_local_suffix` | uses `POST /records` |
| `tests/test_zone.py::test_deleting_the_last_record_removes_the_suffix` | uses `POST` / `DELETE /records` |
| `tests/test_zone.py::test_deleted_record_no_longer_resolves` | uses `DELETE /records` |
| `tests/test_zone.py::test_local_queries_leave_cache_counters_alone` | reads `/stats` |
| `tests/test_zone.py::test_local_queries_are_logged_as_local` | reads `/log` |
| `tests/test_forwarder.py::test_forwarded_query_is_logged_as_forwarded` | reads `/log` |
| `tests/test_forwarder.py::test_servfail_is_logged_as_error` | reads `/log` |
| `tests/test_blocklist.py::test_file_yields_exactly_its_entries` | reads `GET /blocklist` |
| `tests/test_blocklist.py::test_local_zone_wins_over_blocklist` | uses `POST /blocklist` |

The `tests/test_admin_api.py` tests named in FR-001, FR-002, FR-010 – FR-012, FR-014 and FR-024
are also checked when 004 merges; they verify that the stores built here behave as the admin API
needs.

**Deferred to 003 (cache)**: `tests/test_cache.py::test_repeat_query_is_not_sent_upstream_again`
and `tests/test_cache.py::test_servfail_from_timeout_is_not_cached` (FR-021, FR-023). The second
passes trivially while the cache is a placeholder; it is checked for real with 003.

**Deferred to both 003 and 004**: `tests/test_cache.py::test_blocking_a_cached_name_takes_effect_immediately`,
`tests/test_cache.py::test_local_record_for_a_cached_name_takes_effect_immediately`,
`tests/test_cache.py::test_stats_count_misses_and_hits`,
`tests/test_cache.py::test_cache_hit_is_logged_as_cached` (FR-021, FR-024); the last two need the
query log and `/stats` as well as the cache.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every record in the fixture zone (46 records) is returned for its name and type,
  with its own TTL and AA=1, over UDP and TCP.
- **SC-002**: 0 queries for a local name, a name under a local zone suffix, or a blocked name reach
  the upstream.
- **SC-003**: Each of the four fixture blocklist entries, and every subdomain of one, gets the
  blocking response for A, AAAA and other types; 0 parents, suffix-string look-alikes or
  commented-out names are blocked.
- **SC-004**: With a silent or spoofing upstream, 100% of forwarded queries are answered SERVFAIL
  within 3.5 s of asking, and the server answers the next query normally.
- **SC-005**: Over 20 forwarded queries, at least 18 distinct upstream query IDs and at least 10
  distinct source ports are used, none equal to the client's ID, with no fixed step between
  consecutive values.
- **SC-006**: A 40-record answer fetched over TCP after a truncated upstream reply reaches a TCP
  client complete, and a UDP client within 512 bytes with TC=1.
- **SC-007**: All 65 tests listed as required under Verification status pass.
- **SC-008**: Features 003 and 004 need no change to the handler, the zone, blocklist or
  forwarder modules to make their tests pass (checked in their reviews).

## Assumptions

- The zone and blocklist files are well-formed as contract.md describes, and the test fixtures are
  the reference. Handling of a missing or unreadable file, a zone line that does not fit the
  format, or a blocklist line that is not a valid name is not specified by contract.md and has no
  test. The plan's decision (research R-3): the server prints `dnsd: <path>:<line>: <reason>` (or
  the read error) to standard error and exits with status 1 before binding any socket. No
  requirement is made of it (Principle IV).
- The class field of a zone file line is `IN`; records are stored with class IN.
- A record's TTL in the zone file is 0–4294967295.
- A query of type ANY at a local name is treated like any other type: it matches records of type
  255 only, so it gets NODATA (or the CNAME answer at an alias). contract.md defines ANY only for
  blocked names.
- CNAME following is a single step (contract.md § Zone file › CNAME speaks of "the target"); no
  chain is followed and no CNAME loop is possible.
- The handler ignores the query class; contract.md leaves classes other than IN unspecified.
- An upstream reply is matched by ID (contract.md, Principle VI). Whether it must also have QR=1,
  come from the upstream's address and port, and carry the same question, is a plan decision
  (RFC 5452 recommends the last two; research R-7 requires all three); either way a non-matching
  reply is ignored, never answered.
- The upstream address is IPv4, as in contract.md § Command line and 001's Config.
- Calls to the cache role go through the placeholder until 003 merges; until then the cached
  branch never fires, and every name that is neither local nor blocked is forwarded.
- The blocklist store lives in the `blocklist` module of constitution Principle IX; only the
  feature that builds it changes (002 instead of 004). Module boundaries and the interfaces of 001
  are unchanged.
- This feature does not modify `tests/`. Prompt-log entries (`docs/prompt-log.md`) are written by
  the user, as for 001.
