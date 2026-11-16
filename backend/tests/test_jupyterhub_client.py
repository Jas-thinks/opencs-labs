"""JupyterHub client parsing tests.

These pin the *shape* of the Hub REST responses the backend relies on. The
bug that motivated them: JupyterHub 4 returns ``server`` as a URL string and
the readiness detail in ``servers[""]``; reading ``server`` as an object raised
AttributeError inside a launch request.
"""

from __future__ import annotations

import pytest

from app.integrations.jupyterhub import HubClient


@pytest.fixture()
def client(monkeypatch):
    hub = HubClient(api_url="http://hub.test/hub/api", token="t", public_url="http://app.test")
    return hub


def _stub_user(monkeypatch, hub: HubClient, payload: dict) -> None:
    monkeypatch.setattr(hub, "get_user", lambda username: payload)


def test_reads_ready_state_from_servers_map(client, monkeypatch):
    _stub_user(
        monkeypatch,
        client,
        {
            # JupyterHub 4.1.5 shape: "server" is a URL string.
            "server": "/user/student1/",
            "servers": {
                "": {
                    "ready": True,
                    "pending": None,
                    "url": "/user/student1/",
                    "started": "2026-11-16T17:07:36.287686Z",
                }
            },
        },
    )
    state = client.get_server_state("student1")
    assert state.running is True
    assert state.ready is True
    assert state.url == "/user/student1/"
    assert state.started_at == "2026-11-16T17:07:36.287686Z"


def test_pending_server_is_running_but_not_ready(client, monkeypatch):
    _stub_user(
        monkeypatch,
        client,
        {"servers": {"": {"ready": False, "pending": "spawn", "url": None}}},
    )
    state = client.get_server_state("student1")
    assert state.running is True
    assert state.ready is False
    assert state.pending == "spawn"


def test_string_server_without_detail_is_not_ready(client, monkeypatch):
    """A bare URL must not raise, and must not be reported as ready."""
    _stub_user(monkeypatch, client, {"server": "/user/student1/"})
    state = client.get_server_state("student1")
    assert state.running is True
    assert state.ready is False
    assert state.url == "/user/student1/"


def test_no_server_is_stopped(client, monkeypatch):
    _stub_user(monkeypatch, client, {"server": None, "servers": {}})
    state = client.get_server_state("student1")
    assert state.running is False
    assert state.ready is False


def test_missing_user_is_stopped(client, monkeypatch):
    monkeypatch.setattr(client, "get_user", lambda username: None)
    state = client.get_server_state("nobody")
    assert state.running is False


def test_as_dict_reports_a_status(client, monkeypatch):
    _stub_user(monkeypatch, client, {"servers": {"": {"ready": True, "url": "/u/x/"}}})
    payload = client.get_server_state("x").as_dict()
    assert payload["status"] == "running"
    assert payload["ready"] is True
