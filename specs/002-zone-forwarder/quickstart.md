# Quickstart: validating the zone, blocklist and forwarder

How to check that feature 002 works. Public names are in [contracts/modules.md](contracts/modules.md);
the acceptance gate is spec.md § Verification status.

## Prerequisites

- Python 3.11 on `PATH` as `python`.
- From the repo root: `pip install -r tests/requirements.txt` (for `tests/` and CI only).

## 1. Lint and security scan (Principle VII)

```sh
ruff check dnsd
bandit -r dnsd
```

Expected: no findings from either tool.

## 2. Acceptance gate: the 65 required tests

The six suites below, minus the 9 tests deferred to 004:

```sh
pytest --impl=. \
  tests/test_zone.py tests/test_forwarder.py tests/test_blocklist.py \
  tests/test_listener.py tests/test_fuzz.py tests/test_harness.py \
  --deselect tests/test_zone.py::test_api_record_creates_a_local_suffix \
  --deselect tests/test_zone.py::test_deleting_the_last_record_removes_the_suffix \
  --deselect tests/test_zone.py::test_deleted_record_no_longer_resolves \
  --deselect tests/test_zone.py::test_local_queries_leave_cache_counters_alone \
  --deselect tests/test_zone.py::test_local_queries_are_logged_as_local \
  --deselect tests/test_forwarder.py::test_forwarded_query_is_logged_as_forwarded \
  --deselect tests/test_forwarder.py::test_servfail_is_logged_as_error \
  --deselect tests/test_blocklist.py::test_file_yields_exactly_its_entries \
  --deselect tests/test_blocklist.py::test_local_zone_wins_over_blocklist
```

Expected: every selected test passes (65 functions; parametrised ones expand to more cases).

## 3. Full suite (what CI runs)

```sh
pytest tests --impl .
```

Expected: the only failures are the tests spec.md § Verification status defers to 003 or 004,
and each fails on the missing cache, `/stats`, `/log`, `/records` or `/blocklist`, never on
"dnsd exited" or "no response" (constitution § Technical Constraints: the reviewer checks this).

## 4. By hand

Start the server on a free port with the fixtures and a real or fake upstream:

```sh
python -m dnsd --listen 127.0.0.1:5300 --admin 127.0.0.1:8300 \
  --zone tests/fixtures/zone.txt --blocklist tests/fixtures/blocklist.txt \
  --upstream 1.1.1.1:53
```

Then, with `dig` (or dnspython):

| Query | Expected |
|---|---|
| `dig @127.0.0.1 -p 5300 nas.home.lan A` | `192.168.1.10`, flag `aa` |
| `dig @127.0.0.1 -p 5300 files.home.lan A` | CNAME `nas.home.lan.`, then `192.168.1.10`, `aa` |
| `dig @127.0.0.1 -p 5300 missing.home.lan A` | `NXDOMAIN`, `aa` |
| `dig @127.0.0.1 -p 5300 sub.ads.example.com AAAA` | `::`, TTL 60, no `aa` |
| `dig @127.0.0.1 -p 5300 example.org A` | the upstream's answer, no `aa` |
| `dig @127.0.0.1 -p 5300 big.home.lan A +notcp +ignore` | `tc` set, ≤ 512 bytes |

Startup errors (exit status 1, one `dnsd: ...` line on stderr, no socket bound):

```sh
python -m dnsd ... --zone /nonexistent ...                 # cannot read the file
printf 'nas.home.lan. 300 IN MX 10 x.\n' > /tmp/z.txt      # malformed line
python -m dnsd ... --zone /tmp/z.txt ...                   # "dnsd: /tmp/z.txt:1: ..."
```
