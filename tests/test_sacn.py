import struct

import pytest

from apc_bridge import sacn
from apc_bridge.sacn import SacnError, SacnSender, build_packet

CID = bytes(range(16))


def test_full_universe_packet_layout():
    data = bytes([0] * 511 + [200])
    p = build_packet(10, data, sequence=7, cid=CID, source_name="Test")
    assert len(p) == 638
    assert p[0:2] == b"\x00\x10" and p[2:4] == b"\x00\x00"
    assert p[4:16] == b"ASC-E1.17\x00\x00\x00"
    assert struct.unpack("!H", p[16:18])[0] == 0x7000 | 622
    assert struct.unpack("!I", p[18:22])[0] == 4
    assert p[22:38] == CID
    assert struct.unpack("!H", p[38:40])[0] == 0x7000 | 600
    assert struct.unpack("!I", p[40:44])[0] == 2
    assert p[44:48] == b"Test" and p[48:108] == bytes(60)
    assert p[108] == 100                       # priority
    assert p[111] == 7                         # sequence
    assert p[112] == 0                         # options
    assert struct.unpack("!H", p[113:115])[0] == 10
    assert struct.unpack("!H", p[115:117])[0] == 0x7000 | 523
    assert p[117] == 0x02 and p[118] == 0xA1
    assert struct.unpack("!HHH", p[119:125]) == (0, 1, 513)
    assert p[125] == 0                         # DMX start code
    assert p[126:] == data and p[-1] == 200


def test_validation():
    with pytest.raises(SacnError):
        build_packet(0, b"", 0, CID)
    with pytest.raises(SacnError):
        build_packet(64000, b"", 0, CID)
    with pytest.raises(SacnError):
        build_packet(1, bytes(513), 0, CID)
    with pytest.raises(SacnError):
        build_packet(1, b"", 0, b"short")


def test_multicast_address():
    assert sacn.multicast_address(1) == "239.255.0.1"
    assert sacn.multicast_address(300) == "239.255.1.44"


class FakeSock:
    def __init__(self):
        self.sent = []
        self.closed = False

    def setsockopt(self, *a):
        pass

    def sendto(self, data, addr):
        self.sent.append((data, addr))

    def close(self):
        self.closed = True


def test_sender_sequence_and_terminate():
    sock = FakeSock()
    s = SacnSender(5, sock_factory=lambda: sock)
    s.send(bytes(512))
    s.send(bytes(512))
    assert [p[111] for p, _ in sock.sent] == [1, 2]
    assert sock.sent[0][1] == ("239.255.0.5", 5568)
    s.stop()
    assert [p[112] for p, _ in sock.sent[2:]] == [0x40] * 3
    assert sock.closed


def test_unicast_destination():
    sock = FakeSock()
    s = SacnSender(5, unicast_ip="127.0.0.1", sock_factory=lambda: sock)
    s.send(b"\x01")
    assert sock.sent[0][1] == ("127.0.0.1", 5568)


def test_send_error_wrapped():
    class Bad(FakeSock):
        def sendto(self, data, addr):
            raise OSError("network unreachable")

    s = SacnSender(5, sock_factory=Bad)
    with pytest.raises(SacnError):
        s.send(b"\x00")
