"""Resolution-handler interface, shared state and the UDP/TCP listener.

Interfaces: specs/001-parser-listener/contracts/interfaces.md §§ 2-4.
"""
import contextlib
import socket
import socketserver
import struct
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

from dnsd.parser import (
    FORMERR,
    NOTIMP,
    SERVFAIL,
    TYPE_OPT,
    FormErr,
    Header,
    Message,
    Name,
    NotImp,
    ResourceRecord,
    decode_query,
    encode,
    type_to_text,
)

Result = Literal["local", "blocked", "cached", "forwarded", "error"]


# --- resolution handler (contracts § 2)

@dataclass(frozen=True)
class Query:
    message: Message
    client: tuple[str, int]


@dataclass(frozen=True)
class Outcome:
    response: Message
    result: Result
    upstream_asked: bool


Handler = Callable[[Query], Outcome]


def stub_handler(query: Query) -> Outcome:
    """FR-019: SERVFAIL for every query until feature 002 installs the real handler."""
    return Outcome(Message(Header(rcode=SERVFAIL)), "error", False)


# --- shared state (contracts § 3)

@dataclass(frozen=True)
class Config:
    listen: tuple[str, int]
    admin: tuple[str, int]
    upstream: tuple[str, int]
    zone_path: str
    blocklist_path: str


@dataclass(frozen=True)
class LogEntry:
    time: float
    client: str
    name: str
    type: str
    result: Result


@dataclass(frozen=True)
class Answer:
    records: tuple[ResourceRecord, ...]


@dataclass(frozen=True)
class NoData:
    """ZoneStore.lookup: the name exists but has no record of the type."""


@dataclass(frozen=True)
class NXDomain:
    """ZoneStore.lookup: the name does not exist in a local zone."""


@dataclass(frozen=True)
class NotLocal:
    """ZoneStore.lookup: the name is not covered by local data."""


@dataclass(frozen=True)
class Invalid:
    reason: str


@dataclass(frozen=True)
class ServerState:
    config: Config
    zone: Any
    blocklist: Any
    cache: Any
    stats: Any
    log: Any


class Stats:
    """The /stats counters (FR-031); updated by the listener only."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.queries = 0
        self.blocked = 0
        self.cache_hits = 0
        self.cache_misses = 0

    def record(self, outcome: Outcome) -> None:
        with self._lock:
            self.queries += 1
            if outcome.result == "blocked":
                self.blocked += 1
            if outcome.result == "cached":
                self.cache_hits += 1
            if outcome.upstream_asked:
                self.cache_misses += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "queries": self.queries,
                "blocked": self.blocked,
                "cache_hits": self.cache_hits,
                "cache_misses": self.cache_misses,
            }


# --- placeholder stores, replaced by features 002-004 (stateless, no lock)

class PlaceholderZoneStore:
    def lookup(self, name: Name, qtype: int) -> Answer | NoData | NXDomain | NotLocal:
        return NotLocal()

    def records(self) -> list[ResourceRecord]:
        return []

    def add(self, record: ResourceRecord) -> None:
        return None

    def remove(self, name: Name, rtype: int) -> int:
        return 0

    def make_record(self, name_text: str, type_text: str, ttl: int, value_text: str
                    ) -> ResourceRecord | Invalid:
        return Invalid("no zone support")

    def value_text(self, record: ResourceRecord) -> str:
        return ""


class PlaceholderBlocklist:
    def is_blocked(self, name: Name) -> bool:
        return False

    def domains(self) -> list[Name]:
        return []

    def add(self, name: Name) -> None:
        return None

    def remove(self, name: Name) -> bool:
        return False


class PlaceholderCache:
    def get(self, name: Name, qtype: int) -> Message | None:
        return None

    def put(self, name: Name, qtype: int, reply: Message) -> None:
        return None


class PlaceholderQueryLog:
    def append(self, entry: LogEntry) -> None:
        return None

    def recent(self, limit: int) -> list[LogEntry]:
        return []


# --- per-message processing

def _finalise(query: Message, response: Message) -> Message:
    """Overwrite the listener-owned parts of the handler's response (FR-012 - FR-014)."""
    header = replace(
        response.header,
        id=query.header.id,
        qr=True,
        opcode=0,
        rd=query.header.rd,
        ra=True,
        tc=False,
        z=0,
    )
    return Message(
        header,
        list(query.questions),
        _without_opt(response.answers),
        _without_opt(response.authority),
        _without_opt(response.additional),
    )


def _without_opt(records: list[ResourceRecord]) -> list[ResourceRecord]:
    """FR-015: responses never carry an OPT record."""
    return [record for record in records if record.rtype != TYPE_OPT]


def _account(state: ServerState, query: Query, outcome: Outcome, arrival: float) -> None:
    """Count and log one answered valid query (FR-031)."""
    question = query.message.questions[0]
    state.stats.record(outcome)
    state.log.append(LogEntry(
        time=arrival,
        client=query.client[0],
        name=question.name.to_text(),
        type=type_to_text(question.qtype),
        result=outcome.result,
    ))


_UDP_LIMIT = 512
_TCP_LIMIT = 65535


