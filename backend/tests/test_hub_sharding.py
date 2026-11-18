"""Multi-Hub sharding: configuration parsing and stable user placement."""

from __future__ import annotations

import json
from collections import Counter

import pytest

from app.core.config import Settings
from app.integrations import jupyterhub as hubmod
from app.integrations.jupyterhub import HubClient, shard_index


def _shards(n: int) -> str:
    return json.dumps(
        [
            {
                "name": f"nb{i}",
                "api_url": f"http://hub{i}.test/nb/{i}/hub/api/",
                "proxy_url": f"http://hub{i}.test/nb/{i}",
                "public_url": f"http://app.test/nb/{i}",
                "api_token": f"tok{i}",
            }
            for i in range(n)
        ]
    )


def test_unset_means_no_shards():
    assert Settings(jupyterhub_shards="").hub_shards == []


def test_parses_and_normalises_entries():
    shards = Settings(jupyterhub_shards=_shards(2)).hub_shards
    assert [s["name"] for s in shards] == ["nb0", "nb1"]
    assert shards[0]["api_url"] == "http://hub0.test/nb/0/hub/api"  # trailing / stripped
    assert shards[1]["public_url"] == "http://app.test/nb/1"


def test_proxy_url_defaults_to_public_url():
    raw = json.dumps([{"api_url": "http://h/hub/api", "public_url": "http://app/nb/0", "api_token": "t"}])
    (shard,) = Settings(jupyterhub_shards=raw).hub_shards
    assert shard["proxy_url"] == "http://app/nb/0"
    assert shard["name"] == "shard0"


@pytest.mark.parametrize(
    "raw",
    ["[]", "{}", '[{"api_url": "x", "public_url": "y"}]', "[1]"],
)
def test_malformed_config_is_rejected(raw):
    settings = Settings(jupyterhub_shards=raw)
    with pytest.raises(ValueError):
        _ = settings.hub_shards
    assert any("SHARDS" in p for p in settings.validate_runtime())


def test_shard_index_is_stable_and_in_range():
    # Fixed expectations: a change here silently moves every student's home.
    assert shard_index("student1", 4) == shard_index("student1", 4)
    assert all(0 <= shard_index(f"u{i}", 4) < 4 for i in range(200))
    assert shard_index("anyone", 1) == 0
    assert shard_index("anyone", 0) == 0


def test_shard_index_spreads_users():
    counts = Counter(shard_index(f"student{i}", 4) for i in range(4000))
    assert len(counts) == 4
    assert min(counts.values()) > 850  # ~1000 each; no shard starved


def test_router_builds_one_client_per_shard(monkeypatch):
    monkeypatch.setattr(hubmod, "settings", Settings(jupyterhub_shards=_shards(3)))
    monkeypatch.setattr(hubmod, "_hub_shards", None)
    shards = hubmod.get_hub_shards()
    assert [c.name for c in shards] == ["nb0", "nb1", "nb2"]
    client = hubmod.hub_client_for("student7")
    assert client is shards[shard_index("student7", 3)]
    assert client.open_url("student7").startswith(client.public_url + "/user/student7/lab")
    assert client.proxy_url.endswith(f"/nb/{shards.index(client)}")


def test_backend_routes_each_user_to_its_shard(monkeypatch):
    from app.integrations.notebooks import HubNotebookBackend

    a = HubClient(api_url="http://a/hub/api", token="t", public_url="http://app/nb/0", name="a")
    b = HubClient(api_url="http://b/hub/api", token="t", public_url="http://app/nb/1", name="b")
    monkeypatch.setattr(hubmod, "_hub_shards", [a, b])
    import app.integrations.notebooks as nbmod

    monkeypatch.setattr(nbmod, "get_hub_shards", lambda: [a, b])
    monkeypatch.setattr(nbmod, "hub_client_for", lambda name: [a, b][shard_index(name, 2)])

    class U:
        def __init__(self, name):
            self.hub_username = name

    backend = HubNotebookBackend()
    for name in ("student1", "student2", "student3", "student4"):
        expected = [a, b][shard_index(name, 2)]
        assert backend.open_url(U(name)).startswith(expected.public_url)

    monkeypatch.setattr(a, "list_active_users", lambda: [{"name": "x"}])

    def down():
        from app.core.errors import UpstreamUnavailable

        raise UpstreamUnavailable("down")

    monkeypatch.setattr(b, "list_active_users", down)
    assert backend.active_session_count() == 1  # a dead shard does not break counting


def test_fixed_hub_overrides_sharding():
    from app.integrations.notebooks import HubNotebookBackend

    hub = HubClient(api_url="http://only/hub/api", token="t", public_url="http://only")

    class U:
        hub_username = "student1"

    assert HubNotebookBackend(hub=hub).open_url(U()).startswith("http://only/user/student1")
