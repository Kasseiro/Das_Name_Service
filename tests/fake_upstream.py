"""Fake upstream resolver for the black-box suite.

A DNS server on 127.0.0.1 that runs in background threads, serves canned
answers and records every query it receives. It listens on UDP and, on the same
port number, on TCP. Tests point the server under test at it with --upstream,
so nothing ever leaves the machine.

Modes:
  normal     canned answers, NXDOMAIN for unknown names
  wrong_id   as normal, but the reply carries a different ID
  silent     never replies
  big        the UDP reply carries an answer over 512 bytes
  truncated  the UDP reply is empty with TC=1; the answer over 512 bytes is
             only available over TCP, as a real upstream would do it
"""
import socket
import struct
import threading
from collections import namedtuple

import dns.exception
import dns.flags
import dns.message
import dns.name
import dns.rcode
import dns.rdatatype
import dns.rrset

Query = namedtuple("Query", "id source_port name rdtype")

MODES = ("normal", "wrong_id", "silent", "big", "truncated")

# Each A record costs 16 bytes with name compression, so 40 of them push any
# response well past the 512 byte UDP limit.
BIG_RECORDS = 40


class FakeUpstream:
    def __init__(self, host="127.0.0.1"):
        self._sock, self._tcp = self._bind(host)
        self.host, self.port = self._sock.getsockname()
        self.mode = "normal"
        self.delay = 0.0  # seconds to wait before each reply
        self.rcode = None  # if set, every reply has this RCODE and no answer
        self.authority = []  # rrsets added to the authority section of every reply
        self.additional = []  # rrsets added to the additional section of every reply
        self._answers = {}
        self._queries = []
        self._tcp_queries = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads = [
            threading.Thread(target=self._serve_udp, name="fake-upstream-udp", daemon=True),
            threading.Thread(target=self._serve_tcp, name="fake-upstream-tcp", daemon=True),
        ]

    @staticmethod
    def _bind(host):
        """A UDP and a TCP socket on the same free port."""
        for _ in range(50):
            udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp.bind((host, 0))
            tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                tcp.bind((host, udp.getsockname()[1]))
            except OSError:
                udp.close()
                tcp.close()
                continue
            tcp.listen()
            udp.settimeout(0.1)
            tcp.settimeout(0.1)
            return udp, tcp
        raise RuntimeError("could not find a port free for both UDP and TCP")

    @property
    def addr(self):
        return f"{self.host}:{self.port}"

    def start(self):
        for thread in self._threads:
            thread.start()
        return self

    def stop(self):
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=2)
        self._sock.close()
        self._tcp.close()

    def set_answer(self, name, rdtype, ttl, *values):
        """Serve `values` (text rdata, e.g. "192.0.2.1") for name/rdtype with the given TTL.

        With no values the reply is NOERROR with an empty answer section.
        """
        key = (dns.name.from_text(name), dns.rdatatype.from_text(rdtype))
        with self._lock:
            self._answers[key] = (ttl, values)

    @property
    def queries(self):
        """Every query received over UDP so far, oldest first."""
        with self._lock:
            return list(self._queries)

    @property
    def tcp_queries(self):
        """Every query received over TCP so far, oldest first."""
        with self._lock:
            return list(self._tcp_queries)

    def clear(self):
        with self._lock:
            self._queries.clear()
            self._tcp_queries.clear()

    def _handle(self, wire, source_port, tcp):
        """Record one query and return the reply bytes, or None for no reply."""
        try:
            query = dns.message.from_wire(wire)
            question = query.question[0]
        except (dns.exception.DNSException, IndexError):
            return None
        with self._lock:
            seen = self._tcp_queries if tcp else self._queries
            seen.append(Query(query.id, source_port, question.name, dns.rdatatype.to_text(question.rdtype)))
            canned = self._answers.get((question.name, question.rdtype))
        mode = self.mode
        if mode == "silent":
            return None
        if self.delay:
            self._stop.wait(self.delay)
        try:
            return self._build_reply(query, question, canned, mode, tcp)
        except (dns.exception.DNSException, ValueError):
            # A query the server derived from fuzz input may not be answerable; keep serving.
            return None

    def _serve_udp(self):
        while not self._stop.is_set():
            try:
                wire, client = self._sock.recvfrom(65535)
            except TimeoutError:
                continue
            except OSError:
                return
            reply = self._handle(wire, client[1], tcp=False)
            if reply is not None:
                try:
                    self._sock.sendto(reply, client)
                except OSError:
                    pass

    def _serve_tcp(self):
        while not self._stop.is_set():
            try:
                conn, client = self._tcp.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(2)
                try:
                    wire = self._read_message(conn)
                    reply = self._handle(wire, client[1], tcp=True) if wire else None
                    if reply is not None:
                        conn.sendall(struct.pack("!H", len(reply)) + reply)
                except OSError:
                    pass

    @staticmethod
    def _read_message(conn):
        data = b""
        while len(data) < 2 or len(data) < 2 + struct.unpack("!H", data[:2])[0]:
            chunk = conn.recv(65535)
            if not chunk:
                return None
            data += chunk
        return data[2:]

    def _build_reply(self, query, question, canned, mode, tcp):
        response = dns.message.make_response(query)
        response.flags |= dns.flags.RA
        if mode == "truncated" and not tcp:
            response.flags |= dns.flags.TC
            return response.to_wire()
        if self.rcode is not None:
            response.set_rcode(self.rcode)
        elif mode in ("big", "truncated"):
            values = [f"198.51.100.{i + 1}" for i in range(BIG_RECORDS)]
            ttl = canned[0] if canned else 60
            response.answer.append(dns.rrset.from_text_list(question.name, ttl, "IN", "A", values))
        elif canned:
            ttl, values = canned
            if values:  # no values: NOERROR with an empty answer section (NODATA)
                response.answer.append(
                    dns.rrset.from_text_list(question.name, ttl, "IN", question.rdtype, list(values))
                )
        else:
            response.set_rcode(dns.rcode.NXDOMAIN)
        response.authority.extend(self.authority)
        response.additional.extend(self.additional)
        if mode == "wrong_id":
            response.id = (query.id + 1) & 0xFFFF
        return response.to_wire(max_size=65535)
