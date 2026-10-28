"""Start the bridge with its HTML interface in a desktop window.

    py -3.12 run_bridge.py              real APC mini
    py -3.12 run_bridge.py --simulate   fake APC mini, to try it out
    py -3.12 run_bridge.py --browser    use your web browser instead of a window

The window is provided by pywebview, which uses Microsoft Edge WebView2
(already part of Windows 11). If pywebview is not installed, the interface
opens in the default browser instead.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import webbrowser
from pathlib import Path

APP_NAME = "APC mini - Titan Go Bridge"


def app_folder() -> Path:
    """Where settings and logs live: next to the .exe, or the current folder."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bridge", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--simulate", action="store_true", help="use a fake APC mini")
    parser.add_argument("--browser", action="store_true", help="open in the web browser, not a window")
    parser.add_argument("--port", type=int, default=0, help="local port (default: any free port)")
    args = parser.parse_args(argv)

    folder = app_folder()
    (folder / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(folder / "logs" / "bridge.log", encoding="utf-8")])

    from .app_core import BridgeCore
    from .web_server import make_server, serve_in_background

    core = BridgeCore(folder, simulate_midi=args.simulate)
    core.start()
    server, url = make_server(core, args.port)
    serve_in_background(server)
    logging.getLogger(__name__).info("Interface at %s", url)

    try:
        webview = None
        if not args.browser:
            try:
                import webview  # pywebview
            except ImportError:
                print("pywebview is not installed, opening the interface in your browser instead.")
        if webview is not None:
            webview.create_window(APP_NAME + (" [SIMULATED APC]" if args.simulate else ""), url,
                                  width=1340, height=900, min_size=(1100, 720))
            webview.start()
        else:
            webbrowser.open(url)
            print(f"{APP_NAME} is running at {url}\nPress Ctrl+C here to stop it.")
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        core.shutdown()   # output OFF (stream terminated), LEDs we lit off, ports closed
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
