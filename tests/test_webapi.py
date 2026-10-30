import io
import threading
import time
import urllib.error

import pytest

from apc_bridge import apc_mini, webapi
from apc_bridge.app_core import BridgeCore
from apc_bridge.bridge import BridgeEngine
from apc_bridge.config import TITAN, BridgeConfig, ConfigError, titan_webapi_preset

PB = {"handle_type": "userNumber", "handle": "3"}


def paths(calls):
    return [c.path for c in calls]


def test_button_calls_follow_the_avolites_reference():
    a = lambda **kw: webapi.normalise({**PB, **kw}, "button")
    assert paths(webapi.button_calls(a(type="go"), True)) == ["titan/script/2/CueLists/Play?handle_userNumber=3"]
    assert paths(webapi.button_calls(a(type="cue_go", cue=4.5), True)) == [
        "titan/script/2/CueLists/SetNextCue?handle_userNumber=3&stepNumber=4.5",
        "titan/script/2/CueLists/Play?handle_userNumber=3"]
    assert paths(webapi.button_calls(a(type="fire", level=50), True)) == [
        "titan/script/2/Playbacks/FirePlaybackAtLevel?handle_userNumber=3&level_level=0.5&alwaysRefire=false"]
    assert paths(webapi.button_calls(a(type="release_all"), True)) == ["titan/script/2/Playbacks/KillAllPlaybacks"]
    assert paths(webapi.button_calls(a(type="macro", macro="My.Macro"), True)) == [
        "titan/script/2/Macros/Run?macroId=My.Macro"]


@pytest.mark.parametrize("action,press,release", [
    ("flash", "Playbacks/FlashPlayback", "Playbacks/ClearFlashPlayback"),
    ("swop", "Playbacks/SwopPlayback", "Playbacks/ClearSwopPlayback"),
    ("master_flash", "Masters/Flash", "Masters/ClearFlash"),
    ("dbo", "Masters/DeadBlackOut", "Masters/ClearFlash"),
])
def test_held_actions_send_a_release(action, press, release):
    a = webapi.normalise({**PB, "type": action}, "button")
    assert press in webapi.button_calls(a, True)[0].path
    assert release in webapi.button_calls(a, False)[0].path


def test_go_sends_nothing_on_release():
    assert webapi.button_calls(webapi.normalise({**PB, "type": "go"}, "button"), False) == []


def test_every_action_builds_requests():
    for name, spec in webapi.ACTIONS.items():
        a = webapi.normalise({**PB, "type": name, "macro": "M"}, spec["kind"])
        if spec.get("relative"):
            assert webapi.encoder_call(a, 0.5, 0.1).path.startswith("titan/script/2/Programmer/Editor/Fixtures/Increment")
        elif name == "tap_tempo":
            assert webapi.speed_call(a, 128).path.endswith("Masters/SetSpeed?handle_userNumber=3&value=128")
        elif spec["kind"] == "button":
            assert webapi.button_calls(a, True)
        else:
            assert webapi.fader_call(a, 0.5).path.startswith("titan/")


def test_fader_calls():
    level = webapi.normalise({**PB, "type": "playback_level"}, "fader")
    assert webapi.fader_call(level, 0.25).path == \
        "titan/script/2/Playbacks/SetPlaybackLevel?srcHandle_userNumber=3&level_level=0.25"
    speed = webapi.normalise({**PB, "type": "speed", "min": 60, "max": 180}, "fader")
    assert webapi.fader_call(speed, 0.5).path.endswith("Masters/SetSpeed?handle_userNumber=3&value=120")
    wheel = webapi.normalise({"type": "wheel", "wheel": "c", "min": 0, "max": 255}, "fader")
    call = webapi.fader_call(wheel, 1.0)
    assert (call.method, call.path, call.body) == (
        "POST", "titan/set/2/Programmer/Editor/Fixtures/AttributeCValue", b"255")


@pytest.mark.parametrize("bad", [
    {"type": "nope"}, {"type": "go", "handle": ""}, {"type": "go", "handle": "abc"},
    {"type": "go", "handle_type": "x"}, {"type": "cue_go", "handle": "1", "cue": 0},
    {"type": "macro", "macro": " "}, {"type": "playback_level", "handle": "1"},
])
def test_bad_button_actions(bad):
    with pytest.raises(webapi.ActionError):
        webapi.normalise(bad, "button")


def test_location_handles_allow_text():
    a = webapi.normalise({"type": "go", "handle_type": "location", "handle": "playback_2_1"}, "button")
    assert webapi.button_calls(a, True)[0].path.endswith("CueLists/Play?handle_location=playback_2_1")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def test_check_reports_titan_unavailable():
    opener = lambda req, timeout: FakeResponse(b"<string>Titan is unavailable.</string>")
    with pytest.raises(webapi.WebApiError, match="unavailable"):
        webapi.check("127.0.0.1", opener=opener)
    reply = webapi.check("127.0.0.1", opener=lambda r, timeout: FakeResponse(b"<string>18.0</string>"))
    assert reply == "18.0"


