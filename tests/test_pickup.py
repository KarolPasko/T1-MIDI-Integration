from apc_bridge.pickup import Pickup, midi_to_dmx


def test_midi_to_dmx_scaling():
    assert midi_to_dmx(0) == 0
    assert midi_to_dmx(127) == 255
    assert midi_to_dmx(64) == 129
    assert midi_to_dmx(127, max_percent=50) == 128
    assert midi_to_dmx(200) == 255 and midi_to_dmx(-5) == 0


def test_pickup_waits_until_fader_reaches_target():
    p = Pickup(target=100, tolerance=2)
    assert p.update(10) is None
    assert p.update(50) is None
    assert p.update(99) == 99          # within tolerance
    assert p.update(20) == 20          # picked up: follows freely, including lowering


def test_pickup_on_crossing():
    p = Pickup(target=100, tolerance=0)
    assert p.update(90) is None
    assert p.update(120) == 120        # jumped across the target in one message


def test_reset_requires_new_pickup():
    p = Pickup(target=0)
    assert p.update(0) == 0
    p.reset(200)
    assert p.update(50) is None
