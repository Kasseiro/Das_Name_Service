"""Entry point: python -m dnsd (contract.md § Command line)."""
import argparse
import sys

from dnsd.api import start_admin
from dnsd.blocklist import load_blocklist
from dnsd.cache import Cache
from dnsd.forwarder import make_handler
from dnsd.listener import (
    Config,
    ServerState,
    Stats,
    serve,
)
from dnsd.querylog import QueryLog
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
        Cache(),
        Stats(),
        QueryLog(),
    )
    try:
        start_admin(state)  # 004 FR-002: before serve()
    except OSError as exc:
        print(f"dnsd: admin {args.admin[0]}:{args.admin[1]}: {exc}", file=sys.stderr)  # DC-4
        sys.exit(1)
    serve(state, make_handler(state))


if __name__ == "__main__":
    main()
