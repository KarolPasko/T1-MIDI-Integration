"""sACN trigger test: find out whether Titan Go can follow an APC mini fader.

Run:  py -3.12 run_sacn_test.py      (add --simulate to use the fake APC mini)

This sends ONE sACN channel on ONE universe. Titan Go does nothing with it
unless you create a matching trigger in System -> Triggers, so it cannot
affect your lights by surprise. Output starts OFF and only runs while the
"Send sACN" switch is on.
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

from . import apc_mini, ports
from .midi_input import MidiInputError, MidiInputListener
from .pickup import Pickup, midi_to_dmx
from .sacn import SacnError, SacnSender, multicast_address

log = logging.getLogger(__name__)

POLL_MS = 25
KEEPALIVE_S = 0.8   # receivers drop a source after 2.5 s of silence
MIN_GAP_S = 0.025   # at most ~40 packets/s while the value is changing

STEPS = (
    "How to test with Titan Go (T1 plugged in):\n"
    "1. In Titan Go open System > Triggers and add a mapping.\n"
    "2. Add a trigger: Type = Item, pick a playback, action = Set Level.\n"
    "3. Change its source to Streaming ACN (sACN). Turn Learn On.\n"
    "4. Here: set universe/channel, switch 'Send sACN' ON and move the slider "
    "(or the chosen APC fader).\n"
    "5. Watch the playback's level in Titan Go. Does it follow the slider smoothly, "
    "only switch on/off, or do nothing?"
)


class SacnTestApp:
    def __init__(self, root: tk.Tk, simulate: bool = False):
        self.root = root
        self.simulate = simulate
        self.events: queue.Queue = queue.Queue()
        if simulate:
            from . import simulation
            self.midi_in = MidiInputListener(self.events, opener=simulation.open_input)
        else:
            self.midi_in = MidiInputListener(self.events)
        self.sender: SacnSender | None = None
        self.value = 0              # DMX value 0-255 we are sending
        self.dirty = False
        self.last_send = 0.0
        self.pickup = Pickup(0, tolerance=4)
        self._programmatic = False  # True while we move the slider ourselves

        root.title("sACN Trigger Test - APC Bridge" + ("  [SIMULATED APC]" if simulate else ""))
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._build()
        self.refresh_midi()
        self.root.after(POLL_MS, self._tick)

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        pad = {"padx": 6, "pady": 4}
        self.status = tk.Label(self.root, text="", font=("Segoe UI", 12, "bold"), fg="white", pady=6)
        self.status.pack(fill="x", **pad)

        net = ttk.LabelFrame(self.root, text="sACN destination")
        net.pack(fill="x", **pad)
        ttk.Label(net, text="Universe:").grid(row=0, column=0, sticky="w")
        self.universe = tk.IntVar(value=10)
        ttk.Spinbox(net, from_=1, to=63999, textvariable=self.universe, width=7).grid(row=0, column=1, sticky="w")
        ttk.Label(net, text="Channel (address):").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.channel = tk.IntVar(value=1)
        ttk.Spinbox(net, from_=1, to=512, textvariable=self.channel, width=5).grid(row=0, column=3, sticky="w")
        self.mode = tk.StringVar(value="multicast")
        ttk.Radiobutton(net, text="Multicast (standard)", variable=self.mode, value="multicast").grid(
            row=1, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(net, text="Unicast to IP:", variable=self.mode, value="unicast").grid(
            row=1, column=2, sticky="w", padx=(12, 0))
        self.ip = tk.StringVar(value="127.0.0.1")
        ttk.Entry(net, textvariable=self.ip, width=15).grid(row=1, column=3, sticky="w")
        ttk.Label(net, foreground="grey", text="Use a universe Titan is NOT outputting on. "
                  "Settings are locked while sending.").grid(row=2, column=0, columnspan=4, sticky="w")
        self.net_frame = net

        lvl = ttk.LabelFrame(self.root, text="Level")
        lvl.pack(fill="x", **pad)
        self.slider = ttk.Scale(lvl, from_=0, to=255, orient="horizontal", length=360,
                                command=self._slider_moved)
        self.slider.grid(row=0, column=0, columnspan=3, sticky="we")
        self.value_label = ttk.Label(lvl, text="0 (0%)", width=12)
        self.value_label.grid(row=0, column=3)
        ttk.Label(lvl, text="Max output %:").grid(row=1, column=0, sticky="w")
        self.max_pct = tk.IntVar(value=100)
        ttk.Spinbox(lvl, from_=0, to=100, textvariable=self.max_pct, width=5).grid(row=1, column=1, sticky="w")
        ttk.Button(lvl, text="Set to 0", command=lambda: self._set_value(0, from_slider=False)).grid(
            row=1, column=2, sticky="w")

        apc = ttk.LabelFrame(self.root, text="Drive it from the APC mini (optional)")
        apc.pack(fill="x", **pad)
        self.midi_name = tk.StringVar()
        self.midi_combo = ttk.Combobox(apc, textvariable=self.midi_name, state="readonly", width=32)
        self.midi_combo.grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Button(apc, text="Refresh", command=self.refresh_midi).grid(row=0, column=2)
        ttk.Button(apc, text="Connect", command=self.connect_midi).grid(row=0, column=3)
        ttk.Label(apc, text="Follow:").grid(row=1, column=0, sticky="w")
        self.follow = tk.StringVar(value="(none)")
        choices = ["(none)"] + [apc_mini.describe_cc(cc) for cc in apc_mini.FADER_CCS]
        cb = ttk.Combobox(apc, textvariable=self.follow, values=choices, state="readonly", width=14)
        cb.grid(row=1, column=1, sticky="w")
        cb.bind("<<ComboboxSelected>>", lambda e: self.pickup.reset(self.value))
        self.pickup_label = ttk.Label(apc, text="")
        self.pickup_label.grid(row=1, column=2, columnspan=2, sticky="w")

        ctl = ttk.Frame(self.root)
        ctl.pack(fill="x", **pad)
        self.send_btn = ttk.Button(ctl, text="Send sACN: switch ON", command=self.toggle_send)
        self.send_btn.pack(side="left")
        self.count_label = ttk.Label(ctl, text="")
        self.count_label.pack(side="left", padx=12)

        ttk.Label(self.root, text=STEPS, justify="left", wraplength=520).pack(fill="x", **pad)
        self._update_status()

    # ------------------------------------------------------------------- MIDI
    def refresh_midi(self) -> None:
        if self.simulate:
            from .simulation import SIM_PORT
            names = [SIM_PORT]
        else:
            pl = ports.list_ports()
            names = pl.inputs
            if pl.error:
                log.error(pl.error)
        self.midi_combo.configure(values=names)
        if self.midi_name.get() not in names:
            self.midi_name.set((ports.find_apc_mini(names) if not self.simulate else names[0]) or "")

    def connect_midi(self) -> None:
        name = self.midi_name.get()
        if not name:
            return
        try:
            self.midi_in.open(name)
        except MidiInputError as exc:
            messagebox.showerror("MIDI input", str(exc))

    def _follow_cc(self) -> int | None:
        for cc in apc_mini.FADER_CCS:
            if apc_mini.describe_cc(cc) == self.follow.get():
                return cc
        return None

    # ------------------------------------------------------------------ level
    def _cap(self) -> int:
        try:
            return min(max(int(self.max_pct.get()), 0), 100)
        except (tk.TclError, ValueError):
            return 100

    def _slider_moved(self, _=None) -> None:
        if self._programmatic:
            return
        self._set_value(int(float(self.slider.get())), from_slider=True)

    def _set_value(self, value: int, from_slider: bool) -> None:
        cap = round(255 * self._cap() / 100)
        value = min(max(value, 0), cap)
        if not from_slider:
            self._programmatic = True
            try:
                self.slider.set(value)
            finally:
                self._programmatic = False
        if value != self.value:
            self.value = value
            self.dirty = True
        if from_slider:
            self.pickup.reset(self.value)  # moving the slider means the fader must pick up again
        self.value_label.configure(text=f"{self.value} ({round(self.value / 2.55)}%)")

    # ---------------------------------------------------------------- sending
    def toggle_send(self) -> None:
        if self.sender is None:
            self.start_sending()
        else:
            self.stop_sending()

    def start_sending(self) -> None:
        try:
            universe, channel = int(self.universe.get()), int(self.channel.get())
            if not 1 <= channel <= 512:
                raise SacnError("Channel must be 1-512")
            ip = self.ip.get().strip() if self.mode.get() == "unicast" else None
            self.sender = SacnSender(universe, unicast_ip=ip, source_name="APC Bridge test")
        except (SacnError, tk.TclError, ValueError) as exc:
            messagebox.showerror("sACN", str(exc))
            return
        self.dirty = True
        for child in self.net_frame.winfo_children():
            try:
                child.configure(state="disabled")
            except tk.TclError:
                pass
        log.info("sACN output ON: universe %s ch %s -> %s", self.sender.universe, channel, self.sender.dest[0])
        self._update_status()

    def stop_sending(self) -> None:
        if self.sender is not None:
            self.sender.stop(self._frame())
            log.info("sACN output OFF (stream-terminated sent)")
            self.sender = None
        for child in self.net_frame.winfo_children():
            try:
                child.configure(state="normal")
            except tk.TclError:
                pass
        self._update_status()

    def _frame(self) -> bytes:
        data = bytearray(512)
        data[int(self.channel.get()) - 1] = self.value
        return bytes(data)

    def _update_status(self) -> None:
        if self.sender is None:
            self.status.configure(text="sACN OUTPUT: OFF (nothing is being sent)", bg="#555555")
            self.send_btn.configure(text="Send sACN: switch ON")
        else:
            dest = self.sender.dest[0]
            kind = "multicast" if dest == multicast_address(self.sender.universe) else "unicast"
            self.status.configure(
                text=f"sACN OUTPUT: ON  universe {self.sender.universe}, channel {self.channel.get()} "
                     f"({kind} {dest})", bg="#b00000")
            self.send_btn.configure(text="Send sACN: switch OFF")

    # ------------------------------------------------------------------- loop
    def _tick(self) -> None:
        try:
            self._drain_midi()
            if self.sender is not None:
                now = time.monotonic()
                if (self.dirty and now - self.last_send >= MIN_GAP_S) or now - self.last_send >= KEEPALIVE_S:
                    self.sender.send(self._frame())
                    self.last_send = now
                    self.dirty = False
                    self.count_label.configure(text=f"{self.sender.packets_sent} packets sent")
        except SacnError as exc:
            log.error("%s", exc)
            self.sender = None
            self._update_status()
            messagebox.showerror("sACN", f"{exc}\n\nOutput has been switched OFF.")
        finally:
            self.root.after(POLL_MS, self._tick)

    def _drain_midi(self) -> None:
        cc = self._follow_cc()
        for _ in range(500):
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                break
            if cc is None or not ev.is_cc or ev.number != cc or ev.channel != 1:
                continue
            scaled = midi_to_dmx(ev.value, self._cap())
            taken = self.pickup.update(scaled)
            if taken is None:
                self.pickup_label.configure(
                    text=f"Waiting for pickup: move fader to {round(self.value / 2.55)}%",
                    foreground="#b36b00")
            else:
                self.pickup_label.configure(text="Fader picked up", foreground="green")
                self._set_value(taken, from_slider=False)
        if cc is None:
            self.pickup_label.configure(text="")

    def on_close(self) -> None:
        try:
            self.stop_sending()
            self.midi_in.close()
        finally:
            self.root.destroy()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sacn_test", description=__doc__)
    parser.add_argument("--simulate", action="store_true", help="use a fake APC mini")
    args = parser.parse_args(argv)
    log_dir = Path.cwd() / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(log_dir / "sacn_test.log", encoding="utf-8")])
    root = tk.Tk()
    SacnTestApp(root, simulate=args.simulate)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