def test_check_reports_unreachable():
    def opener(req, timeout):
        raise urllib.error.URLError("refused")
    with pytest.raises(webapi.WebApiError, match="cannot reach"):
        webapi.check("10.0.0.9", opener=opener)


def test_client_sends_in_order_and_merges_fader_moves():
    seen, gate = [], threading.Event()

    def opener(req, timeout):
        gate.wait(2)                    # Titan is slow: fader moves pile up meanwhile
        seen.append(req.full_url.split("4430/")[1])
        return FakeResponse(b"")
    client = webapi.TitanClient("1.2.3.4", opener=opener)
    client.submit(webapi.button_calls(webapi.normalise({**PB, "type": "go"}, "button"), True))
    level = webapi.normalise({**PB, "type": "playback_level"}, "fader")
    time.sleep(0.05)
    for v in (0.1, 0.2, 0.3):
        client.submit_fader(0, webapi.fader_call(level, v))
    gate.set()
    client.close()
    assert seen == ["titan/script/2/CueLists/Play?handle_userNumber=3",
                    "titan/script/2/Playbacks/SetPlaybackLevel?srcHandle_userNumber=3&level_level=0.3"]
    assert client.sent == 2


# ---------------------------------------------------------------- config + engine
def titan_cfg():
    cfg = BridgeConfig()
    b = cfg.button(0)
    b.mode, b.action = TITAN, {**PB, "type": "flash"}
    cfg.faders[0].action = {**PB, "type": "playback_level"}
    cfg.validate()
    return cfg


def test_config_round_trip_and_channel_reuse():
    cfg = titan_cfg()
    cfg.faders[0].address = cfg.faders[1].address   # WebAPI faders don't use their sACN channel
    cfg.validate()
    again = BridgeConfig.from_dict(cfg.to_dict())
    assert again.button(0).action["type"] == "flash" and again.faders[0].uses_webapi


def test_config_rejects_bad_titan_settings():
    cfg = titan_cfg()
    cfg.titan_host = "http://x/"
    with pytest.raises(ConfigError):
        cfg.validate()
    cfg = titan_cfg()
    cfg.button(0).action = {"type": "playback_level"}
    with pytest.raises(ConfigError):
        cfg.validate()


def test_engine_titan_button_only_while_output_on():
    e = BridgeEngine(titan_cfg())
    e.handle_press(0)
    e.handle_release(0)
    assert e.take_titan_events() == []
    e.set_output_enabled(True)
    e.handle_press(0)
    assert e.led_states()[0] == e.config.button(0).active_led
    e.handle_release(0)
    assert e.take_titan_events() == [("press", 0, None), ("release", 0)]


def test_engine_releases_held_flash_on_output_off_and_blackout():
    e = BridgeEngine(titan_cfg())
    e.set_output_enabled(True)
    e.handle_press(0)
    e.set_output_enabled(False)
    assert e.take_titan_events() == [("press", 0, None), ("release", 0)]
    e.set_output_enabled(True)
    e.handle_press(0)
    e.set_blackout(True)
    events = e.take_titan_events()
    assert ("release", 0) in events and ("fader", 0, 0.0) in events
    e.handle_press(0)
    assert e.take_titan_events() == []      # ignored during blackout


def test_engine_titan_fader_needs_pickup_and_skips_sacn():
    e = BridgeEngine(titan_cfg())
    e.set_output_enabled(True)
    cc = apc_mini.FADER_CCS[0]
    e.handle_cc(1, cc, 100)                 # not picked up yet (last output 0)
    assert e.take_titan_events() == []
    e.handle_cc(1, cc, 0)
    e.handle_cc(1, cc, 127)
    assert e.take_titan_events()[-1] == ("fader", 0, 1.0)
    assert e.dmx_frame()[e.config.faders[0].address - 1] == 0


def test_tap_tempo():
    taps = webapi.TapTempo()
    assert taps.tap(5, 10.0) is None              # one tap is not a tempo
    assert taps.tap(5, 10.5) == 120.0
    assert taps.tap(5, 11.0) == 120.0
    assert taps.tap(5, 11.6) == pytest.approx(112.5, abs=0.1)   # average of the gaps so far
    assert taps.tap(5, 20.0) is None              # a long pause starts again
    assert taps.tap(5, 20.25) == 240.0
    for i in range(10):                           # only the last 4 gaps count
        taps.tap(6, 100 + i * 0.6)
    assert taps.tap(6, 100 + 10 * 0.6) == 100.0
    assert taps.bpm[6] == 100.0


def test_core_tap_tempo_sets_speed_master(tmp_path, monkeypatch):
    sent = []

    class Client:
        def __init__(self, host, port, dry_run):
            self.sent = self.errors = 0
            self.last_error = None

        def submit(self, calls):
            sent.extend(c.path for c in calls)

        def close(self, wait_s=0):
            pass

    monkeypatch.setattr(webapi, "TitanClient", Client)
    cfg = BridgeConfig()
    b = cfg.button(7)
    b.mode, b.action = TITAN, {"type": "tap_tempo", "handle_type": "userNumber", "handle": "1"}
    cfg.validate()
    core = BridgeCore(tmp_path, simulate_midi=True)
    core.engine.apply_config(cfg)
    core.simulate_output = True
    core.set_output(True)
    for t in (1.0, 1.5, 2.0):
        core.engine.handle_press(7, t)
        core.engine.handle_release(7)
        core._send_titan()
    assert sent == ["titan/script/2/Masters/SetSpeed?handle_userNumber=1&value=120"] * 2
    assert core.state()["titan"]["tempo"] == {"7": 120.0}
    core.shutdown()


