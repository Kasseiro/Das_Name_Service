# Research: Wire Parser and UDP/TCP Listener

Phase 0 of [plan.md](plan.md). The Technical Context had no open unknowns (language, libraries
and file layout were fixed by the planning input); this file records each design decision the
spec left to the plan, with rationale and the alternatives rejected.

## R-1 Concurrency model

- **Decision**: `socketserver.ThreadingUDPServer` and `socketserver.ThreadingTCPServer`, both with
  `daemon_threads = True`. One thread per UDP datagram and per TCP connection. The TCP server's
  `serve_forever` runs in a daemon thread; the UDP server's runs in the main thread. No limit on
  in-flight queries.
- **Rationale**: stdlib, a few lines, and each handler call runs in its own thread, so a 2 s
  upstream wait never delays other clients (FR-007, SC-004). With `daemon_threads = True`
  `ThreadingMixIn` does not keep a list of threads, so nothing grows over time, and the process
  exits on SIGTERM without joining.
- **Alternatives**: `asyncio` (the handler contract is a blocking call, so every handler would
  need `run_in_executor`: more code for the same effect); a fixed thread pool / in-flight limit
  (contract.md does not ask for one; Principle VIII); `selectors` loop (hand-written state machine
  for TCP, more code).

## R-2 Locking

- **Decision**: every stateful store has one private `threading.Lock`, taken for the duration of a
  single operation only. Inside the lock a store does only in-memory work: no socket call, no call
  to another store, no callback. Operations return copies or immutable values (FR-030).
  Placeholder stores hold no state and need no lock.
- **Rationale**: FR-028 (atomic per operation, visible on return) and FR-029 (no lock across I/O or
  stores). One lock per store means no lock ordering and therefore no deadlock.
- **Alternatives**: one global lock in ServerState (serialises admin API and queries; a forwarder
  bug holding it would stall everything); `RLock` (re-entry is never needed); lock-free reliance
  on the GIL (not guaranteed for multi-step updates such as Stats).

## R-3 `decode_query` result for a valid query

- **Decision**: `decode_query` returns the decoded `Message` itself for rule 6; the other results
  are `Short()`, `IsResponse()`, `NotImp(header)`, `FormErr(header)`. The listener wraps the
  Message and the client address into the handler's `Query`.
- **Rationale**: the spec writes the rule-6 result as `Query(Message)` and also names the handler
  input `Query`. Two classes called `Query` in `parser` and `listener` would be confusing; a bare
  `Message` is the same information. Accepted; spec § Message model was amended to say
  `decode_query` returns the `Message` itself.
- **Alternatives**: `parser.Query` plus `listener.Query` (name clash); raising exceptions for rules
  1–5 (exceptions for expected control flow, and an uncaught one would be a crash risk).

## R-4 Message model representation

- **Decision**: `@dataclass(frozen=True)` for every model type. `Message` holds Python lists for its
  four sections (`field(default_factory=list)`); everything else holds immutable values
  (`tuple`, `bytes`, `int`, `bool`, `ipaddress.IPv4Address`/`IPv6Address`). `Name` uses
  `eq=False` with its own `__eq__`/`__hash__` over ASCII-lowercased labels (RFC 4343).
  `ResourceRecord.ttl` is `field(compare=False)` so identity is name, type, class, rdata.
  Constructors check ranges in `__post_init__` and raise `ValueError`, so `encode` never fails.
- **Rationale**: as requested in the planning input; frozen fields stop accidental reassignment,
  and the custom Name equality gives case-insensitive comparison while the original bytes (and
  case) are kept for echoing the question (FR-013). `ipaddress` gives parsing, text form and
  `.packed` for free.
- **Note**: a frozen `Message` is only shallowly immutable (its lists can be mutated). Code that
  builds a response uses `dataclasses.replace` with new lists; stores never hand out their own
  lists (FR-030).
- **Alternatives**: `NamedTuple` (no per-field `compare=False`, no `__post_init__`); tuples in
  `Message` (planning input asked for lists); plain dicts (no validation, no equality rules).

## R-5 Name compression on write

- **Decision**: `encode` writes names uncompressed.
- **Rationale**: spec § Message model allows it ("MAY be compressed on write"), and no test depends
  on it. It also guarantees the question is echoed byte-for-byte (FR-013). The cost is that a
  relayed upstream answer can grow; over UDP the result is a truncated reply (contract-compliant,
  client retries over TCP), over TCP the 65535-byte guard of FR-017 answers SERVFAIL.
- **Alternatives**: suffix-table compression (~25 more lines and a second code path to test;
  revisit only if a test or a real client needs it).

## R-6 Decoding rules and bounds

- **Decision**:
  - One `_read_name(data, offset)` helper used by question and RDATA decoding: follows pointers
    (`0b11` top bits) only to offsets inside the message, fails when a pointer targets an offset
    already visited for this name (a set of visited pointer targets, which catches every loop), rejects
    label types `0b01`/`0b10`, labels > 63 and total wire length > 255, and checks every offset
    before indexing.
  - `decode_query` reads 12 header bytes, applies FR-008 rules 1–4 on the header, then reads one
    question (rule 5). It never looks at later sections or trailing bytes (FR-009).
  - `decode_message` reads all four sections according to the header counts; any failure returns
    `Malformed()` (never a partial message). RDATA for A must be exactly 4 bytes, AAAA 16; names in
    CNAME/NS/PTR/MX/SOA are decompressed and the parsed RDATA must end exactly at RDLENGTH
    (FR-022). Bytes after the last counted section are ignored (unspecified by contract.md).
  - Internally the parser raises a private exception on the first out-of-bounds or invalid field;
    the two public decode functions catch it and return `FormErr`/`Malformed`. Public functions
    never raise on any input.
