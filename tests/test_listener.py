"""Listener: framing, header fields, truncation and malformed input.

Blocked names from fixtures/blocklist.txt are used wherever any answerable
query will do, so these tests do not depend on the zone or the forwarder.
The exception is truncation, which needs a large answer and takes it from
fixtures/zone.txt.
"""
import socket
import struct

import dns.flags
import dns.message
import dns.rcode
import pytest

BLOCKED = "ads.example.com."
BIG_NAME = "big.home.lan."
BIG_RECORDS = 40  # A records for BIG_NAME in fixtures/zone.txt

QR = 0x8000
TC = 0x0200
RA = 0x0080
RCODE = 0x000F

QUESTION = b"\x03ads\x07example\x03com\x00\x00\x01\x00\x01"
TYPE_CLASS = b"\x00\x01\x00\x01"


def header(wire):
    """(id, flags, qdcount, ancount, nscount, arcount) of a raw message."""
    return struct.unpack("!6H", wire[:12])


def raw_header(qid, qdcount=1, flags=0x0100):
    return struct.pack("!6H", qid, flags, qdcount, 0, 0, 0)


def tcp_exchange(addr, payload, timeout=2.0):
    """Send one length-prefixed message. Returns (bytes received, connection closed by server)."""
    received = b""
    with socket.create_connection(addr, timeout=timeout) as sock:
        sock.sendall(struct.pack("!H", len(payload)) + payload)
        try:
            while True:
                chunk = sock.recv(65535)
                if not chunk:
                    return received, True
                received += chunk
                if len(received) >= 2 and len(received) >= 2 + struct.unpack("!H", received[:2])[0]:
                    return received, False
        except ConnectionError:
            return received, True
        except TimeoutError:
            return received, False


# Packets that must get FORMERR: the header parses, the rest does not.
FORMERR_PACKETS = {
    "no question after header": raw_header(0x2B67),
    "name cut off inside a label": raw_header(0x2B67) + b"\x03ads\x07exam",
    "name without terminating zero": raw_header(0x2B67) + b"\x03ads\x07example\x03com",
    "name complete, type and class missing": raw_header(0x2B67) + b"\x03ads\x07example\x03com\x00",
    "name complete, class missing": raw_header(0x2B67) + b"\x03ads\x07example\x03com\x00\x00\x01",
    "label length runs past the end": raw_header(0x2B67) + b"\x3fabc",
    "label over 63 bytes": raw_header(0x2B67) + b"\x40" + b"a" * 64 + b"\x00" + TYPE_CLASS,
    "name over 255 bytes": raw_header(0x2B67) + (b"\x3f" + b"a" * 63) * 5 + b"\x00" + TYPE_CLASS,
    "compression pointer to itself": raw_header(0x2B67) + b"\xc0\x0c" + TYPE_CLASS,
    "compression pointers in a loop": raw_header(0x2B67) + b"\xc0\x0e\xc0\x0c" + TYPE_CLASS,
    "compression pointer outside the packet": raw_header(0x2B67) + b"\xc0\xff" + TYPE_CLASS,
    "QDCOUNT=0": raw_header(0x2B67, qdcount=0),
    "QDCOUNT=2 with two questions": raw_header(0x2B67, qdcount=2) + QUESTION + QUESTION,
    "QDCOUNT=50 with one question": raw_header(0x2B67, qdcount=50) + QUESTION,
}

# Opcode sits in bits 11-14 of the flags word.
NOTIMP_PACKETS = {
    "opcode 1 (IQUERY)": raw_header(0x2B67, flags=0x0900) + QUESTION,
    "opcode 2 (STATUS)": raw_header(0x2B67, flags=0x1100) + QUESTION,
    "opcode 15": raw_header(0x2B67, flags=0x7900) + QUESTION,
}


def assert_bare_error(wire, rcode):
    """contract: a FORMERR or NOTIMP reply is a bare 12-byte header."""
    assert wire is not None, "no response"
    assert len(wire) == 12
    qid, flags, *counts = header(wire)
    assert qid == 0x2B67
    assert flags & QR
    assert flags & RA
    assert flags & RCODE == rcode
    assert counts == [0, 0, 0, 0]


# --- header fields

@pytest.mark.parametrize("qid", [0, 1, 0x1234, 0xFFFF])
def test_response_echoes_id(server, qid):
    """contract.md, Responses: the ID is copied from the query; RFC 1035 4.1.1"""
    response = server.udp(BLOCKED, "A", qid=qid)
    assert response.id == qid


