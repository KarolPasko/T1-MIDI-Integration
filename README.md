# T1-MIDI-Integration

A free, open-source Windows 11 app that lets an **original first-generation
AKAI APC mini** control playback levels in **Avolites Titan Go** running with a
**T1** interface, with feedback on the APC mini's LEDs.

## How it works

With a T1, Titan Go cannot take MIDI in directly (that needs a T2), and its
WebAPI is not available. Titan Go *does* accept **sACN** (a free network
lighting protocol) as a trigger input, and a **Set Level** trigger follows the
incoming value like a fader. This was verified with Titan Go v18.0 and a T1 on
28 Oct 2026. So:

```
APC mini fader --MIDI--> this app --sACN (one channel per fader)--> Titan Go trigger --> playback level
```

## The three programs

| Run | What it is for |
|---|---|
| `py -3.12 run_bridge.py` | **The bridge.** Faders control Titan Go playbacks, with LED feedback |
| `py -3.12 run_apc_bridge.py` | MIDI monitor and LED test. Read-only, sends no lighting data |
| `py -3.12 run_sacn_test.py` | Single-channel sACN test, used to prove the Titan trigger works |

Only one of them can use the APC mini at a time.

| Stage | What | Status |
|---|---|---|
| 1 | MIDI monitor and LED test | Done, verified on hardware |
| 2 | Fader mapping, pickup/soft takeover, saved settings, simulated output | Done |
| 3 | Find a legitimate way to control Titan Go with the T1 | Done: sACN triggers, verified |
| 4 | Connect mapping to Titan Go | **This release**: the bridge, needs a full test on your rig |
| 5 | Package as a standalone .exe | Not started |

## Using the bridge

### One-time setup in Titan Go

For each fader you want to use, in Titan Go go to **System → Triggers**, add
a mapping (or use the one from the test), and add a trigger:

* Type **Item**. Pick the playback and set the action to **Set Level**.
* Source **Streaming ACN (sACN)**, universe **10**, address = the fader's
  **sACN ch** from the bridge's table. By default fader 1 is channel 1,
  fader 2 is channel 2, and so on, with the master fader on channel 9.

Or turn **Learn On**, switch the bridge's output on, and move that one fader.

Titan saves triggers per show and per hardware, so this is done once per show.
Triggers cannot target Titan's masters, so the APC master fader is mapped to
a ninth playback by default.

### Every time

1. Plug in the APC mini, start Titan Go, then run `py -3.12 run_bridge.py`.
2. Click **Connect**. The top-right scene button blinks: output is **OFF**.
3. Click **Switch output ON** (the bar at the top turns red).
4. **Pickup:** each fader only takes control once you move it to its last
   level. The Status column says where ("Move fader to 0%"), and the track
   button under the fader blinks until then. That way nothing jumps when you
   switch on or change settings.
5. Click **Switch output OFF** when done. Titan keeps the last levels.

### On the APC mini

* **Grid columns:** a level meter for faders 1–8 (green, then yellow, red at the top).
* **Track buttons (under the grid):** press to switch that fader on/off.
  Lit = live, blinking = waiting for pickup or output off, dark = off.
* **Bottom scene button:** the same for the master fader.
* **Top scene button:** lit = output ON, blinking = output OFF.

The LEDs show **what this app is doing**. sACN only goes one way, so they
cannot show Titan's real playback state. If you move a playback in Titan
itself, the LEDs will not know.

### Settings

* The table sets each fader's label, sACN channel, on/off, and min/max %.
  **Max output %** caps every fader. Settings are locked while output is ON.
* **Save settings** writes `config.json` in the folder you run from.
  It is loaded automatically next time.
* **Simulate only** calculates everything but sends nothing to the network,
  for trying settings without touching the lights.
* If Titan does not react, try **Unicast to 127.0.0.1** instead of Multicast.
* If the APC mini is unplugged while output is on, output switches **OFF**.
  Reconnect and switch it on again (pickup applies).

## sACN trigger test

`run_sacn_test.py` sends a single sACN channel, to check a Titan trigger on its
own. Details are in [docs/TITAN_INTEGRATION.md](docs/TITAN_INTEGRATION.md).

```
py -3.12 run_sacn_test.py
```

* It starts with **output OFF**. Nothing is sent until you click "Send sACN: switch ON".
* It sends one channel on one universe (default universe 10, channel 1).
  Titan ignores it unless you create a matching trigger in System → Triggers.
* A slider sets the value. Optionally, one APC mini fader drives it with
  **pickup**: the fader does nothing until it reaches the current level, so
  nothing jumps. A max output % caps the level.
* Switching it off sends the standard sACN "stream terminated" message, so
  Titan releases the source straight away.

Close the main app before using an APC fader here, because only one program
can open the APC mini at a time.

## What is documented vs. verified

