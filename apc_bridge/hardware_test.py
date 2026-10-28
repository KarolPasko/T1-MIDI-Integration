"""APC mini hardware test: a light show, a button test and a fader test.

Pure logic, like bridge.py. While a test runs, the app sends this module's
LED states instead of the mapping's, and APC mini input only goes here, so
nothing reaches the mapping engine or Titan. Tests only run while output is OFF.
"""

from __future__ import annotations

from . import apc_mini
from .apc_mini import GridLed, RoundLed

LIGHTS, BUTTONS, FADERS = "lights", "buttons", "faders"
MODES = (LIGHTS, BUTTONS, FADERS)

STEP_S = 2.0           # how long each light-show step lasts
DIAGONAL_STEPS = 3     # the diagonal part lasts this many steps
DIAGONAL_TICK_S = 0.25  # the stripes move one pad per tick
EDGE = 3               # a fader counts as fully down/up within this many MIDI steps of 0/127

ROUND_NOTES = apc_mini.TRACK_BUTTON_NOTES + apc_mini.SCENE_BUTTON_NOTES

# (name, grid state, round-button state)
SOLID_STEPS = [
    ("All red", GridLed.RED, RoundLed.ON),
    ("All green", GridLed.GREEN, RoundLed.ON),
    ("All yellow", GridLed.YELLOW, RoundLed.ON),
    ("All flashing", None, RoundLed.BLINK),   # None: each pad blinks in a different colour
]
DIAGONAL_COLOURS = (GridLed.RED, GridLed.GREEN, GridLed.YELLOW)
FLASH_COLOURS = (GridLed.RED_BLINK, GridLed.GREEN_BLINK, GridLed.YELLOW_BLINK)
CYCLE_S = STEP_S * (len(SOLID_STEPS) + DIAGONAL_STEPS)


def light_show(t: float) -> tuple[str, dict[int, int]]:
    """Step name and LED states at `t` seconds into the (looping) light show."""
    t %= CYCLE_S
    step = int(t // STEP_S)
    leds: dict[int, int] = {}
    if step < len(SOLID_STEPS):
        name, grid, rnd = SOLID_STEPS[step]
        for n in apc_mini.GRID_NOTES:
            r, c = divmod(n, 8)
            leds[n] = int(grid if grid is not None else FLASH_COLOURS[(r + c) % 3])
        for n in ROUND_NOTES:
            leds[n] = int(rnd)
        return name, leds
    phase = int(t / DIAGONAL_TICK_S)
    for n in apc_mini.GRID_NOTES:
        r, c = divmod(n, 8)
        leds[n] = int(DIAGONAL_COLOURS[(r + c + phase) % 3])
    for i, n in enumerate(apc_mini.TRACK_BUTTON_NOTES):     # a light running along the bottom row
        leds[n] = int(RoundLed.ON if (i - phase) % 8 == 0 else RoundLed.OFF)
    for i, n in enumerate(apc_mini.SCENE_BUTTON_NOTES):     # and up the right-hand column
        leds[n] = int(RoundLed.ON if (i + phase) % 8 == 0 else RoundLed.OFF)
    return "Diagonal colours", leds


class HardwareTest:
    def __init__(self, mode: str, now: float):
        if mode not in MODES:
            raise ValueError(f"Unknown test {mode!r}")
        self.mode = mode
        self.started = now
        self.seen: set[int] = set()          # buttons pressed at least once
        self.held: set[int] = set()
        self.faders = [{"value": None, "low": False, "high": False} for _ in apc_mini.FADER_CCS]

    # ------------------------------------------------------------- input
    def press(self, note: int) -> None:
        if note in apc_mini.LED_NOTES or note == apc_mini.SHIFT_NOTE:
            self.seen.add(note)
            self.held.add(note)

    def release(self, note: int) -> None:
        self.held.discard(note)

    def fader(self, cc: int, value: int) -> None:
        if cc not in apc_mini.FADER_CCS:
            return
        f = self.faders[apc_mini.FADER_CCS.index(cc)]
        f["value"] = value
        f["low"] |= value <= EDGE
        f["high"] |= value >= 127 - EDGE

    # ----------------------------------------------------------- results
    def faders_done(self) -> int:
        return sum(f["low"] and f["high"] for f in self.faders)

    def leds(self, now: float) -> tuple[str, dict[int, int]]:
        if self.mode == LIGHTS:
            return light_show(now - self.started)
        leds: dict[int, int] = {}
        if self.mode == BUTTONS:
            for n in self.seen:
                if apc_mini.control_kind(n) == "grid":
                    leds[n] = int(GridLed.YELLOW if n in self.held else GridLed.GREEN)
                elif n in ROUND_NOTES:
                    leds[n] = int(RoundLed.BLINK if n in self.held else RoundLed.ON)
            total = len(apc_mini.LED_NOTES) + 1
            return f"{len(self.seen)} of {total} buttons pressed", leds
        # Faders: each of faders 1-8 shows its position as a meter in the grid column above it;
        # the bottom-row button under it lights once it has been fully down and fully up.
        for i, f in enumerate(self.faders[:8]):
            if f["value"] is not None:
                lit = round(f["value"] * 8 / 127)
                for row in range(lit):
                    leds[apc_mini.grid_note(row, i)] = int(
                        GridLed.GREEN if row < 5 else GridLed.YELLOW if row < 7 else GridLed.RED)
            if f["low"] and f["high"]:
                leds[apc_mini.TRACK_BUTTON_NOTES[i]] = int(RoundLed.ON)
        master = self.faders[8]
        if master["value"] is not None:   # the master fader uses the right-hand column
            lit = round(master["value"] * 8 / 127)
            for row in range(lit):
                leds[apc_mini.SCENE_BUTTON_NOTES[7 - row]] = int(RoundLed.ON)
        return f"{self.faders_done()} of {len(self.faders)} faders checked", leds

    def to_dict(self, now: float) -> dict:
        step, _ = self.leds(now)
        return {"mode": self.mode, "step": step, "seen": sorted(self.seen),
                "faders": self.faders, "faders_done": self.faders_done()}
