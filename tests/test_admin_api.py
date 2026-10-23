"""Admin API: every endpoint, status code and field in the contract.

Blocked names are used for queries wherever any query will do. Tests that need
a name that is not blocked let the fake upstream answer it. Cache counters and
the "local", "cached", "forwarded" and "error" log results are left to the
zone, cache and forwarder suites.
"""
import ipaddress
import struct
import time

import dns.message
import dns.rcode
import pytest
import requests
from helpers import addresses, assert_equal, eventually, get_json, norm, settled

TIMEOUT = 2
STATS_KEYS = {"queries", "blocked", "cache_hits", "cache_misses"}
RECORD_KEYS = {"name", "type", "ttl", "value"}
LOG_KEYS = {"time", "client", "name", "type", "result"}

FILE_BLOCKLIST = {"ads.example.com", "tracker.test", "upper.example.net", "dotted.example.net"}
NEW_RECORD = {"name": "added.home.lan.", "type": "A", "ttl": 120, "value": "192.168.1.99"}

QUESTION = b"\x03ads\x07example\x03com\x00\x00\x01\x00\x01"
# Input that must not be counted or logged: (description, packet, expects a reply).
UNCOUNTED = [
    ("FORMERR", struct.pack("!6H", 1, 0x0100, 1, 0, 0, 0) + b"\x03ads\x07exam", True),
    ("NOTIMP", struct.pack("!6H", 2, 0x1100, 1, 0, 0, 0) + QUESTION, True),
    ("under 12 bytes", b"\x00\x03\x01\x00\x00", False),
    ("QR=1", struct.pack("!6H", 4, 0x8180, 1, 0, 0, 0) + QUESTION, False),
]


def same_value(rtype, a, b):
    if rtype in ("A", "AAAA"):
        return ipaddress.ip_address(a) == ipaddress.ip_address(b)
    return norm(a) == norm(b)


def matching(records, wanted):
    return [
        r for r in records
        if norm(r["name"]) == norm(wanted["name"])
        and r["type"] == wanted["type"]
        and same_value(wanted["type"], r["value"], wanted["value"])
    ]


def send_uncounted(server):
    for description, packet, expects_reply in UNCOUNTED:
        reply = server.udp_raw(packet, timeout=2.0 if expects_reply else 0.3)
        assert (reply is not None) == expects_reply, description


# --- status codes

@pytest.mark.parametrize("path", ["/stats", "/blocklist", "/records", "/log"])
def test_get_returns_200_json(admin, path):
    """contract.md, Admin API, Status codes: a successful GET returns 200 with Content-Type application/json"""
    response = requests.get(f"{admin}{path}", timeout=TIMEOUT)
    assert response.status_code == 200
    assert response.headers.get("Content-Type", "").split(";")[0].strip().lower() == "application/json"
    response.json()


@pytest.mark.parametrize("path", ["/", "/nope", "/stats/extra", "/blocklists", "/ui/extra"])
def test_unknown_path_is_404(admin, path):
    """contract.md, Admin API, Status codes: an unknown path returns 404"""
    assert requests.get(f"{admin}{path}", timeout=TIMEOUT).status_code == 404


@pytest.mark.parametrize(
    "method, path",
    [("POST", "/stats"), ("DELETE", "/stats"), ("PUT", "/blocklist"), ("DELETE", "/blocklist"),
     ("PUT", "/records"), ("DELETE", "/records"), ("POST", "/log"), ("DELETE", "/log")],
)
def test_method_not_in_table_is_405(admin, method, path):
    """contract.md, Admin API, Status codes: a known path with a method not in the table returns 405"""
    assert requests.request(method, f"{admin}{path}", json={}, timeout=TIMEOUT).status_code == 405


@pytest.mark.parametrize(
    "body",
    [b"{not json", b"", b"{}", b'{"domain": 5}', b'{"domain": null}', b'["ads.example.com"]'],
    ids=["invalid JSON", "empty body", "field missing", "domain is a number", "domain is null", "not an object"],
)
def test_post_blocklist_bad_body_is_400(admin, body):
    """contract.md, Admin API, Status codes: invalid JSON, a missing field or a field of the wrong kind returns 400"""
    response = requests.post(f"{admin}/blocklist", data=body, headers={"Content-Type": "application/json"}, timeout=TIMEOUT)
    assert response.status_code == 400


