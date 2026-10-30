"""Titan WebAPI: actions a button or fader can trigger, and the HTTP client that sends them.

Every action here is a command published in the Avolites Titan API reference
(api.avolites.com/18.0), called as
    http://<titan>:4430/titan/script/2/<Namespace>/<Method>?<parameters>
Avolites documents the WebAPI as unavailable on Titan One and T1, so this only
works where Titan itself answers the WebAPI; "Check connection" shows what
Titan replies. Nothing here works around that.

None of these commands has been tried on a real rig yet: they follow the
Avolites reference, and the interface says they are untested. The programmer
wheel action uses the documented `titan/set` property URL, but Avolites does
not document the request body, so it is marked experimental.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

log = logging.getLogger(__name__)

DEFAULT_PORT = 4430
TIMEOUT_S = 1.5
HANDLE_TYPES = ("userNumber", "location", "titanId")
WHEELS = "ABCDE"

# kind: "button" (press / release) or "fader" (a 0-1 level).
# params: the settings the action needs, beyond the playback/master handle.
ACTIONS: dict[str, dict] = {
    # ----- cue lists
    "go": {"kind": "button", "group": "Cue lists", "label": "Go", "handle": True,
           "help": "Plays the next cue on the playback (continues it if paused). CueLists.Play"},
    "go_back": {"kind": "button", "group": "Cue lists", "label": "Go back", "handle": True,
                "help": "Fires the cue before the live one. CueLists.GoBack"},
    "pause": {"kind": "button", "group": "Cue lists", "label": "Pause", "handle": True,
              "help": "Pauses the playback; press again while paused to go back. CueLists.Pause"},
    "cue_go": {"kind": "button", "group": "Cue lists", "label": "Go to cue", "handle": True, "params": ["cue"],
               "help": "Sets the next cue to this number, then plays it. CueLists.SetNextCue + CueLists.Play"},
    "set_next_cue": {"kind": "button", "group": "Cue lists", "label": "Set next cue", "handle": True,
                     "params": ["cue"],
                     "help": "Makes this cue number the next one, without playing it. CueLists.SetNextCue"},
    # ----- playbacks
    "fire": {"kind": "button", "group": "Playbacks", "label": "Fire at level", "handle": True, "params": ["level"],
             "help": "Fires the playback at a level. Playbacks.FirePlaybackAtLevel"},
    "toggle_latch": {"kind": "button", "group": "Playbacks", "label": "Toggle on/off", "handle": True,
                     "help": "Toggles the playback on and off; on a cue list it plays the next cue. "
                             "Playbacks.ToggleLatchPlayback"},
    "flash": {"kind": "button", "group": "Playbacks", "label": "Flash (while held)", "handle": True,
              "help": "Flashes the playback while the button is held. Playbacks.FlashPlayback / ClearFlashPlayback"},
    "swop": {"kind": "button", "group": "Playbacks", "label": "Swop (while held)", "handle": True,
             "help": "Swops to the playback while held. Playbacks.SwopPlayback / ClearSwopPlayback"},
    "release": {"kind": "button", "group": "Playbacks", "label": "Release", "handle": True,
                "help": "Kills (releases) the playback. Playbacks.KillPlayback"},
    "release_all": {"kind": "button", "group": "Playbacks", "label": "Release all", "handle": False,
                    "help": "Kills every playback. Playbacks.KillAllPlaybacks"},
    # ----- palettes, macros, programmer
    "palette": {"kind": "button", "group": "Programmer", "label": "Palette", "handle": True,
                "params": ["palette_times"],
                "help": "Recalls a palette. Palette.ApplyPalette"},
    "macro": {"kind": "button", "group": "Programmer", "label": "Macro", "handle": False, "params": ["macro"],
              "help": "Runs a macro by its id. Macros.Run"},
    "clear": {"kind": "button", "group": "Programmer", "label": "Clear programmer", "handle": False,
              "help": "Clears the programmer and the selection. Programmer.Editor.ClearAll"},
    "select": {"kind": "button", "group": "Selection", "label": "Select fixtures/groups", "handle": False,
               "params": ["numbers"],
               "help": "Makes these user numbers the selection (e.g. a group's number, or 1,2,3 for fixtures). "
                       "Programmer.Editor.Selection.SetNewHandleSelection"},
    "select_clear": {"kind": "button", "group": "Selection", "label": "Clear selection", "handle": False,
                     "help": "Clears the fixture selection. Programmer.Editor.Selection.Clear"},
    "sel_next": {"kind": "button", "group": "Selection", "label": "Next fixture", "handle": False,
                 "help": "Moves the selection pattern one place to the right (one fixture at a time). "
                         "Programmer.Editor.Selection.PatternNext"},
    "sel_prev": {"kind": "button", "group": "Selection", "label": "Previous fixture", "handle": False,
                 "help": "Moves the selection pattern one place to the left. "
                         "Programmer.Editor.Selection.PatternPrevious"},
    "locate": {"kind": "button", "group": "Selection", "label": "Locate", "handle": False,
               "help": "Sets every attribute of the selected fixtures to its locate value. "
                       "Programmer.Editor.Fixtures.LocateSelectedFixtures"},
    "fan": {"kind": "button", "group": "Selection", "label": "Fan on/off", "handle": False,
            "help": "Toggles fan mode for the selection. Programmer.Editor.Fixtures.Fan.ToggleFan"},
    "nudge": {"kind": "button", "group": "Selection", "label": "Nudge attribute", "handle": False,
              "params": ["attr", "step"],
              "help": "Each press turns dimmer, pan or tilt of the selected fixtures by a fixed step, "
                      "like one click of an encoder (a negative step turns it down/left). "
                      "Programmer.Editor.Fixtures.IncrementDimmer / IncrementPan / IncrementTilt"},
    # ----- masters
    "master_flash": {"kind": "button", "group": "Masters", "label": "Master flash (held)", "handle": True,
                     "help": "Flashes a master to full while held. Masters.Flash / ClearFlash"},
    "tap_tempo": {"kind": "button", "group": "Masters", "label": "Tap tempo", "handle": True,
                  "help": "Tap in time: the app works out the BPM from your last taps and sets the speed "
                          "master to it (from the 2nd tap; a pause of 2 s starts again). Masters.SetSpeed"},
    "dbo": {"kind": "button", "group": "Masters", "label": "DBO (held)", "handle": True,
            "help": "Dead black out: flashes a master to zero while held. Masters.DeadBlackOut / ClearFlash"},
    # ----- fader actions
    "playback_level": {"kind": "fader", "group": "Fader", "label": "Playback level", "handle": True,
                       "zero_on_blackout": True,
                       "help": "The fader sets the playback's level. Playbacks.SetPlaybackLevel"},
    "master_level": {"kind": "fader", "group": "Fader", "label": "Master level", "handle": True,
                     "zero_on_blackout": True,
                     "help": "The fader sets a master's level. Masters.SetMaster"},
    "group_level": {"kind": "fader", "group": "Fader", "label": "Group intensity", "handle": False,
                    "params": ["group_index"], "zero_on_blackout": True,
                    "help": "The fader sets the intensity of a group. Group.SetGroupFaderLevel"},
    "speed": {"kind": "fader", "group": "Fader", "label": "Speed master (BPM)", "handle": True,
              "params": ["range"],
              "help": "The fader sets a speed master between the two values. Masters.SetSpeed"},
    "encoder": {"kind": "fader", "group": "Fader", "label": "Encoder (dimmer/pan/tilt)", "handle": False,
                "params": ["attr", "amount"], "relative": True,
                "help": "Works like an encoder on the selected fixtures: moving the fader up turns it up/right, "
                        "moving it down turns it down/left. The amount is how far one full fader travel turns it. "
                        "Programmer.Editor.Fixtures.IncrementDimmer / IncrementPan / IncrementTilt"},
    "encoder_control": {"kind": "fader", "group": "Fader", "label": "Encoder (any attribute by ID)", "handle": False,
                        "params": ["control", "amount"], "relative": True,
                        "help": "Like the encoder above, for any attribute, picked by its Titan control ID "
                                "(Programmer.Editor.Fixtures.GetControlIdFromName gives it). "
                                "Programmer.Editor.Fixtures.IncrementAttribute"},
    "wheel": {"kind": "fader", "group": "Fader", "label": "Programmer wheel", "handle": False,
              "params": ["wheel", "range"], "experimental": True,
              "help": "Sets the value on wheel A-E for the selected fixtures, like turning an encoder. "
                      "Programmer.Editor.Fixtures.Attribute<wheel>Value. Experimental: Avolites does not "
                      "document how the value is sent."},
}

# Actions whose release also sends a command.
RELEASE_CALLS = {"flash", "swop", "master_flash", "dbo"}

ATTRS = {"dimmer": "IncrementDimmer", "pan": "IncrementPan", "tilt": "IncrementTilt"}
DEFAULTS = {"attr": "dimmer", "step": 5, "amount": 100, "numbers": "1", "control": 1,
            "handle_type": "userNumber", "handle": "1", "cue": 1, "level": 100, "palette_times": True,
            "macro": "", "group": "Groups", "index": 1, "wheel": "A", "min": 0, "max": 255}


class ActionError(ValueError):
    pass


def actions_for(kind: str) -> dict[str, dict]:
    return {k: v for k, v in ACTIONS.items() if v["kind"] == kind}


def normalise(action: dict, kind: str) -> dict:
    """A cleaned copy of a saved action; raises ActionError if it can't be used."""
    if not isinstance(action, dict):
        raise ActionError("Titan action must be an object")
    t = action.get("type")
    spec = ACTIONS.get(t)
    if spec is None or spec["kind"] != kind:
        raise ActionError(f"'{t}' is not a Titan {kind} action")
    out = {"type": t}
    try:
        if spec["handle"]:
            ht = str(action.get("handle_type", DEFAULTS["handle_type"]))
            if ht not in HANDLE_TYPES:
                raise ActionError(f"Unknown handle type '{ht}'")
            h = str(action.get("handle", DEFAULTS["handle"])).strip()
            if not h:
                raise ActionError(f"{spec['label']}: enter the playback / handle")
            if ht in ("userNumber", "titanId") and not h.isdigit():
                raise ActionError(f"{spec['label']}: '{h}' must be a whole number")
            out.update(handle_type=ht, handle=h)
        for p in spec.get("params", []):
            if p == "cue":
                cue = float(action.get("cue", DEFAULTS["cue"]))
                if cue <= 0:
                    raise ActionError("Cue number must be above 0")
                out["cue"] = cue
            elif p == "level":
                level = float(action.get("level", DEFAULTS["level"]))
                if not 0 <= level <= 100:
                    raise ActionError("Level must be 0-100%")
                out["level"] = level
            elif p == "palette_times":
                out["palette_times"] = bool(action.get("palette_times", True))
            elif p == "macro":
                macro = str(action.get("macro", "")).strip()
                if not macro:
                    raise ActionError("Enter the macro id")
                out["macro"] = macro
            elif p == "group_index":
                out["group"] = str(action.get("group", DEFAULTS["group"])).strip() or DEFAULTS["group"]
                out["index"] = int(action.get("index", DEFAULTS["index"]))
            elif p == "attr":
                attr = str(action.get("attr", "dimmer")).lower()
                if attr not in ATTRS:
                    raise ActionError("Attribute must be dimmer, pan or tilt")
                out["attr"] = attr
            elif p == "step":
                out["step"] = float(action.get("step", DEFAULTS["step"]))
                if out["step"] == 0:
                    raise ActionError("Step must not be 0")
            elif p == "amount":
                out["amount"] = float(action.get("amount", DEFAULTS["amount"]))
                if out["amount"] == 0:
                    raise ActionError("Amount must not be 0")
            elif p == "control":
                out["control"] = int(action.get("control", DEFAULTS["control"]))
            elif p == "numbers":
                nums = [n.strip() for n in str(action.get("numbers", DEFAULTS["numbers"])).replace(";", ",").split(",") if n.strip()]
                if not nums or not all(n.isdigit() for n in nums):
                    raise ActionError("Enter user numbers separated by commas, e.g. 1,2,3")
                out["numbers"] = ",".join(nums)
            elif p == "wheel":
                wheel = str(action.get("wheel", "A")).upper()
                if wheel not in WHEELS:
                    raise ActionError("Wheel must be A, B, C, D or E")
                out["wheel"] = wheel
            elif p == "range":
                out["min"] = float(action.get("min", DEFAULTS["min"] if t == "wheel" else 60))
                out["max"] = float(action.get("max", DEFAULTS["max"] if t == "wheel" else 180))
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ActionError):
            raise
        raise ActionError(f"{spec['label']}: {exc}") from exc
    return out


