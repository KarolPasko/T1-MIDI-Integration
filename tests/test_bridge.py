from apc_bridge import apc_mini
from apc_bridge.apc_mini import GridLed, RoundLed
from apc_bridge.bridge import BridgeEngine, scale
from apc_bridge.config import MOMENTARY, TOGGLE, BridgeConfig, FaderMapping

OUTPUT_STATUS_NOTE = apc_mini.SCENE_BUTTON_NOTES[0]
MASTER_STATUS_NOTE = apc_mini.SCENE_BUTTON_NOTES[-1]

CH = 1  # MIDI channel as shown (1-16)


def engine(**kw):
    e = BridgeEngine(BridgeConfig(**kw))
    return e


def test_scale_min_max_and_cap():
    m = FaderMapping(48, "x", 1)
    assert scale(0, m, 100) == 0 and scale(127, m, 100) == 255
    m2 = FaderMapping(48, "x", 1, min_percent=20, max_percent=60)
    assert scale(0, m2, 100) == 51 and scale(127, m2, 100) == 153
    assert scale(127, m, 50) in (127, 128)


def test_nothing_happens_while_output_off():
    e = engine()
    assert e.handle_cc(CH, 48, 127) is False
    assert e.faders[0].output == 0
    assert e.dmx_frame() == bytes(512)


def test_pickup_after_enabling_output_prevents_jump():
    e = engine()
    e.handle_cc(CH, 48, 100)            # fader is already up when output is switched on
    e.set_output_enabled(True)
    assert e.handle_cc(CH, 48, 101) is False   # not picked up: stays at 0
    assert e.faders[0].output == 0
    e.handle_cc(CH, 48, 1)              # bring it down to 0 -> picked up
    assert e.faders[0].picked_up
    assert e.handle_cc(CH, 48, 127)
    assert e.dmx_frame()[0] == 255


def test_lowering_after_pickup_follows_down():
    e = engine()
    e.set_output_enabled(True)
    e.handle_cc(CH, 48, 0)
    e.handle_cc(CH, 48, 127)
    e.handle_cc(CH, 48, 0)
    assert e.dmx_frame()[0] == 0


def test_output_off_then_on_needs_pickup_at_last_level():
    e = engine()
    e.set_output_enabled(True)
    e.handle_cc(CH, 48, 0)
    e.handle_cc(CH, 48, 64)
    level = e.faders[0].output
    e.set_output_enabled(False)
    e.handle_cc(CH, 48, 0)              # moved while off
    e.set_output_enabled(True)
    assert e.handle_cc(CH, 48, 10) is False
    assert e.faders[0].output == level
    e.handle_cc(CH, 48, 70)             # crosses the old level -> takes over
    assert e.faders[0].picked_up


def test_wrong_channel_and_unknown_cc_ignored():
    e = engine()
    e.set_output_enabled(True)
    assert e.handle_cc(2, 48, 0) is False
    assert e.handle_cc(CH, 7, 0) is False


def test_track_button_toggles_fader_and_rearms():
    e = engine()
    e.set_output_enabled(True)
    e.handle_cc(CH, 48, 0)
    e.handle_cc(CH, 48, 127)
    e.handle_press(apc_mini.TRACK_BUTTON_NOTES[0])
    assert not e.faders[0].mapping.enabled
    assert e.handle_cc(CH, 48, 0) is False and e.faders[0].output == 255  # disabled holds level
    e.handle_press(apc_mini.TRACK_BUTTON_NOTES[0])
    assert e.faders[0].mapping.enabled and not e.faders[0].picked_up
    e.handle_press(MASTER_STATUS_NOTE)
    assert not e.faders[8].mapping.enabled
    assert e.handle_press(5) is False   # grid pads do nothing


def test_min_percent_pickup_is_reachable():
    cfg = BridgeConfig()
    cfg.faders[0].min_percent = 50
    e = BridgeEngine(cfg)
    e.set_output_enabled(True)
    e.handle_cc(CH, 48, 0)              # bottom of travel = 50%, the clamped pickup target
    assert e.faders[0].picked_up


def test_apply_config_keeps_levels_and_rearms():
    e = engine()
    e.set_output_enabled(True)
    e.handle_cc(CH, 48, 0)
    e.handle_cc(CH, 48, 127)
    cfg = BridgeConfig()
    cfg.faders[0].address = 20
    e.apply_config(cfg)
    assert e.faders[0].output == 255 and not e.faders[0].picked_up
    assert e.dmx_frame()[19] == 255


def test_max_output_cap():
    e = engine(max_output_percent=50)
    e.set_output_enabled(True)
    e.handle_cc(CH, 48, 0)
    e.handle_cc(CH, 48, 127)
    assert e.dmx_frame()[0] in (127, 128)  # 50% of 255


def test_led_states():
    e = engine(show_meters=True)
    leds = e.led_states()
    assert leds[OUTPUT_STATUS_NOTE] == RoundLed.BLINK
    assert leds[apc_mini.TRACK_BUTTON_NOTES[0]] == RoundLed.BLINK
    e.set_output_enabled(True)
    e.handle_cc(CH, 48, 0)
    e.handle_cc(CH, 48, 127)
    leds = e.led_states()
    assert leds[OUTPUT_STATUS_NOTE] == RoundLed.ON
    assert leds[apc_mini.TRACK_BUTTON_NOTES[0]] == RoundLed.ON
    column = [leds.get(apc_mini.grid_note(r, 0), 0) for r in range(8)]
    assert column == [GridLed.GREEN] * 5 + [GridLed.YELLOW] * 2 + [GridLed.RED]
    assert all(leds.get(apc_mini.grid_note(r, 1), 0) == 0 for r in range(8))
    e.toggle_fader(0)
    leds = e.led_states()
    assert leds.get(apc_mini.TRACK_BUTTON_NOTES[0], 0) == RoundLed.OFF
    assert apc_mini.grid_note(0, 0) not in leds
    # every state produced must be a valid LED message
    for note, state in leds.items():
        apc_mini.led_message(note, state)