@pytest.mark.parametrize(
    "body",
    [
        "{not json",
        {"type": "A", "ttl": 60, "value": "192.168.1.5"},
        {"name": "bad.home.lan.", "ttl": 60, "value": "192.168.1.5"},
        {"name": "bad.home.lan.", "type": "A", "value": "192.168.1.5"},
        {"name": "bad.home.lan.", "type": "A", "ttl": 60},
        {"name": "bad.home.lan.", "type": "A", "ttl": "60", "value": "192.168.1.5"},
        {"name": "bad.home.lan.", "type": "A", "ttl": -1, "value": "192.168.1.5"},
        {"name": "bad.home.lan.", "type": "A", "ttl": 60, "value": 5},
        {"name": "bad.home.lan.", "type": "MX", "ttl": 60, "value": "10 mail.home.lan."},
        {"name": "bad.home.lan.", "type": "TXT", "ttl": 60, "value": "hello"},
    ],
    ids=["invalid JSON", "name missing", "type missing", "ttl missing", "value missing",
         "ttl is a string", "ttl negative", "value is a number", "type MX", "type TXT"],
)
def test_post_records_bad_body_is_400(admin, body):
    """contract.md, Admin API, Status codes and /records: bad JSON, missing or wrong fields, or a type other than A, AAAA, CNAME returns 400"""
    if isinstance(body, str):
        response = requests.post(f"{admin}/records", data=body, headers={"Content-Type": "application/json"}, timeout=TIMEOUT)
    else:
        response = requests.post(f"{admin}/records", json=body, timeout=TIMEOUT)
    assert response.status_code == 400


# --- /stats

def test_get_stats(admin):
    """contract.md, Admin API: GET /stats"""
    stats = get_json(f"{admin}/stats")
    assert STATS_KEYS <= stats.keys()
    for key in STATS_KEYS:
        assert type(stats[key]) is int and stats[key] >= 0, f"{key}={stats[key]!r}"


def test_stats_cache_counters_start_at_zero(admin):
    """contract.md, Admin API, /stats: all counters start at 0 (the startup probe is a blocked query and touches neither cache counter)"""
    stats = get_json(f"{admin}/stats")
    assert (stats["cache_hits"], stats["cache_misses"]) == (0, 0)


def test_stats_queries_counts_udp_and_tcp(server, admin):
    """contract.md, Admin API, /stats: "queries" counts queries answered over UDP and TCP"""
    before = settled(lambda: get_json(f"{admin}/stats"))["queries"]
    server.udp("q1.ads.example.com.", "A")
    server.udp("q2.ads.example.com.", "TXT")
    server.tcp("q3.ads.example.com.", "A")
    server.tcp("q4.ads.example.com.", "AAAA")
    eventually(lambda: assert_equal(get_json(f"{admin}/stats")["queries"], before + 4))


def test_stats_queries_ignores_uncounted_input(server, admin):
    """contract.md, Admin API, /stats: input that got no reply, FORMERR or NOTIMP is not counted"""
    before = settled(lambda: get_json(f"{admin}/stats"))["queries"]
    send_uncounted(server)
    server.udp("ads.example.com.", "A")
    after = settled(lambda: get_json(f"{admin}/stats"))["queries"]
    assert after == before + 1


def test_stats_blocked_counts_blocking_responses(server, admin):
    """contract.md, Admin API, /stats: "blocked" counts queries that got a blocking response"""
    before = settled(lambda: get_json(f"{admin}/stats"))["blocked"]
    for rdtype in ("A", "AAAA", "TXT"):
        server.udp("ads.example.com.", rdtype)
    eventually(lambda: assert_equal(get_json(f"{admin}/stats")["blocked"], before + 3))


def test_stats_blocked_ignores_unblocked_queries(server, admin, upstream):
    """contract.md, Admin API, /stats: "blocked" counts only blocking responses"""
    upstream.set_answer("example.com.", "A", 300, "192.0.2.10")
    before = settled(lambda: get_json(f"{admin}/stats"))
    server.udp("example.com.", "A")
    after = settled(lambda: get_json(f"{admin}/stats"))
    assert after["queries"] == before["queries"] + 1
    assert after["blocked"] == before["blocked"]