Everything below comes from Akai's protocol sheet for the original APC mini
and matching user reports. On **28 Oct 2026** it was confirmed on a real
first-generation APC mini (Windows 11, Python 3.12) using the Stage 1 monitor
and LED test: all buttons, all faders and all LED states behaved as listed.
The APC mini cannot report its LED state, so LED results are by eye.

| Fact | Value used | Status |
|---|---|---|
| MIDI channel | 1 | Verified on hardware |
| 8x8 grid pads | Notes 0-63, bottom-left = 0, top-left = 56 | Verified on hardware |
| Track buttons (under the grid) | Notes 64-71, red LED | Verified on hardware |
| Scene buttons (right side) | Notes 82-89, green LED, top = 82 | Verified on hardware |
| Shift | Note 98, no LED | Verified on hardware |
| Faders 1-8 / Master | CC 48-55 / CC 56 | Verified on hardware |
| Grid LED (Note On velocity) | 0 off, 1 green, 2 green blink, 3 red, 4 red blink, 5 yellow, 6 yellow blink | Verified on hardware |
| Round button LED (velocity) | 0 off, 1 on, 2 blink | Verified on hardware |
| RGB colours / brightness levels | **Not supported** on the original APC mini | The app does not offer them |

The **APC mini mk2** (2022, RGB pads) uses a different protocol. The app
warns you if it sees one, and its LED messages will not be correct for it.

All of these numbers live in one file, `apc_bridge/apc_mini.py`, so if your
hardware disagrees they only need fixing in one place.

---

## Installation (Windows 11, step by step)

You only do this once.

### 1. Install Python

1. Go to <https://www.python.org/downloads/windows/>, scroll down to the latest
   **Python 3.12.x** release, and download its "Windows installer (64-bit)".

   **It must be 3.12, not 3.13 or 3.14.** The MIDI library `python-rtmidi`
   (version 1.5.8, the newest) only ships ready-made Windows downloads for
   Python 3.8 to 3.12. On newer Python, pip tries to compile it from source
   and fails with "Unknown compiler(s)". It is fine to have 3.12 installed
   alongside a newer Python; all commands below use `py -3.12` to pick it.
2. Run the installer. On the first screen **tick "Add python.exe to PATH"**,
   then click **Install Now**. Leave the "tcl/tk and IDLE" option ticked (it is
   by default); the app's window needs it.
3. Open **Command Prompt** (press the Windows key, type `cmd`, press Enter) and
   check it worked:

   ```
   py -3.12 --version
   ```

   You should see something like `Python 3.12.x`. (`py --list` shows every
   Python you have installed.)

### 2. Get the code

Either:

* On the GitHub page click **Code → Download ZIP**, then unzip it somewhere easy,
  e.g. `C:\APC-Bridge`; or
* if you have Git: `git clone https://github.com/KarolPasko/T1-MIDI-Integration.git`

### 3. Install the two MIDI libraries

In Command Prompt, go into the folder (change the path to wherever you put it):

```
cd C:\APC-Bridge
py -3.12 -m pip install -r requirements.txt
```

This installs `mido` and `python-rtmidi` (both free and open source).

### 4. Run it

Plug in the APC mini first, then:

```
py -3.12 run_apc_bridge.py
```

To look around **without the controller plugged in**, run the simulator. It
invents fader moves and button presses and is clearly labelled SIMULATION:

```
py -3.12 run_apc_bridge.py --simulate
```

A log file is written to `logs\apc_bridge.log` in the folder you ran it from.

---

## Verifying the protocol (please do this and report back)

Close Titan Go (and anything else that might use the APC mini, like Ableton)
before you start. On Windows only one program can use a MIDI device at a time.

**A. Input check**

1. Start the app. The APC mini should already be picked in both drop-downs.
   Click **Connect**. "MIDI input: CONNECTED" should turn green.
2. Move each fader from bottom to top. In section 3, each bar should follow,
   going 0 to 127. Note whether any fader shows up under "Other controllers seen"
   instead (that would mean its CC number differs from the documentation).
3. Press a few pads, a track button, a scene button and Shift. Each should show
   a **Note On** then a **Note Off** in the monitor, with the "Documented
   control" column naming the button you actually pressed. Check one corner pad
   in particular: the top-left pad should say "Pad row 1 col 1" (note 56).

**B. LED test, Step 1 (one button)**

1. Press the top-left pad on the APC mini (or click it in the picture). It
   becomes the selected button.
2. Choose **Green** and click **Light selected button**.
3. Look at the controller. If that one pad is green, click **Yes, it lit**. If
   nothing happened, click **No, nothing happened** and see Troubleshooting.
4. Optional: try Red, Yellow and a Blink state, and a round track/scene button.

**C. LED test, Step 2 (whole controller)**

