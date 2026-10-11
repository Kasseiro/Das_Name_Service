"""Local zone: authoritative answers from fixtures/zone.txt.

The fixture defines nas (A, AAAA), files (CNAME to nas), printer (A),
tabs (A, TTL 60), ext (CNAME to a name outside the zone) and big (40 A
records), all under home.lan.
"""
import dns.flags
import dns.rcode
import dns.rdatatype
import pytest
import requests
from helpers import addresses, log_results, records, stats

TIMEOUT = 2


def assert_authoritative(response, rcode=dns.rcode.NOERROR):
    assert response.rcode() == rcode
    assert response.flags & dns.flags.AA
    assert response.flags & dns.flags.RA


# --- name in local zone, type exists

def test_a_record(server):
    """contract.md, Responses: name in local zone, type exists"""
    response = server.udp("nas.home.lan.", "A")
    assert_authoritative(response)
    assert records(response.answer) == {("nas.home.lan", "A", 300, "192.168.1.10")}


def test_aaaa_record(server):
    """contract.md, Responses: name in local zone, type exists"""
    response = server.udp("nas.home.lan.", "AAAA")
    assert_authoritative(response)
    assert records(response.answer) == {("nas.home.lan", "AAAA", 300, "fd00::10")}


def test_cname_record(server):
    """contract.md, Responses: name in local zone, type exists"""
    response = server.udp("files.home.lan.", "CNAME")
    assert_authoritative(response)
    assert records(response.answer) == {("files.home.lan", "CNAME", 300, "nas.home.lan.")}


def test_ttl_comes_from_the_zone_file(server):
    """contract.md, Zone file: each record carries its own TTL"""
    response = server.udp("tabs.home.lan.", "A")
    assert_authoritative(response)
    assert records(response.answer) == {("tabs.home.lan", "A", 60, "192.168.1.30")}


def test_several_records_with_one_name_and_type(server):
    """contract.md, Zone file: several records may share a name and type, all of them are returned"""
    response = server.tcp("big.home.lan.", "A")
    assert_authoritative(response)
    assert records(response.answer) == {("big.home.lan", "A", 300, f"192.168.2.{i}") for i in range(1, 41)}


@pytest.mark.parametrize("name", ["NAS.HOME.LAN.", "Nas.Home.Lan.", "nAs.hOmE.lAn."])
def test_names_match_case_insensitively(server, name):
    """contract.md, Zone file: names compare case-insensitively; RFC 4343"""
    response = server.udp(name, "A")
    assert_authoritative(response)
    assert addresses(response) == ["192.168.1.10"]


def test_local_answer_over_tcp(server):
    """contract.md, TCP: the same rules apply as over UDP"""
    response = server.tcp("nas.home.lan.", "A")
    assert_authoritative(response)
    assert records(response.answer) == {("nas.home.lan", "A", 300, "192.168.1.10")}


# --- CNAME

@pytest.mark.parametrize("rdtype, value", [("A", "192.168.1.10"), ("AAAA", "fd00::10")])
def test_cname_is_followed_inside_the_zone(server, rdtype, value):
    """contract.md, Zone file, CNAME: the CNAME record followed by the records of the requested type at a local target"""
    response = server.udp("files.home.lan.", rdtype)
    assert_authoritative(response)
    assert len(response.answer) == 2
    assert response.answer[0].rdtype == dns.rdatatype.CNAME, "the CNAME record does not come first"
    assert records(response.answer) == {
        ("files.home.lan", "CNAME", 300, "nas.home.lan."),
        ("nas.home.lan", rdtype, 300, value),
    }


def test_cname_to_local_target_without_the_requested_type(server):
    """contract.md, Zone file, CNAME: the target has no records of the requested type, so only the CNAME is returned"""
    response = server.udp("files.home.lan.", "TXT")
    assert_authoritative(response)
    assert records(response.answer) == {("files.home.lan", "CNAME", 300, "nas.home.lan.")}


def test_cname_to_target_outside_the_zone(server, upstream):
    """contract.md, Zone file, CNAME: if the target is not in the local zone, the answer is the CNAME record alone"""
    upstream.set_answer("www.example.org.", "A", 300, "192.0.2.80")
    response = server.udp("ext.home.lan.", "A")
    assert_authoritative(response)
    assert records(response.answer) == {("ext.home.lan", "CNAME", 300, "www.example.org.")}


# --- NODATA and NXDOMAIN

