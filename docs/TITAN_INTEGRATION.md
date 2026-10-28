# Stage 3: How can the app control Titan Go with a T1?

Investigated 28 Oct 2026 for **Titan Go v18.0 + T1, running on the same laptop
as the APC mini**. Only public Avolites documentation and community sources
were used. The "Test" sections say how to check each point safely.

**Update 28 Oct 2026:** the WebAPI browser test returned
`<string>Titan is unavailable.</string>`, so the WebAPI route is closed with a
T1. The plan is now **sACN triggers** (section 5), tested with
`run_sacn_test.py`.

**Verified 28 Oct 2026:** with `run_sacn_test.py`, a Set Level trigger with an
sACN source in Titan Go v18.0 + T1 on the same laptop "works perfect". The
playback follows the sent value. `run_bridge.py` is built on this.

## Short answer

| Route | Works with T1? | Source |
|---|---|---|
| Titan's built-in MIDI triggers (System → Triggers, "learn" a MIDI device) | **No, per Avolites.** That needs a **T2** or a console | Avolites manual (T1 and T2 page) and Avolites staff on the forum |
| Titan **WebAPI** (official HTTP interface, port 4430) | **No.** Documented as unavailable on T1, and the test on v18 answered "Titan is unavailable" | avosupport.de WebAPI docs + test |
| Titan **sACN triggers** (Triggers window, source = Streaming ACN) | **Yes, verified** on v18.0 + T1 with Set Level | avosupport.de trigger docs + test |
| Mouse automation of Titan Go's on-screen playback faders | Yes, technically. It is the least reliable route | Fallback in the project plan |
| Copying how OsiMIDI T1 does it | Unknown. OsiMIDI is closed-source and does not publish its method | App Store listing |

## 1. Titan's built-in MIDI triggers

What you saw on the **Tiger Touch** (Triggers → add MIDI device → press the
hardware) is Titan's built-in MIDI triggering. It works there because the
Tiger Touch is a full console.

For the T1, Avolites' own manual for v18.0 says **"USB-MIDI devices are not
supported"**. It also says it is the **T2** that "enables the use of a USB
MIDI device plugged into the host computer for MIDI triggering of Titan". An
Avolites staff member on their forum says the same: *"For Titan to be able to
receive MIDI you would need to have a T2 or above."* The Triggers window can
still be opened on a T1, but it will not act on incoming MIDI.

**Test (2 minutes, harmless):** in Titan Go, open System → Triggers and try
adding the APC mini as a MIDI device. Close this app first, because only one
program can open the APC mini at a time. If it learns button presses, the
documentation is wrong for your setup and this becomes the best route. Most
likely it will not work.

Upgrading to a **T2** would make this route work natively, with no extra
software. The T2 is not free, so it is outside this project's £0 budget, but
it is the officially supported way.

## 2. Titan WebAPI (official HTTP interface)