def test_stats_blocked_queries_leave_cache_counters_alone(server, admin):
    """contract.md, Admin API, /stats: queries answered from the blocklist change neither cache counter"""
    for rdtype in ("A", "AAAA", "TXT", "A"):
        server.udp("ads.example.com.", rdtype)
    stats = settled(lambda: get_json(f"{admin}/stats"))
    assert (stats["cache_hits"], stats["cache_misses"]) == (0, 0)


# --- /blocklist

def test_get_blocklist_lists_file_entries(admin):
    """contract.md, Admin API, /blocklist: GET lists every blocked domain, including those loaded from the file"""
    listed = get_json(f"{admin}/blocklist")
    assert isinstance(listed, list)
    assert all(isinstance(entry, str) for entry in listed)
    assert sorted(norm(entry) for entry in listed) == sorted(FILE_BLOCKLIST)


def test_post_blocklist(admin):
    """contract.md, Admin API: POST /blocklist -> 201; /blocklist: GET lists domains added through the API"""
    response = requests.post(f"{admin}/blocklist", json={"domain": "new.example.net"}, timeout=TIMEOUT)
    assert response.status_code == 201
    assert sorted(norm(entry) for entry in get_json(f"{admin}/blocklist")) == sorted(FILE_BLOCKLIST | {"new.example.net"})


def test_post_blocklist_takes_effect_immediately(server, admin, upstream):
    """contract.md, Admin API: changes through the API take effect immediately"""
    upstream.set_answer("new.example.net.", "A", 300, "192.0.2.20")
    upstream.set_answer("sub.new.example.net.", "A", 300, "192.0.2.21")
    assert "0.0.0.0" not in addresses(server.udp("new.example.net.", "A"))
    requests.post(f"{admin}/blocklist", json={"domain": "new.example.net"}, timeout=TIMEOUT)
    assert addresses(server.udp("new.example.net.", "A")) == ["0.0.0.0"]
    assert addresses(server.udp("sub.new.example.net.", "A")) == ["0.0.0.0"]


@pytest.mark.parametrize("domain", ["ads.example.com", "new.example.net"], ids=["from file", "from API"])
def test_post_blocklist_duplicate(admin, domain):
    """contract.md, Admin API, /blocklist: POST of a domain that is already listed returns 201 and leaves it listed once"""
    requests.post(f"{admin}/blocklist", json={"domain": domain}, timeout=TIMEOUT)
    assert requests.post(f"{admin}/blocklist", json={"domain": domain}, timeout=TIMEOUT).status_code == 201
    assert [norm(entry) for entry in get_json(f"{admin}/blocklist")].count(domain) == 1


def test_delete_blocklist(admin):
    """contract.md, Admin API: DELETE /blocklist/{domain} -> 204"""
    requests.post(f"{admin}/blocklist", json={"domain": "new.example.net"}, timeout=TIMEOUT)
    response = requests.delete(f"{admin}/blocklist/new.example.net", timeout=TIMEOUT)
    assert response.status_code == 204
    assert sorted(norm(entry) for entry in get_json(f"{admin}/blocklist")) == sorted(FILE_BLOCKLIST)


def test_delete_blocklist_unblocks_immediately(server, admin, upstream):
    """contract.md, Admin API: changes through the API take effect immediately"""
    upstream.set_answer("new.example.net.", "A", 300, "192.0.2.20")
    requests.post(f"{admin}/blocklist", json={"domain": "new.example.net"}, timeout=TIMEOUT)
    assert addresses(server.udp("new.example.net.", "A")) == ["0.0.0.0"]
    requests.delete(f"{admin}/blocklist/new.example.net", timeout=TIMEOUT)
    assert "0.0.0.0" not in addresses(server.udp("new.example.net.", "A"))


def test_delete_blocklist_entry_loaded_from_file(server, admin, upstream):
    """contract.md, Admin API, /blocklist: entries loaded from the file can be deleted"""
    upstream.set_answer("tracker.test.", "A", 300, "192.0.2.30")
    assert requests.delete(f"{admin}/blocklist/tracker.test", timeout=TIMEOUT).status_code == 204
    assert sorted(norm(entry) for entry in get_json(f"{admin}/blocklist")) == sorted(FILE_BLOCKLIST - {"tracker.test"})
    assert "0.0.0.0" not in addresses(server.udp("tracker.test.", "A"))


