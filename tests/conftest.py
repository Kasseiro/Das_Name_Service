"""Harness for the black-box suite.

Starts the build under test with `python -m dnsd` and talks to it over the
network only. Nothing here imports from dnsd.
"""
import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

import dns.message
import pytest
from fake_upstream import FakeUpstream

FIXTURES = Path(__file__).resolve().parent / "fixtures"
STARTUP_TIMEOUT = 5.0
# Listed in fixtures/blocklist.txt; used to probe that the server is up.
PROBE_NAME = "ads.example.com."


def pytest_addoption(parser):
    parser.addoption(
        "--impl",
        default=".",
        help="path to the repo root of the build under test (the directory containing dnsd/)",
    )


def _impl_root(config):
    return Path(config.getoption("--impl")).resolve()


def pytest_collection_modifyitems(config, items):
    entry = _impl_root(config) / "dnsd" / "__main__.py"
    if entry.exists():
        return
    skip = pytest.mark.skip(reason=f"no build to test: {entry} does not exist (use --impl <repo root>)")
    for item in items:
        item.add_marker(skip)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    log_path = getattr(item, "_dnsd_log", None)
    if report.failed and log_path is not None and log_path.exists():
        text = log_path.read_text(errors="replace")
        report.sections.append(("dnsd output", text or "(empty)"))


def _recv_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def udp_raw(addr, payload, timeout=2.0):
    """Send one datagram, return the first reply as bytes or None on timeout."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(payload, addr)
        try:
            return sock.recvfrom(65535)[0]
        except (TimeoutError, ConnectionError):
            return None


def tcp_raw(addr, payload, timeout=2.0):
    """Send one message with the 2-byte length prefix, return the reply body or None."""
    with socket.create_connection(addr, timeout=timeout) as sock:
        sock.sendall(struct.pack("!H", len(payload)) + payload)
        try:
            prefix = _recv_exact(sock, 2)
            if prefix is None:
                return None
            return _recv_exact(sock, struct.unpack("!H", prefix)[0])
        except (TimeoutError, ConnectionError):
            return None


def make_query(name, rdtype="A", qid=None):
    """A plain query: RD set, no EDNS."""
    return dns.message.make_query(name, rdtype, id=qid)


class Server:
    """Handle on a running build under test."""

    def __init__(self, proc, dns_addr, admin_addr, log_path):
        self.proc = proc
        self.dns_addr = dns_addr
        self.admin_addr = admin_addr
        self.admin_url = f"http://{admin_addr[0]}:{admin_addr[1]}"
        self.log_path = log_path

    def udp_raw(self, payload, timeout=2.0):
        return udp_raw(self.dns_addr, payload, timeout)

    def tcp_raw(self, payload, timeout=2.0):
        return tcp_raw(self.dns_addr, payload, timeout)

    def udp(self, name, rdtype="A", qid=None, timeout=2.0):
        """Query over UDP and return the parsed response."""
        wire = self.udp_raw(make_query(name, rdtype, qid).to_wire(), timeout)
        assert wire is not None, f"no UDP response for {name} {rdtype} within {timeout} s"
        return dns.message.from_wire(wire, ignore_trailing=True)

    def tcp(self, name, rdtype="A", qid=None, timeout=2.0):
        """Query over TCP and return the parsed response."""
        wire = self.tcp_raw(make_query(name, rdtype, qid).to_wire(), timeout)
        assert wire is not None, f"no TCP response for {name} {rdtype} within {timeout} s"
        return dns.message.from_wire(wire)

    def log(self):
        return self.log_path.read_text(errors="replace")


def _free_ports():
    """Two free ports on 127.0.0.1; the first is free for both UDP and TCP."""
    for _ in range(50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp:
            tcp.bind(("127.0.0.1", 0))
            dns_port = tcp.getsockname()[1]
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                try:
                    udp.bind(("127.0.0.1", dns_port))
                except OSError:
                    continue
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as admin:
                admin.bind(("127.0.0.1", 0))
                return dns_port, admin.getsockname()[1]
    raise RuntimeError("could not find free ports")


def _wait_until_answering(server):
    probe = make_query(PROBE_NAME, "A").to_wire()
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if server.proc.poll() is not None:
            pytest.fail(f"dnsd exited with code {server.proc.returncode} during startup", pytrace=False)
        reply = server.udp_raw(probe, timeout=0.1)
        if reply is not None and len(reply) >= 12 and reply[:2] == probe[:2]:
            return
        time.sleep(0.1)
    pytest.fail(f"dnsd did not answer a query within {STARTUP_TIMEOUT:g} s", pytrace=False)


@pytest.fixture
def upstream():
    """Fake upstream resolver; the server under test forwards to it."""
    fake = FakeUpstream().start()
    yield fake
    fake.stop()


@pytest.fixture
def server(request, tmp_path, upstream):
    """Start the build under test on two free ports and kill it afterwards."""
    impl = _impl_root(request.config)
    dns_port, admin_port = _free_ports()
    log_path = tmp_path / "dnsd.log"
    request.node._dnsd_log = log_path
    cmd = [
        sys.executable, "-m", "dnsd",
        "--listen", f"127.0.0.1:{dns_port}",
        "--admin", f"127.0.0.1:{admin_port}",
        "--zone", str(FIXTURES / "zone.txt"),
        "--blocklist", str(FIXTURES / "blocklist.txt"),
        "--upstream", upstream.addr,
    ]
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    with open(log_path, "wb") as log:
        proc = subprocess.Popen(cmd, cwd=impl, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    handle = Server(proc, ("127.0.0.1", dns_port), ("127.0.0.1", admin_port), log_path)
    try:
        _wait_until_answering(handle)
        yield handle
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


@pytest.fixture
def admin(server):
    """Base URL of the admin API, once it accepts connections."""
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while True:
        try:
            socket.create_connection(server.admin_addr, timeout=0.5).close()
            return server.admin_url
        except OSError:
            if time.monotonic() >= deadline:
                pytest.fail(f"admin API not reachable at {server.admin_url}", pytrace=False)
            time.sleep(0.1)
