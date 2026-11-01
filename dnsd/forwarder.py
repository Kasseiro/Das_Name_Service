"""Resolution handler and upstream exchange.

Interfaces: specs/001-parser-listener/contracts/interfaces.md § 2 (handler),
specs/002-zone-forwarder/contracts/modules.md. Behaviour: contract.md § Responses.
"""
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
)

_BLOCKED_TTL = 60


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
        # TEMPORARY (T005): replaced by the cache and forwarder branch (T020).
        return Outcome(Message(Header(rcode=SERVFAIL)), "error", False)

    return handle
