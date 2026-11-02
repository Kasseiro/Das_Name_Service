# Research: Local Zone, Blocklist, Forwarder and Resolution Handler

Phase 0 of [plan.md](plan.md). The Technical Context had no open unknowns (language, files,
locking, socket use and startup-error behaviour were fixed by the planning input); this file
records each decision the spec left to the plan, with rationale and the alternatives rejected.
Interfaces come from [001 contracts/interfaces.md](../001-parser-listener/contracts/interfaces.md)
and are not repeated here.

## R-1 Zone file parsing

- **Decision**: read the file as UTF-8, line by line. Text from the first `;` to the end of the
  line is a comment (RFC 1035 5.1); a line that is then blank is skipped. Every other line must
  split (on any whitespace) into exactly five fields `name ttl class type value`:
  - `name` ends with `.` (contract.md § Zone file: names are absolute);
  - `ttl` is ASCII decimal digits only (no sign, no `_`), checked before `int()`;
  - `class` is `IN`, case-insensitively;
  - `type`, `ttl`, `value` and `name` then go through `ZoneStore.make_record` (R-4), so the zone
    file and the admin API validate records with the same code.
  Any other line is malformed: the loader raises `ValueError("<path>:<line>: <reason>")`.
- **Rationale**: contract.md § Zone file fixes the five-field form and whole-line `;` comments;
  where it is silent (a comment after a record), RFC 1035 decides (Principle I), and RFC 1035
  allows a trailing `;` comment. Reusing `make_record` keeps one validator (Principle VIII).
- **Alternatives**: whole-line comments only (rejects valid RFC 1035 lines for no gain); accepting
  a missing class or relative names (not in the contract; would need `$ORIGIN` semantics).

## R-2 Blocklist file parsing

- **Decision**: read as UTF-8, line by line. Text from the first `#` to the end of the line is a
  comment; a line that is then blank is skipped. This covers whole-line comments (first non-blank
  character `#`, contract.md § Blocklist file) and a trailing comment, so `ads.example.com # ads`
  lists `ads.example.com`. What remains must be exactly one whitespace-free field, converted with
  `Name.from_text` (trailing dot optional, case kept). More than one field, or an invalid name
  (empty label, label over 63 bytes, name over 255 bytes), is malformed: the loader raises
  `ValueError("<path>:<line>: <reason>")`.
- **Rationale**: contract.md § Blocklist file defines whole-line `#` comments and leaves a `#`
  later in a line unspecified. Treating it as the start of a comment is what blocklist authors
  expect, matches the zone file's trailing `;` rule (R-1), and is one `split("#", 1)`, the same
  operation that already handles whole-line comments. `#` cannot occur in a hostname, so no entry
  is lost. `Name.from_text` accepts spaces inside a label, so the one-field check is what rejects
  `ads example.com`.
- **Alternatives**: whole-line comments only, so `ads.example.com # ads` is malformed (two fields)
  and the server refuses to start over a harmless annotation; skip bad lines with a warning
  (planning input: malformed file → exit).

## R-3 Startup errors

- **Decision**: `zone.load_zone(path)` and `blocklist.load_blocklist(path)` return a filled store
  or raise `OSError` (missing, unreadable) or `ValueError` (malformed line, including
  `UnicodeDecodeError`, which is a `ValueError`). `__main__` catches exactly these two, prints
  `dnsd: <message>` to stderr and exits with status 1, before `serve` binds any socket.
- **Rationale**: planning input; nothing is answered from a partly loaded zone (001 FR-005).
  Status 1 is distinct from argparse's 2.
- **Alternatives**: a custom exception class (one more type for two call sites; Principle VIII).

## R-4 ZoneStore design

