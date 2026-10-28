"""Protocol facts for the ORIGINAL (first-generation) AKAI APC mini.

Everything the rest of the program knows about the controller lives here, so
there is exactly one place to correct if real hardware behaves differently.

Where these facts come from
---------------------------
* DOCUMENTED: Akai Professional's "APC mini Communications Protocol" sheet for
  the first-generation unit, plus multiple independent user reports of the
  same LED velocity table. None of it has been VERIFIED on this project's own
  hardware yet. The MIDI monitor and the LED test in the app exist precisely
  to verify it - see README.md, "Verifying the protocol".

* The APC mini mk2 (2022, RGB pads) uses a DIFFERENT protocol (different
  button notes, RGB velocity palette). Nothing in this file applies to it.

Layout (all on MIDI channel 1, which mido numbers as channel 0):

    8x8 clip-launch grid   Note 0-63    bottom-left pad = 0, rows go upward,
                                        so the top-left pad is 56.
                                        LED: green / red / yellow, each steady
                                        or blinking.
    Track buttons (under   Note 64-71   single red LED: off / on / blink
      the grid, round)
    Scene buttons (right   Note 82-89   single green LED: off / on / blink
      side, round)
    Shift                  Note 98      no LED
    Faders 1-8             CC 48-55     value 0-127
    Master fader           CC 56        value 0-127

Buttons send Note On (velocity 127) when pressed and a Note Off when
released. LEDs are set by SENDING Note On to the controller: the note picks
the LED, the velocity picks the colour/state. The unit cannot report its LED
state back, so software can only remember what it last sent.
"""

from __future__ import annotations

from enum import IntEnum

import mido

# MIDI channel 1 (mido counts channels from 0).
CHANNEL = 0

GRID_NOTES = tuple(range(0, 64))
TRACK_BUTTON_NOTES = tuple(range(64, 72))
SCENE_BUTTON_NOTES = tuple(range(82, 90))
SHIFT_NOTE = 98
FADER_CCS = tuple(range(48, 57))  # 48-55 = faders 1-8, 56 = master

LED_NOTES = GRID_NOTES + TRACK_BUTTON_NOTES + SCENE_BUTTON_NOTES


class GridLed(IntEnum):
    """LED states for the 64 grid pads (velocity values)."""

    OFF = 0
    GREEN = 1
    GREEN_BLINK = 2
    RED = 3
    RED_BLINK = 4
    YELLOW = 5
    YELLOW_BLINK = 6


class RoundLed(IntEnum):
    """LED states for the single-colour round track and scene buttons."""

    OFF = 0
    ON = 1
    BLINK = 2


class LedMessageError(ValueError):
    """Raised when asked to build an LED message the APC mini does not support."""


def control_kind(note: int) -> str | None:
    """Return 'grid', 'track', 'scene' or None (no LED) for a note number."""
    if note in GRID_NOTES:
        return "grid"
    if note in TRACK_BUTTON_NOTES:
        return "track"
    if note in SCENE_BUTTON_NOTES:
        return "scene"
    return None


def allowed_states(note: int) -> tuple[IntEnum, ...]:
    """The LED states the hardware supports for this note (empty if no LED)."""
    kind = control_kind(note)
    if kind == "grid":
        return tuple(GridLed)
    if kind in ("track", "scene"):
        return tuple(RoundLed)
    return ()


def state_label(note: int, state: int) -> str:
    """Human-readable name for an LED state on a given control."""
    kind = control_kind(note)
    if kind == "grid":
        return GridLed(state).name.replace("_", " ").title()
    if kind == "track":
        return {0: "Off", 1: "Red", 2: "Red Blink"}[RoundLed(state)]
    if kind == "scene":
        return {0: "Off", 1: "Green", 2: "Green Blink"}[RoundLed(state)]
    raise LedMessageError(f"Note {note} has no LED")


def led_message(note: int, state: int) -> mido.Message:
    """Build the Note On message that sets one LED.

    Only notes and velocities listed in this module are accepted, so a typo
    elsewhere can never send an arbitrary MIDI message to the controller.
    """
    if not isinstance(note, int) or isinstance(note, bool):
        raise LedMessageError(f"Note must be an int, got {note!r}")
    states = allowed_states(note)
    if not states:
        raise LedMessageError(f"Note {note} is not an LED on the original APC mini")
    if int(state) not in [int(s) for s in states]:
        raise LedMessageError(
            f"State {state} is not supported by {describe_note(note)}; "
            f"allowed: {[int(s) for s in states]}"
        )
    return mido.Message("note_on", channel=CHANNEL, note=note, velocity=int(state))


def all_off_messages() -> list[mido.Message]:
    """Messages that switch every LED on the controller off."""
    return [led_message(n, 0) for n in LED_NOTES]


def grid_note(row: int, col: int) -> int:
    """Note number of a grid pad. row 0 is the BOTTOM row, col 0 the left column."""
    if not (0 <= row < 8 and 0 <= col < 8):
        raise ValueError("row and col must be 0-7")
    return row * 8 + col


def grid_position(note: int) -> tuple[int, int]:
    """(row, col) for a grid note, row 0 = bottom."""
    if note not in GRID_NOTES:
        raise ValueError(f"Note {note} is not a grid pad")
    return divmod(note, 8)


def describe_note(note: int) -> str:
    """Documented name of a button note, e.g. 'Pad row 1 col 1'."""
    kind = control_kind(note)
    if kind == "grid":
        row, col = grid_position(note)
        # Show rows counted from the top, as a user reads the grid.
        return f"Pad row {8 - row} col {col + 1}"
    if kind == "track":
        return f"Track button {note - 63}"
    if kind == "scene":
        return f"Scene button {note - 81}"
    if note == SHIFT_NOTE:
        return "Shift"
    return "Unknown button"


def describe_cc(cc: int) -> str:
    """Documented name of a control-change number."""
    if cc in FADER_CCS:
        return "Master fader" if cc == 56 else f"Fader {cc - 47}"
    return "Unknown control"


def is_mk2_name(port_name: str) -> bool:
    """True if a port name looks like the newer APC mini mk2."""
    lowered = port_name.lower()
    return "apc mini" in lowered and ("mk2" in lowered or "mk ii" in lowered)
