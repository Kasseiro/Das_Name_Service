"""Forwarder: queries that are neither local nor blocked go to the upstream.

Every test uses the fake upstream from fake_upstream.py. Each test uses its own
names, so nothing here depends on what the cache does with an earlier answer.
"""
import itertools
import time

import dns.flags
import dns.message
import dns.rcode
import dns.rrset
import pytest
from helpers import addresses, log_results, records

SERVFAIL_WAIT = 3.5  # the contract's 2 s upstream timeout plus slack


def assert_forwarded_flags(response):
    assert not response.flags & dns.flags.AA
    assert response.flags & dns.flags.RA


# --- answers as upstream

def test_answer_is_relayed(server, upstream):
    """contract.md, Responses: anything else -> RCODE and answer as upstream, AA=0"""
    upstream.set_answer("www.example.org.", "A", 300, "192.0.2.1")
    response = server.udp("www.example.org.", "A")
    assert response.rcode() == dns.rcode.NOERROR
    assert records(response.answer) == {("www.example.org", "A", 300, "192.0.2.1")}
    assert_forwarded_flags(response)


def test_several_records_are_relayed(server, upstream):
    """contract.md, Forwarded queries: the answer section is that of the upstream reply"""
    upstream.set_answer("multi.example.org.", "A", 120, "192.0.2.1", "192.0.2.2", "192.0.2.3")
    response = server.udp("multi.example.org.", "A")
    assert records(response.answer) == {("multi.example.org", "A", 120, f"192.0.2.{i}") for i in (1, 2, 3)}


@pytest.mark.parametrize(
    "rdtype, value",
    [
        ("AAAA", "2001:db8::1"),
        ("CNAME", "target.example.org."),
        ("TXT", '"v=spf1 -all"'),
        ("MX", "10 mail.example.org."),
        ("NS", "ns1.example.org."),
    ],
)
def test_other_types_are_relayed(server, upstream, rdtype, value):
    """contract.md, Scope: everything else forwarded; Forwarded queries: the answer section is that of the upstream reply"""
    upstream.set_answer("types.example.org.", rdtype, 200, value)
    response = server.udp("types.example.org.", rdtype)
    assert response.rcode() == dns.rcode.NOERROR
    assert records(response.answer) == {("types.example.org", rdtype, 200, value.lower())}
    assert_forwarded_flags(response)


def test_nxdomain_is_relayed(server, upstream):
    """contract.md, Forwarded queries: RCODE is that of the upstream reply"""
    response = server.udp("nowhere.example.org.", "A")
    assert response.rcode() == dns.rcode.NXDOMAIN
    assert response.answer == []
    assert_forwarded_flags(response)


def test_authority_and_additional_are_relayed(server, upstream):
    """contract.md, Forwarded queries: the authority and additional sections are those of the upstream reply"""
    upstream.set_answer("deleg.example.org.", "A", 300, "192.0.2.9")
    upstream.authority = [dns.rrset.from_text("example.org.", 600, "IN", "NS", "ns1.example.org.")]
    upstream.additional = [dns.rrset.from_text("ns1.example.org.", 600, "IN", "A", "192.0.2.53")]
    response = server.udp("deleg.example.org.", "A")
    assert records(response.answer) == {("deleg.example.org", "A", 300, "192.0.2.9")}
    assert records(response.authority) == {("example.org", "NS", 600, "ns1.example.org.")}
    assert records(response.additional) == {("ns1.example.org", "A", 600, "192.0.2.53")}


def test_nxdomain_authority_is_relayed(server, upstream):
    """contract.md, Forwarded queries: RCODE and the authority section are those of the upstream reply"""
    soa = "ns1.example.org. hostmaster.example.org. 2026101101 7200 3600 1209600 300"
    upstream.authority = [dns.rrset.from_text("example.org.", 300, "IN", "SOA", soa)]
    response = server.udp("absent.example.org.", "A")
    assert response.rcode() == dns.rcode.NXDOMAIN
    assert records(response.authority) == {("example.org", "SOA", 300, soa)}


def test_response_carries_the_clients_id_and_question(server, upstream):
    """contract.md, Responses: in every response the ID and the question are copied from the query"""
    upstream.set_answer("ident.example.org.", "A", 300, "192.0.2.4")
    query = dns.message.make_query("Ident.Example.ORG.", "A", id=0xBEEF).to_wire()
    wire = server.udp_raw(query)
    assert wire is not None, "no response"
    assert wire[:2] == b"\xbe\xef"
    assert wire[12 : len(query)] == query[12:]
    assert addresses(dns.message.from_wire(wire)) == ["192.0.2.4"]


