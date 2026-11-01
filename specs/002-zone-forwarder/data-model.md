# Data Model: Local Zone, Blocklist, Forwarder and Resolution Handler

Phase 1 of [plan.md](plan.md). The message model (`Name`, `Header`, `Question`, `ResourceRecord`,
RDATA types, `Message`), `Query`, `Outcome`, `ServerState` and the ZoneStore result types are
defined in [001 data-model.md](../001-parser-listener/data-model.md) and
[001 contracts/interfaces.md](../001-parser-listener/contracts/interfaces.md); this file covers
only the state the 002 modules keep and the values they build. Decisions are in
[research.md](research.md).

## Zone record

A `ResourceRecord` with:

| Field | Rule |
|---|---|
| `name` | any valid `Name`; from the zone file it must have been written with a trailing dot |
| `rtype` | `TYPE_A`, `TYPE_AAAA` or `TYPE_CNAME` |
| `rclass` | `CLASS_IN` |
| `ttl` | 0–4294967295; from the zone file, ASCII digits only |
| `rdata` | `A(IPv4Address)`, `AAAA(IPv6Address)` without scope ID, or `CNAME(Name)` |

Identity: name (case-insensitive), type, class, rdata; TTL excluded (001 message model).
Built only by `ZoneStore.make_record` (zone file loader and, in 004, the admin API).

## ZoneStore state (`dnsd/zone.py`)

| Field | Type | Meaning |
|---|---|---|
| `_lock` | `threading.Lock` | taken for the whole body of `lookup`, `records`, `add`, `remove` |
| `_by_name` | `dict[Name, list[ResourceRecord]]` | records per owner name; a key exists only while its list is non-empty |
| `_suffixes` | `set[Name]` | `{n.parent() for n in _by_name if n is not the root}`; recomputed when the key set changes |

Invariants: no two equal records under one name; `_suffixes` always matches `_by_name`'s keys
after an operation returns.

Transitions:

- **load** (startup): every zone-file line → `make_record` → `add`. Duplicate lines collapse to
  one record with the last TTL.
- **add(record)**: equal record present → replaced (TTL updated); else appended; new name →
  suffixes recomputed.
- **remove(name, rtype)**: matching records dropped; empty list → key dropped and suffixes
  recomputed; returns the count.

`lookup(name, qtype)` classification (first match wins):

| Condition | Result |
|---|---|
| `name` has records of `qtype` | `Answer(those records)` |
| `name` has records, `qtype` ≠ CNAME, `name` has CNAME records | `Answer(CNAMEs + qtype records at each CNAME target)` |
| `name` has records | `NoData()` |
| `name` or an ancestor is in `_suffixes` | `NXDomain()` |
| otherwise | `NotLocal()` |

## Blocklist state (`dnsd/blocklist.py`)

| Field | Type | Meaning |
|---|---|---|
| `_lock` | `threading.Lock` | taken for the whole body of every operation |
| `_listed` | `dict[Name, None]` | listed entries in insertion order; first spelling kept |

`is_blocked(name)` is true when `name` or any ancestor (up to and including the root) is a key.
Transitions: **load** (each line with its `#` comment removed, if not blank → `Name.from_text` → `add`), **add** (insert if
absent), **remove** (delete if listed; returns whether it was).

## Upstream exchange (`dnsd/forwarder.py`, per call, not shared)

| Value | Source | Rule |
|---|---|---|
| deadline | `time.monotonic() + 2.0` | covers UDP send/receive and any TCP retry |
| UDP source port | `1024 + secrets.randbelow(64512)` | fresh per query; up to 5 bind attempts |
| query ID | `secrets.randbelow(65536)` | fresh per query, new one for the TCP retry |
| query | `Message(Header(id, rd=True), [question])` | the client's question unchanged |
| counting reply | `decode_message` result | `Message`, `qr` set, same ID, same question |

States: *UDP waiting* → (counting reply, TC=0) *done* · (counting reply, TC=1) *TCP* · (deadline
or `OSError`) *failed*. *TCP* → (counting reply) *done* · (anything else) *failed*. Result: the
reply `Message`, or `None` for *failed*.

## Handler responses (`dnsd/forwarder.py`)

The handler fills only `header.rcode`, `header.aa` and the three sections; the listener sets the
rest (001 FR-012 – FR-017).

| Path | RCODE | AA | answers | authority / additional | result | upstream_asked |
|---|---|---|---|---|---|---|
| `Answer` | NOERROR | 1 | the records | empty | `local` | false |
| `NoData` | NOERROR | 1 | empty | empty | `local` | false |
| `NXDomain` | NXDOMAIN | 1 | empty | empty | `local` | false |
| blocked, A | NOERROR | 0 | `<qname> 60 IN A 0.0.0.0` | empty | `blocked` | false |
| blocked, AAAA | NOERROR | 0 | `<qname> 60 IN AAAA ::` | empty | `blocked` | false |
| blocked, other | NXDOMAIN | 0 | empty | empty | `blocked` | false |
| cache hit | cached | 0 | cached | cached | `cached` | false |
| upstream reply | upstream | 0 | upstream | upstream | `forwarded`, or `error` if SERVFAIL | true |
| exchange failed | SERVFAIL | 0 | empty | empty | `error` | true |