- **Rationale**: FR-021/FR-022, Principle V, test_fuzz; one helper for all names keeps the bounds
  checks in one place.

## R-7 TCP handling and idle timeout

- **Decision**: per connection: one deadline 5 s after accept; each `recv` uses
  `settimeout(remaining)`. Read the 2-byte length, then exactly that many bytes. On timeout, EOF or
  `OSError` the connection is closed without reply. Otherwise classify as over UDP; no-reply cases
  close the connection; replies are written with `sendall(length prefix + wire)`, write errors
  ignored (`contextlib.suppress(OSError)`). The connection is closed after the first reply.
- **Rationale**: FR-006 (5 s chosen from the spec's "a few seconds" in the planning input), and a
  single deadline rather than a per-recv timeout so a client trickling bytes cannot keep a thread
  forever. Answering one query per connection is allowed by contract.md § TCP.
- **Alternatives**: per-recv timeout (trickle attack keeps connection open indefinitely);
  persistent connections (unspecified by contract.md; more code).

## R-8 Response finalisation and truncation

- **Decision**: the listener builds the response from the handler's Outcome as:
  header = handler header with `id`=query ID, `qr`=1, `opcode`=0, `rd`=query RD, `ra`=1, `tc`=0,
  `z`=0 (handler keeps `aa` and `rcode`); `questions` = the query's question; the three sections
  from the handler with every OPT (41) record removed. Over UDP, if `len(encode(...)) > 512`, it
  re-encodes with `tc`=1 and all three sections empty. Over TCP, if the encoding is > 65535 bytes,
  it sends the FR-020 SERVFAIL response instead. FORMERR/NOTIMP replies are `encode(Message(header))`
  with ID, opcode and RD from the query, QR=1, RA=1 and the RCODE (12 bytes, counts zero).
- **Rationale**: FR-010, FR-012–FR-017. An empty truncated reply always fits (header + one question
  ≤ 12 + 255 + 4 bytes) and contains only whole records trivially (spec Assumptions). `z` is
  RFC 1035 "must be zero" and is not handler-owned in spec § Resolution handler.
- **Alternatives**: keep as many whole answer records as fit (allowed, but needs an incremental
  encoder; nothing requires it).

## R-9 Where shared interface types live

- **Decision**: `dnsd/listener.py` defines `Config`, `Query`, `Outcome`, `Handler`, `LogEntry`,
  `ServerState`, `Stats`, the zone result types `Answer`, `NoData`, `NXDomain`, `NotLocal`,
  `Invalid`, and the four placeholder stores. Features 002–004 import these from `dnsd.listener`
  and put their real stores in their own modules (`zone.ZoneStore`, `blocklist.Blocklist`,
  `cache.Cache`, `querylog.QueryLog`), then change `__main__.py` to install them.
- **Rationale**: the placeholders must return these types now (e.g. `lookup` → `NotLocal()`), and
  the planning input allows only four files. Keeping all shared types in one module also gives
  002–004 one import site. The types are public interface, not internals, so Principle IX holds.
  Accepted; spec § Shared state was amended to say these types are defined in `dnsd/listener.py`
  and imported from there by 002–004.
- **Alternatives**: define zone result types in a future `zone.py` (placeholder could not return
  them in 001); `typing.Protocol` classes for each store (extra layer, no runtime value;
  Principle VIII; the signatures in contracts/interfaces.md are the reference instead).

## R-10 Command line

- **Decision**: `argparse` with five `required=True` options. `--listen`, `--admin`, `--upstream`
  use a `type=` function that does `host, _, port = text.rpartition(":")` and returns
  `(host, int(port))`; `int()` raising `ValueError` makes argparse print usage and exit 2.
  `--zone`, `--blocklist` are kept as `str`. No further validation (spec Q1). Sockets are bound
  after the ServerState is built, so startup loading by later features completes before the first
  answer (FR-005). A bind failure propagates as an exception (FR-004 removed).
- **Rationale**: FR-001, FR-002, spec Clarifications Q1, Principle VIII.

## R-11 Errors and accounting

- **Decision**: errors are reported with `print("dnsd: ...", file=sys.stderr)`; no logging module.
  Every message is processed inside one `try/except Exception` in the request handler so that any
  defect in one message is reported and others are unaffected (FR-011). The handler call has its
  own `try/except` so a handler failure becomes the FR-020 SERVFAIL Outcome. Accounting
  (`Stats.record`, `QueryLog.append`) happens after finalisation and before sending, so a client
  that disconnects is still counted (spec Edge Cases, FR-031). The log entry's `time` is taken
  with `time.time()` when the message is received.
- **Rationale**: planning input; FR-020, FR-031.

## R-12 Lint and scan

- **Decision**: avoid `assert` (bandit B101), `try/except/pass` (B110; use `contextlib.suppress`),
  `random` (B311) and literal `0.0.0.0` bind addresses (B104) in `dnsd/`. Set
  `ThreadingUDPServer.max_packet_size = 65535` so large client datagrams are read whole
  (spec Edge Cases).
- **Rationale**: Principle VII; CI runs both tools on every push.
