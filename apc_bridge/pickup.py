"""Value scaling and fader pickup (soft takeover) for non-motorised faders."""

from __future__ import annotations


def midi_to_dmx(value: int, max_percent: float = 100.0) -> int:
    """Scale a 0-127 MIDI value to 0-255 DMX, capped at max_percent of full."""
    value = min(max(int(value), 0), 127)
    cap = min(max(max_percent, 0.0), 100.0) / 100.0
    return round(value * 255 / 127 * cap)


class Pickup:
    """Ignores a physical fader until it reaches the current target value.

    Until the fader crosses (or lands on) `target`, update() returns None so
    nothing jumps. After that, the fader is "picked up" and every value passes
    through until reset() is called (e.g. when the target is changed elsewhere).
    """

    def __init__(self, target: int = 0, tolerance: int = 2):
        self.target = target
        self.tolerance = tolerance
        self.picked_up = False
        self._last: int | None = None

    def reset(self, target: int) -> None:
        self.target = target
        self.picked_up = False
        self._last = None

    def update(self, value: int) -> int | None:
        if not self.picked_up:
            near = abs(value - self.target) <= self.tolerance
            crossed = self._last is not None and (
                (self._last - self.target) * (value - self.target) < 0)
            self._last = value
            if not (near or crossed):
                return None
            self.picked_up = True
        self.target = value
        return value
