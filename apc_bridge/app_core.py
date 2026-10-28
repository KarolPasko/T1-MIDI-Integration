"""The running bridge: MIDI in, mapping engine, sACN out, LEDs out.

One background thread does all the real-time work every 25 ms. The web
interface only calls the public methods below, which all take the same
lock, so the interface can never race the MIDI/sACN loop.
"""

from __future__ import annotations

import collections
import logging
import queue
import threading
import time
from pathlib import Path

from . import apc_mini, config as config_mod, ports
from .bridge import BridgeEngine
from .config import BridgeConfig, ConfigError
from .led_output import LedOutput, LedOutputError
from .midi_input import MidiInputError, MidiInputListener
from .sacn import SacnError, SacnSender

log = logging.getLogger(__name__)

TICK_S = 0.025
LED_S = 0.06        # LED refresh; unchanged LEDs are never re-sent
WATCHDOG_S = 1.5
KEEPALIVE_S = 0.8   # sACN receivers drop a source after 2.5 s of silence
MIN_GAP_S = 0.025


class ActionError(RuntimeError):
    """A user action that could not be done; the message is shown in the interface."""


class _NullSocket:
    """Stands in for the network in simulated-output mode."""

    def setsockopt(self, *args):
        pass

    def sendto(self, data, addr):
        pass

    def close(self):
        pass


class _LogBuffer(logging.Handler):
    def __init__(self, size: int = 300):
        super().__init__()
        self.lines: collections.deque = collections.deque(maxlen=size)
        self.seq = 0
        self._lock = threading.Lock()
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))

    def emit(self, record):
        try:
            text = self.format(record)
        except Exception:
            return
        with self._lock:
            self.seq += 1
            self.lines.append((self.seq, record.levelname, text))

    def since(self, seq: int) -> list:
        with self._lock:
            return [{"seq": s, "level": lvl, "text": t} for s, lvl, t in self.lines if s > seq]


