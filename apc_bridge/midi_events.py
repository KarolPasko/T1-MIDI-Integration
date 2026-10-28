"""Turn raw mido messages into display-friendly events for the monitor."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import mido

from . import apc_mini


@dataclass(frozen=True)
class MidiEvent:
    """One incoming MIDI message, already decoded for display.

    channel is 1-16 as printed on hardware (mido uses 0-15 internally).
    number is the note or controller number; value is velocity or CC value.
    """

    kind: str
    channel: int | None
    number: int | None
    value: int | None
    raw: str
    description: str
    timestamp: float = field(default_factory=time.time)

    @property
    def is_cc(self) -> bool:
        return self.kind == "Control Change"

    @property
    def is_press(self) -> bool:
        return self.kind == "Note On"

    @property
    def is_release(self) -> bool:
        return self.kind == "Note Off"


def event_from_message(msg: mido.Message, timestamp: float | None = None) -> MidiEvent:
    """Decode a mido message. Never raises for unusual message types."""
    ts = time.time() if timestamp is None else timestamp
    raw = " ".join(f"{b:02X}" for b in msg.bytes())
    channel = msg.channel + 1 if hasattr(msg, "channel") else None

    if msg.type == "note_on" and msg.velocity > 0:
        return MidiEvent("Note On", channel, msg.note, msg.velocity, raw,
                         apc_mini.describe_note(msg.note), ts)
    if msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
        # Many devices send "Note On, velocity 0" to mean release.
        return MidiEvent("Note Off", channel, msg.note, msg.velocity, raw,
                         apc_mini.describe_note(msg.note), ts)
    if msg.type == "control_change":
        return MidiEvent("Control Change", channel, msg.control, msg.value, raw,
                         apc_mini.describe_cc(msg.control), ts)
    # Anything else (sysex, clock, pitchwheel...) is shown but not interpreted.
    return MidiEvent(msg.type.replace("_", " ").title(), channel, None, None, raw, "", ts)
