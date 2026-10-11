"""Blocklist: the blocking response and which names it applies to.

fixtures/blocklist.txt lists ads.example.com, tracker.test, UPPER.Example.NET
and dotted.example.net. (with trailing dot), plus comment and blank lines.
"""
import dns.flags
import dns.rcode
import pytest
import requests

SINKHOLES = {"0.0.0.0", "::"}
FILE_ENTRIES = {"ads.example.com", "tracker.test", "upper.example.net", "dotted.example.net"}


def addresses(response):
    return [rdata.to_text() for rrset in response.answer for rdata in rrset]


def is_blocked(response):
    """True if the response is one of the contract's blocking responses."""
    if response.rcode() == dns.rcode.NXDOMAIN:
        return True
    return any(address in SINKHOLES for address in addresses(response))


@pytest.mark.parametrize("name", ["ads.example.com.", "tracker.test."])
def test_blocked_a(server, name):
    """contract.md, Responses: blocked domain, type A"""
    response = server.udp(name, "A")
    assert response.rcode() == dns.rcode.NOERROR
    assert addresses(response) == ["0.0.0.0"]
    assert response.answer[0].ttl == 60
    assert not response.flags & dns.flags.AA


@pytest.mark.parametrize("name", ["ads.example.com.", "tracker.test."])
def test_blocked_aaaa(server, name):
    """contract.md, Responses: blocked domain, type AAAA"""
    response = server.udp(name, "AAAA")
    assert response.rcode() == dns.rcode.NOERROR
    assert addresses(response) == ["::"]
    assert response.answer[0].ttl == 60
    assert not response.flags & dns.flags.AA


@pytest.mark.parametrize("rdtype", ["TXT", "MX", "CNAME", "NS", "ANY"])
def test_blocked_other_types(server, rdtype):
    """contract.md, Responses: blocked domain, other types (every type except A and AAAA, including ANY)"""
    response = server.udp("ads.example.com.", rdtype)
    assert response.rcode() == dns.rcode.NXDOMAIN
    assert response.answer == []
    assert not response.flags & dns.flags.AA


def test_blocked_over_tcp(server):
    """contract.md, TCP: the same rules apply as over UDP"""
    response = server.tcp("ads.example.com.", "A")
    assert response.rcode() == dns.rcode.NOERROR
    assert addresses(response) == ["0.0.0.0"]
    assert response.answer[0].ttl == 60
    assert not response.flags & dns.flags.AA


@pytest.mark.parametrize("name", ["sub.ads.example.com.", "a.b.c.ads.example.com.", "www.tracker.test."])
def test_subdomain_of_listed_domain_is_blocked(server, name):
    """contract.md, Blocklist file: a listed domain also blocks its subdomains"""
    assert addresses(server.udp(name, "A")) == ["0.0.0.0"]
    assert addresses(server.udp(name, "AAAA")) == ["::"]
    assert server.udp(name, "TXT").rcode() == dns.rcode.NXDOMAIN


def test_parent_of_listed_domain_is_not_blocked(server, upstream):
    """contract.md, Blocklist file: matching is by whole labels, example.com is not blocked"""
    upstream.set_answer("example.com.", "A", 300, "192.0.2.10")
    response = server.udp("example.com.", "A")
    assert not is_blocked(response)


def test_name_sharing_only_a_suffix_string_is_not_blocked(server, upstream):
    """contract.md, Blocklist file: matching is by whole labels, xads.example.com is not blocked"""
    upstream.set_answer("xads.example.com.", "A", 300, "192.0.2.11")
    response = server.udp("xads.example.com.", "A")
    assert not is_blocked(response)


@pytest.mark.parametrize("name", ["commented.example.org.", "indented-comment.example.org."])
def test_comment_lines_are_ignored(server, upstream, name):
    """contract.md, Blocklist file: a line whose first non-blank character is # is a comment"""
    upstream.set_answer(name, "A", 300, "192.0.2.12")
    response = server.udp(name, "A")
    assert not is_blocked(response)


def test_file_yields_exactly_its_entries(admin):
    """contract.md, Blocklist file: comment and blank lines are ignored; Admin API, /blocklist: GET lists entries loaded from the file"""
    listed = requests.get(f"{admin}/blocklist", timeout=2).json()
    assert sorted(entry.lower().rstrip(".") for entry in listed) == sorted(FILE_ENTRIES)


def test_entry_with_trailing_dot_blocks(server):
    """contract.md, Blocklist file: entries may be written with or without a trailing dot"""
    assert addresses(server.udp("dotted.example.net.", "A")) == ["0.0.0.0"]
    assert addresses(server.udp("sub.dotted.example.net.", "A")) == ["0.0.0.0"]


@pytest.mark.parametrize("name", ["ADS.EXAMPLE.COM.", "Ads.Example.Com.", "SuB.aDs.eXaMpLe.cOm.", "upper.example.net."])
def test_names_match_case_insensitively(server, name):
    """contract.md, Blocklist file: entries match case-insensitively; RFC 4343"""
    assert addresses(server.udp(name, "A")) == ["0.0.0.0"]


def test_local_zone_wins_over_blocklist(server, admin):
    """contract.md, Responses: rows are tried top to bottom, a name both in the local zone and blocked gets the local zone answer"""
    assert requests.post(f"{admin}/blocklist", json={"domain": "nas.home.lan"}, timeout=2).status_code == 201
    response = server.udp("nas.home.lan.", "A")
    assert response.rcode() == dns.rcode.NOERROR
    assert addresses(response) == ["192.168.1.10"]
    assert response.flags & dns.flags.AA