def test_selection_and_nudge_calls():
    b = lambda **kw: webapi.normalise(kw, "button")
    assert paths(webapi.button_calls(b(type="select", numbers="3, 4;5"), True)) == [
        "titan/script/2/Programmer/Editor/Selection/SetNewHandleSelection?newSelection_userNumberList=3%2C4%2C5"]
    assert paths(webapi.button_calls(b(type="nudge", attr="pan", step=-2), True)) == [
        "titan/script/2/Programmer/Editor/Fixtures/IncrementPan?value=-2&timeDelta=0&shiftEnabled=false"]
    with pytest.raises(webapi.ActionError):
        b(type="select", numbers="a,b")


def test_encoder_calls():
    enc = webapi.normalise({"type": "encoder", "attr": "tilt", "amount": 50}, "fader")
    assert webapi.encoder_call(enc, -0.5, 0.04).path == \
        "titan/script/2/Programmer/Editor/Fixtures/IncrementTilt?value=-25&timeDelta=0.04&shiftEnabled=false"
    ctl = webapi.normalise({"type": "encoder_control", "control": 12, "amount": 10}, "fader")
    assert webapi.encoder_call(ctl, 1.0, 0.1).path == ("titan/script/2/Programmer/Editor/Fixtures/IncrementAttribute"
                                                       "?controlId=12&value=10&timeDelta=0.1&shiftEnabled=false")


def test_engine_encoder_fader_sends_movement_without_pickup():
    cfg = BridgeConfig()
    cfg.faders[0].action = {"type": "encoder", "attr": "pan", "amount": 100}
    cfg.validate()
    e = BridgeEngine(cfg)
    cc = apc_mini.FADER_CCS[0]
    e.handle_cc(1, cc, 64)                     # output off: just remembered
    e.set_output_enabled(True)
    e.handle_cc(1, cc, 70)                     # up = right
    e.handle_cc(1, cc, 60)                     # down = left
    assert e.take_titan_events() == [("fader_delta", 0, 6 / 127), ("fader_delta", 0, -10 / 127)]
    assert e.led_states()[apc_mini.TRACK_BUTTON_NOTES[0]] == 1      # live straight away
    e.set_blackout(True)
    e.handle_cc(1, cc, 100)
    assert e.take_titan_events() == []


def test_client_adds_up_encoder_moves_while_busy():
    seen, gate = [], threading.Event()

    def opener(req, timeout):
        gate.wait(2)
        seen.append(req.full_url.split("4430/")[1])
        return FakeResponse(b"")
    client = webapi.TitanClient("1.2.3.4", opener=opener)
    enc = webapi.normalise({"type": "encoder", "attr": "dimmer", "amount": 100}, "fader")
    client.submit([webapi.Call("GET", "titan/get/System/SoftwareVersion")])
    time.sleep(0.05)
    for d in (0.1, 0.2, -0.05):
        client.submit_delta(0, d, lambda total, gap: webapi.encoder_call(enc, total, 0))
    gate.set()
    client.close()
    assert seen[1] == "titan/script/2/Programmer/Editor/Fixtures/IncrementDimmer?value=25&timeDelta=0&shiftEnabled=false"
    assert len(seen) == 2


def test_starter_preset_is_valid():
    cfg = titan_webapi_preset()
    assert sum(b.mode == TITAN for b in cfg.buttons) == 34
    assert all(f.uses_webapi for f in cfg.faders)


def test_core_sends_titan_requests(tmp_path, monkeypatch):
    sent = []

    class Client:
        def __init__(self, host, port, dry_run):
            self.sent = self.errors = 0
            self.last_error = None

        def submit(self, calls):
            sent.extend(c.path for c in calls)

        def submit_fader(self, key, call):
            sent.append(call.path)

        def close(self, wait_s=0):
            sent.append("closed")

    monkeypatch.setattr(webapi, "TitanClient", Client)
    core = BridgeCore(tmp_path, simulate_midi=True)
    core.engine.apply_config(titan_cfg())
    core.simulate_output = True
    core.set_output(True)
    assert core.titan is not None
    core.engine.handle_press(0)
    core._tick()
    core.set_output(False)
    assert sent == ["titan/script/2/Playbacks/FlashPlayback?handle_userNumber=3",
                    "titan/script/2/Playbacks/ClearFlashPlayback?handle_userNumber=3", "closed"]
    core.shutdown()


def test_core_without_titan_mappings_has_no_client(tmp_path):
    core = BridgeCore(tmp_path, simulate_midi=True)
    core.simulate_output = True
    core.set_output(True)
    assert core.titan is None
    assert core.state()["titan"]["active"] is False
    core.shutdown()