def describe(action: dict) -> str:
    """Short text for a pad label, e.g. 'Go PB 3'."""
    spec = ACTIONS.get(action.get("type"), {})
    text = spec.get("label", "?").replace(" (while held)", "").replace(" (held)", "")
    if spec.get("handle"):
        text += f" {action.get('handle', '')}"
    if "cue" in action:
        text += f" Q{action['cue']:g}"
    if action.get("type") == "macro":
        text += f" {action.get('macro', '')}"
    if action.get("type") == "wheel":
        text = f"Wheel {action.get('wheel', 'A')}"
    if action.get("type") in ("encoder", "nudge"):
        text = f"{spec.get('label', '').split(' ')[0]} {action.get('attr', '')}"
    return text


@dataclass(frozen=True)
class Call:
    method: str       # "GET" or "POST"
    path: str         # after http://host:port/
    body: bytes | None = None


def _q(params: dict) -> str:
    return urllib.parse.urlencode(params)


def _handle(action: dict, prefix: str = "handle") -> dict:
    return {f"{prefix}_{action['handle_type']}": action["handle"]}


def _script(ns_method: str, params: dict | None = None) -> Call:
    return Call("GET", f"titan/script/2/{ns_method}" + (f"?{_q(params)}" if params else ""))


def button_calls(action: dict, pressed: bool) -> list[Call]:
    """The WebAPI requests for a button press (pressed=True) or release."""
    t = action["type"]
    if not pressed:
        if t == "flash":
            return [_script("Playbacks/ClearFlashPlayback", _handle(action))]
        if t == "swop":
            return [_script("Playbacks/ClearSwopPlayback", _handle(action))]
        if t in ("master_flash", "dbo"):
            return [_script("Masters/ClearFlash", _handle(action))]
        return []
    if t == "go":
        return [_script("CueLists/Play", _handle(action))]
    if t == "go_back":
        return [_script("CueLists/GoBack", _handle(action))]
    if t == "pause":
        return [_script("CueLists/Pause", {**_handle(action), "goBackIfPaused": "true"})]
    if t in ("cue_go", "set_next_cue"):
        calls = [_script("CueLists/SetNextCue", {**_handle(action), "stepNumber": f"{action['cue']:g}"})]
        if t == "cue_go":
            calls.append(_script("CueLists/Play", _handle(action)))
        return calls
    if t == "fire":
        return [_script("Playbacks/FirePlaybackAtLevel",
                        {**_handle(action), "level_level": _num(action["level"] / 100), "alwaysRefire": "false"})]
    if t == "toggle_latch":
        return [_script("Playbacks/ToggleLatchPlayback", _handle(action))]
    if t == "flash":
        return [_script("Playbacks/FlashPlayback", _handle(action))]
    if t == "swop":
        return [_script("Playbacks/SwopPlayback", _handle(action))]
    if t == "release":
        return [_script("Playbacks/KillPlayback", _handle(action))]
    if t == "release_all":
        return [_script("Playbacks/KillAllPlaybacks")]
    if t == "palette":
        return [_script("Palette/ApplyPalette",
                        {**_handle(action), "usePaletteTimes": "true" if action["palette_times"] else "false"})]
    if t == "macro":
        return [_script("Macros/Run", {"macroId": action["macro"]})]
    if t == "clear":
        return [_script("Programmer/Editor/ClearAll", {"presets": "false", "allProgrammers": "false"})]
    if t == "master_flash":
        return [_script("Masters/Flash", _handle(action))]
    if t == "dbo":
        return [_script("Masters/DeadBlackOut", _handle(action))]
    if t == "tap_tempo":
        return []      # needs the tap times: see TapTempo and speed_call()
    if t == "select":
        return [_script("Programmer/Editor/Selection/SetNewHandleSelection",
                        {"newSelection_userNumberList": action["numbers"]})]
    if t == "select_clear":
        return [_script("Programmer/Editor/Selection/Clear")]
    if t == "sel_next":
        return [_script("Programmer/Editor/Selection/PatternNext")]
    if t == "sel_prev":
        return [_script("Programmer/Editor/Selection/PatternPrevious")]
    if t == "locate":
        return [_script("Programmer/Editor/Fixtures/LocateSelectedFixtures", {"allAttributes": "true"})]
    if t == "fan":
        return [_script("Programmer/Editor/Fixtures/Fan/ToggleFan")]
    if t == "nudge":
        return [increment_call(action, action["step"], 0.0)]
    raise ActionError(f"'{t}' is not a button action")


