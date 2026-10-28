"""The bridge window: APC mini faders -> sACN -> Titan Go triggers.

Run:  py -3.12 run_bridge.py            (real APC mini)
      py -3.12 run_bridge.py --simulate (fake APC mini, for trying it out)

Output starts OFF. While it is off nothing is sent. When it is switched on,
every fader must be moved to its last level ("pickup") before it takes over.
"""

from __future__ import annotations

import argparse
import logging
import queue
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import apc_mini, config as config_mod, ports
from .bridge import BridgeEngine
from .config import BridgeConfig, ConfigError, FaderMapping
from .gui import QueueLogHandler
from .led_output import LedOutput, LedOutputError
from .midi_input import MidiInputError, MidiInputListener
from .sacn import SacnError, SacnSender

log = logging.getLogger(__name__)

POLL_MS = 25
LED_MS = 60         # LED refresh; unchanged LEDs are never re-sent
VIEW_MS = 100       # fader table refresh
WATCHDOG_MS = 1500
KEEPALIVE_S = 0.8
MIN_GAP_S = 0.025

TITAN_HELP = (
    "Titan Go setup (once per show): System > Triggers > add a mapping. For each fader add a "
    "trigger: Type = Item, choose the playback, action = Set Level, source = Streaming ACN, "
    "universe and channel as in the table below (or Learn On and move the fader with output ON)."
)


class _NullSocket:
    """Stands in for the network in simulated-output mode."""

    def setsockopt(self, *args):
        pass

    def sendto(self, data, addr):
        pass

    def close(self):
        pass


