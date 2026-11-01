"""DNS message model, wire decoding and encoding (RFC 1035).

Interfaces: specs/001-parser-listener/contracts/interfaces.md § 1.
"""
import struct
from dataclasses import dataclass, field
from ipaddress import IPv4Address, IPv6Address

# --- constants (FR-025 codes; RFC 1035 classes and RCODEs)
TYPE_A, TYPE_NS, TYPE_CNAME, TYPE_SOA, TYPE_PTR = 1, 2, 5, 6, 12
TYPE_MX, TYPE_TXT, TYPE_AAAA, TYPE_OPT, TYPE_ANY = 15, 16, 28, 41, 255
CLASS_IN = 1
NOERROR, FORMERR, SERVFAIL, NXDOMAIN, NOTIMP = 0, 1, 2, 3, 4

_U16 = 0xFFFF
_U32 = 0xFFFFFFFF


def _check_range(value: int, high: int, what: str) -> None:
    if not isinstance(value, int) or not 0 <= value <= high:
        raise ValueError(f"{what} out of range: {value!r}")


def _check_type(value: object, cls: type, what: str) -> None:
    if not isinstance(value, cls):
        raise ValueError(f"{what} must be {cls.__name__}")  # noqa: TRY004 - contract: constructors raise ValueError


def _check_name(value: object, what: str) -> None:
    _check_type(value, Name, what)


# --- names

@dataclass(frozen=True, eq=False)
class Name:
    labels: tuple[bytes, ...]

    def __post_init__(self) -> None:
        _check_type(self.labels, tuple, "labels")
        wire_length = 1
        for label in self.labels:
            if not isinstance(label, bytes) or not 1 <= len(label) <= 63:
                raise ValueError("each label must be 1-63 bytes")
            wire_length += len(label) + 1
        if wire_length > 255:
            raise ValueError("name longer than 255 bytes")

    def _key(self) -> tuple[bytes, ...]:
        return tuple(label.lower() for label in self.labels)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Name):
            return NotImplemented
        return self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())

    def parent(self) -> "Name":
        if not self.labels:
            raise ValueError("the root has no parent")
        return Name(self.labels[1:])

    def is_subdomain_of(self, other: "Name") -> bool:
        n = len(other.labels)
        if n > len(self.labels):
            return False
        if n == 0:
            return True
        return self._key()[-n:] == other._key()

    def to_text(self) -> str:
        if not self.labels:
            return "."
        parts = []
        for label in self.labels:
            chars = []
            for byte in label:
                if 0x21 <= byte <= 0x7E and byte not in (0x2E, 0x5C):
                    chars.append(chr(byte))
                else:
                    chars.append(f"\\{byte:03d}")
            parts.append("".join(chars))
        return ".".join(parts) + "."

    @classmethod
    def from_text(cls, text: str) -> "Name":
        if text == "":
            raise ValueError("empty name")
        if text == ".":
            return cls(())
        labels: list[bytes] = []
        current = bytearray()
        i = 0
        while i < len(text):
            char = text[i]
            if char == "\\":
                if i + 1 >= len(text):
                    raise ValueError("bad escape at end of name")
                digits = text[i + 1:i + 4]
                if text[i + 1].isascii() and text[i + 1].isdigit():
                    if len(digits) != 3 or not (digits.isascii() and digits.isdigit()):
                        raise ValueError("bad \\DDD escape")
                    value = int(digits)
                    if value > 255:
                        raise ValueError("bad \\DDD escape")
                    current.append(value)
                    i += 4
                else:
                    current += text[i + 1].encode()
                    i += 2
            elif char == ".":
                if not current:
                    raise ValueError("empty label")
                labels.append(bytes(current))
                current = bytearray()
                i += 1
            else:
                current += char.encode()
                i += 1
        if current:
            labels.append(bytes(current))
        return cls(tuple(labels))


# --- header and question

@dataclass(frozen=True)
class Header:
    id: int = 0
    qr: bool = False
    opcode: int = 0
    aa: bool = False
    tc: bool = False
    rd: bool = False
    ra: bool = False
    z: int = 0
    rcode: int = 0

    def __post_init__(self) -> None:
        _check_range(self.id, _U16, "id")
        _check_range(self.opcode, 15, "opcode")
        _check_range(self.z, 7, "z")
        _check_range(self.rcode, 15, "rcode")


@dataclass(frozen=True)
class Question:
    name: Name
    qtype: int
    qclass: int

    def __post_init__(self) -> None:
        _check_name(self.name, "question name")
        _check_range(self.qtype, _U16, "qtype")
        _check_range(self.qclass, _U16, "qclass")


# --- RDATA (FR-023)

