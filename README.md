# T1-MIDI-Integration

A free, open-source Windows 11 (and macOS) app that lets an **original first-generation
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

Since version 1.3.0 a button or fader can also send a **Titan WebAPI**
command (Go, Go to cue, Flash, Release, palettes, masters and more). This only
works on a Titan that answers the WebAPI: Avolites documents the WebAPI as not
available on Titan One or T1, and the app never tries to get around that. Use
**Output settings → Check connection** to see what your Titan replies. See
[Titan WebAPI actions](#titan-webapi-actions).

## Getting the app

**Easiest: download the ready-made .exe.** Every change to `main` is built
automatically on GitHub's Windows machines:

1. Open the repository on GitHub and click **Actions**, then **Windows build**.
2. Click the newest run with a green tick, scroll down to **Artifacts**, and
   download **APC-Titan-Bridge**. It is a .zip with `APC-Titan-Bridge.exe` inside.
3. Put the .exe in its own folder, e.g. `C:\APC-Bridge`. Your saved
   mappings (in a `mappings` folder) and `logs` are kept next to it.

Windows SmartScreen may warn that the app is from an "unknown publisher",
because it is not code-signed (signing costs money). Click **More info →
Run anyway**. You only need Python if you want to run from source or
build the .exe yourself (see "Installation" and "Building the .exe" below).

## On a Mac

Titan Go only runs on Windows, so on a Mac the bridge does **not** talk to
Titan on the same computer. The setup is:

```
APC mini --USB--> Mac (this app) --sACN over the network--> Windows PC running Titan Go + T1
```

The Mac and the Titan PC must be on the same network (a network cable
between them, or the same router/switch). **Not verified yet:** this route
(Mac to a separate Titan PC) has not been tested on a real rig. Only the
same-laptop Windows setup has been.

**Installing:**

1. On GitHub click **Actions → Mac build**, open the newest run with a green
   tick, and download the **.dmg** for your Mac:
   * **APC-Titan-Bridge-mac-arm64** for Apple silicon (M1, M2, M3, M4…)
   * **APC-Titan-Bridge-mac-x86_64** for older Intel Macs
   (Apple menu → **About This Mac** shows which one you have.)
2. Unzip it, open the .dmg, and drag **APC Titan Bridge** onto **Applications**.
3. The app is not signed with a paid Apple developer certificate, so the
   first time macOS says it "cannot be opened" or "cannot verify the
   developer". Click **Done** (not Move to Bin), then open **System Settings →
   Privacy & Security**, scroll down and click **Open Anyway** next to
   APC Titan Bridge, and confirm with your password. After that it opens
   normally. (On older macOS you can instead right-click the app → **Open**.)
4. When macOS asks whether the app may **find devices on your local
   network**, click **Allow**. Without it no sACN reaches Titan. You can
   change it later in **System Settings → Privacy & Security → Local Network**.

**Settings on a Mac:**

* Your saved mappings and logs are in **Documents → APC Titan Bridge**.
* In **Output settings**, choose **Unicast to IP** and enter the **Titan PC's
  IP address** (on the Titan PC: Settings → Network & Internet → your
  connection → IPv4 address). The default Multicast may also work, but on a
  Mac it can go out of the wrong network connection (e.g. Wi-Fi instead of
  the cable), so unicast is the safer choice.
* On the Titan PC, Windows Firewall may block incoming sACN (UDP port 5568).
  If Titan's trigger does not react, allow Titan Go through the firewall for
  private networks.
* The Titan Go trigger setup is the same as on Windows (see below).

## The programs

| Run | What it is for |
|---|---|
| `APC-Titan-Bridge.exe` or `py -3.12 run_bridge.py` | **The bridge.** Faders and buttons control Titan Go, with LED feedback |
| `py -3.12 run_apc_bridge.py` | MIDI monitor and LED test. Read-only, sends no lighting data |
| `py -3.12 run_sacn_test.py` | Single-channel sACN test, used to prove the Titan trigger works |

Only one of them can use the APC mini at a time.

| Stage | What | Status |
|---|---|---|
| 1 | MIDI monitor and LED test | Done, verified on hardware |
| 2 | Fader mapping, pickup/soft takeover, saved settings, simulated output | Done |
| 3 | Find a legitimate way to control Titan Go with the T1 | Done: sACN triggers, verified |
| 4 | Connect mapping to Titan Go | Done: faders and buttons, needs a full test on your rig |
| 5 | Package as a standalone .exe with an HTML interface | **This release** |

## Using the bridge

### The start screen

When the bridge starts it asks which mapping to load:

* **Your files**: mappings you saved before (newest first).
* **Ready-made files**, shipped with the app:

  | File | What it does | sACN channels |
  |---|---|---|
  | All buttons momentary | Every pad and round button is ON while held | faders 1–9, pads 10–73, bottom row 74–81, right column 82–89 |
  | All buttons toggle | Every pad and round button latches: press on, press again off | same as above |
  | Faders only (basic) | Just the 9 faders; the bottom buttons switch faders on/off | faders 1–9 |

  In both "All buttons" files the 64 pads are **red when off and green when
  on**. The round buttons only have one colour each (the APC mini hardware
  cannot show red/green there), so the **bottom row is red when off and
  blinking red when on**, and the **right-hand column is dark when off and
  green when on**. Shift has no light and is left unused.
* **Open a file from the computer…** loads a mapping file from anywhere, and
  **Start empty** begins with the basic fader setup.

Ready-made files are never overwritten. Change one and use **Save as** to
keep it under your own name; it then appears under "Your files". **Open** in
the top bar brings the start screen back. Settings saved by older versions
(`config.json`) appear as "My settings".

### Editing

The window shows a picture of the APC mini. Click any pad, round button,
Shift or fader to edit it on the right, or click **Learn** and then press or
move the real control. Changes take effect straight away; click **Save** (or
**Save as**) to keep them.

### Live-show features

* **BLACKOUT** (button in the top bar, or the **Esc** key): every channel goes
  to 0 straight away, and faders and buttons are ignored until you click
  **Release blackout**. Toggles stay off, and each fader must be brought down
  to 0 before it takes control again, so nothing jumps back on. You can also
  give an APC mini button (Shift works well) the **Blackout** mode: press
  once for blackout, press again to release. It blinks during blackout.
  Releasing on purpose needs the button, never the Esc key.
* **Auto-reconnect:** if the APC mini's USB cable comes out, output switches
  OFF and a red banner says so. Plug it back in and it reconnects by itself
  within a couple of seconds. Output stays OFF until you switch it on again.
* **Activity lights:** the MIDI light flashes when the APC mini sends
  something, the sACN light when levels go out to Titan. **Show timer:** how
  long output has been ON.
* A red banner appears if the window loses contact with the bridge, and the
  window asks before it closes (closing stops the output).
* Mappings are locked while output is ON, so a stray click cannot change them
  mid-show. **Ctrl+S** (Cmd+S on a Mac) saves.

### Testing the APC mini

Click **Test APC mini** (output must be OFF). While a test runs, nothing is
sent to Titan and the mapping ignores the controller. Pick a test in the blue bar:

* **Light show:** every pad and button goes red, then green, then yellow,
  then everything flashes, then coloured diagonal stripes move across the
  grid while a light runs along the round buttons. It loops, so you can spot
  a dead LED.
* **Button test:** press every pad and button. Each lights up once pressed
  (yellow or blinking while held), and the bar counts how many of the 81 you
  have pressed. Shift has no light but still counts.
* **Fader test:** push each fader fully up and fully down. The grid column
  above it shows its level (the master fader uses the right-hand column), and
  the round button under it lights once it has done both. The bar counts
  checked faders.

Click **Finish test** to go back to normal.

### What each button can do

| Mode | What happens | sACN it sends |
|---|---|---|
| Not used | Nothing (the pads in "Faders only") | – |
| Momentary | ON while you hold it, like a flash button | ON level while held, OFF level otherwise |
| Toggle | Press once for ON, again for OFF | ON level or OFF level |
| Toggle in a group | Give toggles the same **Group** number (1–99): switching one on switches the others in that group off, like radio buttons. Pressing the lit one turns it off. Shown as [G1] etc. on the pads | ON level or OFF level |
| Fader on/off | Switches one fader on/off (the bottom row and bottom-right button in "Faders only") | – |
| Output status light | Lit while output is ON, blinking while OFF (the top-right button in "Faders only") | – |
| Blackout | Press: every channel to 0. Press again: release. Blinks during blackout | 0 on every channel |
| Titan WebAPI action | Sends a Titan command over the network instead of sACN (see below). Lit while held | – |

Each momentary/toggle button gets its own sACN channel (a free one is picked
when you choose the mode) and its own **light when ON** and **light when OFF**
colours, using only what the hardware can show:
* grid pads: off, green, red or yellow, each steady or blinking
* bottom row: red or blinking red
* right-hand column: green or blinking green

Giving a mapped button a "light when OFF" colour makes every mapped pad
visible at a glance.

Buttons only react while output is ON, so pressing them while output is off
cannot fire anything later.

### Titan WebAPI actions

Below the APC mini picture is an **Actions** palette. Drag an action onto a
pad, round button or fader, or select a control and click an action. Orange
actions are Titan button commands, purple ones are Titan fader commands, and
blue/green ones are this app's own modes and sACN. A dropped action guesses
the playback from where it lands (pad column 3 = playback 3), which you can
change in the editor on the right.

| Action | What it does (Titan API command) |
|---|---|
| Go | Plays the next cue; continues a paused playback (CueLists.Play) |
| Go back | Fires the cue before the live one (CueLists.GoBack) |
| Pause | Pauses; press again while paused to go back (CueLists.Pause) |
| Go to cue | Sets the next cue number, then plays it (CueLists.SetNextCue + Play) |
| Set next cue | Sets the next cue number without playing it (CueLists.SetNextCue) |
| Fire at level | Fires a playback at a chosen level (Playbacks.FirePlaybackAtLevel) |
| Toggle on/off | Toggles a playback (Playbacks.ToggleLatchPlayback) |
| Flash / Swop (while held) | Flash or swop while the button is held (Playbacks.Flash/Swop, Clear… on release) |
| Release / Release all | Kills one playback or all (Playbacks.KillPlayback / KillAllPlaybacks) |
| Palette | Recalls a palette (Palette.ApplyPalette) |
| Macro | Runs a macro by its id (Macros.Run) |
| Clear programmer | Clears the programmer and selection (Programmer.Editor.ClearAll) |
| Master flash / DBO (held) | Flashes a master to full, or to zero, while held (Masters.Flash / DeadBlackOut, ClearFlash on release) |
| Fader: Playback level | The fader sets a playback's level (Playbacks.SetPlaybackLevel) |
| Fader: Master level | The fader sets a master (Masters.SetMaster) |
| Fader: Group intensity | The fader sets a group's intensity (Group.SetGroupFaderLevel) |
| Fader: Speed master (BPM) | The fader sets a speed master between two values (Masters.SetSpeed) |
| Fader: Programmer wheel ⚠ | Experimental: sets wheel A–E for the selected fixtures, like an encoder |

Playbacks are picked by their Titan **user number** by default (a location
such as `playback_2_1` or a Titan ID also works).

Things to know:

* These commands come from the Avolites Titan API reference (version 18.0).
  **None has been tried on a real rig yet.** Try each one before a show.
* The programmer wheel action uses the documented property URL, but Avolites
  does not document how the value is sent, so it may do nothing.
* Titan actions follow the same safety rules as sACN: nothing is sent while
  output is OFF, faders need pickup, and settings are locked while output is
  ON. Blackout pulls WebAPI playback, master and group faders to 0 and
  releases held flashes, but it does not undo a Go.
* **Titan WebAPI** in Output settings is the address of the computer running
  Titan (127.0.0.1 = this computer) and port 4430. On a Mac, enter the Titan
  PC's IP address.
* The **Titan WebAPI starter** file sets faders 1–8 and the master fader to
  playbacks 1–9, and the pad rows from the bottom to Go, Go back, Flash and
  Release for playbacks 1–8.
* The WebAPI light in the top bar flashes when a command goes out, and a red
  "Titan WebAPI: error" pill shows if Titan does not answer (hover for why).

### One-time setup in Titan Go

For every fader and every mapped button, in Titan Go go to **System → Triggers**,
add a trigger:

* Type **Item**. Pick the playback and set the action to **Set Level**.
* Source **Streaming ACN (sACN)**, universe **10** (or yours), address = the
  control's **sACN channel** in the bridge. By default faders 1–8 are channels
  1–8 and the master fader is channel 9.

Or turn **Learn On** in Titan, switch the bridge's output on, and use that
control once.

Titan saves triggers per show and per hardware, so this is done once per show.
Triggers cannot target Titan's masters, so the APC master fader is mapped to
a ninth playback by default. Only **Set Level** has been tested. Other Titan
trigger actions (for example Go on a cue list) may also work with a button,
but they have not been verified.

### Every time

1. Plug in the APC mini, start Titan Go, then start the bridge.
2. Pick a mapping on the start screen. The bridge connects to the APC mini by
   itself (or choose it and click **Connect**).
3. Click **Switch output ON** (the bar at the top turns red).
4. **Pickup:** each fader only takes control once you move it to its last
   level. Its status shows "Pickup N%", and its on/off button blinks until
   then. That way nothing jumps when you switch on or change settings.
5. Click **Switch output OFF** when done. *Not verified yet:* whether Titan
   keeps the last levels or releases the playbacks when sACN stops. Please
   check this once, with no audience present.

The LEDs show **what this app is doing**. sACN only goes one way, so they
cannot show Titan's real playback state. If you change a playback in Titan
itself, the LEDs will not know.

### Settings

* Mappings and settings are locked while output is ON. Switch output OFF to
  change them.
* **Output settings** (folded away under the editor): universe, multicast or
  unicast, **Max output %** (caps every fader and button), pad lights, level
  meters, and **Test mode**, which calculates everything but sends nothing.
* If Titan does not react, try **Unicast to IP** with 127.0.0.1 instead of
  Multicast.
* If the APC mini is unplugged while output is on, output switches **OFF**.
  Reconnect and switch it on again (pickup applies).
* `py -3.12 run_bridge.py --simulate` runs with a fake APC mini, and
  `--browser` opens the interface in your web browser instead of a window.

## Building the .exe yourself

With Python 3.12 installed (see below), double-click `build_exe.bat` or run it
in Command Prompt from the project folder. It installs PyInstaller (free) and
creates `dist\APC-Titan-Bridge.exe`.

Why not Tauri? Tauri would mean installing Rust and Visual Studio build
tools, and rewriting the tested MIDI/sACN code in another language. Instead,
this app uses the same kind of HTML interface in a native window
(**pywebview**, which uses the Edge WebView2 engine built into Windows 11),
packaged with **PyInstaller**. Both are free and need nothing but Python.

To build the Mac app yourself, on a Mac with Python 3.12 run
`./build_mac.sh` in the project folder. It creates
`dist/APC-Titan-Bridge-mac-<arm64 or x86_64>.dmg`.

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

### 3. Install the libraries

In Command Prompt, go into the folder (change the path to wherever you put it):

```
cd C:\APC-Bridge
py -3.12 -m pip install -r requirements.txt
```

This installs `mido`, `python-rtmidi` and `pywebview` (all free and open source).

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
* The bridge's interface server only listens on this computer (127.0.0.1)
  and needs a secret token that only its own window has, so web pages open
  in a browser cannot control it.
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
| `apc_bridge/config.py` | Bridge settings, JSON save/load, the ready-made mappings |
| `apc_bridge/library.py` | The `mappings` folder and the ready-made files in `apc_bridge/presets` |
| `apc_bridge/bridge.py` | Mapping engine (pure logic, unit tested) |
| `apc_bridge/app_core.py` | Running bridge: MIDI/sACN/LED loop on one thread, with a lock |
| `apc_bridge/web_server.py` | Local-only web server and JSON API (token-protected) |
| `apc_bridge/web/index.html` | The HTML interface |
| `apc_bridge/app.py` | Starts it all in a pywebview window |

What is needed to start Stages 2 and 3 is in [docs/NEXT_STEPS.md](docs/NEXT_STEPS.md).
The Titan Go investigation (Stage 3) is in [docs/TITAN_INTEGRATION.md](docs/TITAN_INTEGRATION.md).

## Credits

Made by **Karol Pasko** · Instagram [@karol.pasko](https://www.instagram.com/karol.pasko/) ·
[KarolPasko.github.io](https://karolpasko.github.io/)

The app icon (with "Karol Pasko" on it; the smallest sizes show only the pads,
because the name would be unreadable) is drawn by `assets/make_icon.py`.
