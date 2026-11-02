# Feature Specification: Query log, admin API and web dashboard

**Feature Branch**: `004-querylog-api`
**Created**: 2026-11-02
**Status**: Draft
**Input**: contract.md § Admin API; specs/001-parser-listener/contracts/interfaces.md (QueryLog role,
ServerState, Stats, ZoneStore and Blocklist operations); the tests 002 and 003 deferred to 004.

Built by hand without Spec Kit (README, change of plan 2026-11-02). External behaviour is defined by
contract.md and is cited here, not restated (Principle II).

## User Scenarios & Testing *(mandatory)*

The users are the operator of the home network, who watches and changes the server while it runs,
and the test suite, which reads `/stats` and `/log` and changes the zone and blocklist through the API.

### User Story 1 - The operator sees what the server is doing (Priority: P1)

The operator reads the four counters and the most recent queries, newest first.

**Independent Test**: send a few blocked queries, then check `GET /stats` and `GET /log`.

### User Story 2 - The operator changes the blocklist and the local records (Priority: P1)

The operator adds and removes blocked domains and local records while the server runs, and the
next query sees the change.

**Independent Test**: `POST /blocklist`, query the name, get the blocking response; `DELETE` it,
query again, get the upstream's answer. The same for `/records`.

### User Story 3 - The operator uses a dashboard (Priority: P2)

The operator opens `/ui` in a browser and does all of the above without writing HTTP requests.

**Independent Test**: start the server, open `/ui`, add and delete a domain and a record, and see an
API error shown on the page (checked by hand, DC-2).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001** (QueryLog store): `dnsd/querylog.py` provides `QueryLog`, filling the QueryLog role of
  001 interfaces.md § 3 exactly (`append`, `recent(limit)` newest first), under the concurrency rules
  of the same section.
  *Tests*: `tests/test_admin_api.py::test_log_honours_limit_newest_first`,
  `tests/test_admin_api.py::test_log_limit_larger_than_log_returns_everything`,
  `tests/test_admin_api.py::test_log_default_limit_is_100`

- **FR-002** (startup): `__main__.py` installs a `QueryLog` in `ServerState` in place of
  `PlaceholderQueryLog` and starts the admin server on `--admin`, in its own thread, before calling
  `serve` (001 interfaces.md § 4).
  *Tests*: every test that uses the `admin` fixture (`tests/conftest.py`), first among them
  `tests/test_admin_api.py::test_get_stats`

- **FR-003** (status codes): contract.md § Admin API › Status codes.
  *Tests*: `tests/test_admin_api.py::test_get_returns_200_json`,
  `tests/test_admin_api.py::test_unknown_path_is_404`,
  `tests/test_admin_api.py::test_method_not_in_table_is_405`,
  `tests/test_admin_api.py::test_post_blocklist_bad_body_is_400`,
  `tests/test_admin_api.py::test_post_records_bad_body_is_400`

- **FR-004** (names): contract.md § Admin API › Names, in bodies and URLs.
  *Tests*: `tests/test_admin_api.py::test_blocklist_accepts_names_in_any_form`,
  `tests/test_admin_api.py::test_delete_record_accepts_names_and_types_in_any_form`

- **FR-005** (/stats): `GET /stats` returns `state.stats.snapshot()` (contract.md § /stats; the
  counting itself is 001 FR-031).
  *Tests*: `tests/test_admin_api.py::test_get_stats`,
  `tests/test_admin_api.py::test_stats_cache_counters_start_at_zero`,
  `tests/test_admin_api.py::test_stats_queries_counts_udp_and_tcp`,
  `tests/test_admin_api.py::test_stats_queries_ignores_uncounted_input`,
  `tests/test_admin_api.py::test_stats_blocked_counts_blocking_responses`,
  `tests/test_admin_api.py::test_stats_blocked_ignores_unblocked_queries`,
  `tests/test_admin_api.py::test_stats_blocked_queries_leave_cache_counters_alone`,
  `tests/test_zone.py::test_local_queries_leave_cache_counters_alone`,
  `tests/test_cache.py::test_stats_count_misses_and_hits`,
  `tests/test_cache.py::test_stats_count_a_miss_after_expiry`

- **FR-006** (/blocklist): contract.md § /blocklist, through the Blocklist store's `domains`, `add`
  and `remove` only.
  *Tests*: `tests/test_admin_api.py::test_get_blocklist_lists_file_entries`,
  `tests/test_admin_api.py::test_post_blocklist`,
  `tests/test_admin_api.py::test_post_blocklist_duplicate`,
  `tests/test_admin_api.py::test_delete_blocklist`,
  `tests/test_admin_api.py::test_delete_blocklist_entry_loaded_from_file`,
  `tests/test_admin_api.py::test_delete_blocklist_twice_is_404`,
  `tests/test_admin_api.py::test_delete_blocklist_unknown_is_404`,
  `tests/test_admin_api.py::test_delete_blocklist_subdomain_of_listed_is_404`,
  `tests/test_blocklist.py::test_file_yields_exactly_its_entries`