def fader_call(action: dict, level: float) -> Call:
    """The WebAPI request for a fader at `level` (0.0-1.0)."""
    level = min(max(level, 0.0), 1.0)
    t = action["type"]
    if t == "playback_level":
        return _script("Playbacks/SetPlaybackLevel", {**_handle(action, "srcHandle"), "level_level": _num(level)})
    if t == "master_level":
        return _script("Masters/SetMaster", {**_handle(action), "value_level": _num(level)})
    if t == "group_level":
        return _script("Group/SetGroupFaderLevel", {"group": action["group"], "index": action["index"],
                                                    "value_level": _num(level), "accuracy": "0"})
    value = action["min"] + (action["max"] - action["min"]) * level
    if t == "speed":
        return _script("Masters/SetSpeed", {**_handle(action), "value": _num(value)})
    if t == "wheel":
        return Call("POST", f"titan/set/2/Programmer/Editor/Fixtures/Attribute{action['wheel']}Value",
                    _num(value).encode())
    raise ActionError(f"'{t}' is not a fader action")


def is_relative(action: dict) -> bool:
    return bool(ACTIONS.get(action.get("type"), {}).get("relative"))


def increment_call(action: dict, value: float, time_delta: float) -> Call:
    """Turn an attribute of the selected fixtures by `value`, like an encoder click."""
    params = {"value": _num(value), "timeDelta": _num(time_delta), "shiftEnabled": "false"}
    if action["type"] == "encoder_control":
        return _script("Programmer/Editor/Fixtures/IncrementAttribute", {"controlId": action["control"], **params})
    return _script(f"Programmer/Editor/Fixtures/{ATTRS[action['attr']]}", params)