Titan has an official, documented WebAPI on **TCP port 4430**
([api.avolites.com/18.0](https://api.avolites.com/18.0/)). It can, for example,
set a playback's level:

```
http://localhost:4430/titan/script/Playbacks/FirePlaybackAtLevel?userNumber=1&level=0.5&bool=false
```

It may also be able to read playback state, which would allow real LED
feedback. However, the community documentation at avosupport.de says the
WebAPI is **"not available on the Titan One or the Titan Simulator"**, and
the T1 is the Titan One's successor. Avolites' v18 pages do not say either
way for the T1.

**Test (30 seconds, read-only, cannot change any lights):** with Titan Go
running and the T1 plugged in, open a web browser on the same laptop and go to:

```
http://localhost:4430/titan/get/System/SoftwareVersion
```

* If it shows a version number such as `"18.0"`, the WebAPI is reachable on
  your setup. That is an officially documented interface, and Stage 4 would
  use it.
* If the page fails to load ("refused to connect"), the WebAPI is not
  available with the T1, as documented. We will **not** try to work around
  that, because it is a licensing restriction.

**Result (28 Oct 2026):** the URL returned `<string>Titan is unavailable.</string>`.
Something on port 4430 answers, but it will not give access to Titan with a T1
(this matches the documentation). If Titan Go was not fully started with a
show loaded during that test, it could be worth one retry. Otherwise this
route is closed.

## 3. Mouse automation (fallback)

If both of the above are unavailable, the app can move Titan Go's on-screen
playback faders with the mouse, exactly as you would by hand. This is
allowed, but it is clearly worse than a real interface:

* It needs Titan Go's window visible, at a known size and position, and it is
  sensitive to Windows display scaling.
* It takes over the mouse pointer while a fader moves, and can only move one
  fader at a time.
* It **cannot read playback state**, so pad LEDs would show only what the
  app sent, not what Titan is actually doing. The app will label this.
* It needs a pause/stop control and focus checking (already planned).

## 4. OsiMIDI T1

OsiMIDI T1 is a paid, closed-source Windows app. Its public material
(including its free iOS "OsiMIDI T1 Remote" companion) says it controls Titan
Go from MIDI controllers and from a phone. It does not say how it talks to
Titan Go. We will not reverse-engineer it or copy its code. If the WebAPI
test above fails, the most likely explanation is that it drives Titan Go's
user interface, which is route 3, but that is a guess.

## 5. sACN triggers (current plan)

sACN (ANSI E1.31, "Streaming ACN") is an open standard for sending DMX over a
network. Titan's Triggers window can take **Streaming ACN** as an input source
(settings: Universe and Address). The community trigger documentation marks
it as supported on **Titan One and T1**. An item trigger can use actions
including **Fire At Level** and **Set Level**.

So the app can send sACN, one channel per fader, and Titan Go maps each
channel to a playback with a trigger. That is an official Titan feature used
as intended, and it works on the same laptop.

What is **not** known yet, and what `run_sacn_test.py` checks:

1. Does Titan Go with a T1 accept sACN triggers in v18?
2. Does **Set Level** follow the incoming value continuously, like a fader?
   Or does it fire only once when the value crosses a threshold?
3. Does Titan Go receive sACN sent from the same laptop by multicast? If not,
   does unicast to `127.0.0.1` or to the laptop's own IP address work?

Known limits from the same documentation:

* Triggers are saved per hardware and cannot be copied between shows.
* Triggers cannot target **masters** (so the grand master is probably not
  controllable this way) or **macros**.
* sACN carries data one way only, so Titan's real playback state cannot be
  read back. Pad LEDs would show the app's local state, labelled as such.

**Test steps:** see the README section "Stage 3 test: sACN trigger test".

## What is needed next

1. The result of the **sACN trigger test** (section 5): did the playback
   follow the slider smoothly, only switch on/off, or do nothing? Which
   destination worked (multicast, or unicast to 127.0.0.1)?
2. Which playbacks each fader should control. The default is faders 1–8 →
   playbacks 1–8.

## Sources

* Avolites manual v18.0, "T1 and T2": <https://manual.avolites.com/docs/18.0/about-the-consoles/t1-and-t2>
* Avolites forum, "Titan Virtual Panel MIDI Mapping": <https://forum.avolites.com/viewtopic.php?p=23191>
* avosupport.de, MIDI with Titan: <https://avosupport.de/wiki/external/midi>
* avosupport.de, Titan WebAPI: <https://www.avosupport.de/wiki/webapi/start> and <https://avosupport.de/downloads/webapi/help/index.htm>
* Avolites Titan API reference v18.0: <https://api.avolites.com/18.0/>
* Avolites manual, network ports used by Titan: <https://manual.avolites.com/docs/networking/ports-used-by-titan>
* avosupport.de, Titan triggers (sources, actions, console table): <https://avosupport.de/wiki/external/trigger>
* Avolites manual, MIDI/DMX triggering: <https://manual.avolites.com/docs/13.0/running-the-show/midi-dmx-or-audio-triggering>
* OsiMIDI T1 Remote (App Store): <https://apps.apple.com/app/id6449872669>
