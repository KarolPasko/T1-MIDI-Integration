import mido

from apc_bridge.midi_events import event_from_message


def test_fader_cc():
    ev = event_from_message(mido.Message("control_change", channel=0, control=48, value=100), 1.0)
    assert (ev.kind, ev.channel, ev.number, ev.value) == ("Control Change", 1, 48, 100)
    assert ev.description == "Fader 1"
    assert ev.raw == "B0 30 64"
    assert ev.is_cc


def test_pad_press_and_release():
    on = event_from_message(mido.Message("note_on", channel=0, note=56, velocity=127))
    assert on.is_press and on.description == "Pad row 1 col 1"
    off = event_from_message(mido.Message("note_off", channel=0, note=56, velocity=127))
    assert off.is_release
    off0 = event_from_message(mido.Message("note_on", channel=0, note=56, velocity=0))
    assert off0.is_release


def test_other_channel_reported_one_based():
    ev = event_from_message(mido.Message("note_on", channel=15, note=1, velocity=1))
    assert ev.channel == 16


def test_unusual_message_does_not_crash():
    ev = event_from_message(mido.Message("sysex", data=[1, 2, 3]))
    assert ev.kind == "Sysex" and ev.number is None
