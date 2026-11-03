import asyncio

from fastapi.testclient import TestClient

from common import is_public_url
from main import app

# without 'with', lifespan does not run, so no DB connection is made (pure unit test)
client = TestClient(app)
KEY = {"X-API-Key": "test-key"}
GOOD = {"name": "x", "url": "https://example.com"}


def test_ssrf_blocks_private_and_loopback():
    for url in ["http://127.0.0.1", "http://10.0.0.5", "http://169.254.169.254",
                "http://192.168.1.1:8080", "http://localhost", "http://[::1]"]:
        assert asyncio.run(is_public_url(url)) is False, url


def test_public_ip_allowed():
    assert asyncio.run(is_public_url("http://8.8.8.8")) is True


def test_create_requires_api_key():
    assert client.post("/api/monitors", json=GOOD).status_code == 401
    assert client.post("/api/monitors", json=GOOD, headers={"X-API-Key": "bad"}).status_code == 401


def test_delete_requires_api_key():
    assert client.delete("/api/monitors/1").status_code == 401


def test_create_rejects_private_target():
    r = client.post("/api/monitors", json={"name": "x", "url": "http://127.0.0.1:5432"}, headers=KEY)
    assert r.status_code == 400


def test_validation():
    assert client.post("/api/monitors", json={"name": "x", "url": "nope"}, headers=KEY).status_code == 422
    bad = {**GOOD, "interval_s": 1}
    assert client.post("/api/monitors", json=bad, headers=KEY).status_code == 422


def test_dashboard_served():
    r = client.get("/")
    assert r.status_code == 200 and "PulseWatch" in r.text