After you click Yes, **Run full LED test** unlocks. It shows all grid pads green,
then red, then yellow, then blinking green, then the round buttons on and
blinking. It takes about 7 seconds, then puts the LEDs back the way they were.
**Stop test** stops it early and **All LEDs off** clears everything.

**What to send back:** whether the faders matched CC 48-56, whether the button
names matched, and which LED colours/blinks appeared correctly. A screenshot of
the window and the `logs\apc_bridge.log` file are ideal.

---

## Troubleshooting

**`'py' is not recognized`** – Python is not installed or not on PATH. Re-run
the Python installer, choose *Modify*, and make sure "Add Python to environment
variables" / "py launcher" is ticked. Then close and reopen Command Prompt.

**`pip install` fails while building `python-rtmidi`** (errors such as
"Unknown compiler(s)", "Failed to activate VS environment" or "Microsoft
Visual C++ 14.0 is required") – your Python is too new for python-rtmidi's
ready-made download (it covers Python 3.8-3.12 on Windows). You do not need a
compiler: install Python 3.12 as in step 1, then run
`py -3.12 -m pip install -r requirements.txt` and start the app with
`py -3.12 run_apc_bridge.py`. Because pip stops at the first failure, `mido`
will also be missing until this succeeds.

**`ModuleNotFoundError: No module named 'mido'`** – step 3 was skipped or ran
for a different Python. Run `py -3.12 -m pip install -r requirements.txt` again,
and start the app with `py -3.12`, not plain `py`.

**`No module named 'tkinter'`** – reinstall Python from python.org (not the
Microsoft Store version) and keep "tcl/tk and IDLE" ticked.

**"No APC mini input found"** – check the USB cable (use a data cable, not a
charge-only one), plug it straight into the PC rather than a hub, wait about 5
seconds, then click **Refresh devices**. In Windows *Device Manager* it should
appear under "Sound, video and game controllers" as APC MINI.

**"Could not open MIDI input/output … already using it"** – another program
has the APC mini open. Close Titan Go, Ableton, other DAWs, MIDI-OX, Bome, etc.
and click Connect again.

**Input works but the LEDs do not light** – check that the *MIDI output*
drop-down really is the APC mini (not "Microsoft GS Wavetable Synth"). Click
Disconnect, then Connect. If the button still stays dark, the log line
starting "Sent LED:" shows exactly what was sent; please include it when you
report back. A mk2 controller will not respond correctly to these messages.

**The device disappears while running** – the app notices within about 1.5 s,
closes the ports and says so in the log. It does **not** reconnect by itself;
plug it back in, click **Refresh devices**, then **Connect**.

**A fader shows "--"** – it has not sent anything yet. Move it.

---

## Safety design

* The monitor app has **no lighting output**. Only the bridge and the sACN
  test tool send data Titan can act on. Both start with output **OFF**, and
  Titan does nothing with it unless a matching trigger exists.
* The bridge uses pickup, a max output cap, and switches output off if the
  APC mini disappears. It never claims to know Titan's actual state.
* MIDI input and LED output are separate modules (`midi_input.py`,
  `led_output.py`). Button presses never automatically send LED messages, so
  there are no feedback loops; LEDs only change when you click a test button.
* The LED module can only send Note On messages for the documented LED notes
  and velocities. Anything else is rejected before it reaches the port.
* Repeated identical LED messages are skipped to avoid flooding the controller.
* No automatic reconnection: after an unplug you reconnect explicitly.

## For developers

```
py -3.12 -m pip install -r requirements-dev.txt
py -3.12 -m pytest
```

Code layout:

| File | Purpose |
|---|---|
| `apc_bridge/apc_mini.py` | All APC mini protocol facts and LED message building |
| `apc_bridge/ports.py` | Listing ports, finding the APC mini |
| `apc_bridge/midi_input.py` | MIDI input only, queues events for the GUI |
| `apc_bridge/led_output.py` | LED output only, validated messages, state + restore |
| `apc_bridge/midi_events.py` | Decoding messages for display |
| `apc_bridge/simulation.py` | Fake APC mini for `--simulate` |
| `apc_bridge/gui.py` | tkinter window |
| `apc_bridge/sacn.py` | sACN (E1.31) packet builder and sender |
| `apc_bridge/pickup.py` | MIDI to DMX scaling and fader pickup |
| `apc_bridge/sacn_test.py` | sACN trigger test window |
| `apc_bridge/config.py` | Bridge settings, JSON save/load |
| `apc_bridge/bridge.py` | Mapping engine (pure logic, unit tested) |
| `apc_bridge/bridge_gui.py` | Bridge window |

What is needed to start Stages 2 and 3 is in [docs/NEXT_STEPS.md](docs/NEXT_STEPS.md).
The Titan Go investigation (Stage 3) is in [docs/TITAN_INTEGRATION.md](docs/TITAN_INTEGRATION.md).
