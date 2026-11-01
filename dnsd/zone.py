"""Local zone: zone file loading and the ZoneStore.

Interfaces: specs/001-parser-listener/contracts/interfaces.md § 3 (ZoneStore role),
specs/002-zone-forwarder/contracts/modules.md. Behaviour: contract.md § Zone file.
"""
import ipaddress
import threading

from dnsd.listener import Answer, Invalid, NoData, NotLocal, NXDomain
from dnsd.parser import (
    AAAA,
    CLASS_IN,
    CNAME,
    TYPE_A,
    TYPE_AAAA,
    TYPE_CNAME,
    A,
    Name,
    ResourceRecord,
    type_from_text,
)

_ZONE_TYPES = (TYPE_A, TYPE_AAAA, TYPE_CNAME)
_MAX_TTL = 0xFFFFFFFF


class ZoneStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_name: dict[Name, list[ResourceRecord]] = {}
        self._suffixes: set[Name] = set()

    def _recompute_suffixes(self) -> None:
        """Local zone suffixes from the current names (contract.md § Zone file). Lock held."""
        self._suffixes = {name.parent() for name in self._by_name if name.labels}

    def lookup(self, name: Name, qtype: int) -> Answer | NoData | NXDomain | NotLocal:
        with self._lock:
            return NotLocal()

    def records(self) -> list[ResourceRecord]:
        with self._lock:
            return [record for records in self._by_name.values() for record in records]

    def add(self, record: ResourceRecord) -> None:
        with self._lock:
            records = self._by_name.get(record.name)
            if records is None:
                self._by_name[record.name] = [record]
                self._recompute_suffixes()
                return
            for index, existing in enumerate(records):
                if existing == record:  # identity ignores TTL: replace it
                    records[index] = record
                    return
            records.append(record)

    def remove(self, name: Name, rtype: int) -> int:
        with self._lock:
            records = self._by_name.get(name)
            if records is None:
                return 0
            kept = [record for record in records if record.rtype != rtype]
            removed = len(records) - len(kept)
            if kept:
                self._by_name[name] = kept
            else:
                del self._by_name[name]
                self._recompute_suffixes()
            return removed

    def make_record(self, name_text: str, type_text: str, ttl: int, value_text: str
                    ) -> ResourceRecord | Invalid:
        try:
            name = Name.from_text(name_text)
            rtype = type_from_text(type_text)
            if rtype not in _ZONE_TYPES:
                return Invalid(f"type {type_text} is not A, AAAA or CNAME")
            if type(ttl) is not int or not 0 <= ttl <= _MAX_TTL:
                return Invalid("ttl must be an integer 0-4294967295")
            rdata: A | AAAA | CNAME
            if rtype == TYPE_A:
                rdata = A(ipaddress.IPv4Address(value_text))
            elif rtype == TYPE_AAAA:
                address = ipaddress.IPv6Address(value_text)
                if address.scope_id is not None:
                    return Invalid("IPv6 address must not have a scope ID")
                rdata = AAAA(address)
            else:
                rdata = CNAME(Name.from_text(value_text))
            return ResourceRecord(name, rtype, CLASS_IN, ttl, rdata)
        except ValueError as exc:
            return Invalid(str(exc))

    def value_text(self, record: ResourceRecord) -> str:
        rdata = record.rdata
        if isinstance(rdata, CNAME):
            return rdata.target.to_text()
        if isinstance(rdata, A | AAAA):
            return str(rdata.address)
        return ""


def load_zone(path: str) -> ZoneStore:
    """Read the zone file once (contract.md § Zone file; research R-1, R-3).

    Raises OSError if the file cannot be read and ValueError for a malformed line.
    """
    store = ZoneStore()
    with open(path, encoding="utf-8") as file:
        for number, line in enumerate(file, start=1):
            fields = line.split(";", 1)[0].split()
            if not fields:
                continue
            if len(fields) != 5:
                raise ValueError(f"{path}:{number}: expected name ttl class type value")
            name, ttl, rclass, rtype, value = fields
            if not name.endswith("."):
                raise ValueError(f"{path}:{number}: name {name} is not absolute (no trailing dot)")
            if not (ttl.isascii() and ttl.isdigit()):
                raise ValueError(f"{path}:{number}: ttl {ttl} is not a number")
            if rclass.upper() != "IN":
                raise ValueError(f"{path}:{number}: class {rclass} is not IN")
            record = store.make_record(name, rtype, int(ttl), value)
            if isinstance(record, ResourceRecord):
                store.add(record)
                continue
            raise ValueError(f"{path}:{number}: {record.reason}")
    return store
