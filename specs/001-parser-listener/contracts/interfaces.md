# Contract: Inter-module interfaces (binding for features 002–004)

This file turns spec.md § Inter-module interfaces into concrete Python signatures. It and that
section must agree; changing either is an amendment of [spec.md](../spec.md) (constitution
Principle IX). Field rules are in [data-model.md](../data-model.md); behaviour is in spec.md and
the cited contract.md sections.

Notation: bodies are omitted (`...`). Every class shown with `@dataclass(frozen=True)` is a frozen
dataclass. Other modules import only the names listed here.

## 1. `dnsd.parser` — message model

```python
from dataclasses import dataclass, field
from ipaddress import IPv4Address, IPv6Address

# --- constants (FR-025 codes; RFC 1035 classes and RCODEs)
TYPE_A, TYPE_NS, TYPE_CNAME, TYPE_SOA, TYPE_PTR = 1, 2, 5, 6, 12
TYPE_MX, TYPE_TXT, TYPE_AAAA, TYPE_OPT, TYPE_ANY = 15, 16, 28, 41, 255
CLASS_IN = 1
NOERROR, FORMERR, SERVFAIL, NXDOMAIN, NOTIMP = 0, 1, 2, 3, 4


@dataclass(frozen=True, eq=False)
class Name:
    labels: tuple[bytes, ...]                 # as received, case kept; () is the root
    # __post_init__: ValueError unless every label is 1–63 bytes and wire length ≤ 255
    def __eq__(self, other: object) -> bool: ...   # ASCII case-insensitive (RFC 4343)
    def __hash__(self) -> int: ...                 # consistent with __eq__
    def parent(self) -> "Name": ...                # first label removed; ValueError for root
    def is_subdomain_of(self, other: "Name") -> bool: ...  # whole-label suffix; self counts
    def to_text(self) -> str: ...                  # "a.b." ; root "." ; \DDD escapes (FR-026)
    @classmethod
    def from_text(cls, text: str) -> "Name": ...   # trailing dot optional; ValueError if invalid


@dataclass(frozen=True)
class Header:
    id: int = 0
    qr: bool = False
    opcode: int = 0
    aa: bool = False
    tc: bool = False
    rd: bool = False
    ra: bool = False
    z: int = 0
    rcode: int = 0
    # __post_init__: ValueError if any int is out of range (id 16 bit, opcode/rcode 4 bit, z 3 bit)


@dataclass(frozen=True)
class Question:
    name: Name
    qtype: int
    qclass: int


# --- RDATA (FR-023)
@dataclass(frozen=True)
class A:
    address: IPv4Address

@dataclass(frozen=True)
class AAAA:
    address: IPv6Address

@dataclass(frozen=True)
class CNAME:
    target: Name

@dataclass(frozen=True)
class NS:
    host: Name

@dataclass(frozen=True)
class PTR:
    target: Name

@dataclass(frozen=True)
class MX:
    preference: int
    exchange: Name

@dataclass(frozen=True)
class SOA:
    mname: Name
    rname: Name
    serial: int
    refresh: int
    retry: int
    expire: int
    minimum: int

@dataclass(frozen=True)
class Raw:
    data: bytes                               # every other type, re-encoded unchanged

RData = A | AAAA | CNAME | NS | PTR | MX | SOA | Raw


@dataclass(frozen=True)
class ResourceRecord:
    name: Name
    rtype: int
    rclass: int
    ttl: int = field(compare=False)           # not part of identity (spec § Message model)
    rdata: RData
    # __post_init__: ValueError if rdata class does not match rtype, or a value is out of range


@dataclass(frozen=True)
class Message:
    header: Header
    questions: list[Question] = field(default_factory=list)
    answers: list[ResourceRecord] = field(default_factory=list)
    authority: list[ResourceRecord] = field(default_factory=list)
    additional: list[ResourceRecord] = field(default_factory=list)


# --- decode results (FR-008)
@dataclass(frozen=True)
class Short: ...                              # rule 1

@dataclass(frozen=True)
class IsResponse: ...                         # rule 2

@dataclass(frozen=True)
class NotImp:                                 # rule 3
    header: Header

@dataclass(frozen=True)
class FormErr:                                # rules 4 and 5
    header: Header

@dataclass(frozen=True)
class Malformed: ...                          # decode_message failure


def decode_query(data: bytes) -> Short | IsResponse | NotImp | FormErr | Message: ...
    # FR-008 rules 1–6 in order. A returned Message is the spec's "Query(Message)":
    # header plus exactly one question; answers/authority/additional empty.
    # Never reads past the question. Never raises.

def decode_message(data: bytes) -> Message | Malformed: ...
    # All sections (forwarder: upstream replies). All-or-nothing. Never raises.

def encode(message: Message) -> bytes: ...
    # Counts from list lengths; names written uncompressed. Never raises for a valid Message.

def type_to_text(code: int) -> str: ...       # "A", ..., "ANY"; otherwise f"TYPE{code}"
def type_from_text(text: str) -> int: ...     # case-insensitive mnemonic or "TYPEn"; ValueError otherwise
```

