from piphi_network_433mhz.profiles import (
    build_entities,
    extract_metrics,
    format_capability_name,
    infer_profile_id,
    metric_units,
    normalize_profile_id,
)


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


def test_infer_leak_profile_from_packet_fields() -> None:
    profile_id = infer_profile_id(
        {
            "model": "Leak-Sensor",
            "id": 9,
            "water": 1,
        }
    )

    assert profile_id == "leak_sensor"


def test_extract_weather_metrics_prefers_first_matching_fields() -> None:
    metrics = extract_metrics(
        {
            "model": "Weather",
            "id": 1,
            "temperature_C": 21.5,
            "humidity": 48,
            "wind_avg_km_h": 12.0,
            "wind_speed_km_h": 99.0,
            "rain_mm": 4.2,
            "battery_ok": 1,
            "rssi": -70,
        },
        "weather_basic",
    )

    assert metrics["temperature_c"] == 21.5
    assert metrics["humidity_percent"] == 48
    assert metrics["wind_speed_kph"] == 12.0
    assert metrics["rain_total_mm"] == 4.2
    assert metrics["signal_rssi"] == -70


def test_normalize_profile_id_falls_back_for_unknown_values() -> None:
    assert normalize_profile_id("not-a-real-profile") == "generic_sensor"
    assert normalize_profile_id(None) == "generic_sensor"


def test_build_entities_and_metric_units_follow_profile_definition() -> None:
    entities = build_entities(
        device_name="Garage Sensor",
        device_key="garage::1::na",
        profile_id="contact_sensor",
    )
    units = metric_units("weather_basic", ["temperature_c", "humidity_percent", "unknown"])

    assert entities[0]["id"] == "garage::1::na.contact_open"
    assert entities[0]["name"] == "Garage Sensor Contact Open"
    assert units == {
        "temperature_c": "C",
        "humidity_percent": "%",
    }


def test_format_capability_name_title_cases_words() -> None:
    assert format_capability_name("rain_total_mm") == "Rain Total Mm"
