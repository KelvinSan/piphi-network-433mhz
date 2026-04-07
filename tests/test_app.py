from fastapi.testclient import TestClient

from piphi_network_433mhz.app import app, recent_seen_devices


def test_discover_returns_recent_seen_device() -> None:
    recent_seen_devices.clear()
    client = TestClient(app)

    ingest_response = client.post(
        "/ingest/rtl433",
        json={
            "model": "Nexus-TH",
            "id": 42,
            "channel": 1,
            "temperature_C": 23.1,
            "humidity": 51,
        },
    )
    discover_response = client.post("/discover", json={"inputs": {}})

    assert ingest_response.status_code == 200
    assert discover_response.status_code == 200
    devices = discover_response.json()["devices"]
    assert len(devices) == 1
    assert devices[0]["profile"] == "weather_basic"
