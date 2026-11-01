# Data Model: Wire Parser and UDP/TCP Listener

Phase 1 of [plan.md](plan.md). Exact Python signatures are in
[contracts/interfaces.md](contracts/interfaces.md); this file describes fields, validation and
lifecycles. All types are frozen dataclasses unless stated otherwise.

## Message model (`dnsd/parser.py`)

### Name

| Field | Type | Rules |
|---|---|---|
| `labels` | `tuple[bytes, ...]` | each label 1–63 bytes; `sum(len(l) + 1) + 1 ≤ 255`; `()` is the root |

- Labels are kept as received, letter case included (FR-013).
- Equality and hash use the labels lowercased in ASCII (RFC 4343).
- `parent()` drops the first label (root has no parent: `ValueError`).
- `is_subdomain_of(other)`: whole-label suffix match, a name is a subdomain of itself, every name
  is a subdomain of the root.
- Text form (FR-026): labels joined by `.`, trailing `.`, root is `.`. Bytes `0x21`–`0x7E` other
  than `.` and `\` are written as-is; every other byte as `\DDD` (three decimal digits).
  `from_text` accepts `\DDD` and `\X`, an optional trailing dot, keeps case, and raises
  `ValueError` for an empty string, an empty label or a limit violation.

### Header

| Field | Type | Range |
|---|---|---|
| `id` | int | 0–65535 |
| `qr`, `aa`, `tc`, `rd`, `ra` | bool | |
| `opcode` | int | 0–15 |
| `z` | int | 0–7 |
| `rcode` | int | 0–15 |

All fields default to 0/False. Section counts are not stored; `encode` derives them from the
section lengths.

### Question

`name: Name`, `qtype: int` (0–65535), `qclass: int` (0–65535).

### ResourceRecord

| Field | Type | In identity |
|---|---|---|
| `name` | Name | yes |
| `rtype` | int 0–65535 | yes |
| `rclass` | int 0–65535 | yes |
| `ttl` | int 0–4294967295 | **no** |
| `rdata` | one of the RDATA types | yes |

`rdata` must match `rtype`: `A` ↔ 1, `NS` ↔ 2, `CNAME` ↔ 5, `SOA` ↔ 6, `PTR` ↔ 12, `MX` ↔ 15,
`AAAA` ↔ 28, `Raw` ↔ any other type (including TXT and OPT). A mismatch raises `ValueError`.

### RDATA types

| Type | Fields |
|---|---|
| `A` | `address: IPv4Address` |
| `AAAA` | `address: IPv6Address` |
| `CNAME` | `target: Name` |
| `NS` | `host: Name` |
| `PTR` | `target: Name` |
| `MX` | `preference: int` (0–65535), `exchange: Name` |
| `SOA` | `mname: Name`, `rname: Name`, `serial`, `refresh`, `retry`, `expire`, `minimum` (each 0–4294967295) |
| `Raw` | `data: bytes` (≤ 65535 bytes) |

Names in RDATA are fully decompressed on decode so a record re-encodes in any message (FR-023).

### Message

`header: Header`, `questions`, `answers`, `authority`, `additional`: `list` of `Question` /
`ResourceRecord`, each defaulting to an empty list. Frozen, but the lists themselves are mutable:
producers build new lists (`dataclasses.replace`) and stores never return their own lists.

### Decode results

| Result | Meaning (FR-008 rule) |
|---|---|
| `Short()` | 1: fewer than 12 bytes |
| `IsResponse()` | 2: QR=1 |
| `NotImp(header)` | 3: opcode ≠ 0 |
| `FormErr(header)` | 4/5: QDCOUNT ≠ 1, or the question cannot be parsed |
| `Message` | 6: valid query; exactly one question, other sections empty |
| `Malformed()` | `decode_message` only: any section fails to parse |

## Interface types (`dnsd/listener.py`)

| Entity | Fields | Notes |
|---|---|---|
| **Config** | `listen`, `admin`, `upstream`: `tuple[str, int]`; `zone_path`, `blocklist_path`: `str` | built once by `__main__` |
| **Query** | `message: Message`, `client: tuple[str, int]` | message from `decode_query` |
| **Outcome** | `response: Message`, `result: Result`, `upstream_asked: bool` | `Result` = `"local" \| "blocked" \| "cached" \| "forwarded" \| "error"` |
| **LogEntry** | `time: float`, `client: str`, `name: str`, `type: str`, `result: Result` | field values already in contract.md § Admin API › /log form |
| **Answer** | `records: tuple[ResourceRecord, ...]` | ZoneStore.lookup results |
| **NoData**, **NXDomain**, **NotLocal** | none | ZoneStore.lookup results |
| **Invalid** | `reason: str` | ZoneStore.make_record failure |
| **ServerState** | `config`, `zone`, `blocklist`, `cache`, `stats`, `log` | one instance per process (FR-027) |

### Stats (mutable, own lock)

Four `int` counters starting at 0: `queries`, `blocked`, `cache_hits`, `cache_misses`.
`record(outcome)` applies FR-031 under the lock:

- `queries += 1`
- `blocked += 1` if `outcome.result == "blocked"`
- `cache_hits += 1` if `outcome.result == "cached"`
- `cache_misses += 1` if `outcome.upstream_asked`

`snapshot()` returns all four as one dict read under the lock.

### Placeholder stores (stateless, no lock)

| Placeholder | Behaviour |
|---|---|
| ZoneStore | `lookup` → `NotLocal()`; `records` → `[]`; `add` does nothing; `remove` → 0; `make_record` → `Invalid("no zone support")`; `value_text` → `""` |
| Blocklist | `is_blocked` → False; `domains` → `[]`; `add` does nothing; `remove` → False |
| Cache | `get` → None; `put` does nothing |
| QueryLog | `append` does nothing; `recent` → `[]` (spec Assumptions) |

## Lifecycles

### Per message (listener)

```text
received bytes ──decode_query──► Short / IsResponse ──► no reply (TCP: close)
                              ├► NotImp / FormErr ────► bare 12-byte header
                              └► Message ──► Query ──► handler(query)
                                                        │ exception / not an Outcome
                                                        ├──► SERVFAIL Outcome ("error", False) + stderr
                                                        ▼
                                               finalise (ID, question, QR/RA/opcode/RD, TC=0, Z=0, drop OPT)
                                                        ▼
                                               encode ─► UDP > 512 → header+question, TC=1
                                                       └► TCP > 65535 → SERVFAIL form
                                                        ▼
                                               Stats.record + QueryLog.append ─► send
```

Only the bottom branch changes counters or the log (FR-031).

### Process (`__main__`)

parse flags → Config → build placeholders and Stats → ServerState → handler (stub in 001) →
`listener.serve(state, handler)` binds UDP and TCP and serves forever. Later features insert their
file loading before `serve` (FR-005).
