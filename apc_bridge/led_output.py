"""MIDI OUTPUT to the APC mini's LEDs - and nothing else.

Every message goes through apc_mini.led_message(), which only builds Note On
messages for documented LED notes and velocities. This class has no way to
send Control Change, SysEx or anything that could be read as a lighting
command, and it only ever talks to the port it was opened on.
"""

from __future__ import annotations

import logging
from typing import Callable

from . import apc_mini

log = logging.getLogger(__name__)


class LedOutputError(RuntimeError):
    pass


class LedOutput:
    """Sends LED messages and remembers what was last sent to each LED.

    The APC mini cannot report its LED state, so `sent_state` is only "what
    this program last told it", which is what restore() puts back.
    """

    def __init__(self, opener: Callable | None = None):
        self._opener = opener
        self._port = None
        self.port_name: str | None = None
        self._sent: dict[int, int] = {}
        self.messages_sent = 0

    @property
    def is_open(self) -> bool:
        return self._port is not None

    @property
    def sent_state(self) -> dict[int, int]:
        """Copy of {note: state} for every LED last set to something other than off."""
        return {n: s for n, s in self._sent.items() if s != 0}

    def open(self, name: str) -> None:
        self.close()
        opener = self._opener
        if opener is None:
            import mido
            opener = mido.open_output
        try:
            self._port = opener(name)
        except Exception as exc:
            self._port = None
            raise LedOutputError(
                f"Could not open MIDI output '{name}': {exc}. "
                "Is another program already using the APC mini?"
            ) from exc
        self.port_name = name
        # We do not know what the LEDs show right now, so forget old state.
        self._sent.clear()
        log.info("LED output opened: %s", name)

    def close(self) -> None:
        port, self._port = self._port, None
        if port is not None:
            try:
                port.close()
            except Exception:
                log.exception("Error closing LED output %s", self.port_name)
            log.info("LED output closed: %s", self.port_name)
        self.port_name = None

    def set_led(self, note: int, state: int, force: bool = False) -> bool:
        """Set one LED. Returns True if a message was actually sent.

        Repeating the state an LED already has is skipped (unless force=True)
        to avoid flooding the controller with redundant messages.
        Raises LedMessageError for unsupported note/state, LedOutputError if
        the port is closed or sending fails (the port is then closed).
        """
        msg = apc_mini.led_message(note, state)  # validates first
        if self._port is None:
            raise LedOutputError("LED output is not open")
        if not force and self._sent.get(note) == int(state):
            return False
        try:
            self._port.send(msg)
        except Exception as exc:
            log.error("LED send failed on %s: %s", self.port_name, exc)
            self.close()
            raise LedOutputError(f"Sending to the APC mini failed: {exc}") from exc
        self._sent[note] = int(state)
        self.messages_sent += 1
        return True

    def all_off(self) -> int:
        """Switch every LED off (always sent, even if we think it is off)."""
        count = 0
        for note in apc_mini.LED_NOTES:
            count += self.set_led(note, 0, force=True)
        return count

    def restore(self, snapshot: dict[int, int]) -> int:
        """Return LEDs to a snapshot taken from sent_state. LEDs not in it go off."""
        count = 0
        for note in apc_mini.LED_NOTES:
            target = snapshot.get(note, 0)
            if target == 0 and note not in self._sent:
                continue  # never touched by us since opening
            count += self.set_led(note, target)
        return count