class BridgeCore:
    def __init__(self, config_path: Path, simulate_midi: bool = False):
        self.config_path = Path(config_path)
        self.simulate_midi = simulate_midi
        self.lock = threading.RLock()
        self.events: queue.Queue = queue.Queue()
        if simulate_midi:
            from . import simulation
            self.midi_in = MidiInputListener(self.events, opener=simulation.open_input)
            self.leds = LedOutput(opener=simulation.open_output)
        else:
            self.midi_in = MidiInputListener(self.events)
            self.leds = LedOutput()
        self.logbuf = _LogBuffer()
        logging.getLogger().addHandler(self.logbuf)

        try:
            cfg = config_mod.load(self.config_path)
            log.info("Settings loaded from %s", self.config_path)
        except ConfigError as exc:
            log.warning("%s - starting with default settings", exc)
            cfg = BridgeConfig()
        self.engine = BridgeEngine(cfg)
        self.unsaved = False
        self.sender: SacnSender | None = None
        self.simulate_output = False
        self.led_error: str | None = None
        self.port_list = ports.PortList([], [])
        self.dirty = False
        self._last_send = self._last_led = self._last_watchdog = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="bridge-core", daemon=True)

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self.refresh_ports()
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        with self.lock:
            self.disconnect()
        logging.getLogger().removeHandler(self.logbuf)

    def _run(self) -> None:
        while not self._stop.wait(TICK_S):
            with self.lock:
                try:
                    self._tick()
                except Exception:
                    log.exception("Unexpected error in the bridge loop")

    def _tick(self) -> None:
        for _ in range(500):
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                break
            if ev.channel != 1:
                continue
            if ev.is_cc:
                self.dirty |= self.engine.handle_cc(ev.channel, ev.number, ev.value)
            elif ev.is_press:
                self.dirty |= self.engine.handle_press(ev.number)
            elif ev.is_release:
                self.dirty |= self.engine.handle_release(ev.number)
        now = time.monotonic()
        if self.sender is not None:
            if (self.dirty and now - self._last_send >= MIN_GAP_S) or now - self._last_send >= KEEPALIVE_S:
                try:
                    self.sender.send(self.engine.dmx_frame())
                except SacnError as exc:
                    log.error("%s - output switched OFF", exc)
                    self.engine.set_output_enabled(False)
                    self.sender = None
                self._last_send = now
                self.dirty = False
        if now - self._last_led >= LED_S:
            self._last_led = now
            self._update_leds()
        if now - self._last_watchdog >= WATCHDOG_S:
            self._last_watchdog = now
            self._watchdog()

    def _update_leds(self) -> None:
        if not (self.leds.is_open and self.engine.config.led_feedback):
            return
        wanted = self.engine.led_states()
        try:
            for note in apc_mini.LED_NOTES:
                self.leds.set_led(note, wanted.get(note, 0))
        except LedOutputError as exc:
            self.led_error = str(exc)
            log.error("LED feedback stopped: %s", exc)

    def _watchdog(self) -> None:
        if self.simulate_midi or not (self.midi_in.is_open or self.leds.is_open):
            return
        pl = ports.list_ports()
        if pl.error:
            return
        if self.midi_in.is_open and not ports.still_present(self.midi_in.port_name, pl.inputs):
            self.midi_in.close()
            if self.engine.output_enabled:
                self.set_output(False)
                log.warning("APC mini unplugged: output switched OFF. Reconnect, then switch output "
                            "ON again (faders will need pickup).")
            else:
                log.warning("APC mini input disappeared (unplugged?)")
        if self.leds.is_open and not ports.still_present(self.leds.port_name, pl.outputs):
            self.leds.close()
            self.led_error = "APC mini LED output disappeared"
            log.warning(self.led_error)

    # ---------------------------------------------------------------- devices
    def refresh_ports(self) -> None:
        with self.lock:
            if self.simulate_midi:
                from .simulation import SIM_PORT
                self.port_list = ports.PortList([SIM_PORT], [SIM_PORT])
            else:
                self.port_list = ports.list_ports()
                if self.port_list.error:
                    log.error(self.port_list.error)

    def connect(self, input_name: str, output_name: str) -> None:
        with self.lock:
            errors = []
            if input_name:
                try:
                    self.midi_in.open(input_name)
                except MidiInputError as exc:
                    errors.append(str(exc))
            if output_name:
                try:
                    self.leds.open(output_name)
                    self.led_error = None
                except LedOutputError as exc:
                    self.led_error = str(exc)
                    errors.append(str(exc))
            if errors:
                raise ActionError(" ".join(errors))
            log.info("Connected")

    def disconnect(self) -> None:
        with self.lock:
            self.set_output(False)
            if self.leds.is_open:
                try:
                    self.leds.restore({})
                except LedOutputError:
                    pass
            self.midi_in.close()
            self.leds.close()

    # ----------------------------------------------------------------- output
    def set_output(self, on: bool) -> None:
        with self.lock:
            if on and not self.engine.output_enabled:
                cfg = self.engine.config
                try:
                    self.sender = SacnSender(cfg.universe, unicast_ip=cfg.unicast_ip, source_name="APC Bridge",
                                             sock_factory=_NullSocket if self.simulate_output else None)
                except SacnError as exc:
                    raise ActionError(str(exc)) from exc
                self.engine.set_output_enabled(True)
                self.dirty = True
                log.info("Output ON (%s) universe %d -> %s. Move each fader to its last level to pick it up.",
                         "SIMULATED" if self.simulate_output else "sACN", cfg.universe, self.sender.dest[0])
            elif not on and self.engine.output_enabled:
                self.engine.set_output_enabled(False)
                if self.sender is not None:
                    self.sender.stop(self.engine.dmx_frame())
                    self.sender = None
                log.info("Output OFF (sACN stream terminated)")

    def set_simulate_output(self, on: bool) -> None:
        with self.lock:
            if self.engine.output_enabled:
                raise ActionError("Switch output OFF before changing simulate mode")
            self.simulate_output = bool(on)

    # --------------------------------------------------------------- settings
    def apply_settings(self, data: dict) -> None:
        with self.lock:
            if self.engine.output_enabled:
                raise ActionError("Settings are locked while output is ON. Switch output OFF first.")
            try:
                cfg = BridgeConfig.from_dict(data)
            except ConfigError as exc:
                raise ActionError(str(exc)) from exc
            self.engine.apply_config(cfg)
            self.unsaved = True
            if not cfg.led_feedback and self.leds.is_open:
                try:
                    self.leds.restore({})
                except LedOutputError:
                    pass
            log.info("Settings applied (not saved yet)")

    def save(self) -> None:
        with self.lock:
            try:
                config_mod.save(self.engine.config, self.config_path)
            except (OSError, ConfigError) as exc:
                raise ActionError(f"Could not save: {exc}") from exc
            self.unsaved = False
            log.info("Settings saved to %s", self.config_path)

    def reload(self) -> None:
        with self.lock:
            if self.engine.output_enabled:
                raise ActionError("Switch output OFF first.")
            try:
                self.engine.apply_config(config_mod.load(self.config_path))
            except ConfigError as exc:
                raise ActionError(str(exc)) from exc
            self.unsaved = False
            log.info("Saved settings reloaded")

    def defaults(self) -> None:
        with self.lock:
            if self.engine.output_enabled:
                raise ActionError("Switch output OFF first.")
            self.engine.apply_config(BridgeConfig())
            self.unsaved = True
            log.info("Default settings loaded (not saved yet)")

    def set_learning(self, on: bool) -> None:
        with self.lock:
            self.engine.set_learning(bool(on))

    # ------------------------------------------------------------------ state
    def state(self, log_since: int = 0) -> dict:
        with self.lock:
            e = self.engine
            learned = e.take_learned()
            return {
                "simulate_midi": self.simulate_midi,
                "ports": {"inputs": self.port_list.inputs, "outputs": self.port_list.outputs,
                          "error": self.port_list.error},
                "midi_in": {"open": self.midi_in.is_open, "name": self.midi_in.port_name},
                "leds": {"open": self.leds.is_open, "name": self.leds.port_name, "error": self.led_error,
                         "states": {str(n): s for n, s in e.led_states().items()}
                         if e.config.led_feedback else {}},
                "output": {"enabled": e.output_enabled, "simulate": self.simulate_output,
                           "dest": self.sender.dest[0] if self.sender else None,
                           "packets": self.sender.packets_sent if self.sender else 0},
                "learning": e.learning,
                "learned": list(learned) if learned else None,
                "pressed": sorted(e.pressed),
                "active": sorted(e.active),
                "faders": [{"physical": f.physical, "output": f.output, "picked_up": f.picked_up,
                            "enabled": f.mapping.enabled, "target": f.pickup.target} for f in e.faders],
                "config": e.config.to_dict(),
                "unsaved": self.unsaved,
                "config_path": str(self.config_path),
                "log": self.logbuf.since(log_since),
            }
