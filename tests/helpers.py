"""Small helpers shared by the test modules."""
import time

import dns.rdatatype
import requests

TIMEOUT = 2


def norm(name):
    """Names compare without case and without the trailing dot."""
    return str(name).lower().rstrip(".")


def addresses(response):
    """Every rdata in the answer section as text, in order."""
    return [rdata.to_text() for rrset in response.answer for rdata in rrset]


def records(section):
    """A section as a set of (owner, type, ttl, rdata text), for order-independent comparison."""
    return {
        (norm(rrset.name), dns.rdatatype.to_text(rrset.rdtype), rrset.ttl, rdata.to_text().lower())
        for rrset in section
        for rdata in rrset
    }


def get_json(url, **params):
    response = requests.get(url, params=params, timeout=TIMEOUT)
    assert response.status_code == 200, f"GET {response.url} -> {response.status_code}"
    return response.json()


def assert_equal(actual, expected):
    assert actual == expected


def eventually(check, timeout=1.0):
    """Retry an assertion briefly: a server may update its counters and log just after replying."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            return check()
        except AssertionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def settled(fetch):
    """Read until two reads in a row agree, so late updates are not missed."""
    previous = fetch()
    for _ in range(20):
        time.sleep(0.1)
        current = fetch()
        if current == previous:
            return current
        previous = current
    return previous


def stats(admin):
    return settled(lambda: get_json(f"{admin}/stats"))


def log_results(admin, limit):
    """(name, result) of the newest log entries, newest first."""
    entries = settled(lambda: get_json(f"{admin}/log", limit=limit))
    return [(norm(entry["name"]), entry["result"]) for entry in entries]