@pytest.mark.parametrize("name, rdtype", [("printer.home.lan.", "AAAA"), ("nas.home.lan.", "TXT"), ("nas.home.lan.", "MX")])
def test_nodata(server, name, rdtype):
    """contract.md, Responses: name in local zone, type missing (NODATA)"""
    response = server.udp(name, rdtype)
    assert_authoritative(response)
    assert response.answer == []


@pytest.mark.parametrize("name", ["missing.home.lan.", "a.b.home.lan.", "sub.nas.home.lan."])
@pytest.mark.parametrize("rdtype", ["A", "AAAA", "TXT"])
def test_nxdomain_under_local_suffix(server, name, rdtype):
    """contract.md, Responses: name under a local zone suffix, not defined"""
    response = server.udp(name, rdtype)
    assert_authoritative(response, dns.rcode.NXDOMAIN)
    assert response.answer == []


# --- nothing local goes upstream

def test_local_names_are_not_forwarded(server, upstream):
    """contract.md, Scope: local zone answered authoritatively, everything else forwarded"""
    for name, rdtype in [("nas.home.lan.", "A"), ("printer.home.lan.", "AAAA"), ("missing.home.lan.", "A"), ("files.home.lan.", "A")]:
        server.udp(name, rdtype)
    assert upstream.queries == []


# --- suffixes follow the record set

def test_api_record_creates_a_local_suffix(server, admin, upstream):
    """contract.md, Zone file, Local zone suffix: suffixes follow the current record set, including changes through the admin API"""
    before = server.udp("missing.other.lan.", "A")
    assert not before.flags & dns.flags.AA, "other.lan. is treated as local before any record exists"
    record = {"name": "host.other.lan.", "type": "A", "ttl": 30, "value": "192.168.7.1"}
    assert requests.post(f"{admin}/records", json=record, timeout=TIMEOUT).status_code == 201
    asked = len(upstream.queries)
    response = server.udp("missing.other.lan.", "AAAA")
    assert_authoritative(response, dns.rcode.NXDOMAIN)
    assert len(upstream.queries) == asked, "a name under the new suffix was forwarded"


def test_deleting_the_last_record_removes_the_suffix(server, admin, upstream):
    """contract.md, Zone file, Local zone suffix: suffixes follow the current record set, including changes through the admin API"""
    record = {"name": "host.other.lan.", "type": "A", "ttl": 30, "value": "192.168.7.1"}
    requests.post(f"{admin}/records", json=record, timeout=TIMEOUT)
    assert_authoritative(server.udp("gone.other.lan.", "A"), dns.rcode.NXDOMAIN)
    assert requests.delete(f"{admin}/records/host.other.lan./A", timeout=TIMEOUT).status_code == 204
    upstream.set_answer("gone.other.lan.", "TXT", 30, '"from upstream"')
    response = server.udp("gone.other.lan.", "TXT")
    assert not response.flags & dns.flags.AA
    assert addresses(response) == ['"from upstream"']


def test_deleted_record_no_longer_resolves(server, admin):
    """contract.md, Admin API: changes through the API take effect immediately; Responses: NODATA"""
    assert requests.delete(f"{admin}/records/nas.home.lan./AAAA", timeout=TIMEOUT).status_code == 204
    response = server.udp("nas.home.lan.", "AAAA")
    assert_authoritative(response)
    assert response.answer == []
    assert addresses(server.udp("nas.home.lan.", "A")) == ["192.168.1.10"]


# --- stats and log

def test_local_queries_leave_cache_counters_alone(server, admin):
    """contract.md, Admin API, /stats: queries answered from the local zone change neither cache counter"""
    before = stats(admin)
    for name, rdtype in [("nas.home.lan.", "A"), ("nas.home.lan.", "A"), ("printer.home.lan.", "AAAA"), ("missing.home.lan.", "A")]:
        server.udp(name, rdtype)
    after = stats(admin)
    assert after["queries"] == before["queries"] + 4
    assert (after["cache_hits"], after["cache_misses"]) == (0, 0)
    assert after["blocked"] == before["blocked"]


def test_local_queries_are_logged_as_local(server, admin):
    """contract.md, Admin API, /log: result "local" for queries answered from the local zone"""
    server.udp("nas.home.lan.", "A")
    server.udp("printer.home.lan.", "AAAA")
    server.udp("missing.home.lan.", "A")
    assert log_results(admin, 3) == [("missing.home.lan", "local"), ("printer.home.lan", "local"), ("nas.home.lan", "local")]