def encoder_call(action: dict, fraction: float, time_delta: float) -> Call:
    """A relative fader moved by `fraction` of its travel (-1..1): turn by that share of the amount."""
    return increment_call(action, action["amount"] * fraction, time_delta)


def speed_call(action: dict, bpm: float) -> Call:
    """Set the speed master in `action` to `bpm`."""
    return _script("Masters/SetSpeed", {**_handle(action), "value": _num(bpm)})


class TapTempo:
    """Works out a BPM from button taps, like a console's tap-tempo button.

    Uses the average of the last few gaps between taps. A gap longer than
    RESET_S starts a new count, so the first tap after a pause never sends.
    """

    RESET_S = 2.0
    KEEP = 4          # gaps averaged
    MIN_BPM, MAX_BPM = 20.0, 400.0

    def __init__(self):
        self._taps: dict[int, list[float]] = {}
        self.bpm: dict[int, float] = {}

    def tap(self, key: int, at: float) -> float | None:
        taps = self._taps.setdefault(key, [])
        if taps and not 0 < at - taps[-1] <= self.RESET_S:
            taps.clear()
        taps.append(at)
        del taps[:-(self.KEEP + 1)]
        if len(taps) < 2:
            return None
        gap = (taps[-1] - taps[0]) / (len(taps) - 1)
        bpm = round(min(max(60.0 / gap, self.MIN_BPM), self.MAX_BPM), 1)
        self.bpm[key] = bpm
        return bpm