- **Decision**: state is `dict[Name, list[ResourceRecord]]` (records per owner name, insertion
  order) plus `set[Name]` of local zone suffixes, guarded by one `threading.Lock`.
  - Suffixes are recomputed from the dict keys after every `add`/`remove` that changes the key
    set: `{name.parent() for name in keys if name.labels}` (the root has no parent and is skipped).
  - `lookup(name, qtype)` under the lock:
    1. the name has records: those of type `qtype` → `Answer`; else, if `qtype` ≠ CNAME and the
       name has CNAME records → `Answer(cnames + records of qtype at each CNAME target)`; else
       `NoData`;
    2. no records, and the name or one of its ancestors is in the suffix set (walk `parent()` up to
       the root, ≤ 127 steps) → `NXDomain`;
    3. otherwise `NotLocal`.
    Only one CNAME step is taken (spec FR-008); target records are looked up in the same dict, so
    a target outside the zone simply contributes nothing.
  - `add(record)`: if an equal record (identity ignores TTL) exists under its name, it is replaced
    by the new one (new TTL) in place; otherwise appended.
  - `remove(name, rtype)`: removes every record of that type at that name; drops the key when the
    list empties; returns the count.
  - `records()`: a new flat list, in insertion order per name.
  - `make_record` and `value_text` take no lock (pure; interfaces.md).
- **Rationale**: FR-004 – FR-012; the per-name dict makes every lookup O(depth) and keeps
  `remove`'s "every record with that name and type" a single list filter. Recomputing the suffix
  set is O(names) per admin change, which is negligible for a home zone and avoids reference
  counting. `Answer` holds a tuple of frozen records, so callers cannot change the store
  (concurrency rule 3).
- **Note**: a record directly under the root (e.g. `lan.`) makes the root a suffix, so every
  non-matching name becomes NXDOMAIN. That is what contract.md § Zone file › Local zone suffix
  says; it is not special-cased.
- **Alternatives**: a flat record list scanned per query (O(records) per query); a suffix counter
  updated incrementally (more code for no observable difference).

## R-5 `make_record` / `value_text`