@pytest.mark.parametrize("rdtype", ["A", "AAAA", "TXT"])
def test_response_echoes_question(server, rdtype):
    """contract.md, Responses: the question section is copied from the query; RFC 1035 4.1.2"""
    query = dns.message.make_query("sub." + BLOCKED, rdtype)
    wire = server.udp_raw(query.to_wire())
    assert wire is not None, "no response"
    response = dns.message.from_wire(wire)
    assert response.question == query.question


def test_response_preserves_case_of_question_name(server):
    """contract.md, Responses: the question is copied unchanged, including the case of the name"""
    query = dns.message.make_query("SuB.aDs.ExAmPlE.cOm.", "A").to_wire()
    wire = server.udp_raw(query)
    assert wire is not None, "no response"
    assert header(wire)[2] == 1
    assert wire[12 : len(query)] == query[12:]


RESPONSE_KINDS = {
    "UDP, blocked A (NOERROR)": lambda s: s.udp_raw(dns.message.make_query(BLOCKED, "A").to_wire()),
    "UDP, blocked AAAA (NOERROR)": lambda s: s.udp_raw(dns.message.make_query(BLOCKED, "AAAA").to_wire()),
    "UDP, blocked TXT (NXDOMAIN)": lambda s: s.udp_raw(dns.message.make_query(BLOCKED, "TXT").to_wire()),
    "TCP, blocked A": lambda s: s.tcp_raw(dns.message.make_query(BLOCKED, "A").to_wire()),
    "UDP, FORMERR": lambda s: s.udp_raw(FORMERR_PACKETS["name cut off inside a label"]),
    "UDP, NOTIMP": lambda s: s.udp_raw(NOTIMP_PACKETS["opcode 2 (STATUS)"]),
}


@pytest.mark.parametrize("kind", RESPONSE_KINDS)
def test_qr_set_on_every_response(server, kind):
    """contract.md, Responses: QR is 1; RFC 1035 4.1.1"""
    wire = RESPONSE_KINDS[kind](server)
    assert wire is not None and len(wire) >= 12, "no response"
    assert header(wire)[1] & QR


@pytest.mark.parametrize("kind", RESPONSE_KINDS)
def test_ra_set_on_every_response(server, kind):
    """contract.md, Responses: RA is set in every response"""
    wire = RESPONSE_KINDS[kind](server)
    assert wire is not None and len(wire) >= 12, "no response"
    assert header(wire)[1] & RA


# --- TCP

def test_tcp_query_with_length_prefix(server):
    """contract.md, TCP: two-byte length prefix in both directions; RFC 1035 4.2.2"""
    query = dns.message.make_query(BLOCKED, "A")
    received, _closed = tcp_exchange(server.dns_addr, query.to_wire())
    assert len(received) >= 2, "no response"
    (length,) = struct.unpack("!H", received[:2])
    assert len(received) == 2 + length, "length prefix does not match the message"
    response = dns.message.from_wire(received[2:])
    assert response.id == query.id
    assert response.question == query.question
    assert response.rcode() == dns.rcode.NOERROR
    assert [rdata.address for rrset in response.answer for rdata in rrset] == ["0.0.0.0"]


def test_tcp_formerr(server):
    """contract.md, TCP: the same rules apply as over UDP"""
    assert_bare_error(server.tcp_raw(FORMERR_PACKETS["name cut off inside a label"]), dns.rcode.FORMERR)


def test_tcp_notimp(server):
    """contract.md, TCP: the same rules apply as over UDP"""
    assert_bare_error(server.tcp_raw(NOTIMP_PACKETS["opcode 2 (STATUS)"]), dns.rcode.NOTIMP)


@pytest.mark.parametrize(
    "payload",
    [raw_header(0x2B67)[:5], raw_header(0x2B67)[:11], raw_header(0x2B67, flags=0x8180) + QUESTION],
    ids=["5 bytes", "11 bytes", "QR=1"],
)
def test_tcp_closes_connection_where_udp_gives_no_reply(server, payload):
    """contract.md, TCP: where UDP gives no reply, the server closes the connection"""
    received, closed = tcp_exchange(server.dns_addr, payload)
    assert received == b""
    assert closed, "connection still open after 2 s"
    assert server.tcp(BLOCKED, "A").rcode() == dns.rcode.NOERROR


