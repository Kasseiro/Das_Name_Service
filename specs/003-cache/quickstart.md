# Quickstart: validating the cache

How to check that feature 003 works. Public names are in [contracts/cache.md](contracts/cache.md);
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

## 2. Acceptance gate: the 17 required cache tests

```sh
pytest --impl=. tests/test_cache.py \
  --deselect tests/test_cache.py::test_blocking_a_cached_name_takes_effect_immediately \
  --deselect tests/test_cache.py::test_local_record_for_a_cached_name_takes_effect_immediately \
  --deselect tests/test_cache.py::test_stats_count_misses_and_hits \
  --deselect tests/test_cache.py::test_stats_count_a_miss_after_expiry \
  --deselect tests/test_cache.py::test_cache_hit_is_logged_as_cached
```

Expected: every selected test passes (17 functions; two are parametrised and expand to more
cases). Takes about 20–25 s because of the TTL waits and the upstream timeout.

## 3. No regression: the 65 tests 002 requires

Run the command of [002 quickstart § 2](../002-zone-forwarder/quickstart.md). Expected: all pass.
Each test gets its own server and therefore an empty cache.

## 4. Full suite (what CI runs)

```sh
pytest tests --impl .
```

Expected: every failure is one of the tests deferred to 004: the 5 in spec.md § Verification status
and the 004-deferred tests of 002 (its § Verification status, plus `tests/test_admin_api.py`).
No failure in `tests/test_cache.py` outside those 5.

## 5. Scope check (spec SC-007)

```sh
git diff --stat main -- dnsd/
```

Expected: only `dnsd/cache.py` (new) and `dnsd/__main__.py`.

## 6. Review points (no test)

- DC-1: one lock, taken for the whole body of `get` and `put`; nothing under it does I/O or calls
  another store.
- DC-2: a negative reply with an SOA is stored for `min(SOA ttl, SOA minimum)` (research R-2).
- DC-3: the dict is keyed by the `Name` value itself; no lower-casing or other normalisation.
- DC-4: `_lifetime` returns 0 for a reply with TC=1, before any RCODE branch.
