"""MIDI INPUT only: listens to the controller and queues events for the GUI.

This module never sends anything. MIDI output (LEDs) lives in led_output.py,
and the two never talk to each other directly, so an incoming button press
can never trigger an outgoing message by itself (no feedback loops).
"""

from __future__ import annotations

import logging
import queue
from typing import Callable

from .midi_events import MidiEvent, event_from_message

log = logging.getLogger(__name__)


class MidiInputError(RuntimeError):
    pass


class MidiInputListener:
    """Opens one input port and puts a MidiEvent on `events` for each message.

    The callback runs on python-rtmidi's own background thread. It only does
    a thread-safe queue.put(); the GUI drains the queue on its own thread.
    """

    def __init__(self, events: "queue.Queue[MidiEvent]",
                 opener: Callable | None = None):
        self._events = events
        self._opener = opener
        self._port = None
        self.port_name: str | None = None

    @property
    def is_open(self) -> bool:
        return self._port is not None

    def open(self, name: str) -> None:
        self.close()
        opener = self._opener
        if opener is None:
            import mido
            opener = mido.open_input
        try:
            self._port = opener(name, callback=self._on_message)
        except Exception as exc:
            self._port = None
            raise MidiInputError(
                f"Could not open MIDI input '{name}': {exc}. "
                "Is another program (Titan Go, Ableton, a DAW) already using it?"
            ) from exc
        self.port_name = name
        log.info("MIDI input opened: %s", name)

    def _on_message(self, msg) -> None:
        try:
            self._events.put_nowait(event_from_message(msg))
        except Exception:  # never let an exception escape into rtmidi's thread
            log.exception("Failed to decode MIDI message %r", msg)

    def close(self) -> None:
        port, self._port = self._port, None
        if port is not None:
            try:
                port.close()
            except Exception:
                log.exception("Error closing MIDI input %s", self.port_name)
            log.info("MIDI input closed: %s", self.port_name)
        self.port_name = None
