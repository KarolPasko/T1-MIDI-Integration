# What is needed for Stage 2 and Stage 3

## From the Stage 1 hardware test

Done 28 Oct 2026: buttons, faders and all LED states confirmed on real
hardware. The original checklist is kept below for reference.

Please run the checks in the README ("Verifying the protocol") and report:

1. **Faders:** did all 9 faders appear as CC 48-56 on channel 1? Did any show up
   under "Other controllers seen"? Do they reach exactly 0 at the bottom and 127
   at the top?
2. **Buttons:** did the "Documented control" names match the buttons you
   pressed (especially the top-left pad = note 56 and the top scene button = note 82)?
   Does releasing a button show a Note Off?
3. **LEDs:** which of these worked: grid green / red / yellow, each blinking
   version, track buttons (red), scene buttons (green)? Did "All LEDs off" clear
   everything?
4. The `logs\apc_bridge.log` file and a screenshot, if possible.

The README's protocol table is now marked verified.

## For Stage 2 (mapping engine, all simulated, no lighting)

Stage 2 does not touch Titan Go, so it only needs your preferences:

* Which faders should map to which playbacks (e.g. "fader 1 = playback 1").
* What the pads above each fader should do and show (e.g. "bottom pad green
  when the fader is above 0, red when disabled").
* Whether you want the master fader to act as a grand master limit in software.

Defaults will be chosen if you have no preference; everything will be editable
in the app and saved to a local JSON file.

## For Stage 3 (Titan Go investigation)

No Titan Go integration method has been verified yet. Nothing will be built on
an assumed or undocumented interface. To investigate, please tell us:

1. **Titan Go version:** open Titan Go, then *Help* (or the Avolites logo) →
   *About*, and copy the full version number (for example 17.0 or 18.0).
2. **Is Titan Go on the same PC** as the APC mini?
3. Does the Titan Go install show any **MIDI**, **Remote** or **Web API**
   settings? (Look in *User Settings* / *System* menus; a screenshot is fine.)
4. Your **Windows display scaling** (Settings → System → Display → Scale) and
   screen resolution, in case the mouse-automation fallback is needed.
5. Which playbacks you want to control and whether they are on fixed pages.

Candidate interfaces to check, in the agreed priority order. None of these is
confirmed for your version or with the T1 yet:

| Priority | Candidate | What needs checking |
|---|---|---|
| 1 | Titan's own built-in MIDI support | Whether your Titan Go version accepts MIDI input for playback faders at all, and on which hardware |
| 1 | Avolites' remote-control interfaces (used by their remote/web apps) | Whether it is officially documented, enabled in Titan Go with a T1, and whether it can set playback levels and read back playback state |
| 2 | Other compatible protocols Titan Go supports | Only if documented by Avolites |
| 3 | Windows mouse/keyboard automation | Fallback only: less reliable, depends on window position and scaling, and cannot read playback state reliably |

Whether pad LEDs can reflect Titan's real playback state depends entirely on
which of these turns out to work. Until then, any LED feedback in Stage 2 will
be labelled as local software state.
