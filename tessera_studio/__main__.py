"""Command line entry point: ``python -m tessera_studio``."""
from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from . import __version__
from .server import create_server
from .store import Store, default_roots


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tessera-studio", description="Browse local Tessera catalogs (read-only).")
    parser.add_argument("--store", action="append", type=Path, default=[],
                        help="Extra tessera/projects directory to scan; repeatable. Defaults are always included.")
    parser.add_argument("--port", type=int, default=8765, help="Loopback port (0 picks a free one). Default: 8765")
    parser.add_argument("--open", action="store_true", help="Open the default browser once the server is ready.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    store = Store([*args.store, *default_roots()])
    server = create_server(store, args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    found = len(store.projects())
    print(f"Tessera Studio {__version__} · {found} project(s) · {url}")
    for root in store.roots:
        print(f"  {'found  ' if root.is_dir() else 'missing'} {root}")
    print("Read-only, loopback only. Press Ctrl+C to stop.")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
