"""TTL-respecting cache of upstream replies (contract.md § Responses › Cache; spec 003)."""
import threading
import time
from dataclasses import dataclass, replace

from dnsd.parser import NOERROR, Header, Message, Name, ResourceRecord


@dataclass(frozen=True)
class _Entry:
    rcode: int
    answers: tuple[ResourceRecord, ...]
    authority: tuple[ResourceRecord, ...]
    additional: tuple[ResourceRecord, ...]
    stored: float
    lifetime: int


def _lifetime(reply: Message) -> int:
    """Seconds a reply may be cached; 0 means it is not cached (research R-2)."""
    if reply.header.rcode == NOERROR and reply.answers:
        return min(rr.ttl for rr in reply.answers)
    return 0


def _aged(records: tuple[ResourceRecord, ...], age: int) -> list[ResourceRecord]:
    """New list of the records with each TTL reduced by age seconds, never below 0 (research R-3)."""
    return [replace(rr, ttl=max(rr.ttl - age, 0)) for rr in records]


class Cache:
    """Fills the Cache role of 001 contracts/interfaces.md § 3."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[tuple[Name, int], _Entry] = {}

    def get(self, name: Name, qtype: int) -> Message | None:
        with self._lock:
            entry = self._entries.get((name, qtype))
            if entry is None:
                return None
            age = int(time.monotonic() - entry.stored)
            if age >= entry.lifetime:
                del self._entries[(name, qtype)]
                return None
            return Message(
                Header(rcode=entry.rcode),
                [],
                _aged(entry.answers, age),
                _aged(entry.authority, age),
                _aged(entry.additional, age),
            )

    def put(self, name: Name, qtype: int, reply: Message) -> None:
        lifetime = _lifetime(reply)
        if lifetime <= 0:
            return
        entry = _Entry(
            reply.header.rcode,
            tuple(reply.answers),
            tuple(reply.authority),
            tuple(reply.additional),
            time.monotonic(),
            lifetime,
        )
        with self._lock:
            self._entries[(name, qtype)] = entry
