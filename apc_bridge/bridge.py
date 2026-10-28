"""Mapping engine: APC mini faders and buttons in, sACN levels and LED states out.

Pure logic with no MIDI, network or GUI code, so every rule here is unit
tested. The app feeds it MIDI events and asks it what to send.

Rules:
* Fader output only changes while output is enabled AND the fader is
  enabled AND it has been picked up (soft takeover), so nothing jumps when
  output is switched on, a fader is re-enabled, or a mapping changes.
* Momentary/toggle buttons only react while output is enabled, so presses
  made while output is off cannot fire anything later.
* In learn mode, a press or fader move only selects that control; nothing
  is triggered.
* Blackout sends zero on every channel and ignores faders and buttons until
  it is released. Toggles are switched off, and every fader must then be
  picked up from zero, so nothing jumps back on when it is released.
* LEDs reflect this program's own state. sACN is one-way, so Titan's real
  playback state is never known.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import apc_mini
from .apc_mini import GridLed, RoundLed
from .config import (BLACKOUT, FADER_ENABLE, MOMENTARY, OUTPUT_STATUS, SENDING_MODES, TOGGLE, UNUSED,
                     BridgeConfig, ButtonMapping, FaderMapping)
from .pickup import Pickup


def scale(value: int, mapping: FaderMapping, cap_percent: float) -> int:
    """MIDI 0-127 -> DMX 0-255 using the fader's min/max and the overall cap."""
    value = min(max(int(value), 0), 127)
    lo = mapping.min_percent * 2.55
    hi = mapping.max_percent * 2.55
    out = lo + (hi - lo) * value / 127
    return int(round(min(out, cap_percent * 2.55)))