def _servfail_outcome() -> Outcome:
    """The FR-020 replacement for a failed handler call or an unusable Outcome."""
    return Outcome(Message(Header(rcode=SERVFAIL)), "error", False)


def _bare_reply(header: Header, rcode: int) -> bytes:
    """FORMERR/NOTIMP reply: 12-byte header, all counts zero (FR-010)."""
    return encode(Message(Header(
        id=header.id, qr=True, opcode=header.opcode, rd=header.rd, ra=True, rcode=rcode,
    )))


def _call_handler(handler: Handler, query: Query) -> Outcome:
    """Call the handler; any failure becomes the SERVFAIL Outcome (FR-020)."""
    try:
        outcome = handler(query)
    except Exception as exc:  # noqa: BLE001 - FR-020: any handler error must become SERVFAIL
        print(f"dnsd: handler error: {exc!r}", file=sys.stderr)
        return _servfail_outcome()
    if not isinstance(outcome, Outcome):
        print(f"dnsd: handler error: returned {type(outcome).__name__}, not Outcome",
              file=sys.stderr)
        return _servfail_outcome()
    return outcome


def _process(data: bytes, client: tuple[str, int], tcp: bool, state: ServerState,
             handler: Handler) -> bytes | None:
    """Turn one received message into the reply bytes, or None for no reply."""
    arrival = time.time()
    decoded = decode_query(data)
    if isinstance(decoded, NotImp):
        return _bare_reply(decoded.header, NOTIMP)
    if isinstance(decoded, FormErr):
        return _bare_reply(decoded.header, FORMERR)
    if not isinstance(decoded, Message):
        return None
    query = Query(decoded, client)
    outcome = _call_handler(handler, query)
    try:
        finalised = _finalise(query.message, outcome.response)
        wire = encode(finalised)
    except Exception as exc:  # noqa: BLE001 - FR-020: an unencodable Outcome must become SERVFAIL
        print(f"dnsd: handler error: unusable response: {exc!r}", file=sys.stderr)
        outcome = _servfail_outcome()
        finalised = _finalise(query.message, outcome.response)
        wire = encode(finalised)
    if not tcp and len(wire) > _UDP_LIMIT:
        # FR-016: header and question only, TC=1.
        wire = encode(Message(replace(finalised.header, tc=True), list(finalised.questions)))
    elif tcp and len(wire) > _TCP_LIMIT:
        # FR-017: does not fit the 2-byte length prefix.
        print(f"dnsd: response of {len(wire)} bytes too large for TCP, answering SERVFAIL",
              file=sys.stderr)
        outcome = _servfail_outcome()
        wire = encode(_finalise(query.message, outcome.response))
    _account(state, query, outcome, arrival)
    return wire


# --- transports

def _report(client: tuple[str, int], exc: Exception) -> None:
    print(f"dnsd: error handling message from {client[0]}: {exc!r}", file=sys.stderr)


class _UDPRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        try:
            data, sock = self.request
            reply = _process(data, self.client_address, False,
                             self.server.state, self.server.handler)
            if reply is not None:
                with contextlib.suppress(OSError):
                    sock.sendto(reply, self.client_address)
        except Exception as exc:  # noqa: BLE001 - FR-011: one bad message must not stop the server
            _report(self.client_address, exc)


class _UDPServer(socketserver.ThreadingUDPServer):
    daemon_threads = True
    max_packet_size = 65535

    def __init__(self, address: tuple[str, int], state: ServerState, handler: Handler) -> None:
        self.state = state
        self.handler = handler
        super().__init__(address, _UDPRequestHandler)


_TCP_IDLE_TIMEOUT = 5.0


def _recv_exact(sock: socket.socket, n: int, deadline: float) -> bytes | None:
    """Read exactly n bytes before the deadline; None on timeout, EOF or error."""
    data = b""
    while len(data) < n:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            sock.settimeout(remaining)
            chunk = sock.recv(n - len(data))
        except OSError:
            return None
        if not chunk:
            return None
        data += chunk
    return data


class _TCPRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        try:
            deadline = time.monotonic() + _TCP_IDLE_TIMEOUT
            prefix = _recv_exact(self.request, 2, deadline)
            if prefix is None:
                return
            data = _recv_exact(self.request, struct.unpack("!H", prefix)[0], deadline)
            if data is None:
                return
            reply = _process(data, self.client_address, True,
                             self.server.state, self.server.handler)
            if reply is not None:
                with contextlib.suppress(OSError):
                    self.request.settimeout(_TCP_IDLE_TIMEOUT)  # own write timeout, not the read leftover
                    self.request.sendall(struct.pack("!H", len(reply)) + reply)
        except Exception as exc:  # noqa: BLE001 - FR-011: one bad message must not stop the server
            _report(self.client_address, exc)


class _TCPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], state: ServerState, handler: Handler) -> None:
        self.state = state
        self.handler = handler
        super().__init__(address, _TCPRequestHandler)


def serve(state: ServerState, handler: Handler) -> None:
    """Bind UDP and TCP on state.config.listen and serve forever."""
    tcp_server = _TCPServer(state.config.listen, state, handler)
    udp_server = _UDPServer(state.config.listen, state, handler)
    threading.Thread(target=tcp_server.serve_forever, daemon=True).start()
    udp_server.serve_forever()
