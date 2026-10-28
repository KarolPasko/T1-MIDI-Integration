import json

import pytest

from apc_bridge import config as cfgmod
from apc_bridge.config import BridgeConfig, ConfigError, FaderMapping


def test_defaults_map_nine_faders_to_channels_1_to_9():
    cfg = BridgeConfig()
    assert [f.cc for f in cfg.faders] == list(range(48, 57))
    assert [f.address for f in cfg.faders] == list(range(1, 10))
    assert cfg.universe == 10 and cfg.unicast_ip is None
    cfg.validate()


def test_round_trip(tmp_path):
    path = tmp_path / "config.json"
    cfg = BridgeConfig(universe=20, unicast_ip="127.0.0.1", max_output_percent=80)
    cfg.faders[0].label = "Front wash"
    cfg.faders[0].min_percent = 10
    cfg.faders[2].enabled = False
    cfgmod.save(cfg, path)
    loaded = cfgmod.load(path)
    assert loaded == cfg
    assert not (tmp_path / "config.json.tmp").exists()


def test_missing_file_gives_defaults(tmp_path):
    assert cfgmod.load(tmp_path / "nope.json") == BridgeConfig()


@pytest.mark.parametrize("bad", [
    "not json", "[]", json.dumps({"universe": 0}),
    json.dumps({"faders": [{"cc": 48, "address": 600}]}),
    json.dumps({"faders": [{"cc": 48, "address": 1}, {"cc": 49, "address": 1}]}),
    json.dumps({"faders": [{"cc": 48}]}),
])
def test_invalid_files_rejected(tmp_path, bad):
    path = tmp_path / "config.json"
    path.write_text(bad)
    with pytest.raises(ConfigError):
        cfgmod.load(path)


def test_min_above_max_rejected():
    with pytest.raises(ConfigError):
        FaderMapping(48, "x", 1, min_percent=60, max_percent=40).validate()


def test_save_refuses_invalid(tmp_path):
    cfg = BridgeConfig(universe=0)
    with pytest.raises(ConfigError):
        cfgmod.save(cfg, tmp_path / "c.json")


from apc_bridge.config import MOMENTARY, TOGGLE, ButtonMapping


def test_default_buttons():
    cfg = BridgeConfig()
    assert len(cfg.buttons) == 64 + 8 + 8 + 1
    assert cfg.button(64).mode == "fader_enable" and cfg.button(64).fader == 0
    assert cfg.button(89).fader == 8
    assert cfg.button(82).mode == "output_status"
    assert cfg.button(0).mode == "unused"


def test_old_fader_only_file_still_loads(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"universe": 10, "faders": [{"cc": 48, "label": "A", "address": 1}]}))
    cfg = cfgmod.load(path)
    assert len(cfg.buttons) == 81


def test_button_round_trip_and_validation(tmp_path):
    cfg = BridgeConfig()
    b = cfg.button(0)
    b.mode, b.address, b.label = TOGGLE, 30, "Strobe"
    path = tmp_path / "c.json"
    cfgmod.save(cfg, path)
    assert cfgmod.load(path).button(0) == b


def test_button_channel_clash_with_fader():
    cfg = BridgeConfig()
    cfg.button(0).mode, cfg.button(0).address = MOMENTARY, 1   # fader 1 uses channel 1
    with pytest.raises(ConfigError, match="channel 1"):
        cfg.validate()


@pytest.mark.parametrize("kw", [
    {"mode": "bogus"}, {"mode": MOMENTARY, "address": 0},
    {"mode": MOMENTARY, "address": 30, "on_percent": 150},
    {"active_led": 7}, {"mode": "fader_enable", "fader": 9},
])
def test_invalid_buttons(kw):
    b = ButtonMapping(0, **kw)
    with pytest.raises(ConfigError):
        b.validate(9)


def test_round_button_rejects_grid_colours():
    with pytest.raises(ConfigError):
        ButtonMapping(64, active_led=3).validate(9)