def test_delete_blocklist_twice_is_404(admin):
    """contract.md, Admin API: DELETE /blocklist/{domain} -> 404 if not listed"""
    requests.post(f"{admin}/blocklist", json={"domain": "new.example.net"}, timeout=TIMEOUT)
    requests.delete(f"{admin}/blocklist/new.example.net", timeout=TIMEOUT)
    assert requests.delete(f"{admin}/blocklist/new.example.net", timeout=TIMEOUT).status_code == 404


def test_delete_blocklist_unknown_is_404(admin):
    """contract.md, Admin API: DELETE /blocklist/{domain} -> 404 if not listed"""
    assert requests.delete(f"{admin}/blocklist/never-listed.example.org", timeout=TIMEOUT).status_code == 404


def test_delete_blocklist_subdomain_of_listed_is_404(server, admin):
    """contract.md, Admin API, /blocklist: a subdomain of a listed domain is blocked but not listed, deleting it returns 404"""
    assert requests.delete(f"{admin}/blocklist/sub.ads.example.com", timeout=TIMEOUT).status_code == 404
    assert addresses(server.udp("sub.ads.example.com.", "A")) == ["0.0.0.0"]


def test_blocklist_accepts_names_in_any_form(server, admin):
    """contract.md, Admin API, Names: names are accepted with or without a trailing dot and in any case, in bodies and URLs"""
    assert requests.post(f"{admin}/blocklist", json={"domain": "Mixed.Example.NET."}, timeout=TIMEOUT).status_code == 201
    assert addresses(server.udp("mixed.example.net.", "A")) == ["0.0.0.0"]
    assert requests.delete(f"{admin}/blocklist/MIXED.example.net", timeout=TIMEOUT).status_code == 204
    assert requests.delete(f"{admin}/blocklist/ADS.Example.Com.", timeout=TIMEOUT).status_code == 204
    assert sorted(norm(entry) for entry in get_json(f"{admin}/blocklist")) == sorted(FILE_BLOCKLIST - {"ads.example.com"})


# --- /records

def test_get_records_lists_zone_file_records(admin):
    """contract.md, Admin API, /records: GET lists every record, including those loaded from the zone file"""
    records = get_json(f"{admin}/records")
    assert isinstance(records, list)
    assert len(matching(records, {"name": "nas.home.lan.", "type": "A", "value": "192.168.1.10"})) == 1
    assert len(matching(records, {"name": "nas.home.lan.", "type": "AAAA", "value": "fd00::10"})) == 1
    assert len(matching(records, {"name": "files.home.lan.", "type": "CNAME", "value": "nas.home.lan."})) == 1
    assert len(matching(records, {"name": "printer.home.lan.", "type": "A", "value": "192.168.1.20"})) == 1
    assert len([r for r in records if norm(r["name"]) == "big.home.lan" and r["type"] == "A"]) == 40
    assert len(records) == 46


def test_record_fields(admin):
    """contract.md, Admin API, /records: field kinds of name, type, ttl and value"""
    records = get_json(f"{admin}/records")
    assert records
    for record in records:
        assert RECORD_KEYS <= record.keys()
        assert isinstance(record["name"], str)
        assert record["type"] in ("A", "AAAA", "CNAME")
        assert type(record["ttl"]) is int and record["ttl"] >= 0
        assert isinstance(record["value"], str)
    assert {r["ttl"] for r in records} == {300, 60}


@pytest.mark.parametrize(
    "record",
    [
        NEW_RECORD,
        {"name": "added.home.lan.", "type": "AAAA", "ttl": 90, "value": "fd00::99"},
        {"name": "alias.home.lan.", "type": "CNAME", "ttl": 30, "value": "nas.home.lan."},
    ],
    ids=["A", "AAAA", "CNAME"],
)
def test_post_record(admin, record):
    """contract.md, Admin API: POST /records -> 201; /records: GET lists records added through the API"""
    response = requests.post(f"{admin}/records", json=record, timeout=TIMEOUT)
    assert response.status_code == 201
    found = matching(get_json(f"{admin}/records"), record)
    assert len(found) == 1
    assert found[0]["ttl"] == record["ttl"]


