"""Bridge settings: which APC mini fader drives which sACN channel.

Saved as plain JSON (config.json next to where you run the app) so it can be
read and edited by hand if needed.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import apc_mini

DEFAULT_PATH = Path("config.json")


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
            raise ConfigError(f"sACN channel must be 1-512, got {self.address}")
        if not 0 <= self.min_percent <= 100 or not 0 <= self.max_percent <= 100:
            raise ConfigError("Min/max must be 0-100%")
        if self.min_percent > self.max_percent:
            raise ConfigError(f"{self.label}: min {self.min_percent}% is above max {self.max_percent}%")


def default_faders() -> list[FaderMapping]:
    faders = [FaderMapping(cc, f"Playback {i + 1}", i + 1)
              for i, cc in enumerate(apc_mini.FADER_CCS[:8])]
    faders.append(FaderMapping(apc_mini.FADER_CCS[8], "Playback 9 (master fader)", 9))
    return faders


@dataclass
class BridgeConfig:
    universe: int = 10
    unicast_ip: str | None = None       # None = standard multicast
    max_output_percent: float = 100.0   # overall cap on every fader
    led_feedback: bool = True
    faders: list[FaderMapping] = field(default_factory=default_faders)

    def validate(self) -> None:
        if not 1 <= self.universe <= 63999:
            raise ConfigError(f"Universe must be 1-63999, got {self.universe}")
        if not 0 <= self.max_output_percent <= 100:
            raise ConfigError("Max output must be 0-100%")
        addresses = [f.address for f in self.faders]
        if len(set(addresses)) != len(addresses):
            raise ConfigError("Two faders use the same sACN channel")
        ccs = [f.cc for f in self.faders]
        if len(set(ccs)) != len(ccs):
            raise ConfigError("Two mappings use the same fader")
        for f in self.faders:
            f.validate()

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
            ip = data.get("unicast_ip") or None
            cfg = cls(universe=int(data.get("universe", 10)), unicast_ip=ip,
                      max_output_percent=float(data.get("max_output_percent", 100)),
                      led_feedback=bool(data.get("led_feedback", True)), faders=faders)
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError(f"Config file is not valid: {exc}") from exc
        cfg.validate()
        return cfg


def save(cfg: BridgeConfig, path: Path = DEFAULT_PATH) -> None:
    cfg.validate()
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(cfg.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)  # never leave a half-written config behind


def load(path: Path = DEFAULT_PATH) -> BridgeConfig:
    """Load a config. A missing file gives the defaults."""
    if not Path(path).exists():
        return BridgeConfig()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} does not contain a settings object")
    return BridgeConfig.from_dict(data)
