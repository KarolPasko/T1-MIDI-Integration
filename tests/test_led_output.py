import pytest

from apc_bridge import apc_mini
from apc_bridge.apc_mini import LedMessageError
from apc_bridge.led_output import LedOutput, LedOutputError


class FakePort:
    def __init__(self, name, fail=False):
        self.name = name
        self.sent = []
        self.fail = fail
        self.closed = False

    def send(self, msg):
        if self.fail:
            raise OSError("device unplugged")
        self.sent.append(msg)

    def close(self):
        self.closed = True


@pytest.fixture
def led():
    ports = []

    def opener(name):
        ports.append(FakePort(name))
        return ports[-1]

    out = LedOutput(opener=opener)
    out.open("APC MINI 1")
    out.port = ports[-1]
    return out


def test_send_and_dedupe(led):
    assert led.set_led(0, 1) is True
    assert led.set_led(0, 1) is False          # same state, skipped
    assert led.set_led(0, 1, force=True) is True
    assert len(led.port.sent) == 2
    assert led.sent_state == {0: 1}


def test_invalid_message_never_reaches_port(led):
    with pytest.raises(LedMessageError):
        led.set_led(98, 1)
    assert led.port.sent == []


def test_all_off_sends_every_led(led):
    led.set_led(5, 3)
    led.port.sent.clear()
    assert led.all_off() == len(apc_mini.LED_NOTES)
    assert all(m.velocity == 0 for m in led.port.sent)
    assert led.sent_state == {}


def test_restore_snapshot(led):
    led.set_led(1, 1)
    led.set_led(64, 1)
    snap = led.sent_state
    for n in apc_mini.GRID_NOTES:
        led.set_led(n, 5)
    led.restore(snap)
    assert led.sent_state == {1: 1, 64: 1}


def test_restore_empty_only_touches_lit_leds(led):
    led.set_led(10, 3)
    led.port.sent.clear()
    assert led.restore({}) == 1
    assert led.port.sent[0].note == 10 and led.port.sent[0].velocity == 0


def test_send_failure_closes_port_and_raises():
    out = LedOutput(opener=lambda name: FakePort(name, fail=True))
    out.open("APC MINI 1")
    with pytest.raises(LedOutputError):
        out.set_led(0, 1)
    assert not out.is_open


def test_closed_port_raises():
    out = LedOutput(opener=FakePort)
    with pytest.raises(LedOutputError):
        out.set_led(0, 1)


def test_open_failure_is_reported():
    def bad(name):
        raise OSError("in use")

    out = LedOutput(opener=bad)
    with pytest.raises(LedOutputError, match="in use"):
        out.open("APC MINI 1")
    assert not out.is_open


def test_reopen_forgets_state(led):
    led.set_led(0, 1)
    led.open("APC MINI 1")
    assert led.sent_state == {}