def _num(x: float) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".") or "0"


CHECK_PATH = "titan/get/System/SoftwareVersion"


class TitanClient:
    """Sends WebAPI requests from a background thread, so a slow Titan never holds up the APC mini.

    Fader moves are merged: only the newest level for each fader is sent.
    In dry-run mode (the app's Test mode) requests are counted but not sent.
    """

    def __init__(self, host: str, port: int = DEFAULT_PORT, dry_run: bool = False, opener=None):
        self.base = f"http://{host}:{port}/"
        self.dry_run = dry_run
        self._open = opener or urllib.request.urlopen
        self._jobs: queue.Queue = queue.Queue()
        self._latest: dict = {}           # fader key -> newest Call not yet sent
        self._deltas: dict = {}           # encoder key -> (summed move, call maker) not yet sent
        self._last_delta: dict = {}       # encoder key -> when it last sent
        self._lock = threading.Lock()
        self.sent = 0
        self.errors = 0
        self.last_error: str | None = None
        self.last_ok: float | None = None
        self._thread = threading.Thread(target=self._run, name="titan-webapi", daemon=True)
        self._thread.start()

    def submit(self, calls: list[Call]) -> None:
        for c in calls:
            self._jobs.put(c)

    def submit_delta(self, key, fraction: float, make_call) -> None:
        """Add an encoder move; moves made while Titan is busy are added together."""
        with self._lock:
            fresh = key not in self._deltas
            total, _ = self._deltas.get(key, (0.0, None))
            self._deltas[key] = (total + fraction, make_call)
        if fresh:
            self._jobs.put(("delta", key))

    def submit_fader(self, key, call: Call) -> None:
        with self._lock:
            fresh = key not in self._latest
            self._latest[key] = call
        if fresh:
            self._jobs.put(("fader", key))

    def close(self, wait_s: float = TIMEOUT_S + 0.5) -> None:
        """Send what is queued (e.g. the release of a held flash), then stop."""
        self._jobs.put(None)
        self._thread.join(timeout=wait_s)

    def pending(self) -> int:
        return self._jobs.qsize()

    def _run(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:      # close(): everything queued before it has been sent
                return
            if isinstance(job, tuple) and job[0] == "delta":
                with self._lock:
                    total, make_call = self._deltas.pop(job[1], (0.0, None))
                if make_call is None or abs(total) < 1e-9:
                    continue
                now = time.monotonic()
                gap = min(now - self._last_delta.get(job[1], now - 1.0), 1.0)
                self._last_delta[job[1]] = now
                job = make_call(total, gap)
            elif isinstance(job, tuple):
                with self._lock:
                    job = self._latest.pop(job[1], None)
                if job is None:
                    continue
            self._send(job)

    def _send(self, call: Call) -> None:
        if self.dry_run:
            self.sent += 1
            return
        try:
            request(self.base, call, self._open)
        except WebApiError as exc:
            self.errors += 1
            if str(exc) != self.last_error:
                log.error("Titan WebAPI: %s", exc)
            self.last_error = str(exc)
            return
        self.sent += 1
        self.last_ok = time.monotonic()
        if self.last_error:
            log.info("Titan WebAPI is answering again")
        self.last_error = None


class WebApiError(RuntimeError):
    pass


def request(base: str, call: Call, opener=None) -> str:
    """Send one request and return Titan's reply text."""
    opener = opener or urllib.request.urlopen
    req = urllib.request.Request(base + call.path, data=call.body, method=call.method)
    if call.body is not None:
        req.add_header("Content-Type", "text/plain")
    try:
        with opener(req, timeout=TIMEOUT_S) as resp:
            text = resp.read(4096).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise WebApiError(f"{call.path.split('?')[0]}: Titan answered HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise WebApiError(f"cannot reach Titan at {base} ({reason})") from exc
    if "unavailable" in text.lower():
        raise WebApiError(f"Titan replied '{text.strip()[:120]}'. The WebAPI is switched off on this Titan "
                          "(Avolites documents it as unavailable with a T1).")
    return text


def check(host: str, port: int = DEFAULT_PORT, opener=None) -> str:
    """Ask Titan for its software version. Returns the reply; raises WebApiError."""
    reply = request(f"http://{host}:{port}/", Call("GET", CHECK_PATH), opener)
    return re.sub(r"<[^>]+>", "", reply).strip() or "(empty reply)"