def test_posted_record_resolves(server, admin):
    """contract.md, Admin API: changes through the API take effect immediately"""
    requests.post(f"{admin}/records", json=NEW_RECORD, timeout=TIMEOUT)
    response = server.udp(NEW_RECORD["name"], "A")
    assert response.rcode() == dns.rcode.NOERROR
    assert addresses(response) == [NEW_RECORD["value"]]


def test_post_record_duplicate_replaces_ttl(admin):
    """contract.md, Admin API, /records: POST of an existing name, type and value returns 201, replaces its TTL and leaves it stored once"""
    requests.post(f"{admin}/records", json=NEW_RECORD, timeout=TIMEOUT)
    again = dict(NEW_RECORD, ttl=999)
    assert requests.post(f"{admin}/records", json=again, timeout=TIMEOUT).status_code == 201
    found = matching(get_json(f"{admin}/records"), NEW_RECORD)
    assert [r["ttl"] for r in found] == [999]


def test_delete_record(server, admin):
    """contract.md, Admin API: DELETE /records/{name}/{type} -> 204"""
    requests.post(f"{admin}/records", json=NEW_RECORD, timeout=TIMEOUT)
    response = requests.delete(f"{admin}/records/{NEW_RECORD['name']}/{NEW_RECORD['type']}", timeout=TIMEOUT)
    assert response.status_code == 204
    assert not matching(get_json(f"{admin}/records"), NEW_RECORD)
    assert NEW_RECORD["value"] not in addresses(server.udp(NEW_RECORD["name"], "A"))


def test_delete_record_removes_every_record_of_that_name_and_type(admin):
    """contract.md, Admin API, /records: DELETE removes every record with that name and type"""
    second = dict(NEW_RECORD, value="192.168.1.100")
    other_type = {"name": NEW_RECORD["name"], "type": "AAAA", "ttl": 120, "value": "fd00::99"}
    for record in (NEW_RECORD, second, other_type):
        requests.post(f"{admin}/records", json=record, timeout=TIMEOUT)
    assert requests.delete(f"{admin}/records/{NEW_RECORD['name']}/A", timeout=TIMEOUT).status_code == 204
    records = get_json(f"{admin}/records")
    assert not matching(records, NEW_RECORD)
    assert not matching(records, second)
    assert len(matching(records, other_type)) == 1


def test_delete_record_loaded_from_zone_file(admin):
    """contract.md, Admin API, /records: records loaded from the zone file can be deleted"""
    assert requests.delete(f"{admin}/records/printer.home.lan./A", timeout=TIMEOUT).status_code == 204
    records = get_json(f"{admin}/records")
    assert not [r for r in records if norm(r["name"]) == "printer.home.lan"]
    assert len(records) == 45


def test_delete_record_accepts_names_and_types_in_any_form(admin):
    """contract.md, Admin API, Names and /records: names with or without trailing dot in any case; {type} is matched case-insensitively"""
    requests.post(f"{admin}/records", json=dict(NEW_RECORD, name="Added.Home.LAN"), timeout=TIMEOUT)
    assert len(matching(get_json(f"{admin}/records"), NEW_RECORD)) == 1
    assert requests.delete(f"{admin}/records/ADDED.home.lan/a", timeout=TIMEOUT).status_code == 204
    assert not matching(get_json(f"{admin}/records"), NEW_RECORD)


def test_delete_record_twice_is_404(admin):
    """contract.md, Admin API: DELETE /records/{name}/{type} -> 404"""
    url = f"{admin}/records/{NEW_RECORD['name']}/{NEW_RECORD['type']}"
    requests.post(f"{admin}/records", json=NEW_RECORD, timeout=TIMEOUT)
    requests.delete(url, timeout=TIMEOUT)
    assert requests.delete(url, timeout=TIMEOUT).status_code == 404


@pytest.mark.parametrize("path", ["never-added.home.lan./A", "printer.home.lan./AAAA"], ids=["unknown name", "known name, other type"])
def test_delete_record_unknown_is_404(admin, path):
    """contract.md, Admin API: DELETE /records/{name}/{type} -> 404"""
    assert requests.delete(f"{admin}/records/{path}", timeout=TIMEOUT).status_code == 404


# --- /log

def log_names(admin, limit):
    return [norm(entry["name"]) for entry in get_json(f"{admin}/log", limit=limit)]