def test_frame_only_contains_mapped_channels():
    e = engine()
    frame = e.dmx_frame()
    assert len(frame) == 512 and frame == bytes(512)


def map_button(e, note, mode, address, **kw):
    cfg = e.config
    b = cfg.button(note)
    b.mode, b.address = mode, address
    for k, v in kw.items():
        setattr(b, k, v)
    e.apply_config(cfg)
    return b


def test_momentary_button_sends_while_held():
    e = engine()
    map_button(e, 0, MOMENTARY, 20)
    e.set_output_enabled(True)
    assert e.handle_press(0)
    assert e.dmx_frame()[19] == 255
    assert e.led_states()[0] == GridLed.GREEN
    assert e.handle_release(0)
    assert e.dmx_frame()[19] == 0
    assert e.led_states()[0] == GridLed.YELLOW   # mapped but idle


def test_toggle_button_flips():
    e = engine()
    map_button(e, 5, TOGGLE, 21, on_percent=50, active_led=int(GridLed.RED), idle_led=0)
    e.set_output_enabled(True)
    e.handle_press(5); e.handle_release(5)
    assert e.dmx_frame()[20] in (127, 128)
    assert e.led_states()[5] == GridLed.RED
    e.handle_press(5); e.handle_release(5)
    assert e.dmx_frame()[20] == 0
    assert 5 not in e.led_states()


def test_buttons_ignored_while_output_off():
    e = engine()
    map_button(e, 0, TOGGLE, 20)
    assert e.handle_press(0) is False
    e.set_output_enabled(True)
    assert e.dmx_frame()[19] == 0


def test_output_off_releases_momentary_keeps_toggle():
    e = engine()
    map_button(e, 0, MOMENTARY, 20)
    map_button(e, 1, TOGGLE, 21)
    e.set_output_enabled(True)
    e.handle_press(0); e.handle_press(1)
    e.set_output_enabled(False)
    assert e.active == {1}


def test_button_level_capped_by_max_output():
    e = engine(max_output_percent=40)
    map_button(e, 0, MOMENTARY, 20)
    e.set_output_enabled(True)
    e.handle_press(0)
    assert e.dmx_frame()[19] == 102


def test_learn_selects_without_triggering():
    e = engine()
    map_button(e, 0, TOGGLE, 20)
    e.set_output_enabled(True)
    e.set_learning(True)
    assert e.handle_press(0) is False
    assert e.take_learned() == ("button", 0) and not e.learning
    assert e.dmx_frame()[19] == 0
    e.set_learning(True)
    e.handle_cc(CH, 50, 10)
    assert e.take_learned() == ("fader", 2)
    assert e.take_learned() is None


def test_unused_buttons_do_nothing_and_stay_dark():
    e = engine()
    e.set_output_enabled(True)
    assert e.handle_press(10) is False
    assert 10 not in e.led_states()
    assert e.dmx_frame()[9:20] == bytes(11)


def test_remapping_drops_active_state():
    e = engine()
    map_button(e, 0, TOGGLE, 20)
    e.set_output_enabled(True)
    e.handle_press(0)
    cfg = e.config
    cfg.button(0).mode = "unused"
    e.apply_config(cfg)
    assert e.active == set()


def test_blackout_zeroes_everything_and_ignores_input():
    cfg = BridgeConfig()
    btn = cfg.button(0)
    btn.mode, btn.address, btn.off_percent = TOGGLE, 20, 10
    e = BridgeEngine(cfg)
    e.set_output_enabled(True)
    e.handle_cc(CH, 48, 0)
    e.handle_cc(CH, 48, 127)
    e.handle_press(0)
    assert e.dmx_frame()[0] == 255 and e.dmx_frame()[19] == 255
    e.set_blackout(True)
    assert e.dmx_frame() == bytes(512)          # even the button's 10% OFF level
    assert e.handle_cc(CH, 48, 50) is False and e.handle_press(0) is False
    assert e.dmx_frame() == bytes(512)
    e.set_blackout(False)
    assert 0 not in e.active                    # the toggle stays off
    assert e.dmx_frame()[19] == 26              # back to its OFF level
    assert e.handle_cc(CH, 48, 120) is False    # fader must come down to zero first
    e.handle_cc(CH, 48, 1)
    assert e.faders[0].picked_up and e.handle_cc(CH, 48, 127)


def test_blackout_button_toggles_and_blinks():
    from apc_bridge.config import BLACKOUT
    cfg = BridgeConfig()
    cfg.button(98).mode = BLACKOUT          # Shift
    cfg.button(64).mode = BLACKOUT          # a round button with a light
    e = BridgeEngine(cfg)
    e.set_output_enabled(True)
    assert e.handle_press(98) and e.blackout
    assert e.led_states()[64] == RoundLed.BLINK
    e.handle_release(98)
    assert e.handle_press(98) and not e.blackout
    assert 64 not in e.led_states()
