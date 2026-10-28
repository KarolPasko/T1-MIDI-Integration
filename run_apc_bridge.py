"""Convenience launcher: double-click or run `py -3.12 run_apc_bridge.py`."""

import sys

from apc_bridge.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
