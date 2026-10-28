"""Start the app:  py -3.12 -m apc_bridge            (real hardware)
                   py -3.12 -m apc_bridge --simulate (no hardware, fake APC mini)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apc_bridge", description=__doc__)
    parser.add_argument("--simulate", action="store_true",
                        help="use a fake APC mini instead of real MIDI ports")
    parser.add_argument("--debug", action="store_true", help="more detailed log")
    args = parser.parse_args(argv)

    log_dir = Path.cwd() / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_dir / "apc_bridge.log", encoding="utf-8")],
    )

    try:
        import mido  # noqa: F401
    except ImportError:
        print("The 'mido' library is missing for this Python "
              f"({sys.version.split()[0]}). Install it with:\n"
              "    py -3.12 -m pip install -r requirements.txt\n"
              "then start the app with:  py -3.12 run_apc_bridge.py\n"
              "(python-rtmidi only has ready-made Windows downloads for Python 3.8-3.12.)",
              file=sys.stderr)
        return 1
    try:
        import tkinter as tk
    except ImportError:
        print("tkinter is missing. Reinstall Python from python.org and keep "
              "'tcl/tk and IDLE' ticked.", file=sys.stderr)
        return 1

    from .gui import App

    root = tk.Tk()
    App(root, simulate=args.simulate)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
