"""Resolution handler and upstream exchange.

Interfaces: specs/001-parser-listener/contracts/interfaces.md § 2 (handler),
specs/002-zone-forwarder/contracts/modules.md. Behaviour: contract.md § Responses.
"""
from dnsd.listener import Answer, Handler, NoData, NXDomain, Outcome, Query, ServerState
from dnsd.parser import NXDOMAIN, SERVFAIL, Header, Message


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
        # TEMPORARY (T005): replaced by the blocked branch (T015) and the forwarder (T020).
        return Outcome(Message(Header(rcode=SERVFAIL)), "error", False)

    return handle
