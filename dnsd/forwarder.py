"""Resolution handler and upstream exchange.

Interfaces: specs/001-parser-listener/contracts/interfaces.md § 2 (handler),
specs/002-zone-forwarder/contracts/modules.md. Behaviour: contract.md § Responses.
"""
import secrets
import socket
import struct
import time
from ipaddress import IPv4Address, IPv6Address

from dnsd.listener import Answer, Handler, NoData, NXDomain, Outcome, Query, ServerState
from dnsd.parser import (
    AAAA,
    CLASS_IN,
    NXDOMAIN,
    SERVFAIL,
    TYPE_A,
    TYPE_AAAA,
    A,
    Header,
    Message,
    Question,
    ResourceRecord,
    decode_message,
    encode,
)

_BLOCKED_TTL = 60

# --- upstream exchange (contract.md § Responses › Forwarded queries; research R-7)

_BUDGET = 2.0             # seconds for the whole exchange, TCP retry included
_PORT_LOW = 1024
_PORT_SPAN = 65536 - _PORT_LOW
_BIND_ATTEMPTS = 5


def _random_id() -> int:
    """Principle VI: a fresh 16-bit query ID from secrets for every upstream query."""
    return secrets.randbelow(65536)


def _random_port() -> int:
    """Principle VI: a fresh UDP source port (1024-65535) from secrets for every query."""
    return _PORT_LOW + secrets.randbelow(_PORT_SPAN)


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("upstream budget exhausted")
    return remaining


def _query(question: Question) -> tuple[int, bytes]:
    qid = _random_id()
    return qid, encode(Message(Header(id=qid, rd=True), [question]))


def _counting(data: bytes, qid: int, question: Question) -> Message | None:
    """A reply counts only with QR=1, the ID sent and the same question (spec FR-017)."""
    reply = decode_message(data)
    if (isinstance(reply, Message) and reply.header.qr and reply.header.id == qid
            and reply.questions == [question]):
        return reply
    return None


def _udp_socket() -> socket.socket:
    for attempt in range(1, _BIND_ATTEMPTS + 1):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind(("", _random_port()))
        except OSError:
            sock.close()
            if attempt == _BIND_ATTEMPTS:
                raise
        else:
            return sock
    raise OSError("no free source port")


def _exchange_udp(upstream: tuple[str, int], question: Question, deadline: float) -> Message:
    qid, wire = _query(question)
    with _udp_socket() as sock:
        sock.connect(upstream)  # the kernel then delivers only datagrams from the upstream
        sock.send(wire)
        while True:
            sock.settimeout(_remaining(deadline))
            reply = _counting(sock.recv(65535), qid, question)
            if reply is not None:
                return reply


def _recv_exact(sock: socket.socket, n: int, deadline: float) -> bytes:
    data = b""
    while len(data) < n:
        sock.settimeout(_remaining(deadline))
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("upstream closed the TCP connection")
        data += chunk
    return data


def _exchange_tcp(upstream: tuple[str, int], question: Question,
                  deadline: float) -> Message | None:
    qid, wire = _query(question)  # a new random ID for the retry, too
    with socket.create_connection(upstream, timeout=_remaining(deadline)) as sock:
        sock.sendall(struct.pack("!H", len(wire)) + wire)
        (length,) = struct.unpack("!H", _recv_exact(sock, 2, deadline))
        return _counting(_recv_exact(sock, length, deadline), qid, question)


def exchange(upstream: tuple[str, int], question: Question) -> Message | None:
    """One upstream exchange within 2 s (spec FR-015 - FR-019). None on timeout or failure."""
    deadline = time.monotonic() + _BUDGET
    try:
        reply = _exchange_udp(upstream, question, deadline)
        if reply.header.tc:
            return _exchange_tcp(upstream, question, deadline)
    except OSError:
        return None
    return reply


# --- resolution handler

def _blocked(question: Question) -> Message:
    """contract.md § Responses rows 4-6 (spec FR-022). AA=0."""
    if question.qtype == TYPE_A:
        rdata: A | AAAA = A(IPv4Address(0))
    elif question.qtype == TYPE_AAAA:
        rdata = AAAA(IPv6Address(0))
    else:
        return Message(Header(rcode=NXDOMAIN))
    record = ResourceRecord(question.name, question.qtype, CLASS_IN, _BLOCKED_TTL, rdata)
    return Message(Header(), answers=[record])


def _relayed(reply: Message) -> Message:
    """RCODE and the three sections of an upstream or cached reply, AA=0, new lists."""
    return Message(Header(rcode=reply.header.rcode), [], list(reply.answers),
                   list(reply.authority), list(reply.additional))


def make_handler(state: ServerState) -> Handler:
    """The real resolution handler (spec FR-020 - FR-025), bound to the one ServerState."""

    def handle(query: Query) -> Outcome:
        question = query.message.questions[0]
        local = state.zone.lookup(question.name, question.qtype)
        if isinstance(local, Answer):
            return Outcome(Message(Header(aa=True), answers=list(local.records)), "local", False)
        if isinstance(local, NoData):
            return Outcome(Message(Header(aa=True)), "local", False)
        if isinstance(local, NXDomain):
            return Outcome(Message(Header(aa=True, rcode=NXDOMAIN)), "local", False)
        if state.blocklist.is_blocked(question.name):
            return Outcome(_blocked(question), "blocked", False)
        cached = state.cache.get(question.name, question.qtype)
        if cached is not None:
            return Outcome(_relayed(cached), "cached", False)
        reply = exchange(state.config.upstream, question)
        if reply is None:
            return Outcome(Message(Header(rcode=SERVFAIL)), "error", True)
        state.cache.put(question.name, question.qtype, reply)
        result = "error" if reply.header.rcode == SERVFAIL else "forwarded"  # spec Q1
        return Outcome(_relayed(reply), result, True)

    return handle