def percent_to_dmx(percent: float, cap_percent: float) -> int:
    return int(round(min(percent, cap_percent) * 2.55))


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
        config.validate()
        self.config = config
        self.output_enabled = False
        self.blackout = False
        self.learning = False
        self.learned: tuple[str, int] | None = None   # ("fader", index) or ("button", note)
        self.pressed: set[int] = set()
        self.active: set[int] = set()                 # buttons whose ON level is being sent
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
        # Buttons that no longer send anything lose their ON state.
        self.active = {n for n in self.active
                       if (b := config.button(n)) is not None and b.mode in SENDING_MODES}

    # ------------------------------------------------------------ output
    def set_output_enabled(self, enabled: bool) -> None:
        if enabled and not self.output_enabled:
            for f in self.faders:  # every fader must pick up again
                self._arm(f)
        if not enabled:
            # Held momentary buttons are released; toggles keep their state.
            self.active = {n for n in self.active if self.config.button(n).mode == TOGGLE}
        self.output_enabled = enabled

    def set_blackout(self, on: bool) -> None:
        if on:
            self.active.clear()
            for f in self.faders:
                f.output = 0
                self._arm(f)
        elif self.blackout:
            for f in self.faders:  # pick up from zero
                self._arm(f)
        self.blackout = on

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

    def set_learning(self, on: bool) -> None:
        self.learning = on
        self.learned = None

    def take_learned(self) -> tuple[str, int] | None:
        learned, self.learned = self.learned, None
        return learned

    # ------------------------------------------------------------- input
    def handle_cc(self, channel: int, cc: int, value: int) -> bool:
        """Process a fader move. Returns True if an output value changed."""
        if channel != apc_mini.CHANNEL + 1:
            return False
        f = self._by_cc.get(cc)
        if f is None:
            return False
        f.physical = value
        if self.learning:
            self.learned = ("fader", self.faders.index(f))
            self.learning = False
            return False
        if self.blackout or not (self.output_enabled and f.mapping.enabled):
            return False
        taken = f.pickup.update(scale(value, f.mapping, self.config.max_output_percent))
        if taken is None or taken == f.output:
            return False
        f.output = taken
        return True

    def handle_press(self, note: int) -> bool:
        """A button went down. Returns True if the sACN output changed."""
        self.pressed.add(note)
        b = self.config.button(note)
        if b is None:
            return False
        if self.learning:
            self.learned = ("button", note)
            self.learning = False
            return False
        if b.mode == BLACKOUT:
            self.set_blackout(not self.blackout)
            return True
        if self.blackout:
            return False
        if b.mode == FADER_ENABLE and b.fader < len(self.faders):
            self.toggle_fader(b.fader)
            return False
        if b.mode in SENDING_MODES and self.output_enabled:
            if b.mode == MOMENTARY or note not in self.active:
                self.active.add(note)
            else:
                self.active.discard(note)
            return True
        return False

    def handle_release(self, note: int) -> bool:
        self.pressed.discard(note)
        b = self.config.button(note)
        if b is not None and b.mode == MOMENTARY and note in self.active:
            self.active.discard(note)
            return True
        return False

    # ------------------------------------------------------------ results
    def button_output(self, b: ButtonMapping) -> int:
        percent = b.on_percent if b.note in self.active else b.off_percent
        return percent_to_dmx(percent, self.config.max_output_percent)

    def dmx_frame(self) -> bytes:
        data = bytearray(512)
        if self.blackout:
            return bytes(data)
        for f in self.faders:
            data[f.mapping.address - 1] = f.output
        for b in self.config.buttons:
            if b.mode in SENDING_MODES:
                data[b.address - 1] = self.button_output(b)
        return bytes(data)

    def _fader_status_led(self, index: int) -> int:
        f = self.faders[index]
        if not f.mapping.enabled:
            return RoundLed.OFF
        if self.output_enabled and f.picked_up:
            return RoundLed.ON
        return RoundLed.BLINK  # live but waiting for pickup (or output off)

    def led_states(self) -> dict[int, int]:
        """Desired state of every LED (notes not listed are off)."""
        leds: dict[int, int] = {}
        if self.config.show_meters:
            for i, f in enumerate(self.faders[:8]):
                if f.mapping.enabled:
                    lit = -(-f.output * 8 // 255)  # ceil to 0-8 pads
                    for row in range(lit):
                        leds[apc_mini.grid_note(row, i)] = (
                            GridLed.GREEN if row < 5 else GridLed.YELLOW if row < 7 else GridLed.RED)
        for b in self.config.buttons:
            if b.mode == UNUSED or not apc_mini.control_kind(b.note):
                continue  # unused pads keep the meter (if any); Shift has no LED
            if b.mode in SENDING_MODES:
                leds[b.note] = b.active_led if b.note in self.active else b.idle_led
            elif b.mode == FADER_ENABLE:
                state = self._fader_status_led(b.fader)
                # Use the button's chosen colour for "live" on grid pads.
                leds[b.note] = b.active_led if (state == RoundLed.ON and apc_mini.control_kind(b.note) == "grid") \
                    else self._as_kind(b, state)
            elif b.mode == BLACKOUT:
                if self.blackout:
                    leds[b.note] = self._as_kind(b, RoundLed.BLINK)
            elif b.mode == OUTPUT_STATUS:
                leds[b.note] = self._as_kind(b, RoundLed.ON if self.output_enabled else RoundLed.BLINK)
        return {n: int(s) for n, s in leds.items() if s}

    @staticmethod
    def _as_kind(b: ButtonMapping, round_state: int) -> int:
        """Translate off/on/blink into this button's own LED values."""
        if apc_mini.control_kind(b.note) != "grid":
            return round_state
        if round_state == RoundLed.OFF:
            return GridLed.OFF
        if round_state == RoundLed.BLINK:
            return {GridLed.GREEN: GridLed.GREEN_BLINK, GridLed.RED: GridLed.RED_BLINK,
                    GridLed.YELLOW: GridLed.YELLOW_BLINK}.get(b.active_led, GridLed.GREEN_BLINK)
        return b.active_led or GridLed.GREEN
