# Data Model: TTL-Respecting Cache

All shared types (`Name`, `Message`, `Header`, `ResourceRecord`, `SOA`, the RCODE and type
constants) come from `dnsd.parser` (001 interfaces.md § 1). This feature adds one private type.

## `Cache` state (private to `dnsd/cache.py`)

| Field | Type | Meaning |
|---|---|---|
| `_lock` | `threading.Lock` | the store's one lock (001 concurrency rule 1) |
| `_entries` | `dict[tuple[Name, int], _Entry]` | one entry per question (name, qtype); `Name` equality ignores ASCII case |

## `_Entry` (private, frozen)

| Field | Type | Rule |
|---|---|---|
| `rcode` | `int` | `NOERROR` or `NXDOMAIN` only (FR-003 – FR-005) |
| `answers` | `tuple[ResourceRecord, ...]` | as received, TTLs as received |
| `authority` | `tuple[ResourceRecord, ...]` | as received |
| `additional` | `tuple[ResourceRecord, ...]` | as received |
| `stored` | `float` | `time.monotonic()` when `put` built the entry |
| `lifetime` | `int` | whole seconds, > 0 (research R-2) |

## Lifetime (research R-2)

| Reply | Lifetime |
|---|---|
| NOERROR, answers not empty | lowest answer TTL |
| NXDOMAIN or NOERROR with no answers, ≥ 1 SOA in authority | lowest `min(SOA ttl, SOA minimum)` over those SOAs, capped by the lowest answer TTL if there are answers |
| NXDOMAIN or NOERROR with no answers, no SOA in authority | 0 (not stored) |
| any other RCODE (SERVFAIL, REFUSED, NOTIMP, FORMERR, …) | 0 (not stored) |

A lifetime of 0 means `put` stores nothing and leaves any existing entry unchanged.

## Entry life cycle

```text
          put(name, qtype, reply), lifetime > 0
 (none) ───────────────────────────────────────▶ live
   ▲                                              │  put again, lifetime > 0 → replaced (new stored, lifetime)
   │                                              │  put again, lifetime = 0 → unchanged
   │   get finds age ≥ lifetime: delete, None     │
   └──────────────────────────────────────────────┘
```

- `age = int(time.monotonic() - stored)`.
- **live** (`age < lifetime`): `get` returns `Message(Header(rcode=rcode), [], answers', authority',
  additional')`, where each record is copied with `ttl = max(ttl - age, 0)` and each section is a
  new list. The header carries only the RCODE; the handler and listener set everything else
  (002 `_relayed`, 001 `_finalise`). The question list is empty; the listener copies the client's.
- **expired** (`age ≥ lifetime`): `get` deletes the entry and returns `None`.
- An entry never asked for again after it expires stays in the dict (no sweep, research R-5).
