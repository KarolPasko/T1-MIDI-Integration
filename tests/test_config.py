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