@dataclass(frozen=True)
class A:
    address: IPv4Address

    def __post_init__(self) -> None:
        _check_type(self.address, IPv4Address, "A address")


@dataclass(frozen=True)
class AAAA:
    address: IPv6Address

    def __post_init__(self) -> None:
        _check_type(self.address, IPv6Address, "AAAA address")


@dataclass(frozen=True)
class CNAME:
    target: Name

    def __post_init__(self) -> None:
        _check_name(self.target, "CNAME target")


@dataclass(frozen=True)
class NS:
    host: Name

    def __post_init__(self) -> None:
        _check_name(self.host, "NS host")


@dataclass(frozen=True)
class PTR:
    target: Name

    def __post_init__(self) -> None:
        _check_name(self.target, "PTR target")


@dataclass(frozen=True)
class MX:
    preference: int
    exchange: Name

    def __post_init__(self) -> None:
        _check_range(self.preference, _U16, "MX preference")
        _check_name(self.exchange, "MX exchange")


@dataclass(frozen=True)
class SOA:
    mname: Name
    rname: Name
    serial: int
    refresh: int
    retry: int
    expire: int
    minimum: int

    def __post_init__(self) -> None:
        _check_name(self.mname, "SOA mname")
        _check_name(self.rname, "SOA rname")
        for what in ("serial", "refresh", "retry", "expire", "minimum"):
            _check_range(getattr(self, what), _U32, f"SOA {what}")


@dataclass(frozen=True)
class Raw:
    data: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes) or len(self.data) > _U16:
            raise ValueError("Raw data must be bytes of at most 65535 bytes")


RData = A | AAAA | CNAME | NS | PTR | MX | SOA | Raw

_RDATA_CLASS = {
    TYPE_A: A,
    TYPE_NS: NS,
    TYPE_CNAME: CNAME,
    TYPE_SOA: SOA,
    TYPE_PTR: PTR,
    TYPE_MX: MX,
    TYPE_AAAA: AAAA,
}


@dataclass(frozen=True)
class ResourceRecord:
    name: Name
    rtype: int
    rclass: int
    ttl: int = field(compare=False)
    rdata: RData

    def __post_init__(self) -> None:
        _check_name(self.name, "record name")
        _check_range(self.rtype, _U16, "rtype")
        _check_range(self.rclass, _U16, "rclass")
        _check_range(self.ttl, _U32, "ttl")
        if type(self.rdata) is not _RDATA_CLASS.get(self.rtype, Raw):
            raise ValueError(f"rdata does not match type {self.rtype}")


@dataclass(frozen=True)
class Message:
    header: Header
    questions: list[Question] = field(default_factory=list)
    answers: list[ResourceRecord] = field(default_factory=list)
    authority: list[ResourceRecord] = field(default_factory=list)
    additional: list[ResourceRecord] = field(default_factory=list)


# --- decode results (FR-008)

@dataclass(frozen=True)
class Short:
    """Rule 1: fewer than 12 bytes."""


@dataclass(frozen=True)
class IsResponse:
    """Rule 2: QR=1."""


@dataclass(frozen=True)
class NotImp:
    """Rule 3: opcode is not 0."""

    header: Header


@dataclass(frozen=True)
class FormErr:
    """Rules 4 and 5: QDCOUNT is not 1, or the question cannot be parsed."""

    header: Header


@dataclass(frozen=True)
class Malformed:
    """decode_message failure."""


# --- type mnemonics (FR-025)

_MNEMONICS = {
    TYPE_A: "A",
    TYPE_NS: "NS",
    TYPE_CNAME: "CNAME",
    TYPE_SOA: "SOA",
    TYPE_PTR: "PTR",
    TYPE_MX: "MX",
    TYPE_TXT: "TXT",
    TYPE_AAAA: "AAAA",
    TYPE_OPT: "OPT",
    TYPE_ANY: "ANY",
}
_CODES = {text: code for code, text in _MNEMONICS.items()}


def type_to_text(code: int) -> str:
    return _MNEMONICS.get(code, f"TYPE{code}")


def type_from_text(text: str) -> int:
    upper = text.upper()
    if upper in _CODES:
        return _CODES[upper]
    digits = upper[4:]
    if upper.startswith("TYPE") and digits.isascii() and digits.isdigit():
        code = int(digits)
        if code <= _U16:
            return code
    raise ValueError(f"unknown type: {text!r}")


# --- wire decoding helpers

class _ParseError(Exception):
    """Out-of-bounds read or invalid field; never escapes the public functions."""