- **Decision**: `make_record(name_text, type_text, ttl, value_text)`:
  `Name.from_text(name_text)`; `type_from_text(type_text)` must give A, AAAA or CNAME; `ttl` must
  be an `int` (not `bool`) in 0–4294967295; value: A → `ipaddress.IPv4Address(value_text)`,
  AAAA → `ipaddress.IPv6Address(value_text)` with no scope ID (`%eth0` cannot be encoded),
  CNAME → `Name.from_text(value_text)`; then `ResourceRecord(name, rtype, CLASS_IN, ttl, rdata)`.
  Any `ValueError` on the way becomes `Invalid(<reason>)`. `value_text`: `str(address)` for A and
  AAAA (Python's compressed IPv6 form), `target.to_text()` for CNAME.
- **Rationale**: FR-011, FR-012; `ipaddress` gives strict parsing (it rejects leading zeros in
  IPv4 on 3.11) and the canonical text form.

## R-6 Blocklist store design

- **Decision**: state is `dict[Name, None]` (an insertion-ordered set of listed entries) guarded by
  one `threading.Lock`. `is_blocked(name)` checks the name and each ancestor up to the root
  against the dict; `domains()` returns `list(keys)`; `add` inserts if absent (the first spelling
  is kept); `remove` deletes a listed entry and returns `True`, else `False`.
- **Rationale**: FR-013, FR-014. `Name`'s case-insensitive `__eq__`/`__hash__` gives RFC 4343
  matching and de-duplication for free; walking ancestors is whole-label matching by
  construction, so `xads.example.com` never matches `ads.example.com`.
- **Alternatives**: a set of lower-cased strings (re-implements Name equality); a suffix trie
  (more code; the walk is ≤ 127 dict lookups).

## R-7 Upstream exchange

- **Decision**: `forwarder.exchange(upstream, question) -> Message | None`, one call per forwarded
  query, no shared state:
  1. `deadline = time.monotonic() + 2.0`, covering everything below.
  2. UDP: new `AF_INET`/`SOCK_DGRAM` socket bound to `("", port)` with
     `port = 1024 + secrets.randbelow(64512)`; on `OSError` at bind (port in use), retry with a
     fresh random port, up to 5 attempts. Then `connect(upstream)`, so the kernel delivers only
     datagrams from the upstream address and port, and an ICMP port-unreachable surfaces as an
     `OSError`.
  3. Query: `Message(Header(id=secrets.randbelow(65536), rd=True), [question])`, encoded.
  4. Receive loop: `settimeout(deadline - now)`, `recv(65535)`; a datagram counts only if
     `decode_message` gives a `Message` with `qr` set, the same ID, and `questions == [question]`;
     anything else is ignored and the loop continues until the deadline.
  5. If the counting reply has `tc` set: `socket.create_connection(upstream, timeout=remaining)`,
     send the query again with a **new** random ID behind a two-byte length, read the two-byte
     length and exactly that many bytes, each `recv` with the remaining time; the reply counts
     under the same three checks. One TCP reply only: if it does not count, the exchange fails.
  6. Any `OSError` (including `TimeoutError`) or deadline expiry → `None`.
  Sockets are always closed (`with`).
- **Rationale**: FR-015 – FR-019 and Principle VI. `secrets` for both values (RFC 5452 wants the
  widest port range; 1024–65535 avoids privileged ports). `connect()` adds the RFC 5452
  source-address check at no code cost; the question check is one comparison. RD=1 because the
  server relies on the upstream to recurse (contract.md § Scope: no iterative resolution). A new
  ID for the TCP retry follows "every query sent to the upstream has a 16-bit ID ... chosen at
  random for that query" (contract.md § Responses › Forwarded queries).
- **Alternatives**: let the OS choose the source port (not chosen "from `secrets`"; Principle VI);
  one shared upstream socket with a demultiplexer (fixed port, shared state, more code); retrying
  UDP within the budget (not in the contract).
- **Lint note**: binding `("", port)` is not the `0.0.0.0` literal that bandit B104 flags; if a
  bandit version flags it, the fallback is to bind to the address `connect()` would choose
  (checked in the lint task, not suppressed).

## R-8 Handler

- **Decision**: `forwarder.make_handler(state) -> Handler` returns a closure over `state`:
  1. `state.zone.lookup(name, qtype)`: `Answer` → `Message(Header(aa=True), answers=list(records))`;
     `NoData` → `Header(aa=True)`; `NXDomain` → `Header(aa=True, rcode=NXDOMAIN)`; result
     `local`, `upstream_asked` false.
  2. `NotLocal` and `state.blocklist.is_blocked(name)`: A → one record
     `A(IPv4Address(0))`, AAAA → `AAAA(IPv6Address(0))`, both class IN, TTL 60, owner = question
     name; any other type → `Header(rcode=NXDOMAIN)`; AA=0; `blocked`, false.
  3. `state.cache.get(name, qtype)` not `None` → its RCODE and three sections, AA=0; `cached`,
     false.
  4. `exchange(state.config.upstream, question)`: `None` → `Header(rcode=SERVFAIL)`, `error`,
     true; a reply → `state.cache.put(name, qtype, reply)`, then its RCODE and three sections,
     AA=0; result `error` if the RCODE is SERVFAIL (spec Q1), else `forwarded`; true.
  The handler builds new lists for every section and holds no lock.
- **Rationale**: FR-020 – FR-025. `IPv4Address(0)`/`IPv6Address(0)` avoid a `"0.0.0.0"` string
  literal (bandit B104). The handler lives in `forwarder.py` per the planning input, so no new
  module is added; only `forwarder` imports the parser and listener types it needs.
- **Alternatives**: a separate `resolver.py` (not in Principle IX's module list); blocked responses
  built by the blocklist store (stores do in-memory lookups only; response shape belongs to the
  handler per spec FR-022).

## R-9 Entry point

- **Decision**: `__main__.py` changes in three lines' worth of logic: build `ZoneStore` with
  `load_zone(args.zone)` and `Blocklist` with `load_blocklist(args.blocklist)` (R-3 error
  handling), put them in `ServerState` in place of the two placeholders, and call
  `serve(state, make_handler(state))` instead of `serve(state, stub_handler)`. Cache and query log
  keep their placeholders. `PlaceholderZoneStore`, `PlaceholderBlocklist` and `stub_handler` stay
  in `listener.py` (001 code; removing them is not required and would change 001).
- **Rationale**: FR-003, FR-020; 001 interfaces.md § 2 and § 4.

## R-10 Lint and scan

- **Decision**: same rules as 001 R-12: no `assert`, no `random`, no `try/except/pass`
  (`contextlib.suppress`), no `"0.0.0.0"` literal; `except OSError` only where a socket call can
  fail; no broad `except Exception` in 002 code (the listener's FR-020 guard already covers
  defects).
- **Rationale**: Principle VII; zero findings from `ruff check dnsd` and `bandit -r dnsd`.
