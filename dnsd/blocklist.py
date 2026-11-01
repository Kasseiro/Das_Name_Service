"""Blocklist: blocklist file loading and the Blocklist store.

Interfaces: specs/001-parser-listener/contracts/interfaces.md § 3 (Blocklist role),
specs/002-zone-forwarder/contracts/modules.md. Behaviour: contract.md § Blocklist file.
"""
import threading

from dnsd.parser import Name


class Blocklist:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._listed: dict[Name, None] = {}  # insertion-ordered set; first spelling kept

    def is_blocked(self, name: Name) -> bool:
        with self._lock:
            candidate = name
            while True:
                if candidate in self._listed:
                    return True
                if not candidate.labels:
                    return False
                candidate = candidate.parent()

    def domains(self) -> list[Name]:
        with self._lock:
            return list(self._listed)

    def add(self, name: Name) -> None:
        with self._lock:
            self._listed.setdefault(name, None)

    def remove(self, name: Name) -> bool:
        with self._lock:
            if name in self._listed:
                del self._listed[name]
                return True
            return False


def load_blocklist(path: str) -> Blocklist:
    """Read the blocklist file once (contract.md § Blocklist file; research R-2, R-3).

    Text from the first "#" to the end of a line is a comment. Raises OSError if the file
    cannot be read and ValueError for a malformed line.
    """
    store = Blocklist()
    with open(path, encoding="utf-8") as file:
        for number, line in enumerate(file, start=1):
            fields = line.split("#", 1)[0].split()
            if not fields:
                continue
            if len(fields) != 1:
                raise ValueError(f"{path}:{number}: expected one domain")
            try:
                name = Name.from_text(fields[0])
            except ValueError as exc:
                raise ValueError(f"{path}:{number}: {exc}") from exc
            store.add(name)
    return store
