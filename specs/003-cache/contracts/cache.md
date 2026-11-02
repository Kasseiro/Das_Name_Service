# Contract: public names of `dnsd.cache`

This file lists what `dnsd/cache.py` makes public. It does not change
[001 contracts/interfaces.md](../../001-parser-listener/contracts/interfaces.md), which stays
binding (Principle IX): `Cache` has exactly the two methods of the Cache role there, and every shared
type is imported from `dnsd.parser`.

Only `__main__.py` imports this module. The handler (002) reaches the cache through
`ServerState.cache` and never imports it.

## `dnsd.cache`

```python
from dnsd.parser import Message, Name


class Cache:                     # fills the Cache role; exactly the two methods of interfaces.md § 3
    def __init__(self) -> None: ...          # empty cache

    def get(self, name: Name, qtype: int) -> Message | None: ...
        # spec FR-006 – FR-009; data-model.md § Entry life cycle.
        # A new Message: Header(rcode=...), no questions, the three sections as new lists with
        # TTLs reduced by whole seconds in the cache (never below 0). None if absent or expired.

    def put(self, name: Name, qtype: int, reply: Message) -> None: ...
        # spec FR-003 – FR-005; data-model.md § Lifetime.
        # Stores the reply's RCODE and three sections when its lifetime is > 0; otherwise no-op.
        # A reply with TC=1 has lifetime 0 (spec DC-4).
```

Private names (`_Entry`, `_lifetime`, `_aged`) are not part of the contract.

## `dnsd.__main__` (changed)

`from dnsd.cache import Cache`; build `ServerState(config, zone, blocklist, Cache(), Stats(),
PlaceholderQueryLog())`. `PlaceholderCache` is no longer imported. Nothing else changes.