class BridgeApp:
    def __init__(self, root: tk.Tk, simulate_midi: bool = False, config_path: Path = config_mod.DEFAULT_PATH):
        self.root = root
        self.simulate_midi = simulate_midi
        self.config_path = config_path
        self.events: queue.Queue = queue.Queue()
        self.log_lines: queue.Queue = queue.Queue()
        if simulate_midi:
            from . import simulation
            self.midi_in = MidiInputListener(self.events, opener=simulation.open_input)
            self.leds = LedOutput(opener=simulation.open_output)
        else:
            self.midi_in = MidiInputListener(self.events)
            self.leds = LedOutput()

        try:
            cfg = config_mod.load(config_path)
        except ConfigError as exc:
            messagebox.showwarning("Settings", f"{exc}\n\nStarting with default settings.")
            cfg = BridgeConfig()
        self.engine = BridgeEngine(cfg)
        self.sender: SacnSender | None = None
        self.dirty = False
        self.last_send = 0.0

        handler = QueueLogHandler(self.log_lines)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
        logging.getLogger().addHandler(handler)

        root.title("APC mini -> Titan Go bridge (sACN)" + ("  [SIMULATED APC]" if simulate_midi else ""))
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._build()
        self._load_into_table(cfg)
        self.refresh_ports()
        self._update_output_view()
        for ms, fn in ((POLL_MS, self._tick), (LED_MS, self._led_tick),
                       (VIEW_MS, self._view_tick), (WATCHDOG_MS, self._watchdog)):
            self.root.after(ms, fn)

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        pad = {"padx": 6, "pady": 3}
        self.status = tk.Label(self.root, font=("Segoe UI", 13, "bold"), fg="white", pady=6)
        self.status.pack(fill="x", **pad)

        conn = ttk.LabelFrame(self.root, text="APC mini")
        conn.pack(fill="x", **pad)
        ttk.Label(conn, text="Input:").grid(row=0, column=0, sticky="w")
        self.in_var = tk.StringVar()
        self.in_combo = ttk.Combobox(conn, textvariable=self.in_var, state="readonly", width=30)
        self.in_combo.grid(row=0, column=1)
        ttk.Label(conn, text="LED output:").grid(row=0, column=2, sticky="w", padx=(10, 0))
        self.out_var = tk.StringVar()
        self.out_combo = ttk.Combobox(conn, textvariable=self.out_var, state="readonly", width=30)
        self.out_combo.grid(row=0, column=3)
        ttk.Button(conn, text="Refresh", command=self.refresh_ports).grid(row=0, column=4, padx=3)
        ttk.Button(conn, text="Connect", command=self.connect).grid(row=0, column=5, padx=3)
        ttk.Button(conn, text="Disconnect", command=self.disconnect).grid(row=0, column=6, padx=3)
        self.in_status = ttk.Label(conn, text="Input: disconnected", foreground="grey")
        self.in_status.grid(row=1, column=0, columnspan=2, sticky="w")
        self.led_status = ttk.Label(conn, text="LEDs: not connected", foreground="grey")
        self.led_status.grid(row=1, column=2, columnspan=2, sticky="w")
        self.led_feedback = tk.BooleanVar(value=self.engine.config.led_feedback)
        ttk.Checkbutton(conn, text="LED feedback (shows this app's state, not Titan's)",
                        variable=self.led_feedback, command=self._led_feedback_changed).grid(
            row=1, column=4, columnspan=3, sticky="w")

        out = ttk.LabelFrame(self.root, text="sACN output to Titan Go")
        out.pack(fill="x", **pad)
        self.out_btn = ttk.Button(out, text="", command=self.toggle_output)
        self.out_btn.grid(row=0, column=0, rowspan=2, padx=6, ipady=6)
        self.simulate_out = tk.BooleanVar(value=False)
        self.sim_check = ttk.Checkbutton(out, text="Simulate only (send nothing to the network)",
                                         variable=self.simulate_out)
        self.sim_check.grid(row=0, column=1, columnspan=3, sticky="w")
        ttk.Label(out, text="Universe:").grid(row=1, column=1, sticky="w")
        self.universe = tk.IntVar()
        self.universe_spin = ttk.Spinbox(out, from_=1, to=63999, textvariable=self.universe, width=7)
        self.universe_spin.grid(row=1, column=2, sticky="w")
        self.mode = tk.StringVar()
        self.multi_radio = ttk.Radiobutton(out, text="Multicast", variable=self.mode, value="multicast")
        self.multi_radio.grid(row=1, column=3, sticky="w")
        self.uni_radio = ttk.Radiobutton(out, text="Unicast to:", variable=self.mode, value="unicast")
        self.uni_radio.grid(row=1, column=4, sticky="w")
        self.ip = tk.StringVar()
        self.ip_entry = ttk.Entry(out, textvariable=self.ip, width=15)
        self.ip_entry.grid(row=1, column=5, sticky="w")
        ttk.Label(out, text="Max output %:").grid(row=1, column=6, sticky="w", padx=(10, 0))
        self.max_pct = tk.DoubleVar()
        self.max_spin = ttk.Spinbox(out, from_=0, to=100, textvariable=self.max_pct, width=5)
        self.max_spin.grid(row=1, column=7, sticky="w")
        self.count_label = ttk.Label(out, text="", foreground="grey")
        self.count_label.grid(row=0, column=4, columnspan=4, sticky="w")

        tbl = ttk.LabelFrame(self.root, text="Fader mapping (locked while output is ON)")
        tbl.pack(fill="x", **pad)
        heads = ("Fader", "Titan playback (label)", "sACN ch", "On", "Min %", "Max %",
                 "Fader position", "Output", "Status")
        for c, h in enumerate(heads):
            ttk.Label(tbl, text=h, font=("Segoe UI", 9, "bold")).grid(row=0, column=c, sticky="w", padx=3)
        self.rows = []
        for i in range(len(apc_mini.FADER_CCS)):
            r = i + 1
            row = {
                "label": tk.StringVar(), "address": tk.IntVar(), "enabled": tk.BooleanVar(),
                "min": tk.DoubleVar(), "max": tk.DoubleVar(),
            }
            ttk.Label(tbl, text=apc_mini.describe_cc(apc_mini.FADER_CCS[i])).grid(row=r, column=0, sticky="w")
            row["w"] = [
                ttk.Entry(tbl, textvariable=row["label"], width=20),
                ttk.Spinbox(tbl, from_=1, to=512, textvariable=row["address"], width=5),
                ttk.Checkbutton(tbl, variable=row["enabled"], command=lambda i=i: self._enabled_clicked(i)),
                ttk.Spinbox(tbl, from_=0, to=100, textvariable=row["min"], width=5),
                ttk.Spinbox(tbl, from_=0, to=100, textvariable=row["max"], width=5),
            ]
            for c, w in enumerate(row["w"], start=1):
                w.grid(row=r, column=c, sticky="w", padx=3)
            row["bar"] = ttk.Progressbar(tbl, length=110, maximum=127)
            row["bar"].grid(row=r, column=6, padx=3)
            row["out"] = ttk.Label(tbl, text="0%", width=6)
            row["out"].grid(row=r, column=7)
            row["state"] = ttk.Label(tbl, text="", width=24)
            row["state"].grid(row=r, column=8, sticky="w")
            self.rows.append(row)
        btns = ttk.Frame(tbl)
        btns.grid(row=len(self.rows) + 1, column=0, columnspan=9, sticky="w", pady=4)
        self.apply_btn = ttk.Button(btns, text="Apply changes", command=self.apply_table)
        self.apply_btn.pack(side="left")
        self.save_btn = ttk.Button(btns, text="Save settings", command=self.save)
        self.save_btn.pack(side="left", padx=4)
        self.load_btn = ttk.Button(btns, text="Reload saved", command=self.reload)
        self.load_btn.pack(side="left")
        self.defaults_btn = ttk.Button(btns, text="Defaults", command=self.defaults)
        self.defaults_btn.pack(side="left", padx=4)
        ttk.Label(btns, text=f"File: {self.config_path.resolve()}", foreground="grey").pack(side="left", padx=8)

        ttk.Label(self.root, text=TITAN_HELP + "\nOn the APC mini: track button under a fader = fader on/off "
                  "(lit = live, blinking = waiting for pickup). Bottom scene button = master fader on/off. "
                  "Top scene button: lit = output ON, blinking = OFF. Grid columns = level meters.",
                  wraplength=980, justify="left").pack(fill="x", **pad)

        lf = ttk.LabelFrame(self.root, text="Log")
        lf.pack(fill="both", expand=True, **pad)
        self.log_text = ScrolledText(lf, height=6, state="disabled", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)

        self._settings_widgets = [self.sim_check, self.universe_spin, self.multi_radio, self.uni_radio,
                                  self.ip_entry, self.max_spin, self.apply_btn, self.load_btn,
                                  self.defaults_btn] + [w for r in self.rows for i, w in enumerate(r["w"]) if i != 2]

    # ---------------------------------------------------------------- settings
    def _load_into_table(self, cfg: BridgeConfig) -> None:
        self.universe.set(cfg.universe)
        self.mode.set("unicast" if cfg.unicast_ip else "multicast")
        self.ip.set(cfg.unicast_ip or "127.0.0.1")
        self.max_pct.set(cfg.max_output_percent)
        self.led_feedback.set(cfg.led_feedback)
        for row, f in zip(self.rows, cfg.faders):
            row["label"].set(f.label)
            row["address"].set(f.address)
            row["enabled"].set(f.enabled)
            row["min"].set(f.min_percent)
            row["max"].set(f.max_percent)

    def _read_table(self) -> BridgeConfig:
        try:
            faders = [FaderMapping(cc=cc, label=row["label"].get().strip(), address=int(row["address"].get()),
                                   enabled=bool(row["enabled"].get()), min_percent=float(row["min"].get()),
                                   max_percent=float(row["max"].get()))
                      for cc, row in zip(apc_mini.FADER_CCS, self.rows)]
            cfg = BridgeConfig(universe=int(self.universe.get()),
                               unicast_ip=self.ip.get().strip() if self.mode.get() == "unicast" else None,
                               max_output_percent=float(self.max_pct.get()),
                               led_feedback=bool(self.led_feedback.get()), faders=faders)
        except (tk.TclError, ValueError) as exc:
            raise ConfigError(f"A number in the table is not valid: {exc}") from exc
        cfg.validate()
        return cfg

    def apply_table(self) -> bool:
        try:
            self.engine.apply_config(self._read_table())
        except ConfigError as exc:
            messagebox.showerror("Settings", str(exc))
            return False
        log.info("Mapping applied")
        return True

    def save(self) -> None:
        if self.engine.output_enabled:
            cfg = self.engine.config
        else:
            if not self.apply_table():
                return
            cfg = self.engine.config
        try:
            config_mod.save(cfg, self.config_path)
            log.info("Settings saved to %s", self.config_path.resolve())
        except (OSError, ConfigError) as exc:
            messagebox.showerror("Save settings", str(exc))

    def reload(self) -> None:
        try:
            cfg = config_mod.load(self.config_path)
        except ConfigError as exc:
            messagebox.showerror("Reload", str(exc))
            return
        self._load_into_table(cfg)
        self.engine.apply_config(cfg)
        log.info("Settings reloaded")

    def defaults(self) -> None:
        cfg = BridgeConfig()
        self._load_into_table(cfg)
        self.engine.apply_config(cfg)
        log.info("Default mapping loaded (not saved yet)")

    def _enabled_clicked(self, i: int) -> None:
        # The On column works live, also while output is ON (with pickup).
        if self.engine.faders[i].mapping.enabled != self.rows[i]["enabled"].get():
            self.engine.toggle_fader(i)

    def _led_feedback_changed(self) -> None:
        self.engine.config.led_feedback = self.led_feedback.get()
        if not self.led_feedback.get() and self.leds.is_open:
            try:
                self.leds.restore({})
            except LedOutputError as exc:
                log.warning("%s", exc)

    # -------------------------------------------------------------- MIDI ports
    def refresh_ports(self) -> None:
        if self.simulate_midi:
            from .simulation import SIM_PORT
            pl = ports.PortList([SIM_PORT], [SIM_PORT])
        else:
            pl = ports.list_ports()
            if pl.error:
                log.error(pl.error)
        self.in_combo.configure(values=pl.inputs)
        self.out_combo.configure(values=pl.outputs)
        if self.in_var.get() not in pl.inputs:
            self.in_var.set(ports.find_apc_mini(pl.inputs) or "")
        if self.out_var.get() not in pl.outputs:
            self.out_var.set(ports.find_apc_mini(pl.outputs) or "")

    def connect(self) -> None:
        if self.in_var.get():
            try:
                self.midi_in.open(self.in_var.get())
            except MidiInputError as exc:
                messagebox.showerror("APC mini input", str(exc))
        if self.out_var.get():
            try:
                self.leds.open(self.out_var.get())
            except LedOutputError as exc:
                log.error("%s", exc)
        self._update_conn_view()

    def disconnect(self) -> None:
        self.set_output(False)
        if self.leds.is_open:
            try:
                self.leds.restore({})
            except LedOutputError:
                pass
        self.midi_in.close()
        self.leds.close()
        self._update_conn_view()

    def _update_conn_view(self) -> None:
        self.in_status.configure(text="Input: CONNECTED" if self.midi_in.is_open else "Input: disconnected",
                                 foreground="green" if self.midi_in.is_open else "grey")
        self.led_status.configure(text="LEDs: connected" if self.leds.is_open else "LEDs: not connected",
                                  foreground="green" if self.leds.is_open else "grey")

    def _watchdog(self) -> None:
        try:
            if not self.simulate_midi and (self.midi_in.is_open or self.leds.is_open):
                pl = ports.list_ports()
                if not pl.error:
                    if self.midi_in.is_open and not ports.still_present(self.midi_in.port_name, pl.inputs):
                        self.midi_in.close()
                        if self.engine.output_enabled:
                            self.set_output(False)
                            log.warning("APC mini unplugged: output switched OFF. Reconnect, then switch "
                                        "output ON again (faders will need pickup).")
                        else:
                            log.warning("APC mini input disappeared (unplugged?)")
                    if self.leds.is_open and not ports.still_present(self.leds.port_name, pl.outputs):
                        self.leds.close()
                        log.warning("APC mini LED output disappeared")
                    self._update_conn_view()
        finally:
            self.root.after(WATCHDOG_MS, self._watchdog)

    # ------------------------------------------------------------------ output
    def toggle_output(self) -> None:
        self.set_output(not self.engine.output_enabled)

    def set_output(self, on: bool) -> None:
        if on and not self.engine.output_enabled:
            if not self.apply_table():
                return
            cfg = self.engine.config
            sock_factory = _NullSocket if self.simulate_out.get() else None
            try:
                self.sender = SacnSender(cfg.universe, unicast_ip=cfg.unicast_ip,
                                         source_name="APC Bridge", sock_factory=sock_factory)
            except SacnError as exc:
                messagebox.showerror("sACN", str(exc))
                return
            self.engine.set_output_enabled(True)
            self.dirty = True
            log.info("Output ON (%s) universe %d -> %s. Move each fader to its last level to pick it up.",
                     "SIMULATED" if self.simulate_out.get() else "sACN", cfg.universe, self.sender.dest[0])
        elif not on and self.engine.output_enabled:
            self.engine.set_output_enabled(False)
            if self.sender is not None:
                self.sender.stop(self.engine.dmx_frame())
                self.sender = None
            log.info("Output OFF (sACN stream terminated)")
        self._update_output_view()

    def _update_output_view(self) -> None:
        on = self.engine.output_enabled
        if not on:
            self.status.configure(text="OUTPUT OFF - nothing is being sent to Titan Go", bg="#555555")
        elif self.simulate_out.get():
            self.status.configure(text="SIMULATED OUTPUT - levels are calculated but NOT sent", bg="#00457a")
        else:
            self.status.configure(text=f"OUTPUT ON - sending sACN universe {self.engine.config.universe} "
                                       f"to {self.sender.dest[0]}", bg="#b00000")
        self.out_btn.configure(text="Switch output OFF" if on else "Switch output ON")
        for w in self._settings_widgets:
            try:
                w.configure(state="disabled" if on else "normal")
            except tk.TclError:
                pass

    # -------------------------------------------------------------------- loops
    def _tick(self) -> None:
        try:
            for _ in range(500):
                try:
                    ev = self.events.get_nowait()
                except queue.Empty:
                    break
                if ev.is_cc:
                    self.dirty |= self.engine.handle_cc(ev.channel, ev.number, ev.value)
                elif ev.is_press and ev.channel == 1:
                    if self.engine.handle_press(ev.number):
                        self.dirty = True
                        for row, f in zip(self.rows, self.engine.faders):
                            row["enabled"].set(f.mapping.enabled)
            if self.sender is not None:
                now = time.monotonic()
                if (self.dirty and now - self.last_send >= MIN_GAP_S) or now - self.last_send >= KEEPALIVE_S:
                    self.sender.send(self.engine.dmx_frame())
                    self.last_send = now
                    self.dirty = False
        except SacnError as exc:
            log.error("%s", exc)
            self.engine.set_output_enabled(False)
            self.sender = None
            self._update_output_view()
            messagebox.showerror("sACN", f"{exc}\n\nOutput has been switched OFF.")
        finally:
            self.root.after(POLL_MS, self._tick)

    def _led_tick(self) -> None:
        try:
            if self.leds.is_open and self.led_feedback.get():
                wanted = self.engine.led_states()
                for note in apc_mini.LED_NOTES:
                    self.leds.set_led(note, wanted.get(note, 0))
        except LedOutputError as exc:
            log.error("LED feedback stopped: %s", exc)
            self._update_conn_view()
        finally:
            self.root.after(LED_MS, self._led_tick)

    def _view_tick(self) -> None:
        try:
            for row, f in zip(self.rows, self.engine.faders):
                if f.physical is not None:
                    row["bar"].configure(value=f.physical)
                row["out"].configure(text=f"{round(f.output / 2.55)}%")
                if not f.mapping.enabled:
                    text, colour = "Off", "grey"
                elif not self.engine.output_enabled:
                    text, colour = "Output off", "grey"
                elif f.picked_up:
                    text, colour = "LIVE", "green"
                else:
                    text, colour = f"Move fader to {round(f.pickup.target / 2.55)}%", "#b36b00"
                row["state"].configure(text=text, foreground=colour)
            if self.sender is not None:
                self.count_label.configure(text=f"{self.sender.packets_sent} packets sent")
            lines = []
            while True:
                try:
                    lines.append(self.log_lines.get_nowait())
                except queue.Empty:
                    break
            if lines:
                self.log_text.configure(state="normal")
                self.log_text.insert("end", "\n".join(lines) + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
        finally:
            self.root.after(VIEW_MS, self._view_tick)

    def on_close(self) -> None:
        try:
            self.disconnect()
        finally:
            self.root.destroy()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bridge", description=__doc__)
    parser.add_argument("--simulate", action="store_true", help="use a fake APC mini")
    parser.add_argument("--config", type=Path, default=config_mod.DEFAULT_PATH, help="settings file")
    args = parser.parse_args(argv)
    log_dir = Path.cwd() / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(log_dir / "bridge.log", encoding="utf-8")])
    root = tk.Tk()
    BridgeApp(root, simulate_midi=args.simulate, config_path=args.config)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
