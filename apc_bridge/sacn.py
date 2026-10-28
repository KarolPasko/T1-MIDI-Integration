"""Minimal sACN (ANSI E1.31 "Streaming ACN") sender.

sACN is an open standard for sending DMX over a network. Titan lists sACN
as a trigger input source, including with a T1 (see docs/TITAN_INTEGRATION.md),
so this is how the app talks to Titan Go. Whether Titan's "Set Level"
trigger follows the value smoothly is NOT verified yet; sacn_test.py exists
to find out.

Only the standard E1.31 data packet is implemented: no discovery, no sync.
"""

from __future__ import annotations

import logging
import socket
import struct
import uuid

log = logging.getLogger(__name__)

PORT = 5568
DEFAULT_PRIORITY = 100
OPTION_STREAM_TERMINATED = 0x40

_ACN_ID = b"ASC-E1.17\x00\x00\x00"
VECTOR_ROOT_E131_DATA = 0x00000004
VECTOR_E131_DATA_PACKET = 0x00000002
VECTOR_DMP_SET_PROPERTY = 0x02


class SacnError(RuntimeError):
    pass


def multicast_address(universe: int) -> str:
    """The standard multicast group for a universe: 239.255.<hi>.<lo>."""
    _check_universe(universe)
    return f"239.255.{universe >> 8}.{universe & 0xFF}"


def _check_universe(universe: int) -> None:
    if not 1 <= universe <= 63999:
        raise SacnError(f"Universe must be 1-63999, got {universe}")


def build_packet(universe: int, data: bytes | list[int], sequence: int, cid: bytes,
                 source_name: str = "APC Bridge", priority: int = DEFAULT_PRIORITY,
                 options: int = 0) -> bytes:
    """Build one E1.31 data packet carrying up to 512 DMX slots."""
    _check_universe(universe)
    data = bytes(data)
    if len(data) > 512:
        raise SacnError("At most 512 DMX slots per universe")
    if len(cid) != 16:
        raise SacnError("CID must be 16 bytes")
    if not 0 <= priority <= 200:
        raise SacnError("Priority must be 0-200")
    slots = len(data)
    name = source_name.encode("utf-8")[:63].ljust(64, b"\x00")

    dmp = struct.pack("!HBBHHH", 0x7000 | (10 + 1 + slots), VECTOR_DMP_SET_PROPERTY,
                      0xA1, 0x0000, 0x0001, slots + 1) + b"\x00" + data
    framing = struct.pack("!HI", 0x7000 | (77 + len(dmp)), VECTOR_E131_DATA_PACKET) + name + \
        struct.pack("!BHBBH", priority, 0, sequence & 0xFF, options, universe) + dmp
    root = struct.pack("!HH", 0x0010, 0x0000) + _ACN_ID + \
        struct.pack("!HI", 0x7000 | (22 + len(framing)), VECTOR_ROOT_E131_DATA) + cid + framing
    return root


class SacnSender:
    """Sends one universe to a multicast group or a unicast address.

    Nothing is sent until send() is called; the caller owns the on/off
    decision. stop() sends the standard "stream terminated" packets so
    receivers release the source straight away instead of timing out.
    """

    def __init__(self, universe: int, unicast_ip: str | None = None,
                 source_name: str = "APC Bridge", sock_factory=None):
        _check_universe(universe)
        self.universe = universe
        self.dest = (unicast_ip or multicast_address(universe), PORT)
        self.source_name = source_name
        self.cid = uuid.uuid4().bytes
        self._seq = 0
        self.packets_sent = 0
        factory = sock_factory or (lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM,
                                                          socket.IPPROTO_UDP))
        try:
            self._sock = factory()
            if unicast_ip is None:
                self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
                self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        except OSError as exc:
            raise SacnError(f"Could not create network socket: {exc}") from exc

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFF
        return self._seq

    def send(self, data: bytes | list[int], options: int = 0) -> None:
        packet = build_packet(self.universe, data, self._next_seq(), self.cid,
                              self.source_name, options=options)
        try:
            self._sock.sendto(packet, self.dest)
        except OSError as exc:
            raise SacnError(f"sACN send to {self.dest[0]} failed: {exc}") from exc
        self.packets_sent += 1

    def stop(self, last_data: bytes | list[int] = b"") -> None:
        """Tell receivers this source has ended (E1.31 section 6.7.1), then close."""
        try:
            for _ in range(3):
                self.send(last_data or bytes(1), options=OPTION_STREAM_TERMINATED)
        except SacnError as exc:
            log.warning("Could not send sACN stream-terminated: %s", exc)
        finally:
            self.close()

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass
