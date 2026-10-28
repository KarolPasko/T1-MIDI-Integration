import http.client
import json
import re
import time

import pytest

from apc_bridge.app_core import BridgeCore
from apc_bridge.web_server import make_server, serve_in_background


@pytest.fixture
def app(tmp_path):
    core = BridgeCore(tmp_path / "config.json", simulate_midi=True)
    core.start()
    server, url = make_server(core)
    serve_in_background(server)
    port = server.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", "/")
    page = conn.getresponse().read().decode()
    token = re.search(r'const TOKEN = "([^"]+)"', page).group(1)

    def call(method, path, body=None, token_=token, host=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        headers = {"X-Bridge-Token": token_, "Content-Type": "application/json"}
        if host:
            headers["Host"] = host
        c.request(method, path, json.dumps(body) if body is not None else None, headers)
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"{}")

    yield core, call
    core.shutdown()
    server.shutdown()


def test_state_requires_token(app):
    core, call = app
    assert call("GET", "/api/state", token_="wrong")[0] == 403
    status, body = call("GET", "/api/state")
    assert status == 200 and body["state"]["output"]["enabled"] is False


def test_foreign_host_rejected(app):
    core, call = app
    assert call("GET", "/api/state", host="evil.example:80")[0] == 403


def test_output_settings_and_save_flow(app, tmp_path):
    core, call = app
    status, body = call("GET", "/api/state")
    cfg = body["state"]["config"]
    btn = next(b for b in cfg["buttons"] if b["note"] == 0)
    btn.update(mode="toggle", address=30, label="Strobe")
    assert call("POST", "/api/settings", {"config": cfg})[0] == 200
    assert call("POST", "/api/save", {})[0] == 200
    assert json.loads((tmp_path / "config.json").read_text())["buttons"][0]["label"] == "Strobe"
    assert call("POST", "/api/simulate_output", {"on": True})[0] == 200
    assert call("POST", "/api/output", {"on": True})[0] == 200
    # settings are locked while output is on
    status, body = call("POST", "/api/settings", {"config": cfg})
    assert status == 400 and "locked" in body["error"]
    assert call("POST", "/api/output", {"on": False})[0] == 200


def test_invalid_settings_reported(app):
    core, call = app
    status, body = call("POST", "/api/settings", {"config": {"universe": 0}})
    assert status == 400 and "Universe" in body["error"]


def test_learn_via_simulated_controller(app):
    core, call = app
    call("POST", "/api/connect", {"input": "SIMULATED APC MINI (no hardware)", "output": ""})
    call("POST", "/api/learn", {"on": True})
    deadline = time.time() + 5
    learned = None
    while time.time() < deadline and not learned:
        learned = call("GET", "/api/state")[1]["state"]["learned"]
        time.sleep(0.05)
    assert learned and learned[0] in ("fader", "button")


def test_unknown_action(app):
    core, call = app
    assert call("POST", "/api/format_disk", {})[0] == 404
