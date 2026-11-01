# Contract: public names of the 002 modules

This file lists the names `dnsd/zone.py`, `dnsd/blocklist.py` and `dnsd/forwarder.py` make public.
It does not change [001 contracts/interfaces.md](../../001-parser-listener/contracts/interfaces.md),
which stays binding (Principle IX): the store classes have exactly the methods of their role there,
and every shared type is imported from `dnsd.parser` or `dnsd.listener`.

Only `__main__.py` imports these names. The listener and the admin API (004) reach the stores
through `ServerState` and never import these modules.

## `dnsd.zone`

```python
class ZoneStore:                 # fills the ZoneStore role; exactly the six methods of interfaces.md § 3
    def __init__(self) -> None: ...          # empty store

def load_zone(path: str) -> ZoneStore: ...
    # contract.md § Zone file; research R-1. Raises OSError (cannot read) or
    # ValueError("<path>:<line>: <reason>") (malformed line, bad UTF-8).
```

## `dnsd.blocklist`

```python
class Blocklist:                 # fills the Blocklist role; exactly the four methods of interfaces.md § 3
    def __init__(self) -> None: ...          # empty store

def load_blocklist(path: str) -> Blocklist: ...
    # contract.md § Blocklist file; research R-2. Raises OSError or ValueError as load_zone.
```

## `dnsd.forwarder`

```python
from dnsd.listener import Handler, ServerState
from dnsd.parser import Message, Question

def make_handler(state: ServerState) -> Handler: ...
    # The real resolution handler (spec FR-020 – FR-025; 001 interfaces.md § 2).

def exchange(upstream: tuple[str, int], question: Question) -> Message | None: ...
    # One upstream exchange within 2 s (spec FR-015 – FR-019; research R-7).
    # None on timeout or failure. Never raises for network errors.
```

`exchange` is public only so that `make_handler` and a scratch check can call it; no other module
uses it.

## `dnsd.__main__` (changed)

After argparse: `zone = load_zone(args.zone)`, `blocklist = load_blocklist(args.blocklist)`; on
`OSError` or `ValueError` print `dnsd: <message>` to stderr and exit 1. Build `ServerState(config,
zone, blocklist, PlaceholderCache(), Stats(), PlaceholderQueryLog())` and call
`serve(state, make_handler(state))`.
