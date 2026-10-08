"""Smoke tests. Adam extends this into the full suite; one file per contract section."""
import socket

import dns.flags
import dns.message
import dns.query
import dns.rcode
import requests


def ask(addr, name, rtype="A"):
    host, port = addr
    q = dns.message.make_query(name, rtype)
    return dns.query.udp(q, host, port=port, timeout=2)


def test_local_a_record(dns_addr):
    r = ask(dns_addr, "nas.home.lan.")
    assert r.rcode() == dns.rcode.NOERROR
    assert r.flags & dns.flags.AA
    assert [rr.address for rr in r.answer[0]] == ["192.168.1.10"]


def test_nodata_is_not_nxdomain(dns_addr):
    r = ask(dns_addr, "printer.home.lan.", "AAAA")
    assert r.rcode() == dns.rcode.NOERROR
    assert r.answer == []


def test_nxdomain_under_local_suffix(dns_addr):
    r = ask(dns_addr, "missing.home.lan.")
    assert r.rcode() == dns.rcode.NXDOMAIN


def test_blocked_domain_returns_zero_address(dns_addr):
    r = ask(dns_addr, "sub.ads.example.com.")
    assert r.rcode() == dns.rcode.NOERROR
    assert [rr.address for rr in r.answer[0]] == ["0.0.0.0"]


def test_garbage_does_not_kill_server(dns_addr):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(b"\xde\xad\xbe\xef" * 3, dns_addr)
    s.close()
    assert ask(dns_addr, "nas.home.lan.").rcode() == dns.rcode.NOERROR


def test_stats_endpoint(admin_url):
    body = requests.get(f"{admin_url}/stats", timeout=2).json()
    assert {"queries", "blocked", "cache_hits", "cache_misses"} <= body.keys()
