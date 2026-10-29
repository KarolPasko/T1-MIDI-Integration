import queue

from apc_bridge import app_core, ports, simulation
from apc_bridge.app_core import BridgeCore
from apc_bridge.led_output import LedOutput
from apc_bridge.midi_input import MidiInputListener


def make_core(tmp_path, monkeypatch, listing):
    monkeypatch.setattr(ports, "list_ports", lambda: listing[0])
    core = BridgeCore(tmp_path)
    core.midi_in = MidiInputListener(queue.Queue(), opener=simulation.open_input)
    core.leds = LedOutput(opener=simulation.open_output)
    return core


def test_unplug_switches_output_off_and_replug_reconnects(tmp_path, monkeypatch):
    here = ports.PortList(["APC MINI 0"], ["APC MINI 1"])
    listing = [here]
    core = make_core(tmp_path, monkeypatch, listing)
    core.connect("APC MINI 0", "APC MINI 1")
    core.set_simulate_output(True)
    core.set_output(True)

    listing[0] = ports.PortList([], [])          # unplugged
    core._watchdog()
    s = core.state()
    assert s["apc_lost"] and not s["output"]["enabled"] and not s["midi_in"]["open"]

    listing[0] = ports.PortList(["APC MINI 2"], ["APC MINI 3"])   # back, new index
    core._watchdog()
    s = core.state()
    assert not s["apc_lost"] and s["midi_in"]["name"] == "APC MINI 2" and s["leds"]["open"]
    assert not s["output"]["enabled"]            # never switched back on by itself
    core.shutdown()


def test_manual_disconnect_does_not_reconnect(tmp_path, monkeypatch):
    listing = [ports.PortList(["APC MINI 0"], ["APC MINI 1"])]
    core = make_core(tmp_path, monkeypatch, listing)
    core.connect("APC MINI 0", "APC MINI 1")
    core.disconnect()
    core._watchdog()
    assert not core.state()["midi_in"]["open"]
    core.shutdown()


def test_blackout_and_timer_in_state(tmp_path, monkeypatch):
    core = make_core(tmp_path, monkeypatch, [ports.PortList([], [])])
    core.set_simulate_output(True)
    core.set_output(True)
    core.set_blackout(True)
    s = core.state()
    assert s["blackout"] and s["output_on_for"] == 0 and s["version"] == app_core.__version__
    core.set_output(False)
    assert core.state()["output_on_for"] is None
    core.shutdown()


def test_hardware_test_takes_input_and_blocks_output(tmp_path, monkeypatch):
    from apc_bridge.app_core import ActionError
    import mido
    import pytest
    from apc_bridge.midi_events import event_from_message
    core = make_core(tmp_path, monkeypatch, [ports.PortList([], [])])
    core.start_test("buttons")
    with pytest.raises(ActionError):
        core.set_output(True)
    core.events.put(event_from_message(mido.Message("note_on", note=64, velocity=127)))
    core._tick()
    assert core.state()["test"]["seen"] == [64]
    assert core.engine.faders[0].mapping.enabled      # the fader on/off button did not fire
    core.stop_test()
    core.set_simulate_output(True)
    core.set_output(True)
    with pytest.raises(ActionError):
        core.start_test("lights")
    core.shutdown()
