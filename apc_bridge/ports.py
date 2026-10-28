"""Finding MIDI ports and picking out the APC mini."""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import apc_mini


@dataclass
class PortList:
    inputs: list[str]
    outputs: list[str]
    error: str | None = None


def list_ports() -> PortList:
    """List MIDI input and output port names.

    Returns an error string instead of raising, so the GUI can show a helpful
    message when the MIDI backend (python-rtmidi) is missing or broken.
    """
    try:
        import mido

        return PortList(list(mido.get_input_names()), list(mido.get_output_names()))
    except ImportError as exc:
        return PortList([], [], f"MIDI backend not installed ({exc}). "
                                "Run: py -3.12 -m pip install -r requirements.txt")
    except Exception as exc:  # rtmidi raises its own error types
        return PortList([], [], f"Could not list MIDI ports: {exc}")


def find_apc_mini(names: list[str]) -> str | None:
    """Return the port that looks like an original APC mini, if any.

    Windows names the ports e.g. "APC MINI 0" (input) and "APC MINI 1"
    (output); the trailing number is just the port index. An original unit is
    preferred over an mk2; an mk2 is returned only if nothing else matches,
    and the caller should warn (see apc_mini.is_mk2_name).
    """
    matches = [n for n in names if "apc mini" in n.lower() or "apcmini" in n.lower()]
    originals = [n for n in matches if not apc_mini.is_mk2_name(n)]
    if originals:
        return originals[0]
    return matches[0] if matches else None


def base_name(port_name: str) -> str:
    """Port name without the trailing index Windows/rtmidi adds ("APC MINI 1" -> "APC MINI")."""
    return re.sub(r"\s+\d+$", "", port_name.strip())


def still_present(port_name: str, names: list[str]) -> bool:
    """True if a device with this port's name is still listed.

    The trailing index can change when other MIDI devices are plugged in, so
    it is ignored for the comparison.
    """
    return base_name(port_name) in {base_name(n) for n in names}
