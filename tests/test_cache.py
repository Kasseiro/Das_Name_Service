"""Cache: forwarded answers are reused until their TTL runs out.

The fake upstream counts the queries it receives, which shows from outside
whether an answer came from the cache.
"""
import time

import dns.flags
import dns.message
import dns.rcode
import dns.rrset
import pytest
import requests
from helpers import addresses, log_results, stats

NAME = "cached.example.org."
TIMEOUT = 2
SHORT_TTL = 1
PAST_SHORT_TTL = 2.3  # seconds: longer than SHORT_TTL under any rounding


# --- within the TTL

def test_repeat_query_is_not_sent_upstream_again(server, upstream):
    """contract.md, Scope: TTL-respecting cache"""
    upstream.set_answer(NAME, "A", 300, "192.0.2.50")
    first = server.udp(NAME, "A")
    second = server.udp(NAME, "A")
    third = server.udp(NAME, "A")
    assert addresses(first) == addresses(second) == addresses(third) == ["192.0.2.50"]
    assert len(upstream.queries) == 1


def test_cached_answer_survives_a_change_upstream(server, upstream):
    """contract.md, Scope: TTL-respecting cache (an answer is reused while its TTL lasts)"""
    upstream.set_answer(NAME, "A", 300, "192.0.2.50")
    server.udp(NAME, "A")
    upstream.set_answer(NAME, "A", 300, "192.0.2.51")
    assert addresses(server.udp(NAME, "A")) == ["192.0.2.50"]


def test_cached_answer_keeps_response_shape(server, upstream):
    """contract.md, Responses: anything else -> as upstream, AA=0; RA is set in every response"""
    upstream.set_answer(NAME, "A", 300, "192.0.2.50", "192.0.2.52")
    server.udp(NAME, "A")
    response = server.udp(NAME, "A")
    assert response.rcode() == dns.rcode.NOERROR
    assert sorted(addresses(response)) == ["192.0.2.50", "192.0.2.52"]
    assert not response.flags & dns.flags.AA
    assert response.flags & dns.flags.RA


def test_cached_ttl_counts_down(server, upstream):
    """contract.md, Cache: each TTL is reduced by the time the reply has spent in the cache, to within one second"""
    upstream.set_answer(NAME, "A", 300, "192.0.2.50")
    before_first = time.monotonic()
    assert server.udp(NAME, "A").answer[0].ttl == 300
    after_first = time.monotonic()
    time.sleep(3.2)
    before_second = time.monotonic()
    response = server.udp(NAME, "A")
    after_second = time.monotonic()
    assert len(upstream.queries) == 1, "the second answer did not come from the cache"
    longest, shortest = after_second - before_first, before_second - after_first
    assert 300 - longest - 1 <= response.answer[0].ttl <= 300 - shortest + 1


def test_cached_ttl_right_after_caching(server, upstream):
    """contract.md, Cache: each TTL is reduced by the time the reply has spent in the cache, to within one second"""
    upstream.set_answer(NAME, "A", 300, "192.0.2.50")
    server.udp(NAME, "A")
    assert server.udp(NAME, "A").answer[0].ttl in (299, 300)


def test_entry_lives_for_the_lowest_ttl_in_the_answer(server, upstream):
    """contract.md, Cache: a reply is cached for the lowest TTL in its answer section"""
    upstream.set_answer(NAME, "A", SHORT_TTL, "192.0.2.50")
    upstream.additional = [dns.rrset.from_text("extra.example.org.", 300, "IN", "A", "192.0.2.99")]
    server.udp(NAME, "A")
    time.sleep(PAST_SHORT_TTL)
    server.udp(NAME, "A")
    assert len(upstream.queries) == 2


def test_cached_answer_carries_the_new_querys_id_and_question(server, upstream):
    """contract.md, Responses: in every response the ID and the question are copied from the query"""
    upstream.set_answer(NAME, "A", 300, "192.0.2.50")
    server.udp(NAME, "A", qid=0x1111)
    query = dns.message.make_query("CACHED.Example.Org.", "A", id=0x2222).to_wire()
    wire = server.udp_raw(query)
    assert wire is not None, "no response"
    assert wire[:2] == b"\x22\x22"
    assert wire[12 : len(query)] == query[12:]
    assert addresses(dns.message.from_wire(wire)) == ["192.0.2.50"]


