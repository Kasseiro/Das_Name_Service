"""Entry point: python -m dnsd (contract.md § Command line)."""
import argparse
import sys

from dnsd.blocklist import load_blocklist
from dnsd.forwarder import make_handler
from dnsd.listener import (
    Config,
    PlaceholderCache,
    PlaceholderQueryLog,
    ServerState,
    Stats,
    serve,
)
from dnsd.zone import load_zone


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
    try:
        zone = load_zone(args.zone)
        blocklist = load_blocklist(args.blocklist)
    except (OSError, ValueError) as exc:
        print(f"dnsd: {exc}", file=sys.stderr)
        sys.exit(1)
    state = ServerState(
        config,
        zone,
        blocklist,
        PlaceholderCache(),
        Stats(),
        PlaceholderQueryLog(),
    )
    serve(state, make_handler(state))


if __name__ == "__main__":
    main()
