"""Stage 1 desktop window: device connection, MIDI monitor, fader values,
isolated LED test, and a safety panel showing lighting output is disabled.

Threading: MIDI input arrives on python-rtmidi's thread and is put on a
queue.Queue. Everything that touches tkinter, including all LED output, runs
on the GUI thread, which drains that queue every few milliseconds.
"""

from __future__ import annotations

import logging
import queue
import time
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import apc_mini, ports
from .led_output import LedOutput, LedOutputError
from .midi_events import MidiEvent
from .midi_input import MidiInputError, MidiInputListener

log = logging.getLogger(__name__)

POLL_MS = 25            # how often the GUI drains incoming MIDI
WATCHDOG_MS = 1500      # how often we check the device is still plugged in
MAX_MONITOR_ROWS = 300
MAX_EVENTS_PER_POLL = 500

PAD = 30
GAP = 5

COLOURS = {"off": "#3a3a3a", "green": "#2ecc40", "red": "#ff4136", "yellow": "#ffdc00"}

# Full LED test: (description, state for grid pads, state for round buttons, ms)
FULL_TEST_STEPS = [
    ("all grid pads GREEN", apc_mini.GridLed.GREEN, 0, 800),
    ("all grid pads RED", apc_mini.GridLed.RED, 0, 800),
    ("all grid pads YELLOW", apc_mini.GridLed.YELLOW, 0, 800),
    ("all grid pads GREEN BLINK", apc_mini.GridLed.GREEN_BLINK, 0, 1600),
    ("track (red) + scene (green) buttons ON", 0, apc_mini.RoundLed.ON, 1000),
    ("track + scene buttons BLINK", 0, apc_mini.RoundLed.BLINK, 1600),
]

LED_STATUS_TEXT = {
    "closed": ("LED output: not open", "grey"),
    "open": ("LED output: port open, NOT confirmed (do LED test Step 1)", "#b36b00"),
    "confirmed": ("LED output: WORKING (you confirmed a pad lit)", "green"),
    "failed": ("LED output: port open but you saw NO light", "red"),
    "error": ("LED output: ERROR - see log", "red"),
}


class QueueLogHandler(logging.Handler):
    """Logging handler that is safe to call from any thread."""

    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q

    def emit(self, record):
        try:
            self.q.put_nowait(self.format(record))
        except Exception:
            pass