# --- truncation and EDNS

def test_udp_response_over_512_bytes_is_truncated(server):
    """contract.md, Truncation: at most 512 bytes, TC=1; RFC 1035 4.2.1"""
    query = dns.message.make_query(BIG_NAME, "A")
    wire = server.udp_raw(query.to_wire())
    assert wire is not None, "no response"
    assert len(wire) <= 512
    qid, flags = header(wire)[:2]
    assert qid == query.id
    assert flags & TC


def test_truncated_response_keeps_question_and_whole_records(server):
    """contract.md, Truncation: keeps the question and contains only whole records"""
    query = dns.message.make_query(BIG_NAME, "A")
    wire = server.udp_raw(query.to_wire())
    assert wire is not None, "no response"
    response = dns.message.from_wire(wire)  # fails on a cut-off record or leftover bytes
    assert response.question == query.question


def test_truncated_answer_is_complete_over_tcp(server):
    """contract.md, Truncation: TC is never set over TCP; RFC 1035 4.2.2"""
    response = server.tcp(BIG_NAME, "A")
    assert len(response.to_wire(max_size=65535)) > 512, "fixture answer is not large enough to need truncation"
    assert not response.flags & dns.flags.TC
    assert sum(len(rrset) for rrset in response.answer) == BIG_RECORDS


def test_edns_does_not_raise_udp_limit(server):
    """contract.md, Malformed and unusual queries: an OPT record has no effect, the 512-byte limit always applies"""
    query = dns.message.make_query(BIG_NAME, "A", use_edns=0, payload=4096)
    wire = server.udp_raw(query.to_wire())
    assert wire is not None, "no response"
    assert len(wire) <= 512
    assert header(wire)[1] & TC


def test_query_with_opt_record_is_answered_without_one(server):
    """contract.md, Malformed and unusual queries: records after the question are ignored, responses never carry OPT"""
    query = dns.message.make_query(BLOCKED, "A", use_edns=0, payload=4096)
    wire = server.udp_raw(query.to_wire())
    assert wire is not None, "no response"
    response = dns.message.from_wire(wire)
    assert response.rcode() == dns.rcode.NOERROR
    assert [rdata.address for rrset in response.answer for rdata in rrset] == ["0.0.0.0"]
    assert response.edns == -1, "response carries an OPT record"


# --- malformed and unusual queries

@pytest.mark.parametrize("case", FORMERR_PACKETS)
def test_formerr(server, case):
    """contract.md, Malformed and unusual queries: QDCOUNT other than 1 or unparseable question -> FORMERR, bare header"""
    assert_bare_error(server.udp_raw(FORMERR_PACKETS[case]), dns.rcode.FORMERR)


@pytest.mark.parametrize("case", NOTIMP_PACKETS)
def test_notimp_for_other_opcodes(server, case):
    """contract.md, Malformed and unusual queries: opcode other than 0 -> NOTIMP, bare header"""
    assert_bare_error(server.udp_raw(NOTIMP_PACKETS[case]), dns.rcode.NOTIMP)


def _no_udp_reply(server, payloads):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for payload in payloads:
            sock.sendto(payload, server.dns_addr)
        sock.settimeout(1.0)
        try:
            return sock.recvfrom(65535)[0]
        except (TimeoutError, ConnectionError):
            return None


def test_no_reply_to_packets_shorter_than_a_header(server):
    """contract.md, Malformed and unusual queries: fewer than 12 bytes -> no reply"""
    full_header = raw_header(0x7A7A)
    reply = _no_udp_reply(server, [full_header[:size] for size in range(12)])
    assert reply is None, f"got a {len(reply)} byte reply to a packet under 12 bytes"
    assert server.proc.poll() is None, "server exited"
    assert server.udp(BLOCKED, "A").rcode() == dns.rcode.NOERROR


def test_no_reply_to_packets_with_qr_set(server):
    """contract.md, Malformed and unusual queries: QR=1 -> no reply"""
    reply = _no_udp_reply(server, [raw_header(0x7A7A, flags=0x8180) + QUESTION, raw_header(0x7A7A, flags=0x8000) + QUESTION])
    assert reply is None, f"got a {len(reply)} byte reply to a packet with QR=1"
    assert server.udp(BLOCKED, "A").rcode() == dns.rcode.NOERROR
