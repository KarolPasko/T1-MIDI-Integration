"""Mapping engine: APC mini faders in, sACN levels and LED states out.

Pure logic with no MIDI, network or GUI code, so every rule here is unit
tested. The GUI feeds it MIDI events and asks it what to send.

Rules:
* Output values only change while output is enabled AND the fader is
  enabled AND it has been picked up (soft takeover), so nothing jumps when
  output is switched on, a fader is re-enabled, or a mapping changes.
* LEDs reflect this program's own state. sACN is one-way, so Titan's real
  playback state is never known.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import apc_mini
from .apc_mini import GridLed, RoundLed
from .config import BridgeConfig, FaderMapping
from .pickup import Pickup

OUTPUT_STATUS_NOTE = apc_mini.SCENE_BUTTON_NOTES[0]   # top scene button
MASTER_STATUS_NOTE = apc_mini.SCENE_BUTTON_NOTES[-1]  # bottom scene button, next to master


def scale(value: int, mapping: FaderMapping, cap_percent: float) -> int:
    """MIDI 0-127 -> DMX 0-255 using the fader's min/max and the overall cap."""
    value = min(max(int(value), 0), 127)
    lo = mapping.min_percent * 2.55
    hi = mapping.max_percent * 2.55
    out = lo + (hi - lo) * value / 127
    return int(round(min(out, cap_percent * 2.55)))


@dataclass
class FaderState:
    mapping: FaderMapping
    physical: int | None = None   # last MIDI value seen, None = never moved
    output: int = 0               # DMX value last put in the frame
    pickup: Pickup = field(default_factory=lambda: Pickup(0, tolerance=4))

    @property
    def picked_up(self) -> bool:
        return self.pickup.picked_up


class BridgeEngine:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self.output_enabled = False
        self.faders: list[FaderState] = [FaderState(m) for m in config.faders]
        self._by_cc = {f.mapping.cc: f for f in self.faders}

    # ------------------------------------------------------------ config
    def apply_config(self, config: BridgeConfig) -> None:
        """Swap in new mappings, keeping each fader's last output and re-arming pickup."""
        config.validate()
        old = {f.mapping.cc: f for f in self.faders}
        self.config = config
        self.faders = []
        for m in config.faders:
            prev = old.get(m.cc)
            st = FaderState(m, physical=prev.physical if prev else None,
                            output=prev.output if prev else 0)
            self.faders.append(st)
            self._arm(st)
        self._by_cc = {f.mapping.cc: f for f in self.faders}

    # ------------------------------------------------------------ output
    def set_output_enabled(self, enabled: bool) -> None:
        if enabled and not self.output_enabled:
            for f in self.faders:  # every fader must pick up again
                self._arm(f)
        self.output_enabled = enabled

    def toggle_fader(self, index: int) -> None:
        f = self.faders[index]
        f.mapping.enabled = not f.mapping.enabled
        if f.mapping.enabled:
            self._arm(f)

    def _arm(self, f: FaderState) -> None:
        """Require pickup at the last output, clamped to what the fader can reach."""
        lo = scale(0, f.mapping, self.config.max_output_percent)
        hi = scale(127, f.mapping, self.config.max_output_percent)
        f.pickup.reset(min(max(f.output, lo), hi))

    # ------------------------------------------------------------- input
    def handle_cc(self, channel: int, cc: int, value: int) -> bool:
        """Process a fader move. Returns True if an output value changed."""
        if channel != apc_mini.CHANNEL + 1:
            return False
        f = self._by_cc.get(cc)
        if f is None:
            return False
        f.physical = value
        if not (self.output_enabled and f.mapping.enabled):
            return False
        taken = f.pickup.update(scale(value, f.mapping, self.config.max_output_percent))
        if taken is None or taken == f.output:
            return False
        f.output = taken
        return True

    def handle_press(self, note: int) -> bool:
        """Track button N toggles fader N on/off. Returns True if something changed."""
        if note in apc_mini.TRACK_BUTTON_NOTES:
            idx = note - apc_mini.TRACK_BUTTON_NOTES[0]
            if idx < len(self.faders):
                self.toggle_fader(idx)
                return True
        if note == MASTER_STATUS_NOTE and len(self.faders) > 8:
            self.toggle_fader(8)
            return True
        return False

    # ------------------------------------------------------------ results
    def dmx_frame(self) -> bytes:
        data = bytearray(512)
        for f in self.faders:
            data[f.mapping.address - 1] = f.output
        return bytes(data)

    def led_states(self) -> dict[int, int]:
        """Desired state of every LED (notes not listed are off)."""
        leds: dict[int, int] = {}
        for i, f in enumerate(self.faders):
            if i < 8:
                # Level meter in the grid column above the fader.
                if f.mapping.enabled:
                    lit = -(-f.output * 8 // 255)  # ceil to 0-8 pads
                    for row in range(lit):
                        colour = GridLed.GREEN if row < 5 else GridLed.YELLOW if row < 7 else GridLed.RED
                        leds[apc_mini.grid_note(row, i)] = colour
                status_note = apc_mini.TRACK_BUTTON_NOTES[i]
            else:
                status_note = MASTER_STATUS_NOTE
            if not f.mapping.enabled:
                state = RoundLed.OFF
            elif self.output_enabled and f.picked_up:
                state = RoundLed.ON
            else:
                state = RoundLed.BLINK  # live but waiting for pickup (or output off)
            leds[status_note] = state
        leds[OUTPUT_STATUS_NOTE] = RoundLed.ON if self.output_enabled else RoundLed.BLINK
        return leds
