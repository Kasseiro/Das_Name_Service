"""Entry point: python -m dnsd (contract.md § Command line)."""
import argparse

from dnsd.listener import (
    Config,
    PlaceholderBlocklist,
    PlaceholderCache,
    PlaceholderQueryLog,
    PlaceholderZoneStore,
    ServerState,
    Stats,
    serve,
    stub_handler,
)


def host_port(text: str) -> tuple[str, int]:
    """Split host:port at the last colon; int() raising ValueError makes argparse exit 2."""
    host, _, port = text.rpartition(":")
    return host, int(port)


def main() -> None:
    parser = argparse.ArgumentParser(prog="dnsd")
    parser.add_argument("--listen", type=host_port, required=True)
    parser.add_argument("--admin", type=host_port, required=True)
    parser.add_argument("--upstream", type=host_port, required=True)
    parser.add_argument("--zone", required=True)
    parser.add_argument("--blocklist", required=True)
    args = parser.parse_args()
    config = Config(args.listen, args.admin, args.upstream, args.zone, args.blocklist)
    state = ServerState(
        config,
        PlaceholderZoneStore(),
        PlaceholderBlocklist(),
        PlaceholderCache(),
        Stats(),
        PlaceholderQueryLog(),
    )
    serve(state, stub_handler)


if __name__ == "__main__":
    main()