def test_cached_answer_over_tcp(server, upstream):
    """contract.md, TCP: the same rules apply as over UDP"""
    upstream.set_answer(NAME, "A", 300, "192.0.2.50")
    server.udp(NAME, "A")
    assert addresses(server.tcp(NAME, "A")) == ["192.0.2.50"]


# --- what a cache entry covers

def test_cache_is_per_type(server, upstream):
    """contract.md, Responses: anything else -> as upstream (a cached A answer must not answer an AAAA query)"""
    upstream.set_answer(NAME, "A", 300, "192.0.2.50")
    upstream.set_answer(NAME, "AAAA", 300, "2001:db8::50")
    server.udp(NAME, "A")
    assert addresses(server.udp(NAME, "AAAA")) == ["2001:db8::50"]
    assert addresses(server.udp(NAME, "A")) == ["192.0.2.50"]
    assert sorted(q.rdtype for q in upstream.queries) == ["A", "AAAA"]


def test_cache_is_per_name(server, upstream):
    """contract.md, Responses: anything else -> as upstream (a cached answer must not answer another name)"""
    upstream.set_answer(NAME, "A", 300, "192.0.2.50")
    upstream.set_answer("other.example.org.", "A", 300, "192.0.2.60")
    upstream.set_answer("sub." + NAME, "A", 300, "192.0.2.61")
    server.udp(NAME, "A")
    assert addresses(server.udp("other.example.org.", "A")) == ["192.0.2.60"]
    assert addresses(server.udp("sub." + NAME, "A")) == ["192.0.2.61"]
    assert len(upstream.queries) == 3


# --- after the TTL

def test_expired_answer_is_fetched_again(server, upstream):
    """contract.md, Scope: TTL-respecting cache (an answer is not reused after its TTL)"""
    upstream.set_answer(NAME, "A", SHORT_TTL, "192.0.2.50")
    assert addresses(server.udp(NAME, "A")) == ["192.0.2.50"]
    upstream.set_answer(NAME, "A", SHORT_TTL, "192.0.2.51")
    time.sleep(PAST_SHORT_TTL)
    assert addresses(server.udp(NAME, "A")) == ["192.0.2.51"]
    assert len(upstream.queries) == 2


def test_each_answer_expires_by_its_own_ttl(server, upstream):
    """contract.md, Scope: TTL-respecting cache"""
    upstream.set_answer("short.example.org.", "A", SHORT_TTL, "192.0.2.70")
    upstream.set_answer("long.example.org.", "A", 300, "192.0.2.71")
    server.udp("short.example.org.", "A")
    server.udp("long.example.org.", "A")
    time.sleep(PAST_SHORT_TTL)
    server.udp("short.example.org.", "A")
    server.udp("long.example.org.", "A")
    asked = [str(q.name).lower() for q in upstream.queries]
    assert asked.count("short.example.org.") == 2
    assert asked.count("long.example.org.") == 1


# --- what is not cached

def test_nxdomain_without_soa_is_not_cached(server, upstream):
    """contract.md, Cache: NXDOMAIN without an SOA record in the authority section is not cached"""
    assert server.udp(NAME, "A").rcode() == dns.rcode.NXDOMAIN
    upstream.set_answer(NAME, "A", 300, "192.0.2.50")
    assert addresses(server.udp(NAME, "A")) == ["192.0.2.50"]


def test_empty_noerror_without_soa_is_not_cached(server, upstream):
    """contract.md, Cache: NOERROR with an empty answer section and no SOA record is not cached"""
    upstream.set_answer(NAME, "A", 300)
    first = server.udp(NAME, "A")
    assert first.rcode() == dns.rcode.NOERROR and first.answer == []
    upstream.set_answer(NAME, "A", 300, "192.0.2.50")
    assert addresses(server.udp(NAME, "A")) == ["192.0.2.50"]