def test_forwarded_answer_over_tcp(server, upstream):
    """contract.md, TCP: the same rules apply as over UDP"""
    upstream.set_answer("tcp.example.org.", "A", 300, "192.0.2.5")
    response = server.tcp("tcp.example.org.", "A")
    assert records(response.answer) == {("tcp.example.org", "A", 300, "192.0.2.5")}
    assert_forwarded_flags(response)


# --- what reaches the upstream

def test_upstream_receives_the_question(server, upstream):
    """contract.md, Scope: everything else forwarded; Command line: --upstream"""
    upstream.set_answer("asked.example.org.", "AAAA", 300, "2001:db8::2")
    server.udp("asked.example.org.", "AAAA")
    assert [(str(q.name).lower(), q.rdtype) for q in upstream.queries] == [("asked.example.org.", "AAAA")]


def test_name_outside_every_local_suffix_is_forwarded(server, upstream):
    """contract.md, Zone file, Local zone suffix: only names under a suffix derived from the records are local"""
    upstream.set_answer("other.lan.", "A", 300, "192.0.2.6")
    upstream.set_answer("lan.", "A", 300, "192.0.2.7")
    assert addresses(server.udp("other.lan.", "A")) == ["192.0.2.6"]
    assert addresses(server.udp("lan.", "A")) == ["192.0.2.7"]
    assert not server.udp("other.lan.", "A").flags & dns.flags.AA


def test_blocked_names_are_not_forwarded(server, upstream):
    """contract.md, Responses: blocked domains are answered by the server, only "anything else" goes upstream"""
    for rdtype in ("A", "AAAA", "TXT"):
        server.udp("sub.ads.example.com.", rdtype)
    assert upstream.queries == []


# --- upstream failures

def test_reply_within_two_seconds_is_used(server, upstream):
    """contract.md, Forwarded queries: SERVFAIL only if no matching reply arrives within 2 seconds"""
    upstream.set_answer("slow.example.org.", "A", 300, "192.0.2.8")
    upstream.delay = 1.0
    response = server.udp("slow.example.org.", "A", timeout=SERVFAIL_WAIT)
    assert response.rcode() == dns.rcode.NOERROR
    assert addresses(response) == ["192.0.2.8"]


def test_servfail_when_upstream_is_silent(server, upstream):
    """contract.md, Forwarded queries: if no matching reply arrives within 2 seconds the server answers SERVFAIL"""
    upstream.set_answer("silent.example.org.", "A", 300, "192.0.2.10")
    upstream.mode = "silent"
    started = time.monotonic()
    response = server.udp("silent.example.org.", "A", qid=0x5151, timeout=SERVFAIL_WAIT)
    assert time.monotonic() - started <= SERVFAIL_WAIT
    assert response.rcode() == dns.rcode.SERVFAIL
    assert response.id == 0x5151
    assert response.answer == []
    assert response.flags & dns.flags.RA
    assert len(upstream.queries) >= 1


def test_reply_with_wrong_id_is_ignored(server, upstream):
    """contract.md, Forwarded queries: an upstream reply counts only if its ID matches, any other reply is ignored"""
    upstream.set_answer("spoofed.example.org.", "A", 300, "192.0.2.66")
    upstream.mode = "wrong_id"
    response = server.udp("spoofed.example.org.", "A", timeout=SERVFAIL_WAIT)
    assert response.rcode() == dns.rcode.SERVFAIL
    assert addresses(response) == []


def test_server_keeps_working_after_upstream_failure(server, upstream):
    """contract.md, Responses: the server must never crash on input; Forwarded queries: SERVFAIL on timeout"""
    upstream.mode = "silent"
    assert server.udp("down.example.org.", "A", timeout=SERVFAIL_WAIT).rcode() == dns.rcode.SERVFAIL
    upstream.mode = "normal"
    upstream.set_answer("up.example.org.", "A", 300, "192.0.2.11")
    assert addresses(server.udp("up.example.org.", "A")) == ["192.0.2.11"]
    assert addresses(server.udp("ads.example.com.", "A")) == ["0.0.0.0"]
    assert addresses(server.udp("nas.home.lan.", "A")) == ["192.168.1.10"]


def test_servfail_over_tcp(server, upstream):
    """contract.md, TCP: the same rules apply as over UDP; Forwarded queries: SERVFAIL on timeout"""
    upstream.mode = "silent"
    response = server.tcp("silent-tcp.example.org.", "A", timeout=SERVFAIL_WAIT)
    assert response.rcode() == dns.rcode.SERVFAIL


# --- large upstream answers

