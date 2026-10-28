"""Mapping files: the ready-made ones shipped with the app, and the user's own.

The user's files live in a "mappings" folder next to the app (or the folder
it is run from). Ready-made files are read-only; saving always goes to the
user's folder.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

from . import config as config_mod
from .config import BridgeConfig, ConfigError

PRESET = "preset"
SAVED = "saved"
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _().-]{0,59}$")


def presets_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "apc_bridge" / "presets"


def check_name(name: str) -> str:
    name = (name or "").strip()
    if name.lower().endswith(".json"):
        name = name[:-5]
    if not _NAME.match(name) or ".." in name:
        raise ConfigError("Use a name made of letters, numbers, spaces, - or _ (up to 60 characters)")
    return name


class MappingLibrary:
    def __init__(self, app_folder: Path, presets: Path | None = None):
        self.folder = Path(app_folder) / "mappings"
        self.presets = presets or presets_dir()
        self.folder.mkdir(parents=True, exist_ok=True)
        legacy = Path(app_folder) / "config.json"   # settings saved by older versions
        target = self.folder / "My settings.json"
        if legacy.exists() and not target.exists():
            shutil.copyfile(legacy, target)

    def list(self) -> list[dict]:
        saved = sorted(self.folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        return ([{"kind": SAVED, "name": p.stem} for p in saved] +
                [{"kind": PRESET, "name": p.stem} for p in sorted(self.presets.glob("*.json"))])

    def path(self, kind: str, name: str) -> Path:
        name = check_name(name)
        base = self.presets if kind == PRESET else self.folder
        if kind not in (PRESET, SAVED):
            raise ConfigError(f"Unknown file type {kind}")
        return base / f"{name}.json"

    def load(self, kind: str, name: str) -> BridgeConfig:
        path = self.path(kind, name)
        if not path.exists():
            raise ConfigError(f"'{name}' was not found")
        return config_mod.load(path)

    def save(self, cfg: BridgeConfig, name: str) -> Path:
        path = self.path(SAVED, name)
        config_mod.save(cfg, path)
        return path