@pytest.mark.parametrize("soa_ttl, minimum", [(1, 1), (1, 300), (300, 1)])
def test_nxdomain_with_soa_is_cached_no_longer_than_ttl_and_minimum(server, upstream, soa_ttl, minimum):
    """contract.md, Cache: NXDOMAIN with an SOA record is cached for at most the lower of its TTL and MINIMUM; RFC 2308"""
    soa = f"ns1.example.org. hostmaster.example.org. 1 7200 3600 1209600 {minimum}"
    upstream.authority = [dns.rrset.from_text("example.org.", soa_ttl, "IN", "SOA", soa)]
    assert server.udp(NAME, "A").rcode() == dns.rcode.NXDOMAIN
    upstream.authority = []
    upstream.set_answer(NAME, "A", 300, "192.0.2.50")
    time.sleep(PAST_SHORT_TTL)
    assert addresses(server.udp(NAME, "A")) == ["192.0.2.50"]


def test_servfail_from_timeout_is_not_cached(server, upstream):
    """contract.md, Cache: SERVFAIL is never cached, whether from the upstream or the server itself"""
    upstream.mode = "silent"
    assert server.udp(NAME, "A", timeout=3.5).rcode() == dns.rcode.SERVFAIL
    upstream.mode = "normal"
    upstream.set_answer(NAME, "A", 300, "192.0.2.50")
    assert addresses(server.udp(NAME, "A")) == ["192.0.2.50"]


@pytest.mark.parametrize("rcode", [dns.rcode.SERVFAIL, dns.rcode.REFUSED])
def test_error_reply_from_upstream_is_not_cached(server, upstream, rcode):
    """contract.md, Cache: SERVFAIL is never cached, and neither is a reply with any other RCODE"""
    upstream.rcode = rcode
    assert server.udp(NAME, "A").rcode() == rcode
    upstream.rcode = None
    upstream.set_answer(NAME, "A", 300, "192.0.2.50")
    assert addresses(server.udp(NAME, "A")) == ["192.0.2.50"]


# --- changes through the API beat the cache

def test_blocking_a_cached_name_takes_effect_immediately(server, admin, upstream):
    """contract.md, Admin API: changes through the API take effect immediately"""
    upstream.set_answer(NAME, "A", 300, "192.0.2.50")
    server.udp(NAME, "A")
    assert requests.post(f"{admin}/blocklist", json={"domain": NAME}, timeout=TIMEOUT).status_code == 201
    assert addresses(server.udp(NAME, "A")) == ["0.0.0.0"]


def test_local_record_for_a_cached_name_takes_effect_immediately(server, admin, upstream):
    """contract.md, Admin API: changes through the API take effect immediately"""
    upstream.set_answer(NAME, "A", 300, "192.0.2.50")
    server.udp(NAME, "A")
    record = {"name": NAME, "type": "A", "ttl": 60, "value": "192.168.9.9"}
    assert requests.post(f"{admin}/records", json=record, timeout=TIMEOUT).status_code == 201
    response = server.udp(NAME, "A")
    assert addresses(response) == ["192.168.9.9"]
    assert response.flags & dns.flags.AA


# --- stats and log

def test_stats_count_misses_and_hits(server, admin, upstream):
    """contract.md, Admin API, /stats: cache_misses counts queries sent to the upstream, cache_hits queries answered from the cache"""
    upstream.set_answer(NAME, "A", 300, "192.0.2.50")
    server.udp(NAME, "A")
    after_first = stats(admin)
    assert (after_first["cache_misses"], after_first["cache_hits"]) == (1, 0)
    server.udp(NAME, "A")
    server.udp(NAME, "A")
    after_repeats = stats(admin)
    assert (after_repeats["cache_misses"], after_repeats["cache_hits"]) == (1, 2)


def test_stats_count_a_miss_after_expiry(server, admin, upstream):
    """contract.md, Admin API, /stats: cache_misses counts queries sent to the upstream"""
    upstream.set_answer(NAME, "A", SHORT_TTL, "192.0.2.50")
    server.udp(NAME, "A")
    time.sleep(PAST_SHORT_TTL)
    server.udp(NAME, "A")
    after = stats(admin)
    assert (after["cache_misses"], after["cache_hits"]) == (2, 0)


def test_cache_hit_is_logged_as_cached(server, admin, upstream):
    """contract.md, Admin API, /log: result "cached" for queries answered from the cache, "forwarded" for the upstream"""
    upstream.set_answer(NAME, "A", 300, "192.0.2.50")
    server.udp(NAME, "A")
    server.udp(NAME, "A")
    assert log_results(admin, 2) == [("cached.example.org", "cached"), ("cached.example.org", "forwarded")]