- **FR-007** (/records): contract.md § /records, through the ZoneStore's `records`, `add`,
  `remove`, `make_record` and `value_text` only. A POST body whose fields are not of the right kind
  is rejected before `make_record` is called; an `Invalid` result is a 400.
  *Tests*: `tests/test_admin_api.py::test_get_records_lists_zone_file_records`,
  `tests/test_admin_api.py::test_record_fields`,
  `tests/test_admin_api.py::test_post_record`,
  `tests/test_admin_api.py::test_post_record_duplicate_replaces_ttl`,
  `tests/test_admin_api.py::test_delete_record`,
  `tests/test_admin_api.py::test_delete_record_removes_every_record_of_that_name_and_type`,
  `tests/test_admin_api.py::test_delete_record_loaded_from_zone_file`,
  `tests/test_admin_api.py::test_delete_record_twice_is_404`,
  `tests/test_admin_api.py::test_delete_record_unknown_is_404`

- **FR-008** (/log): contract.md § /log; entries come from `state.log.recent(limit)` and their
  fields from `LogEntry` (001 interfaces.md § 3).
  *Tests*: `tests/test_admin_api.py::test_log_entry_fields`,
  `tests/test_admin_api.py::test_log_type_without_mnemonic`,
  `tests/test_admin_api.py::test_log_limit_zero`,
  `tests/test_admin_api.py::test_log_invalid_limit_is_400`,
  `tests/test_admin_api.py::test_log_ignores_uncounted_input`,
  `tests/test_zone.py::test_local_queries_are_logged_as_local`,
  `tests/test_forwarder.py::test_forwarded_query_is_logged_as_forwarded`,
  `tests/test_forwarder.py::test_servfail_is_logged_as_error`,
  `tests/test_cache.py::test_cache_hit_is_logged_as_cached`

- **FR-009** (changes take effect immediately): contract.md § Admin API. The API changes the same
  store instances the handler reads (001 interfaces.md § 3, rule 5).
  *Tests*: `tests/test_admin_api.py::test_post_blocklist_takes_effect_immediately`,
  `tests/test_admin_api.py::test_delete_blocklist_unblocks_immediately`,
  `tests/test_admin_api.py::test_posted_record_resolves`,
  `tests/test_zone.py::test_api_record_creates_a_local_suffix`,
  `tests/test_zone.py::test_deleting_the_last_record_removes_the_suffix`,
  `tests/test_zone.py::test_deleted_record_no_longer_resolves`,
  `tests/test_blocklist.py::test_local_zone_wins_over_blocklist`,
  `tests/test_cache.py::test_blocking_a_cached_name_takes_effect_immediately`,
  `tests/test_cache.py::test_local_record_for_a_cached_name_takes_effect_immediately`

- **FR-010** (/ui): contract.md § /ui. The page is one inline string in `dnsd/api.py`.
  *Tests*: `tests/test_admin_api.py::test_get_ui_returns_200_html`,
  `tests/test_admin_api.py::test_ui_method_not_in_table_is_405`; the rest is DC-2.

### Design constraints (binding; no test)

Checked in review, because no test can tell them apart (Principle IV).

- **DC-1**: the QueryLog keeps the 1000 most recent entries (contract.md § /log); the tests never
  log more than 105.
- **DC-2**: `/ui` meets every point of contract.md § /ui (self-contained, the four counters, the
  blocklist, the records, recent log entries, add and delete, API errors shown on the page).
  Checked by hand before the PR.
- **DC-3** (Principle V): no HTTP input stops either server. Each request runs in its own thread;
  any unexpected error in a request is answered with 500 and the servers keep running. A body
  over 64 KiB is answered with 400 without being read.
- **DC-4**: if the admin address cannot be bound, the server prints `dnsd: <error>` to standard
  error and exits with status 1 before `serve` is called, like a zone or blocklist file error.
- **DC-5** (Principle IX): only `dnsd/querylog.py` (new), `dnsd/api.py` (new) and
  `dnsd/__main__.py` change. No change to `tests/` or to any 001–003 module.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All 58 test functions listed under Verification status pass.
- **SC-002**: `pytest tests --impl .` gives no failures and no errors; CI is green.
- **SC-003**: `ruff check dnsd` and `bandit -r dnsd` report zero findings.

## Assumptions

Where contract.md says nothing, the simplest option is taken:

- A name in a URL is percent-decoded before use. A DELETE whose name is not a valid domain name,
  or whose `{type}` is not a known type, returns 404 (nothing listed matches). A POST whose name is
  not a valid domain name returns 400.
- Error responses carry `{"error": "<reason>"}` so that `/ui` can show the reason; 201 and 204
  responses have no body.
- `limit` must be ASCII digits only; if it is given more than once, the first value is used.
- The methods GET, HEAD, POST, PUT, PATCH, DELETE and OPTIONS are routed (404 or 405 as above);
  any other method gets the standard library's 501.
- The admin address is IPv4, as in contract.md § Command line and 001's Config.
- Each response closes its connection (HTTP/1.0, the standard library default).

## Verification status

This feature is accepted when all of the following pass under `pytest tests --impl .`, and the
full suite gives no failures and no errors. No tests are deferred.

**Required for acceptance (004)** — 58 test functions:

- All 44 in `tests/test_admin_api.py`.
- The 9 that 002 deferred to 004 (002 § Verification status).
- The 5 that 003 deferred to 004 (003 § Verification status).
- No regression: every test 001–003 list as required.