class App:
    def __init__(self, root: tk.Tk, simulate: bool = False):
        self.root = root
        self.simulate = simulate
        self.events: queue.Queue[MidiEvent] = queue.Queue()
        self.log_lines: queue.Queue[str] = queue.Queue()

        if simulate:
            from . import simulation
            self.midi_in = MidiInputListener(self.events, opener=simulation.open_input)
            self.leds = LedOutput(opener=simulation.open_output)
        else:
            self.midi_in = MidiInputListener(self.events)
            self.leds = LedOutput()

        self.led_status = "closed"
        self.selected_note = 56  # top-left pad
        self.pressed: set[int] = set()
        self.fader_values: dict[int, int] = {}
        self.other_ccs: dict[tuple[int, int], int] = {}
        self.test_job = None
        self.test_snapshot: dict[int, int] | None = None

        handler = QueueLogHandler(self.log_lines)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
        logging.getLogger().addHandler(handler)

        title = "APC mini Monitor & LED Test - Stage 1 (read-only)"
        if simulate:
            title += "  [SIMULATION - no hardware]"
        root.title(title)
        root.minsize(1100, 760)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build()
        self.refresh_ports()
        self.root.after(POLL_MS, self._poll)
        self.root.after(WATCHDOG_MS, self._watchdog)

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        r = self.root
        r.columnconfigure(0, weight=3)
        r.columnconfigure(1, weight=2)
        r.rowconfigure(1, weight=1)
        r.rowconfigure(3, weight=1)

        self._build_connection(r).grid(row=0, column=0, columnspan=2, sticky="nsew", padx=6, pady=4)
        self._build_monitor(r).grid(row=1, column=0, sticky="nsew", padx=6, pady=4)
        self._build_faders(r).grid(row=1, column=1, sticky="nsew", padx=6, pady=4)
        self._build_led_test(r).grid(row=2, column=0, sticky="nsew", padx=6, pady=4)
        self._build_safety(r).grid(row=2, column=1, sticky="nsew", padx=6, pady=4)
        self._build_log(r).grid(row=3, column=0, columnspan=2, sticky="nsew", padx=6, pady=4)
        self._update_status_labels()

    def _build_connection(self, parent) -> ttk.LabelFrame:
        f = ttk.LabelFrame(parent, text="1. Device connection")
        ttk.Label(f, text="MIDI input (buttons/faders):").grid(row=0, column=0, sticky="w")
        self.in_var = tk.StringVar()
        self.in_combo = ttk.Combobox(f, textvariable=self.in_var, state="readonly", width=38)
        self.in_combo.grid(row=0, column=1, padx=4)
        ttk.Label(f, text="MIDI output (LEDs):").grid(row=1, column=0, sticky="w")
        self.out_var = tk.StringVar()
        self.out_combo = ttk.Combobox(f, textvariable=self.out_var, state="readonly", width=38)
        self.out_combo.grid(row=1, column=1, padx=4)

        ttk.Button(f, text="Refresh devices", command=self.refresh_ports).grid(row=0, column=2, padx=4)
        ttk.Button(f, text="Connect", command=self.connect).grid(row=0, column=3, padx=4)
        ttk.Button(f, text="Disconnect", command=self.disconnect).grid(row=1, column=3, padx=4)
        self.off_on_disconnect = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Turn off LEDs this app lit when disconnecting",
                        variable=self.off_on_disconnect).grid(row=1, column=2, padx=4)

        self.in_status = ttk.Label(f, text="", font=("Segoe UI", 10, "bold"))
        self.in_status.grid(row=0, column=4, sticky="w", padx=12)
        self.out_status = ttk.Label(f, text="", font=("Segoe UI", 10, "bold"))
        self.out_status.grid(row=1, column=4, sticky="w", padx=12)
        self.conn_note = ttk.Label(f, text="", foreground="#b36b00", wraplength=1000)
        self.conn_note.grid(row=2, column=0, columnspan=5, sticky="w")
        return f

    def _build_monitor(self, parent) -> ttk.LabelFrame:
        f = ttk.LabelFrame(parent, text="2. MIDI input monitor (live)")
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)
        bar = ttk.Frame(f)
        bar.grid(row=0, column=0, sticky="w")
        self.paused = tk.BooleanVar(value=False)
        self.hide_faders = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Pause list", variable=self.paused).pack(side="left")
        ttk.Checkbutton(bar, text="Hide fader messages", variable=self.hide_faders).pack(side="left", padx=8)
        ttk.Button(bar, text="Clear", command=self.clear_monitor).pack(side="left")
        self.event_count = ttk.Label(bar, text="0 messages")
        self.event_count.pack(side="left", padx=12)
        self.total_events = 0

        cols = ("time", "type", "ch", "num", "value", "control", "raw")
        widths = (100, 110, 40, 60, 60, 170, 90)
        heads = ("Time", "Type", "Ch", "Number", "Value", "Documented control", "Raw bytes")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", height=12)
        for c, w, h in zip(cols, widths, heads):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, stretch=(c == "control"))
        sb = ttk.Scrollbar(f, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        sb.grid(row=1, column=1, sticky="ns")
        return f

    def _build_faders(self, parent) -> ttk.LabelFrame:
        f = ttk.LabelFrame(parent, text="3. Fader values (latest received)")
        self.fader_bars: dict[int, ttk.Progressbar] = {}
        self.fader_labels: dict[int, ttk.Label] = {}
        for i, cc in enumerate(apc_mini.FADER_CCS):
            ttk.Label(f, text=apc_mini.describe_cc(cc).replace(" fader", "").replace("Fader ", "F")
                      ).grid(row=0, column=i, padx=3)
            bar = ttk.Progressbar(f, orient="vertical", length=140, maximum=127)
            bar.grid(row=1, column=i, padx=3)
            lab = ttk.Label(f, text="--", width=4, anchor="center")
            lab.grid(row=2, column=i)
            ttk.Label(f, text=f"CC{cc}", foreground="grey").grid(row=3, column=i)
            self.fader_bars[cc] = bar
            self.fader_labels[cc] = lab
        self.fader_note = ttk.Label(
            f, wraplength=380, foreground="grey",
            text="CC numbers are from Akai's documentation. '--' means that fader has not "
                 "sent anything yet: move each fader once to verify the numbering.")
        self.fader_note.grid(row=4, column=0, columnspan=9, sticky="w", pady=4)
        self.other_cc_label = ttk.Label(f, text="", wraplength=380, foreground="#b36b00")
        self.other_cc_label.grid(row=5, column=0, columnspan=9, sticky="w")
        return f

    def _build_led_test(self, parent) -> ttk.LabelFrame:
        f = ttk.LabelFrame(parent, text="4. LED test (isolated: talks ONLY to the APC mini LEDs)")
        w = 9 * (PAD + GAP) + 20
        h = 9 * (PAD + GAP) + 10
        self.canvas = tk.Canvas(f, width=w, height=h, bg="#1e1e1e", highlightthickness=0)
        self.canvas.grid(row=0, column=0, rowspan=8, padx=6, pady=4)
        self.canvas.bind("<Button-1>", self._canvas_click)
        self._pad_items: dict[int, int] = {}
        self._draw_layout()
        ttk.Label(f, text="Colours show what this app SENT.\nWhite outline = button held now.",
                  foreground="grey", justify="left").grid(row=8, column=0, sticky="w", padx=6)

        c = ttk.Frame(f)
        c.grid(row=0, column=1, sticky="nw", padx=6)
        self.sel_label = ttk.Label(c, text="", font=("Segoe UI", 10, "bold"))
        self.sel_label.grid(row=0, column=0, columnspan=3, sticky="w")
        self.follow_press = tk.BooleanVar(value=True)
        ttk.Checkbutton(c, text="Select the last button I press on the APC mini (or click the picture)",
                        variable=self.follow_press).grid(row=1, column=0, columnspan=3, sticky="w")
        ttk.Label(c, text="LED state:").grid(row=2, column=0, sticky="w")
        self.state_var = tk.StringVar()
        self.state_combo = ttk.Combobox(c, textvariable=self.state_var, state="readonly", width=16)
        self.state_combo.grid(row=2, column=1, sticky="w")

        ttk.Label(c, text="Step 1 - one button only:", font=("Segoe UI", 9, "bold")).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Button(c, text="Light selected button", command=self.light_selected).grid(row=4, column=0, sticky="w")
        ttk.Button(c, text="Turn selected off", command=self.selected_off).grid(row=4, column=1, sticky="w")
        ttk.Label(c, text="Did that button light as expected?").grid(row=5, column=0, columnspan=2, sticky="w")
        ttk.Button(c, text="Yes, it lit", command=lambda: self.confirm_led(True)).grid(row=6, column=0, sticky="w")
        ttk.Button(c, text="No, nothing happened", command=lambda: self.confirm_led(False)).grid(row=6, column=1, sticky="w")

        ttk.Label(c, text="Step 2 - whole controller:", font=("Segoe UI", 9, "bold")).grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.full_btn = ttk.Button(c, text="Run full LED test", command=self.start_full_test, state="disabled")
        self.full_btn.grid(row=8, column=0, sticky="w")
        ttk.Button(c, text="Stop test", command=self.stop_full_test).grid(row=8, column=1, sticky="w")
        self.test_label = ttk.Label(c, text="(Step 2 unlocks after you confirm Step 1)", foreground="grey")
        self.test_label.grid(row=9, column=0, columnspan=3, sticky="w")

        ttk.Button(c, text="All LEDs off", command=self.all_off).grid(row=10, column=0, sticky="w", pady=(8, 0))
        ttk.Button(c, text="Restore LEDs to before test", command=self.restore_snapshot).grid(
            row=10, column=1, sticky="w", pady=(8, 0))
        self.select_note(self.selected_note)
        return f

    def _build_safety(self, parent) -> ttk.LabelFrame:
        f = ttk.LabelFrame(parent, text="5. Safety & Titan Go status")
        tk.Label(f, text="LIGHTING OUTPUT: DISABLED", bg="#7a0000", fg="white",
                 font=("Segoe UI", 12, "bold"), padx=8, pady=6).pack(fill="x", padx=6, pady=6)
        ttk.Label(f, wraplength=380, justify="left", text=(
            "Stage 1 is a read-only monitor. This build contains no Titan Go adapter "
            "and no code that can send a lighting command, so nothing you do here "
            "can change your lights.\n\n"
            "Titan Go integration: not connected - to be investigated in Stage 3.\n\n"
            "The LED test sends Note On messages to the APC mini's own port only. "
            "Close Titan Go (or make sure it is not using the APC mini) while testing, "
            "because on Windows only one program can open a MIDI port at a time."
        )).pack(fill="x", padx=6)
        if self.simulate:
            tk.Label(f, text="SIMULATION MODE: no real MIDI device is used", bg="#00457a",
                     fg="white", font=("Segoe UI", 10, "bold"), pady=4).pack(fill="x", padx=6, pady=6)
        return f

    def _build_log(self, parent) -> ttk.LabelFrame:
        f = ttk.LabelFrame(parent, text="6. Log")
        self.log_text = ScrolledText(f, height=5, state="disabled", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)
        return f

    # ------------------------------------------------------------- LED canvas
    def _note_xy(self, note: int) -> tuple[int, int]:
        step = PAD + GAP
        kind = apc_mini.control_kind(note)
        if kind == "grid":
            row, col = apc_mini.grid_position(note)
            return 4 + col * step, 4 + (7 - row) * step
        if kind == "track":
            return 4 + (note - 64) * step, 8 + 8 * step
        if kind == "scene":
            return 12 + 8 * step, 4 + (note - 82) * step
        return 12 + 8 * step, 8 + 8 * step  # shift

    def _draw_layout(self) -> None:
        for note in apc_mini.LED_NOTES + (apc_mini.SHIFT_NOTE,):
            x, y = self._note_xy(note)
            if apc_mini.control_kind(note) == "grid" or note == apc_mini.SHIFT_NOTE:
                item = self.canvas.create_rectangle(x, y, x + PAD, y + PAD, fill=COLOURS["off"],
                                                    outline="#555", width=1)
            else:
                item = self.canvas.create_oval(x + 6, y + 6, x + PAD - 6, y + PAD - 6,
                                               fill=COLOURS["off"], outline="#555", width=1)
            self._pad_items[note] = item

    def _led_colour(self, note: int, state: int) -> tuple[str, str]:
        """(fill colour, stipple) used to draw a sent LED state."""
        if state == 0:
            return COLOURS["off"], ""
        kind = apc_mini.control_kind(note)
        if kind == "grid":
            name = apc_mini.GridLed(state).name
            colour = COLOURS[name.split("_")[0].lower()]
            return colour, "gray50" if "BLINK" in name else ""
        colour = COLOURS["red"] if kind == "track" else COLOURS["green"]
        return colour, "gray50" if state == apc_mini.RoundLed.BLINK else ""

    def _redraw_pads(self) -> None:
        sent = self.leds.sent_state
        for note, item in self._pad_items.items():
            fill, stipple = (self._led_colour(note, sent.get(note, 0))
                             if note != apc_mini.SHIFT_NOTE else (COLOURS["off"], ""))
            if note in self.pressed:
                outline, width = "white", 3
            elif note == self.selected_note:
                outline, width = "#00bfff", 2
            else:
                outline, width = "#555", 1
            self.canvas.itemconfigure(item, fill=fill, stipple=stipple, outline=outline, width=width)

    def _canvas_click(self, event) -> None:
        for note, item in self._pad_items.items():
            x1, y1, x2, y2 = self.canvas.coords(item)
            if x1 <= event.x <= x2 and y1 <= event.y <= y2 and apc_mini.control_kind(note):
                self.select_note(note)
                return

    def select_note(self, note: int) -> None:
        self.selected_note = note
        states = apc_mini.allowed_states(note)
        labels = [apc_mini.state_label(note, s) for s in states]
        current = self.state_var.get()
        self.state_combo.configure(values=labels)
        self.state_var.set(current if current in labels else labels[1])
        self.sel_label.configure(text=f"Selected: {apc_mini.describe_note(note)} (note {note})")
        self._redraw_pads()

    # ------------------------------------------------------------ connection
    def refresh_ports(self) -> None:
        pl = ports.list_ports()
        if self.simulate:
            from .simulation import SIM_PORT
            pl = ports.PortList([SIM_PORT], [SIM_PORT])
        self.in_combo.configure(values=pl.inputs)
        self.out_combo.configure(values=pl.outputs)
        notes = []
        if pl.error:
            notes.append(pl.error)
            log.error(pl.error)
        apc_in = ports.find_apc_mini(pl.inputs) if not self.simulate else pl.inputs[0]
        apc_out = ports.find_apc_mini(pl.outputs) if not self.simulate else pl.outputs[0]
        if self.in_var.get() not in pl.inputs:
            self.in_var.set(apc_in or (pl.inputs[0] if pl.inputs else ""))
        if self.out_var.get() not in pl.outputs:
            self.out_var.set(apc_out or "")
        if not pl.error and not apc_in:
            notes.append("No APC mini input found. Check the USB cable, wait 5 seconds, then press "
                         "'Refresh devices'. You can still pick another input to monitor.")
        for name in (apc_in, apc_out):
            if name and apc_mini.is_mk2_name(name):
                notes.append(f"'{name}' looks like an APC mini mk2. This app's LED messages are for "
                             "the ORIGINAL APC mini and will not be correct on an mk2.")
                break
        self.conn_note.configure(text="  ".join(notes))
        log.info("Devices refreshed. Inputs: %s | Outputs: %s", pl.inputs or "none", pl.outputs or "none")

    def connect(self) -> None:
        in_name, out_name = self.in_var.get(), self.out_var.get()
        if not in_name and not out_name:
            messagebox.showinfo("Connect", "Pick a MIDI input and/or output first.")
            return
        if in_name:
            try:
                self.midi_in.open(in_name)
            except MidiInputError as exc:
                log.error("%s", exc)
                messagebox.showerror("MIDI input", str(exc))
        if out_name:
            try:
                self.leds.open(out_name)
                self.led_status = "open"
            except LedOutputError as exc:
                self.led_status = "error"
                log.error("%s", exc)
                messagebox.showerror("LED output", str(exc))
        self._update_status_labels()
        self._redraw_pads()

    def disconnect(self, reason: str = "") -> None:
        self.stop_full_test(restore=False)
        if self.leds.is_open and self.off_on_disconnect.get():
            try:
                n = self.leds.restore({})
                log.info("Turned off %d LED(s) before disconnecting", n)
            except LedOutputError as exc:
                log.warning("Could not turn LEDs off: %s", exc)
        self.midi_in.close()
        self.leds.close()
        self.led_status = "closed"
        self.pressed.clear()
        if reason:
            log.warning(reason)
        self._update_status_labels()
        self._redraw_pads()

    def _update_status_labels(self) -> None:
        if self.midi_in.is_open:
            self.in_status.configure(text="MIDI input: CONNECTED", foreground="green")
        else:
            self.in_status.configure(text="MIDI input: disconnected", foreground="grey")
        if not self.leds.is_open and self.led_status not in ("error",):
            self.led_status = "closed"
        text, colour = LED_STATUS_TEXT[self.led_status]
        self.out_status.configure(text=text, foreground=colour)
        unlocked = self.led_status == "confirmed" and self.leds.is_open
        self.full_btn.configure(state="normal" if unlocked else "disabled")

    def _watchdog(self) -> None:
        """Notice an unplugged controller and close its ports cleanly."""
        try:
            if (self.midi_in.is_open or self.leds.is_open) and not self.simulate:
                pl = ports.list_ports()
                if not pl.error:
                    if self.midi_in.is_open and not ports.still_present(self.midi_in.port_name, pl.inputs):
                        self.midi_in.close()
                        log.warning("MIDI input disappeared (unplugged?). Plug it back in and "
                                    "press Refresh devices, then Connect.")
                    if self.leds.is_open and not ports.still_present(self.leds.port_name, pl.outputs):
                        self.stop_full_test(restore=False)
                        self.leds.close()
                        self.led_status = "error"
                        log.warning("LED output disappeared (unplugged?).")
                    self._update_status_labels()
        finally:
            self.root.after(WATCHDOG_MS, self._watchdog)

    # ---------------------------------------------------------------- monitor
    def clear_monitor(self) -> None:
        self.tree.delete(*self.tree.get_children())

    def _poll(self) -> None:
        try:
            self._drain_events()
            self._drain_log()
        except Exception:
            log.exception("Unexpected error while updating the window")
        finally:
            self.root.after(POLL_MS, self._poll)

    def _drain_events(self) -> None:
        changed_pads = faders_changed = others_changed = False
        rows = []
        for _ in range(MAX_EVENTS_PER_POLL):
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                break
            self.total_events += 1
            if ev.is_cc:
                if ev.number in apc_mini.FADER_CCS and ev.channel == 1:
                    self.fader_values[ev.number] = ev.value
                    faders_changed = True
                else:
                    self.other_ccs[(ev.channel, ev.number)] = ev.value
                    others_changed = True
            elif ev.is_press:
                self.pressed.add(ev.number)
                changed_pads = True
                if self.follow_press.get() and apc_mini.control_kind(ev.number):
                    self.select_note(ev.number)
            elif ev.is_release:
                self.pressed.discard(ev.number)
                changed_pads = True
            if not self.paused.get() and not (self.hide_faders.get() and ev.is_cc):
                rows.append(ev)

        if not (rows or changed_pads or faders_changed or others_changed):
            return
        for ev in rows:
            t = time.strftime("%H:%M:%S", time.localtime(ev.timestamp)) + f".{int(ev.timestamp * 1000) % 1000:03d}"
            self.tree.insert("", 0, values=(t, ev.kind, ev.channel or "", ev.number if ev.number is not None else "",
                                            ev.value if ev.value is not None else "", ev.description, ev.raw))
        children = self.tree.get_children()
        if len(children) > MAX_MONITOR_ROWS:
            self.tree.delete(*children[MAX_MONITOR_ROWS:])
        self.event_count.configure(text=f"{self.total_events} messages")
        if faders_changed:
            for cc, value in self.fader_values.items():
                self.fader_bars[cc].configure(value=value)
                self.fader_labels[cc].configure(text=str(value))
        if others_changed:
            seen = ", ".join(f"ch{ch} CC{cc}={v}" for (ch, cc), v in sorted(self.other_ccs.items()))
            self.other_cc_label.configure(text=f"Other controllers seen (not in Akai's documented list): {seen}")
        if changed_pads:
            self._redraw_pads()

    def _drain_log(self) -> None:
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

    # --------------------------------------------------------------- LED test
    def _led_action(self, fn, *args) -> bool:
        """Run an LED operation, turning failures into status + log messages."""
        if not self.leds.is_open:
            messagebox.showinfo("LED test", "Connect a MIDI output (the APC mini) first.")
            return False
        try:
            fn(*args)
            return True
        except LedOutputError as exc:
            self.stop_full_test(restore=False)
            self.led_status = "error"
            log.error("%s", exc)
            return False
        except ValueError as exc:  # LedMessageError
            messagebox.showerror("LED test", str(exc))
            return False
        finally:
            self._update_status_labels()
            self._redraw_pads()

    def _selected_state(self) -> int:
        states = apc_mini.allowed_states(self.selected_note)
        labels = [apc_mini.state_label(self.selected_note, s) for s in states]
        return int(states[labels.index(self.state_var.get())])

    def light_selected(self) -> None:
        note, state = self.selected_note, self._selected_state()
        if self._led_action(self.leds.set_led, note, state, True):
            log.info("Sent LED: %s (note %d) -> %s. Look at the controller and answer Yes/No.",
                     apc_mini.describe_note(note), note, apc_mini.state_label(note, state))

    def selected_off(self) -> None:
        self._led_action(self.leds.set_led, self.selected_note, 0, True)

    def confirm_led(self, worked: bool) -> None:
        if not self.leds.is_open:
            messagebox.showinfo("LED test", "Connect the APC mini output and run Step 1 first.")
            return
        if self.leds.messages_sent == 0:
            messagebox.showinfo("LED test", "Press 'Light selected button' first.")
            return
        self.led_status = "confirmed" if worked else "failed"
        if worked:
            log.info("User confirmed LED output works. Step 2 unlocked.")
            self.test_label.configure(text="Ready for Step 2.", foreground="green")
        else:
            log.warning("User saw no LED. See README 'LEDs do not light' troubleshooting.")
        self._update_status_labels()

    def start_full_test(self) -> None:
        if self.test_job is not None or not self.leds.is_open:
            return
        self.test_snapshot = self.leds.sent_state
        log.info("Full LED test started (current LEDs will be restored afterwards)")
        self._run_test_step(0)

    def _run_test_step(self, i: int) -> None:
        self.test_job = None
        if i >= len(FULL_TEST_STEPS):
            self.restore_snapshot()
            self.test_label.configure(
                text="Test finished, LEDs restored. Did every pad show each colour?",
                foreground="green")
            log.info("Full LED test finished")
            return
        desc, grid_state, round_state, ms = FULL_TEST_STEPS[i]

        def apply():
            for note in apc_mini.GRID_NOTES:
                self.leds.set_led(note, grid_state)
            for note in apc_mini.TRACK_BUTTON_NOTES + apc_mini.SCENE_BUTTON_NOTES:
                self.leds.set_led(note, round_state)

        if not self._led_action(apply):
            return
        self.test_label.configure(text=f"Step {i + 1}/{len(FULL_TEST_STEPS)}: {desc}", foreground="black")
        self.test_job = self.root.after(ms, self._run_test_step, i + 1)

    def stop_full_test(self, restore: bool = True) -> None:
        if self.test_job is not None:
            self.root.after_cancel(self.test_job)
            self.test_job = None
            self.test_label.configure(text="Test stopped.", foreground="grey")
            log.info("Full LED test stopped")
            if restore and self.leds.is_open:
                self.restore_snapshot()

    def restore_snapshot(self) -> None:
        if self.test_snapshot is None:
            log.info("No pre-test LED state saved yet; nothing to restore")
            return
        if self._led_action(self.leds.restore, self.test_snapshot):
            log.info("LEDs restored to their pre-test state")

    def all_off(self) -> None:
        self.stop_full_test(restore=False)
        if self._led_action(self.leds.all_off):
            log.info("All LEDs off")

    # -------------------------------------------------------------- shutdown
    def on_close(self) -> None:
        try:
            self.disconnect()
        finally:
            self.root.destroy()
