import pytest

from apc_bridge import apc_mini
from apc_bridge.apc_mini import GridLed, RoundLed
from apc_bridge.hardware_test import (BUTTONS, CYCLE_S, FADERS, LIGHTS, STEP_S, HardwareTest,
                                      light_show)


def valid(leds):
    for note, state in leds.items():
        assert state in [int(s) for s in apc_mini.allowed_states(note)], (note, state)


def test_light_show_steps_and_loop():
    names = []
    t = 0.1
    while t < CYCLE_S:
        name, leds = light_show(t)
        valid(leds)
        assert len(leds) == 80                     # every pad and round button
        names.append(name)
        t += STEP_S
    assert names[:4] == ["All red", "All green", "All yellow", "All flashing"]
    assert set(names[4:]) == {"Diagonal colours"}
    assert set(light_show(0.1)[1][n] for n in apc_mini.GRID_NOTES) == {GridLed.RED}
    assert light_show(0.1) == light_show(CYCLE_S + 0.1)    # loops


def test_diagonals_move_and_use_three_colours():
    t = STEP_S * 4 + 0.01
    a, b = light_show(t)[1], light_show(t + 0.26)[1]
    assert {a[n] for n in apc_mini.GRID_NOTES} == {GridLed.RED, GridLed.GREEN, GridLed.YELLOW}
    assert a[apc_mini.grid_note(0, 1)] == a[apc_mini.grid_note(1, 0)]   # same diagonal, same colour
    assert a != b


def test_button_test_counts_and_lights():
    t = HardwareTest(BUTTONS, 0)
    t.press(0); t.press(64); t.press(98)
    name, leds = t.leds(1)
    assert name == "3 of 81 buttons pressed"
    assert leds[0] == GridLed.YELLOW and leds[64] == RoundLed.BLINK     # held
    t.release(0); t.release(64)
    _, leds = t.leds(1)
    assert leds[0] == GridLed.GREEN and leds[64] == RoundLed.ON and 98 not in leds
    valid(leds)


def test_fader_test_needs_full_travel():
    t = HardwareTest(FADERS, 0)
    t.fader(48, 0); t.fader(48, 64)
    assert t.faders_done() == 0
    _, leds = t.leds(0)
    assert leds[apc_mini.grid_note(3, 0)] and apc_mini.grid_note(4, 0) not in leds   # half-way meter
    t.fader(48, 127)
    _, leds = t.leds(0)
    assert t.faders_done() == 1 and leds[64] == RoundLed.ON
    t.fader(56, 127)                                 # master fader -> right-hand column
    _, leds = t.leds(0)
    assert all(leds[n] == RoundLed.ON for n in apc_mini.SCENE_BUTTON_NOTES)
    valid(leds)


def test_unknown_mode():
    with pytest.raises(ValueError):
        HardwareTest("dance", 0)
    assert HardwareTest(LIGHTS, 0).to_dict(0)["step"] == "All red"
