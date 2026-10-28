import mido
import pytest

from apc_bridge import apc_mini
from apc_bridge.apc_mini import GridLed, LedMessageError, RoundLed


def test_grid_led_message_bytes():
    msg = apc_mini.led_message(0, GridLed.GREEN)
    assert msg.bytes() == [0x90, 0, 1]  # Note On, channel 1, note 0, velocity 1


@pytest.mark.parametrize("state,velocity", [
    (GridLed.OFF, 0), (GridLed.GREEN, 1), (GridLed.GREEN_BLINK, 2), (GridLed.RED, 3),
    (GridLed.RED_BLINK, 4), (GridLed.YELLOW, 5), (GridLed.YELLOW_BLINK, 6),
])
def test_grid_velocity_table(state, velocity):
    assert apc_mini.led_message(63, state).velocity == velocity


def test_round_buttons_only_accept_off_on_blink():
    for note in apc_mini.TRACK_BUTTON_NOTES + apc_mini.SCENE_BUTTON_NOTES:
        for s in RoundLed:
            assert apc_mini.led_message(note, s).velocity == int(s)
        with pytest.raises(LedMessageError):
            apc_mini.led_message(note, GridLed.RED)  # 3 is not valid for round buttons


@pytest.mark.parametrize("note", [-1, 72, 81, 90, 98, 127])
def test_notes_without_leds_are_rejected(note):
    with pytest.raises(LedMessageError):
        apc_mini.led_message(note, 1)


def test_arbitrary_velocity_rejected():
    with pytest.raises(LedMessageError):
        apc_mini.led_message(10, 127)


def test_non_int_note_rejected():
    with pytest.raises(LedMessageError):
        apc_mini.led_message("5", 1)
    with pytest.raises(LedMessageError):
        apc_mini.led_message(True, 1)


def test_only_note_on_channel_1_is_ever_built():
    for msg in apc_mini.all_off_messages():
        assert msg.type == "note_on" and msg.channel == 0 and msg.velocity == 0
    assert len(apc_mini.all_off_messages()) == 64 + 8 + 8


def test_grid_geometry():
    assert apc_mini.grid_note(0, 0) == 0        # bottom-left
    assert apc_mini.grid_note(7, 0) == 56       # top-left
    assert apc_mini.grid_note(7, 7) == 63       # top-right
    assert apc_mini.grid_position(56) == (7, 0)
    assert apc_mini.describe_note(56) == "Pad row 1 col 1"
    with pytest.raises(ValueError):
        apc_mini.grid_note(8, 0)


def test_descriptions():
    assert apc_mini.describe_cc(48) == "Fader 1"
    assert apc_mini.describe_cc(56) == "Master fader"
    assert apc_mini.describe_cc(7) == "Unknown control"
    assert apc_mini.describe_note(64) == "Track button 1"
    assert apc_mini.describe_note(89) == "Scene button 8"
    assert apc_mini.describe_note(98) == "Shift"
    assert apc_mini.state_label(64, 1) == "Red"
    assert apc_mini.state_label(82, 2) == "Green Blink"
    assert apc_mini.state_label(0, 6) == "Yellow Blink"


def test_mk2_detection():
    assert apc_mini.is_mk2_name("APC mini mk2 0")
    assert not apc_mini.is_mk2_name("APC MINI 1")