def _read_name(data: bytes, offset: int) -> tuple[Name, int]:
    """Read a possibly compressed name at offset (RFC 1035 4.1.4).

    Returns the name and the offset just after it in the original byte stream.
    """
    labels: list[bytes] = []
    wire_length = 1
    end: int | None = None
    visited: set[int] = set()
    pos = offset
    while True:
        if pos >= len(data):
            raise _ParseError("name runs past the end")
        length = data[pos]
        kind = length & 0xC0
        if kind == 0xC0:
            if pos + 1 >= len(data):
                raise _ParseError("pointer runs past the end")
            target = ((length & 0x3F) << 8) | data[pos + 1]
            if end is None:
                end = pos + 2
            if target >= len(data):
                raise _ParseError("pointer outside the message")
            if target in visited:
                raise _ParseError("pointer loop")
            visited.add(target)
            pos = target
            continue
        if kind != 0:
            raise _ParseError("reserved label type")
        if length == 0:
            if end is None:
                end = pos + 1
            return Name(tuple(labels)), end
        if pos + 1 + length > len(data):
            raise _ParseError("label runs past the end")
        wire_length += length + 1
        if wire_length > 255:
            raise _ParseError("name longer than 255 bytes")
        labels.append(data[pos + 1:pos + 1 + length])
        pos += 1 + length


def _read_header(data: bytes) -> tuple[Header, tuple[int, int, int, int]]:
    """Unpack the 12-byte header; every field is in range by bit width, so this cannot fail."""
    ident, flags, qdcount, ancount, nscount, arcount = struct.unpack_from("!HHHHHH", data, 0)
    header = Header(
        id=ident,
        qr=bool(flags >> 15 & 1),
        opcode=flags >> 11 & 0xF,
        aa=bool(flags >> 10 & 1),
        tc=bool(flags >> 9 & 1),
        rd=bool(flags >> 8 & 1),
        ra=bool(flags >> 7 & 1),
        z=flags >> 4 & 0x7,
        rcode=flags & 0xF,
    )
    return header, (qdcount, ancount, nscount, arcount)


def _read_question(data: bytes, offset: int) -> tuple[Question, int]:
    name, pos = _read_name(data, offset)
    if pos + 4 > len(data):
        raise _ParseError("question runs past the end")
    qtype, qclass = struct.unpack_from("!HH", data, pos)
    return Question(name, qtype, qclass), pos + 4


def decode_query(data: bytes) -> Short | IsResponse | NotImp | FormErr | Message:
    """Classify a received message by FR-008 rules 1-6, in order. Never raises."""
    if len(data) < 12:
        return Short()
    header, counts = _read_header(data)
    if header.qr:
        return IsResponse()
    if header.opcode != 0:
        return NotImp(header)
    if counts[0] != 1:
        return FormErr(header)
    try:
        question, _ = _read_question(data, 12)
    except (_ParseError, struct.error, ValueError):
        return FormErr(header)
    return Message(header, [question])


# --- encoding

def _encode_name(name: Name) -> bytes:
    return b"".join(bytes([len(label)]) + label for label in name.labels) + b"\x00"


def _encode_rdata(rdata: RData) -> bytes:
    if isinstance(rdata, (A, AAAA)):
        return rdata.address.packed
    if isinstance(rdata, (CNAME, PTR)):
        return _encode_name(rdata.target)
    if isinstance(rdata, NS):
        return _encode_name(rdata.host)
    if isinstance(rdata, MX):
        return struct.pack("!H", rdata.preference) + _encode_name(rdata.exchange)
    if isinstance(rdata, SOA):
        return (
            _encode_name(rdata.mname)
            + _encode_name(rdata.rname)
            + struct.pack("!IIIII", rdata.serial, rdata.refresh, rdata.retry,
                          rdata.expire, rdata.minimum)
        )
    return rdata.data


def _encode_record(record: ResourceRecord) -> bytes:
    rdata = _encode_rdata(record.rdata)
    return (
        _encode_name(record.name)
        + struct.pack("!HHIH", record.rtype, record.rclass, record.ttl, len(rdata))
        + rdata
    )


def encode(message: Message) -> bytes:
    h = message.header
    flags = (
        int(h.qr) << 15 | h.opcode << 11 | int(h.aa) << 10 | int(h.tc) << 9
        | int(h.rd) << 8 | int(h.ra) << 7 | h.z << 4 | h.rcode
    )
    parts = [struct.pack(
        "!HHHHHH", h.id, flags, len(message.questions), len(message.answers),
        len(message.authority), len(message.additional),
    )]
    for question in message.questions:
        parts.append(_encode_name(question.name))
        parts.append(struct.pack("!HH", question.qtype, question.qclass))
    for section in (message.answers, message.authority, message.additional):
        parts.extend(_encode_record(record) for record in section)
    return b"".join(parts)
