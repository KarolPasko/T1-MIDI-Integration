"""Launcher for the sACN trigger test: `py -3.12 run_sacn_test.py`."""

import sys

from apc_bridge.sacn_test import main

if __name__ == "__main__":
    sys.exit(main())
