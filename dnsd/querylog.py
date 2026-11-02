"""QueryLog store: the /log entries (contract.md § Admin API › /log).

Fills the QueryLog role of specs/001-parser-listener/contracts/interfaces.md § 3.
"""
import threading
from collections import deque
from itertools import islice

from dnsd.listener import LogEntry

KEEP = 1000  # contract.md § /log: keep at least the 1000 most recent entries (DC-1)


class QueryLog:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: deque[LogEntry] = deque(maxlen=KEEP)  # oldest first

    def append(self, entry: LogEntry) -> None:
        with self._lock:
            self._entries.append(entry)

    def recent(self, limit: int) -> list[LogEntry]:
        with self._lock:
            return list(islice(reversed(self._entries), max(limit, 0)))