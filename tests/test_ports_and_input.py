import queue

import mido
import pytest

from apc_bridge import ports
from apc_bridge.midi_input import MidiInputError, MidiInputListener


def test_find_original_apc():
    assert ports.find_apc_mini(["Microsoft GS Wavetable Synth 0", "APC MINI 1"]) == "APC MINI 1"
    assert ports.find_apc_mini(["APC mini mk2 0", "APC MINI 1"]) == "APC MINI 1"
    assert ports.find_apc_mini(["APC mini mk2 0"]) == "APC mini mk2 0"
    assert ports.find_apc_mini(["loopMIDI Port 0"]) is None


def test_still_present_ignores_index():
    assert ports.still_present("APC MINI 1", ["APC MINI 2"])
    assert not ports.still_present("APC MINI 1", ["loopMIDI Port 0"])


class FakeIn:
    def __init__(self, name, callback):
        self.callback = callback
        self.closed = False

    def close(self):
        self.closed = True


def test_input_callback_queues_events():
    q = queue.Queue()
    holder = {}

    def opener(name, callback):
        holder["port"] = FakeIn(name, callback)
        return holder["port"]

    listener = MidiInputListener(q, opener=opener)
    listener.open("APC MINI 0")
    holder["port"].callback(mido.Message("control_change", control=56, value=3))
    ev = q.get_nowait()
    assert ev.description == "Master fader" and ev.value == 3
    listener.close()
    assert holder["port"].closed and not listener.is_open


def test_input_open_failure():
    def opener(name, callback):
        raise OSError("busy")

    listener = MidiInputListener(queue.Queue(), opener=opener)
    with pytest.raises(MidiInputError):
        listener.open("APC MINI 0")
    assert not listener.is_open


def test_led_output_module_cannot_send_cc():
    # The LED module only builds messages via apc_mini.led_message (Note On).
    import inspect
    from apc_bridge import led_output
    src = inspect.getsource(led_output)
    assert "control_change" not in src and "sysex" not in src