## 2. `dnsd.listener` — resolution handler

```python
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from dnsd.parser import Message

Result = Literal["local", "blocked", "cached", "forwarded", "error"]


@dataclass(frozen=True)
class Query:
    message: Message                          # from decode_query: one question, other sections empty
    client: tuple[str, int]                   # (IP address text, port)


@dataclass(frozen=True)
class Outcome:
    response: Message
    result: Result
    upstream_asked: bool                      # True when the upstream was sent the query


Handler = Callable[[Query], Outcome]


def stub_handler(query: Query) -> Outcome: ...
    # FR-019: Outcome(Message(Header(rcode=SERVFAIL)), "error", False). Replaced, not extended, by 002.
```

**Contract** (spec § Resolution handler):

- Called once per valid query, concurrently from many threads, blocking, up to ~2 s.
- Handler owns: `header.rcode`, `header.aa`, `answers`, `authority`, `additional`.
- Listener owns and overwrites: `id`, `questions`, `qr`, `ra`, `opcode`, `rd`, `tc`, `z`, OPT
  removal, truncation, framing, `Stats`, `QueryLog`.
- An exception or a non-`Outcome` return value is turned into SERVFAIL / `"error"` / `False`
  (FR-020). Handlers must not call `Stats.record` or `QueryLog.append`.
- Feature 002 provides the real handler as a function `(ServerState) -> Handler` in its own module
  and changes `__main__.py` to install it in place of `stub_handler`.

## 3. `dnsd.listener` — shared state

```python
from dataclasses import dataclass
from typing import Any

from dnsd.parser import Message, Name, ResourceRecord


@dataclass(frozen=True)
class Config:
    listen: tuple[str, int]
    admin: tuple[str, int]
    upstream: tuple[str, int]
    zone_path: str
    blocklist_path: str


@dataclass(frozen=True)
class LogEntry:
    time: float                               # time.time() at arrival
    client: str                               # IP address, no port
    name: str                                 # Name.to_text() of the question
    type: str                                 # type_to_text(qtype)
    result: Result


# --- ZoneStore.lookup / make_record results
@dataclass(frozen=True)
class Answer:
    records: tuple[ResourceRecord, ...]

@dataclass(frozen=True)
class NoData: ...

@dataclass(frozen=True)
class NXDomain: ...

@dataclass(frozen=True)
class NotLocal: ...

@dataclass(frozen=True)
class Invalid:
    reason: str


@dataclass(frozen=True)
class ServerState:
    config: Config
    zone: Any                                 # role: ZoneStore
    blocklist: Any                            # role: Blocklist
    cache: Any                                # role: Cache
    stats: Any                                # role: Stats (dnsd.listener.Stats)
    log: Any                                  # role: QueryLog
```

