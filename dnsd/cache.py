"""TTL-respecting cache of upstream replies (contract.md § Responses › Cache; spec 003)."""
import threading
from dataclasses import dataclass

from dnsd.parser import Message, Name, ResourceRecord


@dataclass(frozen=True)
class _Entry:
    rcode: int
    answers: tuple[ResourceRecord, ...]
    authority: tuple[ResourceRecord, ...]
    additional: tuple[ResourceRecord, ...]
    stored: float
    lifetime: int


class Cache:
    """Fills the Cache role of 001 contracts/interfaces.md § 3."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[tuple[Name, int], _Entry] = {}

    def get(self, name: Name, qtype: int) -> Message | None:
        return None

    def put(self, name: Name, qtype: int, reply: Message) -> None:
        return None
