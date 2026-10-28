"""A fake APC mini for trying the app without hardware (--simulate).

Everything here is clearly labelled SIMULATED in the GUI. It exists so the
monitor and LED test screens can be explored and tested on any computer; it
proves nothing about the real controller.
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time

import mido

from . import apc_mini

log = logging.getLogger(__name__)

SIM_PORT = "SIMULATED APC MINI (no hardware)"


class FakeInputPort:
    """Generates fader moves and pad presses on a background thread."""

    def __init__(self, name: str, callback):
        self.name = name
        self._callback = callback
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        t0 = time.time()
        while not self._stop.wait(0.05):
            t = time.time() - t0
            fader = int(t) % len(apc_mini.FADER_CCS)
            value = int(63.5 + 63.5 * math.sin(t * 2))
            self._callback(mido.Message("control_change", channel=0,
                                        control=apc_mini.FADER_CCS[fader], value=value))
            if random.random() < 0.03:
                note = random.choice(apc_mini.GRID_NOTES + apc_mini.TRACK_BUTTON_NOTES
                                     + apc_mini.SCENE_BUTTON_NOTES)
                self._callback(mido.Message("note_on", channel=0, note=note, velocity=127))
                time.sleep(0.1)
                self._callback(mido.Message("note_off", channel=0, note=note, velocity=127))

    def close(self) -> None:
        self._stop.set()


class FakeOutputPort:
    """Accepts LED messages and only logs them."""

    def __init__(self, name: str):
        self.name = name
        self.sent: list[mido.Message] = []

    def send(self, msg: mido.Message) -> None:
        self.sent.append(msg)
        log.debug("SIMULATED LED send: %s", msg)

    def close(self) -> None:
        pass


def open_input(name, callback=None):
    return FakeInputPort(name, callback)


def open_output(name):
    return FakeOutputPort(name)