def test_log_entry_fields(server, admin):
    """contract.md, Admin API, /log: time, client, name, type and result of an entry"""
    started = time.time()
    server.udp("fields.ads.example.com.", "AAAA")
    eventually(lambda: assert_equal(log_names(admin, 1), ["fields.ads.example.com"]))
    (entry,) = get_json(f"{admin}/log", limit=1)
    assert LOG_KEYS <= entry.keys()
    assert type(entry["time"]) in (int, float)
    assert started - 1 <= entry["time"] <= time.time() + 1
    assert entry["client"] == "127.0.0.1"
    assert isinstance(entry["name"], str)
    assert entry["type"] == "AAAA"
    assert entry["result"] == "blocked"


def test_log_type_without_mnemonic(server, admin):
    """contract.md, Admin API, /log: "type" is "TYPEn" for a type the server has no name for"""
    query = dns.message.make_query("typed.ads.example.com.", 65280)
    assert server.udp_raw(query.to_wire()) is not None, "no response"
    eventually(lambda: assert_equal(log_names(admin, 1), ["typed.ads.example.com"]))
    assert get_json(f"{admin}/log", limit=1)[0]["type"] == "TYPE65280"


@pytest.mark.parametrize("limit", [1, 3, 5])
def test_log_honours_limit_newest_first(server, admin, limit):
    """contract.md, Admin API, /log: most recent queries, newest first, at most "limit" entries"""
    names = [f"log{i}.ads.example.com" for i in range(5)]
    for name in names:
        server.udp(name + ".", "A")
    eventually(lambda: assert_equal(log_names(admin, limit), names[::-1][:limit]))


def test_log_limit_zero(server, admin):
    """contract.md, Admin API, /log: limit is a non-negative integer"""
    server.udp("ads.example.com.", "A")
    assert get_json(f"{admin}/log", limit=0) == []


def test_log_limit_larger_than_log_returns_everything(server, admin):
    """contract.md, Admin API, /log: one entry per query counted in "queries"; fewer entries than limit returns all of them"""
    server.udp("one.ads.example.com.", "A")
    server.tcp("two.ads.example.com.", "A")
    counted = settled(lambda: get_json(f"{admin}/stats"))["queries"]
    entries = get_json(f"{admin}/log", limit=1000)
    assert len(entries) == counted
    assert [norm(entry["name"]) for entry in entries[:2]] == ["two.ads.example.com", "one.ads.example.com"]


def test_log_default_limit_is_100(server, admin):
    """contract.md, Admin API, /log: limit defaults to 100"""
    for i in range(105):
        server.udp(f"d{i}.ads.example.com.", "A")
    eventually(lambda: assert_equal(norm(get_json(f"{admin}/log")[0]["name"]), "d104.ads.example.com"))
    entries = get_json(f"{admin}/log")
    assert len(entries) == 100
    assert norm(entries[-1]["name"]) == "d5.ads.example.com"


@pytest.mark.parametrize("limit", ["abc", "-1", "1.5"])
def test_log_invalid_limit_is_400(admin, limit):
    """contract.md, Admin API, /log: a limit that is not a non-negative integer returns 400"""
    assert requests.get(f"{admin}/log?limit={limit}", timeout=TIMEOUT).status_code == 400


def test_log_ignores_uncounted_input(server, admin):
    """contract.md, Admin API, /log: one entry per query counted in "queries" (no reply, FORMERR and NOTIMP are not logged)"""
    server.udp("before.ads.example.com.", "A")
    send_uncounted(server)
    server.udp("after.ads.example.com.", "A")
    names = settled(lambda: log_names(admin, 2))
    assert names == ["after.ads.example.com", "before.ads.example.com"]


# --- /ui

def test_get_ui_returns_200_html(admin):
    """contract.md, Admin API, /ui: GET /ui returns 200 with Content-Type text/html"""
    response = requests.get(f"{admin}/ui", timeout=TIMEOUT)
    assert response.status_code == 200
    assert response.headers.get("Content-Type", "").split(";")[0].strip().lower() == "text/html"


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
def test_ui_method_not_in_table_is_405(admin, method):
    """contract.md, Admin API, /ui: other methods return 405, like every other known path"""
    assert requests.request(method, f"{admin}/ui", timeout=TIMEOUT).status_code == 405