### Store operations

`ZoneStore`, `Blocklist`, `Cache` and `QueryLog` are **roles, not importable types**. No class
with those names exists in `dnsd.listener`, and none may be imported from there. The class
blocks below only list the methods a store filling each role must have. For that reason the
`ServerState` store fields are annotated `typing.Any`: a string annotation naming a class that
does not exist would be an undefined name for `ruff` (F821, Principle VII).

Each store class below must provide exactly these methods. The comments on the `ServerState`
fields above name the roles; the classes that fill them are the placeholders in `dnsd.listener` (feature 001) and later
`zone.ZoneStore` (002), `cache.Cache` (003), `blocklist.Blocklist` and `querylog.QueryLog` (004).
`Stats` is final in `dnsd.listener`.

```python
class ZoneStore:                              # owner: zone (002)
    def lookup(self, name: Name, qtype: int) -> Answer | NoData | NXDomain | NotLocal: ...
    def records(self) -> list[ResourceRecord]: ...          # new list each call
    def add(self, record: ResourceRecord) -> None: ...      # adds, or replaces TTL of identical record
    def remove(self, name: Name, rtype: int) -> int: ...    # number removed
    def make_record(self, name_text: str, type_text: str, ttl: int, value_text: str
                    ) -> ResourceRecord | Invalid: ...      # pure; no state read or written
    def value_text(self, record: ResourceRecord) -> str: ...  # zone-file form of rdata; pure


class Blocklist:                              # owner: blocklist (004)
    def is_blocked(self, name: Name) -> bool: ...
    def domains(self) -> list[Name]: ...                    # listed entries, new list each call
    def add(self, name: Name) -> None: ...                  # idempotent
    def remove(self, name: Name) -> bool: ...               # listed entries only


class Cache:                                  # owner: cache (003)
    def get(self, name: Name, qtype: int) -> Message | None: ...
        # header.rcode and the three sections of the cached reply, TTLs reduced by age; new lists
    def put(self, name: Name, qtype: int, reply: Message) -> None: ...
        # stores only what contract.md § Responses › Cache allows


class Stats:                                  # owner: listener (001)
    def record(self, outcome: Outcome) -> None: ...         # FR-031; listener only
    def snapshot(self) -> dict[str, int]: ...
        # {"queries", "blocked", "cache_hits", "cache_misses"}, read as one consistent set


class QueryLog:                               # owner: querylog (004)
    def append(self, entry: LogEntry) -> None: ...          # listener only
    def recent(self, limit: int) -> list[LogEntry]: ...     # newest first; keeps ≥ 1000 newest
```

### Concurrency rules (FR-028, FR-030; rule 2 is design goal DG-2)

1. Each stateful store has one private `threading.Lock`; every public method takes it for its whole
   body and releases it before returning. The operation is atomic and visible to every call that
   starts after it returns.
2. While holding its lock, a store does in-memory work only: no socket or file I/O, no call to
   another store, no call back into caller code.
3. Methods return new lists or immutable values; callers cannot change a store except through its
   methods.
4. The listener and the handler hold no lock while calling the handler, the network or a store.
5. Exactly one `ServerState` exists; `__main__` builds it and passes the same instance to the
   handler factory, the listener and the admin API (FR-027).

## 4. `dnsd.listener` — serving and entry point

```python
def serve(state: ServerState, handler: Handler) -> None: ...
    # Binds UDP and TCP on state.config.listen and serves forever (FR-005 – FR-017, FR-031).
    # Callers finish all startup loading (and start the admin API, 004) before calling it.
```

`python -m dnsd` (`dnsd/__main__.py`): `--listen`, `--admin`, `--upstream` (`host:port`, split at
the last `:`) and `--zone`, `--blocklist` (paths), all required; argparse defaults for anything
else (spec Clarifications Q1).
