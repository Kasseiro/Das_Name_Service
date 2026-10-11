"""Fuzzer: the server must survive arbitrary input and keep answering.

The packet stream is fully determined by SEED, so a failure can be replayed:
packets(SEED)[index] is the packet named in the failure message.
"""
import random
import select
import socket
import struct

import dns.message
import dns.rcode

SEED = 1035
PACKETS = 2000
CHECK_EVERY = 100
PACE = 0.002  # seconds to wait for a reply to each fuzz packet

CANARY = "ads.example.com."  # blocked in fixtures/blocklist.txt
NAMES = [
    "ads.example.com.",
    "sub.tracker.test.",
    "nas.home.lan.",
    "missing.home.lan.",
    "fuzz.example.org.",
    "a.very.long.name.with.many.labels.example.org.",
]
TYPES = ["A", "AAAA", "CNAME", "TXT", "MX", "NS", "SOA", "ANY"]

QUESTION = b"\x03ads\x07example\x03com\x00\x00\x01\x00\x01"
TYPE_CLASS = b"\x00\x01\x00\x01"


def _header(rng, qdcount=1, flags=0x0100, ancount=0, nscount=0, arcount=0):
    return struct.pack("!6H", rng.randrange(65536), flags, qdcount, ancount, nscount, arcount)


# Each entry builds one packet; the offsets assume the question starts at byte 12.
HANDCRAFTED = {
    "compression pointer pointing to itself": lambda r: _header(r) + b"\xc0\x0c" + TYPE_CLASS,
    "two compression pointers pointing at each other": lambda r: _header(r) + b"\xc0\x0e\xc0\x0c" + TYPE_CLASS,
    "label followed by a pointer back to that label": lambda r: _header(r) + b"\x03abc\xc0\x0c" + TYPE_CLASS,
    "compression pointer past the end of the packet": lambda r: _header(r) + b"\xc0\xff" + TYPE_CLASS,
    "64-byte label": lambda r: _header(r) + b"\x40" + b"a" * 64 + b"\x00" + TYPE_CLASS,
    "name longer than 255 bytes": lambda r: _header(r) + (b"\x3f" + b"a" * 63) * 5 + b"\x00" + TYPE_CLASS,
    "QDCOUNT=50 with one question": lambda r: _header(r, qdcount=50) + QUESTION,
    "QDCOUNT=0, header only": lambda r: _header(r, qdcount=0),
    "all section counts 65535 with one question": lambda r: _header(r, 65535, 0x0100, 65535, 65535, 65535) + QUESTION,
    "QR=1 on an otherwise valid query": lambda r: _header(r, flags=0x8180) + QUESTION,
    "reserved opcode 15": lambda r: _header(r, flags=0x7900) + QUESTION,
    "twelve 0xFF bytes": lambda r: b"\xff" * 12,
    "sixty-four 0xFF bytes": lambda r: b"\xff" * 64,
    "valid query with trailing garbage": lambda r: _header(r) + QUESTION + bytes(r.randrange(256) for _ in range(40)),
}


def _valid_query(rng):
    query = dns.message.make_query(rng.choice(NAMES), rng.choice(TYPES), id=rng.randrange(65536))
    return query.to_wire()


def _random_bytes(rng):
    return bytes(rng.randrange(256) for _ in range(rng.randrange(0, 601)))


def _flipped(rng):
    packet = bytearray(_valid_query(rng))
    for _ in range(rng.randint(1, 8)):
        packet[rng.randrange(len(packet))] = rng.randrange(256)
    return bytes(packet)


def _truncated(rng):
    packet = _valid_query(rng)
    return packet[: rng.randrange(len(packet))]


def packets(seed, count=PACKETS):
    """The (kind, bytes) sequence for a seed. Every tenth packet is a handcrafted case."""
    rng = random.Random(seed)
    cases = list(HANDCRAFTED.items())
    result = []
    for index in range(count):
        if index % 10 == 9:
            kind, build = cases[(index // 10) % len(cases)]
            result.append((f"handcrafted: {kind}", build(rng)))
            continue
        roll = rng.random()
        if roll < 0.40:
            result.append(("random bytes", _random_bytes(rng)))
        elif roll < 0.75:
            result.append(("valid query with bytes flipped", _flipped(rng)))
        else:
            result.append(("truncated valid query", _truncated(rng)))
    return result


def _canary_problem(server, qid):
    """None if a valid query gets the correct answer, otherwise a description of what went wrong."""
    query = dns.message.make_query(CANARY, "A", id=qid)
    wire = None
    for _ in range(3):  # the burst before the check may still be queued in the server
        wire = server.udp_raw(query.to_wire(), timeout=2.0)
        if wire is not None:
            break
    if wire is None:
        return "no answer to a valid query (3 attempts, 2 s each)"
    try:
        response = dns.message.from_wire(wire)
    except Exception as exc:  # noqa: BLE001 - any parse failure is reported, not raised
        return f"answer to a valid query does not parse: {exc!r} ({wire.hex()})"
    answers = [rdata.to_text() for rrset in response.answer for rdata in rrset]
    if response.id != qid or response.question != query.question:
        return f"answer does not match the query: id={response.id}, question={response.question}"
    if response.rcode() != dns.rcode.NOERROR or answers != ["0.0.0.0"]:
        return f"wrong answer to a valid query: rcode={dns.rcode.to_text(response.rcode())}, answers={answers}"
    return None


def test_server_survives_fuzzing(server):
    """contract.md, Responses: the server must never crash on input"""
    stream = packets(SEED)

    def report(index, problem):
        kind, packet = stream[index]
        first = index - index % CHECK_EVERY
        return (
            f"{problem}\n"
            f"seed={SEED} packet index={index} (noticed here; packets {first}..{index} were sent since the last passing check)\n"
            f"last packet sent: {kind}, {len(packet)} bytes: {packet.hex()}"
        )

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setblocking(False)
        for index, (_kind, packet) in enumerate(stream):
            sock.sendto(packet, server.dns_addr)
            # Give the server a moment to handle the packet, so that a crash is
            # noticed at (or right after) the packet that caused it.
            select.select([sock], [], [], PACE)
            try:  # replies to fuzz packets are not judged, only discarded
                while True:
                    sock.recvfrom(65535)
            except (BlockingIOError, ConnectionError):
                pass
            assert server.proc.poll() is None, report(index, f"server exited with code {server.proc.returncode}")
            if (index + 1) % CHECK_EVERY == 0:
                problem = _canary_problem(server, qid=index)
                assert server.proc.poll() is None, report(index, f"server exited with code {server.proc.returncode}")
                assert problem is None, report(index, problem)