def test_client_udp_reply_never_exceeds_512_bytes(server, upstream):
    """contract.md, Truncation: a UDP response is at most 512 bytes, and has TC=1 if it was cut"""
    upstream.mode = "big"
    wire = server.udp_raw(dns.message.make_query("large.example.org.", "A").to_wire(), timeout=SERVFAIL_WAIT)
    assert wire is not None, "no response"
    assert len(wire) <= 512
    response = dns.message.from_wire(wire)
    # The contract leaves an upstream UDP reply over 512 bytes unspecified. A
    # server that accepts it must truncate with TC=1; one that does not has no
    # usable reply and answers SERVFAIL.
    assert response.flags & dns.flags.TC or response.rcode() == dns.rcode.SERVFAIL


def test_truncated_upstream_reply_is_retried_over_tcp(server, upstream):
    """contract.md, Forwarded queries: if the upstream reply has TC=1, the server repeats the query over TCP and uses that reply"""
    upstream.mode = "truncated"
    response = server.tcp("huge.example.org.", "A", timeout=SERVFAIL_WAIT)
    assert response.rcode() == dns.rcode.NOERROR
    assert not response.flags & dns.flags.TC
    assert records(response.answer) == {("huge.example.org", "A", 60, f"198.51.100.{i}") for i in range(1, 41)}
    assert [(str(q.name).lower(), q.rdtype) for q in upstream.queries] == [("huge.example.org.", "A")]
    assert [(str(q.name).lower(), q.rdtype) for q in upstream.tcp_queries] == [("huge.example.org.", "A")]


def test_answer_fetched_over_tcp_is_truncated_for_a_udp_client(server, upstream):
    """contract.md, Forwarded queries: TCP retry; Truncation: a UDP response over 512 bytes is cut with TC=1"""
    upstream.mode = "truncated"
    wire = server.udp_raw(dns.message.make_query("huge-udp.example.org.", "A").to_wire(), timeout=SERVFAIL_WAIT)
    assert wire is not None, "no response"
    assert len(wire) <= 512
    response = dns.message.from_wire(wire)
    assert response.flags & dns.flags.TC
    assert response.rcode() == dns.rcode.NOERROR
    assert len(upstream.tcp_queries) == 1


# --- upstream query ID and source port

def _forward_twenty(server, upstream):
    for i in range(20):
        server.udp(f"rand{i}.example.org.", "A", qid=0x0707)
    queries = upstream.queries
    assert len(queries) == 20
    return queries


def test_upstream_query_ids_are_random(server, upstream):
    """contract.md, Forwarded queries: the upstream query ID is chosen at random, not fixed, counted up or copied from the client; RFC 5452"""
    ids = [q.id for q in _forward_twenty(server, upstream)]
    assert len(set(ids)) >= 18, f"IDs repeat: {ids}"
    assert ids.count(0x0707) <= 1, "upstream queries carry the client's ID"
    steps = {(b - a) & 0xFFFF for a, b in itertools.pairwise(ids)}
    assert len(steps) > 3, f"IDs are counted up: {ids}"


def test_upstream_source_ports_are_random(server, upstream):
    """contract.md, Forwarded queries: the upstream source port is chosen at random for each query; RFC 5452"""
    ports = [q.source_port for q in _forward_twenty(server, upstream)]
    assert len(set(ports)) >= 10, f"source ports repeat: {ports}"
    steps = {b - a for a, b in itertools.pairwise(ports)}
    assert len(steps) > 3, f"source ports are counted up: {ports}"


@pytest.mark.parametrize("rcode", [dns.rcode.REFUSED, dns.rcode.SERVFAIL, dns.rcode.NOTIMP])
def test_other_upstream_rcodes_are_relayed(server, upstream, rcode):
    """contract.md, Forwarded queries: RCODE is that of the upstream reply"""
    upstream.rcode = rcode
    response = server.udp("refused.example.org.", "A")
    assert response.rcode() == rcode
    assert response.answer == []
    assert_forwarded_flags(response)


# --- log

def test_forwarded_query_is_logged_as_forwarded(server, admin, upstream):
    """contract.md, Admin API, /log: result "forwarded" for queries answered by the upstream"""
    upstream.set_answer("logged.example.org.", "A", 300, "192.0.2.12")
    server.udp("logged.example.org.", "A")
    assert log_results(admin, 1) == [("logged.example.org", "forwarded")]


def test_servfail_is_logged_as_error(server, admin, upstream):
    """contract.md, Admin API, /log: result "error" for SERVFAIL"""
    upstream.mode = "silent"
    server.udp("failed.example.org.", "A", timeout=SERVFAIL_WAIT)
    assert log_results(admin, 1) == [("failed.example.org", "error")]
