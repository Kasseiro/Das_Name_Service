# Quickstart: validating the parser and listener

How to check that feature 001 works. Interfaces are in
[contracts/interfaces.md](contracts/interfaces.md); the acceptance gate is spec.md
§ Verification status.

## Prerequisites

- Python 3.11 on `PATH` as `python`.
- From the repo root: `pip install -r tests/requirements.txt` (dnspython, pytest, requests, ruff,
  bandit; for `tests/` and CI only — `dnsd/` itself needs nothing installed).

## 1. Lint and security scan (Principle VII)

```sh
ruff check dnsd
bandit -r dnsd
```

Expected: no findings from either tool.

## 2. Acceptance gate: the 11 stub-compatible tests

```sh
pytest --impl=. \
  tests/test_harness.py::test_server_starts_with_documented_flags \
  tests/test_listener.py::test_response_echoes_id \
  tests/test_listener.py::test_response_echoes_question \
  tests/test_listener.py::test_response_preserves_case_of_question_name \
  tests/test_listener.py::test_qr_set_on_every_response \
  tests/test_listener.py::test_ra_set_on_every_response \
  tests/test_listener.py::test_tcp_formerr \
  tests/test_listener.py::test_tcp_notimp \
  tests/test_listener.py::test_formerr \
  tests/test_listener.py::test_notimp_for_other_opcodes \
  tests/test_listener.py::test_truncated_response_keeps_question_and_whole_records
```

Expected: all pass (each name expands to its parametrised cases). Nothing is skipped; a skip
with "no build to test" means `dnsd/__main__.py` is missing.

## 3. Deferred tests (informational)

```sh
pytest --impl=. tests/test_listener.py tests/test_fuzz.py
```

Expected with the stub handler: the 9 tests in spec.md § Verification status › Deferred fail only
on the answer they expect (`0.0.0.0` / NOERROR, or the 40 records of `big.home.lan.`), never
because the server exited or sent nothing to a valid query. In particular, the fuzz test should
fail at its first canary with `wrong answer to a valid query: rcode=SERVFAIL`, not with
`server exited` or `no answer`. They become gate tests when 002 and 004 merge.

## 4. Manual smoke test

Terminal 1:

```sh
python -m dnsd --listen 127.0.0.1:5353 --admin 127.0.0.1:8080 \
    --zone tests/fixtures/zone.txt --blocklist tests/fixtures/blocklist.txt \
    --upstream 1.1.1.1:53
```

Terminal 2 (uses dnspython from `tests/requirements.txt`):

```sh
python -c "import dns.message, dns.query; q = dns.message.make_query('Example.COM.', 'A'); \
r = dns.query.udp(q, '127.0.0.1', port=5353, timeout=2); print(r.id == q.id, r.question, r.flags, r.rcode())"
python -c "import dns.message, dns.query; q = dns.message.make_query('example.com.', 'A'); \
print(dns.query.tcp(q, '127.0.0.1', port=5353, timeout=2).rcode())"
```

Expected: `True`, the question with its original case, flags including `QR RD RA`, RCODE 2
(SERVFAIL) over both UDP and TCP.

Idle TCP connection (FR-006): `python -c "import socket,time; s=socket.create_connection(('127.0.0.1',5353)); t=time.time(); print(s.recv(1), round(time.time()-t))"`
prints `b'' 5`: the server closes it after the 5 s idle timeout, while the queries above still
answer immediately from another terminal.

Missing flag: `python -m dnsd --listen 127.0.0.1:5353` prints argparse usage and exits with
status 2 (argparse default; no requirement).

## 5. Pending

The slow-upstream test for FR-007/FR-029 (SC-004) is to be added by Daniel; it is not part of this
feature's gate.
