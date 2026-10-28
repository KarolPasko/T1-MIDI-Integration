"""Launcher for the bridge: `py -3.12 run_bridge.py` (add --simulate to try it without hardware)."""

import sys

from apc_bridge.app import main

if __name__ == "__main__":
    sys.exit(main())
