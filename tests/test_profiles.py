from piphi_network_433mhz.profiles import extract_metrics, infer_profile_id


def test_infer_weather_profile_from_packet_fields() -> None:
    profile_id = infer_profile_id(
        {
            "model": "Acurite-Tower",
            "id": 42,
            "temperature_C": 21.5,
            "humidity": 48,
        }
    )

    assert profile_id == "weather_basic"


def test_extract_contact_metrics() -> None:
    metrics = extract_metrics(
        {
            "model": "Generic-Contact",
            "id": 7,
            "state": "open",
            "battery_ok": 1,
        },
        "contact_sensor",
    )

    assert metrics["contact_open"] is True
    assert metrics["battery_ok"] == 1
