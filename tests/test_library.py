import json

import pytest

from apc_bridge import apc_mini
from apc_bridge import config as cfgmod
from apc_bridge.config import MOMENTARY, TOGGLE, BridgeConfig, ConfigError, all_buttons_preset
from apc_bridge.library import PRESET, SAVED, MappingLibrary, check_name, presets_dir


@pytest.mark.parametrize("mode", [MOMENTARY, TOGGLE])
def test_all_buttons_preset(mode):
    cfg = all_buttons_preset(mode)
    for b in cfg.buttons:
        if b.note == apc_mini.SHIFT_NOTE:
            assert b.mode == "unused"
            continue
        assert b.mode == mode
        if b.note in apc_mini.GRID_NOTES:   # red when off, green when on
            assert (b.idle_led, b.active_led) == (apc_mini.GridLed.RED, apc_mini.GridLed.GREEN)
    channels = [f.address for f in cfg.faders] + [b.address for b in cfg.buttons if b.mode == mode]
    assert len(channels) == len(set(channels)) == 9 + 64 + 16
    assert max(channels) <= 89


def test_preset_rejects_other_modes():
    with pytest.raises(ValueError):
        all_buttons_preset("unused")


def test_shipped_presets_match_the_code():
    folder = presets_dir()
    expected = {"All buttons momentary": all_buttons_preset(MOMENTARY),
                "All buttons toggle": all_buttons_preset(TOGGLE),
                "Faders only (basic)": BridgeConfig()}
    for name, cfg in expected.items():
        data = json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
        assert data == cfg.to_dict(), f"{name}.json is out of date"
        assert cfgmod.load(folder / f"{name}.json").to_dict() == cfg.to_dict()


@pytest.mark.parametrize("name", ["", "../x", "a/b", "a\\\\b", ".hidden", "x" * 61, "a..b"])
def test_bad_names(name):
    with pytest.raises(ConfigError):
        check_name(name)


def test_good_names():
    assert check_name("  Show 1 (main).json ") == "Show 1 (main)"


def test_save_list_load(tmp_path):
    lib = MappingLibrary(tmp_path)
    assert [f["kind"] for f in lib.list()] == [PRESET] * 3
    cfg = all_buttons_preset(TOGGLE)
    cfg.universe = 7
    lib.save(cfg, "Gig")
    assert lib.list()[0] == {"kind": SAVED, "name": "Gig"}
    assert lib.load(SAVED, "Gig").universe == 7
    assert lib.load(PRESET, "All buttons toggle").universe == 10
    with pytest.raises(ConfigError):
        lib.load(SAVED, "Nope")
    with pytest.raises(ConfigError):
        lib.path("other", "Gig")


def test_old_config_is_kept(tmp_path):
    cfgmod.save(BridgeConfig(universe=5), tmp_path / "config.json")
    lib = MappingLibrary(tmp_path)
    assert lib.load(SAVED, "My settings").universe == 5
