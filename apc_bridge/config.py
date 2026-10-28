"""Bridge settings: what every APC mini fader and button does.

Saved as plain JSON (config.json) so it can be read and edited by hand.
Files saved by older versions (faders only) still load; the buttons then get
their defaults.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import apc_mini

DEFAULT_PATH = Path("config.json")

# What a button does when pressed.
UNUSED = "unused"                # nothing
MOMENTARY = "momentary"          # sends its ON level while held, OFF level when released
TOGGLE = "toggle"                # press = ON level, press again = OFF level
FADER_ENABLE = "fader_enable"    # switches one fader on/off
OUTPUT_STATUS = "output_status"  # light only: lit while output is on, blinking while off
BUTTON_MODES = (UNUSED, MOMENTARY, TOGGLE, FADER_ENABLE, OUTPUT_STATUS)
SENDING_MODES = (MOMENTARY, TOGGLE)

BUTTON_NOTES = apc_mini.LED_NOTES + (apc_mini.SHIFT_NOTE,)


class ConfigError(ValueError):
    pass


@dataclass
class FaderMapping:
    cc: int              # MIDI controller number of the physical fader
    label: str           # what it controls in Titan, for display only
    address: int         # sACN channel (1-512) that Titan's trigger listens to
    enabled: bool = True
    min_percent: float = 0.0    # output when the fader is at the bottom
    max_percent: float = 100.0  # output when the fader is at the top

    def validate(self) -> None:
        if not 0 <= self.cc <= 127:
            raise ConfigError(f"CC must be 0-127, got {self.cc}")
        if not 1 <= self.address <= 512:
            raise ConfigError(f"{self.label}: sACN channel must be 1-512, got {self.address}")
        if not 0 <= self.min_percent <= 100 or not 0 <= self.max_percent <= 100:
            raise ConfigError(f"{self.label}: min/max must be 0-100%")
        if self.min_percent > self.max_percent:
            raise ConfigError(f"{self.label}: min {self.min_percent}% is above max {self.max_percent}%")


@dataclass
class ButtonMapping:
    note: int
    mode: str = UNUSED
    label: str = ""
    address: int = 0             # sACN channel for momentary/toggle
    on_percent: float = 100.0
    off_percent: float = 0.0
    fader: int = 0               # which fader (0-8) for fader_enable
    active_led: int = 1          # LED state while ON (pressed / toggled on)
    idle_led: int = 0            # LED state while mapped but OFF

    @property
    def name(self) -> str:
        return self.label or apc_mini.describe_note(self.note)

    def validate(self, fader_count: int) -> None:
        if self.note not in BUTTON_NOTES:
            raise ConfigError(f"Note {self.note} is not an APC mini button")
        if self.mode not in BUTTON_MODES:
            raise ConfigError(f"{self.name}: unknown mode '{self.mode}'")
        if self.mode in SENDING_MODES:
            if not 1 <= self.address <= 512:
                raise ConfigError(f"{self.name}: sACN channel must be 1-512")
            if not (0 <= self.on_percent <= 100 and 0 <= self.off_percent <= 100):
                raise ConfigError(f"{self.name}: on/off levels must be 0-100%")
        if self.mode == FADER_ENABLE and not 0 <= self.fader < fader_count:
            raise ConfigError(f"{self.name}: fader must be 1-{fader_count}")
        allowed = [int(s) for s in apc_mini.allowed_states(self.note)] or [0]
        for led in (self.active_led, self.idle_led):
            if led not in allowed:
                raise ConfigError(f"{self.name}: LED state {led} is not supported by this button")


def default_faders() -> list[FaderMapping]:
    faders = [FaderMapping(cc, f"Playback {i + 1}", i + 1)
              for i, cc in enumerate(apc_mini.FADER_CCS[:8])]
    faders.append(FaderMapping(apc_mini.FADER_CCS[8], "Playback 9 (master fader)", 9))
    return faders


def default_button(note: int) -> ButtonMapping:
    """A not-yet-used button with sensible LED colours for when it gets mapped."""
    if apc_mini.control_kind(note) == "grid":
        return ButtonMapping(note, active_led=int(apc_mini.GridLed.GREEN), idle_led=int(apc_mini.GridLed.YELLOW))
    if note == apc_mini.SHIFT_NOTE:
        return ButtonMapping(note, active_led=0, idle_led=0)
    return ButtonMapping(note, active_led=int(apc_mini.RoundLed.ON), idle_led=0)


def default_buttons() -> list[ButtonMapping]:
    buttons = {n: default_button(n) for n in BUTTON_NOTES}
    for i, note in enumerate(apc_mini.TRACK_BUTTON_NOTES):     # under faders 1-8
        buttons[note].mode, buttons[note].fader = FADER_ENABLE, i
    buttons[apc_mini.SCENE_BUTTON_NOTES[-1]].mode = FADER_ENABLE  # next to the master fader
    buttons[apc_mini.SCENE_BUTTON_NOTES[-1]].fader = 8
    buttons[apc_mini.SCENE_BUTTON_NOTES[0]].mode = OUTPUT_STATUS
    return [buttons[n] for n in BUTTON_NOTES]


@dataclass
class BridgeConfig:
    universe: int = 10
    unicast_ip: str | None = None       # None = standard multicast
    max_output_percent: float = 100.0   # overall cap on every fader and button
    led_feedback: bool = True
    show_meters: bool = False           # level meters on UNUSED grid pads above each fader
    faders: list[FaderMapping] = field(default_factory=default_faders)
    buttons: list[ButtonMapping] = field(default_factory=default_buttons)

    def button(self, note: int) -> ButtonMapping | None:
        for b in self.buttons:
            if b.note == note:
                return b
        return None

    def validate(self) -> None:
        if not 1 <= self.universe <= 63999:
            raise ConfigError(f"Universe must be 1-63999, got {self.universe}")
        if not 0 <= self.max_output_percent <= 100:
            raise ConfigError("Max output must be 0-100%")
        ccs = [f.cc for f in self.faders]
        if len(set(ccs)) != len(ccs):
            raise ConfigError("Two mappings use the same fader")
        notes = [b.note for b in self.buttons]
        if len(set(notes)) != len(notes):
            raise ConfigError("A button is listed twice")
        for f in self.faders:
            f.validate()
        for b in self.buttons:
            b.validate(len(self.faders))
        senders = [(f.address, f.label or apc_mini.describe_cc(f.cc)) for f in self.faders]
        senders += [(b.address, b.name) for b in self.buttons if b.mode in SENDING_MODES]
        used: dict[int, str] = {}
        for address, name in senders:
            if address in used:
                raise ConfigError(f"sACN channel {address} is used by both '{used[address]}' and '{name}'")
            used[address] = name

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BridgeConfig":
        try:
            faders = [FaderMapping(
                cc=int(f["cc"]), label=str(f.get("label", "")), address=int(f["address"]),
                enabled=bool(f.get("enabled", True)),
                min_percent=float(f.get("min_percent", 0)),
                max_percent=float(f.get("max_percent", 100)),
            ) for f in data.get("faders", [])] or default_faders()
            buttons = {b.note: b for b in default_buttons()}
            for b in buttons.values():  # defaults for faders this file does not have
                if b.mode == FADER_ENABLE and b.fader >= len(faders):
                    b.mode = UNUSED
            for raw in data.get("buttons", []):
                note = int(raw["note"])
                base = default_button(note)
                buttons[note] = ButtonMapping(
                    note=note, mode=str(raw.get("mode", UNUSED)), label=str(raw.get("label", "")),
                    address=int(raw.get("address", 0)),
                    on_percent=float(raw.get("on_percent", 100)), off_percent=float(raw.get("off_percent", 0)),
                    fader=int(raw.get("fader", 0)),
                    active_led=int(raw.get("active_led", base.active_led)),
                    idle_led=int(raw.get("idle_led", base.idle_led)))
            cfg = cls(universe=int(data.get("universe", 10)), unicast_ip=data.get("unicast_ip") or None,
                      max_output_percent=float(data.get("max_output_percent", 100)),
                      led_feedback=bool(data.get("led_feedback", True)),
                      show_meters=bool(data.get("show_meters", False)),
                      faders=faders, buttons=list(buttons.values()))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ConfigError(f"Settings are not valid: {exc}") from exc
        cfg.validate()
        return cfg


def save(cfg: BridgeConfig, path: Path = DEFAULT_PATH) -> None:
    cfg.validate()
    path = Path(path)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(cfg.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)  # never leave a half-written config behind


def load(path: Path = DEFAULT_PATH) -> BridgeConfig:
    """Load a config. A missing file gives the defaults."""
    path = Path(path)
    if not path.exists():
        return BridgeConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} does not contain a settings object")
    return BridgeConfig.from_dict(data)


def all_buttons_preset(mode: str) -> BridgeConfig:
    """Every button with a light mapped to `mode` (momentary or toggle).

    Lights: grid pads red when off, green when on. The round buttons only
    have one colour each, so the bottom row is red when off and blinking red
    when on, and the right-hand column is dark when off and green when on.
    sACN channels: faders 1-9, grid pad n -> 10+n (10-73),
    bottom row -> 74-81, right-hand column -> 82-89. Shift stays unused.
    """
    if mode not in SENDING_MODES:
        raise ValueError(f"mode must be one of {SENDING_MODES}")
    cfg = BridgeConfig()
    for b in cfg.buttons:
        kind = apc_mini.control_kind(b.note)
        if kind is None:
            continue
        b.mode, b.label = mode, ""
        if kind == "grid":
            b.address = b.note + 10
            b.active_led, b.idle_led = int(apc_mini.GridLed.GREEN), int(apc_mini.GridLed.RED)
        elif kind == "track":
            b.address = b.note + 10
            b.active_led, b.idle_led = int(apc_mini.RoundLed.BLINK), int(apc_mini.RoundLed.ON)
        else:
            b.address = b.note
            b.active_led, b.idle_led = int(apc_mini.RoundLed.ON), int(apc_mini.RoundLed.OFF)
    cfg.validate()
    return cfg
