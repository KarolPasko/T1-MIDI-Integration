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

from . import __version__, apc_mini, ports, webapi
from .bridge import BridgeEngine
from .config import TITAN, BridgeConfig, ConfigError
from .hardware_test import HardwareTest
from .library import PRESET, SAVED, MappingLibrary, check_name
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
    def __init__(self, app_folder: Path, simulate_midi: bool = False, presets: Path | None = None):
        self.library = MappingLibrary(app_folder, presets)
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

        # Nothing is loaded until the start screen picks a file.
        self.engine = BridgeEngine(BridgeConfig())
        self.current: dict | None = None   # {"kind": "saved"|"preset"|"imported", "name": ...}
        self.unsaved = False
        self.sender: SacnSender | None = None
        self.simulate_output = False
        self.led_error: str | None = None
        self.port_list = ports.PortList([], [])
        self.wanted_ports: tuple[str, str] | None = None   # what to reconnect to after an unplug
        self.apc_lost = False
        self.midi_count = 0          # MIDI messages received, for the activity light
        self.output_on_since: float | None = None
        self.test: HardwareTest | None = None   # APC mini hardware test, only while output is OFF
        self.titan: webapi.TitanClient | None = None   # only while output is ON and something uses the WebAPI
        self.titan_check: dict | None = None
        self.taps = webapi.TapTempo()
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
        if self._thread.is_alive():
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
            self.midi_count += 1
            if ev.channel != 1:
                continue
            if self.test is not None:   # during a hardware test, input never reaches the mapping
                if ev.is_cc:
                    self.test.fader(ev.number, ev.value)
                elif ev.is_press:
                    self.test.press(ev.number)
                elif ev.is_release:
                    self.test.release(ev.number)
                continue
            if ev.is_cc:
                self.dirty |= self.engine.handle_cc(ev.channel, ev.number, ev.value)
            elif ev.is_press:
                self.dirty |= self.engine.handle_press(ev.number, ev.timestamp)
            elif ev.is_release:
                self.dirty |= self.engine.handle_release(ev.number)
        self._send_titan()
        now = time.monotonic()
        if self.sender is not None:
            if (self.dirty and now - self._last_send >= MIN_GAP_S) or now - self._last_send >= KEEPALIVE_S:
                try:
                    self.sender.send(self.engine.dmx_frame())
                except SacnError as exc:
                    log.error("%s - output switched OFF", exc)
                    self.engine.set_output_enabled(False)
                    self.output_on_since = None
                    self.sender = None
                self._last_send = now
                self.dirty = False
        if now - self._last_led >= LED_S:
            self._last_led = now
            self._update_leds()
        if now - self._last_watchdog >= WATCHDOG_S:
            self._last_watchdog = now
            self._watchdog()

    def _send_titan(self) -> None:
        events = self.engine.take_titan_events()
        if self.titan is None:
            return
        cfg = self.engine.config
        for ev in events:
            try:
                if ev[0] == "fader":
                    f = cfg.faders[ev[1]]
                    if f.uses_webapi:
                        self.titan.submit_fader(ev[1], webapi.fader_call(f.action, ev[2]))
                else:
                    b = cfg.button(ev[1])
                    if b is None or b.mode != TITAN:
                        continue
                    if b.action["type"] == "tap_tempo":
                        if ev[0] == "press":
                            bpm = self.taps.tap(b.note, ev[2] if ev[2] is not None else time.time())
                            if bpm is not None:
                                self.titan.submit([webapi.speed_call(b.action, bpm)])
                    else:
                        self.titan.submit(webapi.button_calls(b.action, ev[0] == "press"))
            except (webapi.ActionError, KeyError, IndexError) as exc:
                log.error("Titan action skipped: %s", exc)

    def _update_leds(self) -> None:
        if not (self.leds.is_open and (self.engine.config.led_feedback or self.test)):
            return
        wanted = self._led_states()
        try:
            for note in apc_mini.LED_NOTES:
                self.leds.set_led(note, wanted.get(note, 0))
        except LedOutputError as exc:
            self.led_error = str(exc)
            log.error("LED feedback stopped: %s", exc)

    def _watchdog(self) -> None:
        if self.simulate_midi or self.wanted_ports is None:
            return
        pl = ports.list_ports()
        if pl.error:
            return
        if self.midi_in.is_open and not ports.still_present(self.midi_in.port_name, pl.inputs):
            self.midi_in.close()
            self.apc_lost = True
            if self.engine.output_enabled:
                self.set_output(False)
                log.warning("APC mini unplugged: output switched OFF. Plug it back in; it reconnects "
                            "by itself, then switch output ON again (faders will need pickup).")
            else:
                log.warning("APC mini input disappeared (unplugged?)")
        if self.leds.is_open and not ports.still_present(self.leds.port_name, pl.outputs):
            self.leds.close()
            self.apc_lost = True
            self.led_error = "APC mini LED output disappeared"
            log.warning(self.led_error)
        if self.apc_lost:
            self._reconnect(pl)

    def _reconnect(self, pl: ports.PortList) -> None:
        """Reopen the APC mini once it is plugged back in. Output stays OFF."""
        want_in, want_out = self.wanted_ports
        new_in = next((n for n in pl.inputs if ports.base_name(n) == ports.base_name(want_in)), None) \
            if want_in else None
        new_out = next((n for n in pl.outputs if ports.base_name(n) == ports.base_name(want_out)), None) \
            if want_out else None
        if (want_in and not new_in) or (want_out and not new_out):
            return
        try:
            if new_in and not self.midi_in.is_open:
                self.midi_in.open(new_in)
            if new_out and not self.leds.is_open:
                self.leds.open(new_out)
                self.led_error = None
        except (MidiInputError, LedOutputError) as exc:
            log.warning("APC mini is back but could not be reopened yet: %s", exc)
            return
        self.apc_lost = False
        self.refresh_ports()
        log.info("APC mini reconnected. Output is still OFF: switch it ON when ready.")

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
            self.wanted_ports = (input_name, output_name)
            self.apc_lost = False
            log.info("Connected")

    def disconnect(self) -> None:
        with self.lock:
            self.wanted_ports = None
            self.apc_lost = False
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
                if self.test is not None:
                    raise ActionError("Finish the APC mini test before switching output ON.")
                cfg = self.engine.config
                try:
                    self.sender = SacnSender(cfg.universe, unicast_ip=cfg.unicast_ip, source_name="APC Bridge",
                                             sock_factory=_NullSocket if self.simulate_output else None)
                except SacnError as exc:
                    raise ActionError(str(exc)) from exc
                if self._uses_webapi(cfg):
                    self.titan = webapi.TitanClient(cfg.titan_host, cfg.titan_port, dry_run=self.simulate_output)
                    log.info("Titan WebAPI actions go to %s:%d%s", cfg.titan_host, cfg.titan_port,
                             " (TEST MODE: not sent)" if self.simulate_output else "")
                self.engine.set_output_enabled(True)
                self.output_on_since = time.monotonic()
                self.dirty = True
                log.info("Output ON (%s) universe %d -> %s. Move each fader to its last level to pick it up.",
                         "SIMULATED" if self.simulate_output else "sACN", cfg.universe, self.sender.dest[0])
            elif not on and self.engine.output_enabled:
                self.engine.set_output_enabled(False)
                self.output_on_since = None
                self._send_titan()     # e.g. the release of a flash that was still held
                if self.titan is not None:
                    self.titan.close(wait_s=0)
                    self.titan = None
                if self.sender is not None:
                    self.sender.stop(self.engine.dmx_frame())
                    self.sender = None
                log.info("Output OFF (sACN stream terminated)")

    @staticmethod
    def _uses_webapi(cfg: BridgeConfig) -> bool:
        return any(b.mode == TITAN for b in cfg.buttons) or any(f.uses_webapi for f in cfg.faders)

    def check_titan(self) -> None:
        """Ask Titan for its version (read-only), in the background; the answer appears in state()."""
        with self.lock:
            host, port = self.engine.config.titan_host, self.engine.config.titan_port
            self.titan_check = {"busy": True, "ok": None, "text": f"Asking {host}:{port}…"}

        def run():
            try:
                reply = webapi.check(host, port)
                result = {"busy": False, "ok": True, "text": f"Titan answered: {reply[:200]}"}
                log.info("Titan WebAPI check: %s", reply[:200])
            except webapi.WebApiError as exc:
                result = {"busy": False, "ok": False, "text": str(exc)}
                log.warning("Titan WebAPI check failed: %s", exc)
            with self.lock:
                self.titan_check = result

        threading.Thread(target=run, name="titan-check", daemon=True).start()

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

    def open_file(self, kind: str, name: str) -> None:
        with self.lock:
            if self.engine.output_enabled:
                raise ActionError("Switch output OFF before opening another mapping.")
            try:
                cfg = self.library.load(kind, name)
            except ConfigError as exc:
                raise ActionError(str(exc)) from exc
            self.engine.apply_config(cfg)
            self.current = {"kind": kind, "name": name}
            self.unsaved = False
            log.info("Opened '%s'", name)

    def import_config(self, data: dict, name: str) -> None:
        """A file the user picked from anywhere on the computer."""
        with self.lock:
            if self.engine.output_enabled:
                raise ActionError("Switch output OFF before opening another mapping.")
            try:
                cfg = BridgeConfig.from_dict(data)
            except ConfigError as exc:
                raise ActionError(str(exc)) from exc
            self.engine.apply_config(cfg)
            self.current = {"kind": "imported", "name": name or "Imported"}
            self.unsaved = True   # it is not in the mappings folder until saved
            log.info("Imported '%s' (use Save as to keep it)", name)

    def new_file(self) -> None:
        with self.lock:
            if self.engine.output_enabled:
                raise ActionError("Switch output OFF first.")
            self.engine.apply_config(BridgeConfig())
            self.current = {"kind": "imported", "name": "New mapping"}
            self.unsaved = True

    def save(self, name: str | None = None) -> None:
        """Save to the current file, or under a new name ("Save as")."""
        with self.lock:
            if name is None:
                if not self.current or self.current["kind"] != SAVED:
                    raise ActionError("Ready-made and imported mappings need 'Save as' with a name of your own.")
                name = self.current["name"]
            try:
                name = check_name(name)
                path = self.library.save(self.engine.config, name)
            except (OSError, ConfigError) as exc:
                raise ActionError(f"Could not save: {exc}") from exc
            self.current = {"kind": SAVED, "name": name}
            self.unsaved = False
            log.info("Saved to %s", path)

    def set_blackout(self, on: bool) -> None:
        with self.lock:
            if bool(on) != self.engine.blackout:
                self.engine.set_blackout(bool(on))
                self._send_titan()
                self.dirty = True
                if on:
                    log.warning("BLACKOUT: every channel at zero")
                else:
                    log.info("Blackout released: bring each fader down to zero to pick it up")

    def _led_states(self) -> dict[int, int]:
        if self.test is not None:
            return self.test.leds(time.monotonic())[1]
        return self.engine.led_states()

    def start_test(self, mode: str) -> None:
        with self.lock:
            if self.engine.output_enabled:
                raise ActionError("Switch output OFF before testing the APC mini.")
            try:
                self.test = HardwareTest(mode, time.monotonic())
            except ValueError as exc:
                raise ActionError(str(exc)) from exc
            self.engine.set_learning(False)
            log.info("APC mini test started: %s", mode)

    def stop_test(self) -> None:
        with self.lock:
            if self.test is not None:
                self.test = None
                if not self.engine.config.led_feedback and self.leds.is_open:
                    try:
                        self.leds.restore({})   # pad lights are switched off in the settings
                    except LedOutputError:
                        pass
                log.info("APC mini test finished")

    def set_learning(self, on: bool) -> None:
        with self.lock:
            self.engine.set_learning(bool(on))

    # ------------------------------------------------------------------ state
    def state(self, log_since: int = 0) -> dict:
        with self.lock:
            e = self.engine
            learned = e.take_learned()
            return {
                "version": __version__,
                "simulate_midi": self.simulate_midi,
                "apc_lost": self.apc_lost,
                "midi_count": self.midi_count,
                "blackout": e.blackout,
                "output_on_for": round(time.monotonic() - self.output_on_since)
                if self.output_on_since is not None else None,
                "ports": {"inputs": self.port_list.inputs, "outputs": self.port_list.outputs,
                          "error": self.port_list.error},
                "midi_in": {"open": self.midi_in.is_open, "name": self.midi_in.port_name},
                "leds": {"open": self.leds.is_open, "name": self.leds.port_name, "error": self.led_error,
                         "states": {str(n): s for n, s in self._led_states().items()}
                         if e.config.led_feedback or self.test else {}},
                "test": self.test.to_dict(time.monotonic()) if self.test else None,
                "output": {"enabled": e.output_enabled, "simulate": self.simulate_output,
                           "dest": self.sender.dest[0] if self.sender else None,
                           "packets": self.sender.packets_sent if self.sender else 0},
                "titan": {"active": self.titan is not None,
                          "sent": self.titan.sent if self.titan else 0,
                          "errors": self.titan.errors if self.titan else 0,
                          "error": self.titan.last_error if self.titan else None,
                          "check": self.titan_check,
                          "held": sorted(e.titan_held),
                          "tempo": {str(n): bpm for n, bpm in self.taps.bpm.items()}},
                "learning": e.learning,
                "learned": list(learned) if learned else None,
                "pressed": sorted(e.pressed),
                "active": sorted(e.active),
                "faders": [{"physical": f.physical, "output": f.output, "picked_up": f.picked_up,
                            "enabled": f.mapping.enabled, "target": f.pickup.target} for f in e.faders],
                "config": e.config.to_dict(),
                "unsaved": self.unsaved,
                "current": self.current,
                "files": self.library.list(),
                "mappings_folder": str(self.library.folder),
                "log": self.logbuf.since(log_since),
            }
