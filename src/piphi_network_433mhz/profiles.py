from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ProfileDefinition:
    id: str
    name: str
    description: str
    capabilities: tuple[str, ...]
    metric_units: dict[str, str]


PROFILE_DEFINITIONS: dict[str, ProfileDefinition] = {
    "generic_sensor": ProfileDefinition(
        id="generic_sensor",
        name="Generic Sensor",
        description="Basic rtl_433 sensor profile for battery and signal-oriented devices.",
        capabilities=("battery_ok", "signal_rssi"),
        metric_units={"signal_rssi": "dBm"},
    ),
    "weather_basic": ProfileDefinition(
        id="weather_basic",
        name="Weather Sensor",
        description="Temperature, humidity, wind, rain, and battery readings.",
        capabilities=(
            "temperature_c",
            "humidity_percent",
            "battery_ok",
            "wind_speed_kph",
            "rain_total_mm",
            "signal_rssi",
        ),
        metric_units={
            "temperature_c": "C",
            "humidity_percent": "%",
            "wind_speed_kph": "km/h",
            "rain_total_mm": "mm",
            "signal_rssi": "dBm",
        },
    ),
    "contact_sensor": ProfileDefinition(
        id="contact_sensor",
        name="Contact Sensor",
        description="Open and closed contact devices such as doors or windows.",
        capabilities=("contact_open", "battery_ok", "signal_rssi"),
        metric_units={"signal_rssi": "dBm"},
    ),
    "leak_sensor": ProfileDefinition(
        id="leak_sensor",
        name="Leak Sensor",
        description="Water and moisture detection devices.",
        capabilities=("leak_detected", "battery_ok", "signal_rssi"),
        metric_units={"signal_rssi": "dBm"},
    ),
}


def list_profiles() -> list[dict[str, str]]:
    return [
        {
            "id": profile.id,
            "name": profile.name,
            "description": profile.description,
        }
        for profile in PROFILE_DEFINITIONS.values()
    ]


def normalize_profile_id(profile_id: str | None) -> str:
    if profile_id and profile_id in PROFILE_DEFINITIONS:
        return profile_id
    return "generic_sensor"


def infer_profile_id(packet: Mapping[str, Any]) -> str:
    if any(
        key in packet
        for key in ("temperature_C", "humidity", "wind_avg_km_h", "wind_speed_km_h", "rain_mm")
    ):
        return "weather_basic"
    if "contact_open" in packet:
        return "contact_sensor"
    if str(packet.get("state", "")).lower() in {"open", "closed"}:
        return "contact_sensor"
    if any(key in packet for key in ("leak", "water", "moisture")):
        return "leak_sensor"
    return "generic_sensor"


def extract_metrics(packet: Mapping[str, Any], profile_id: str) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if profile_id == "weather_basic":
        _copy_if_present(metrics, packet, "temperature_C", "temperature_c")
        _copy_if_present(metrics, packet, "humidity", "humidity_percent")
        _copy_first_present(
            metrics,
            packet,
            ("wind_avg_km_h", "wind_speed_km_h", "wind_speed_kph"),
            "wind_speed_kph",
        )
        _copy_first_present(metrics, packet, ("rain_mm", "rain_total_mm"), "rain_total_mm")
    elif profile_id == "contact_sensor":
        if "contact_open" in packet:
            metrics["contact_open"] = _as_bool(packet.get("contact_open"))
        elif "state" in packet:
            metrics["contact_open"] = str(packet.get("state", "")).lower() == "open"
    elif profile_id == "leak_sensor":
        value = None
        for key in ("leak", "water", "moisture"):
            if key in packet:
                value = packet.get(key)
                break
        if value is not None:
            metrics["leak_detected"] = _as_bool(value)

    _copy_if_present(metrics, packet, "battery_ok", "battery_ok")
    _copy_first_present(metrics, packet, ("rssi", "snr"), "signal_rssi")
    return metrics


def build_entities(device_name: str, device_key: str, profile_id: str) -> list[dict[str, Any]]:
    profile = PROFILE_DEFINITIONS[normalize_profile_id(profile_id)]
    entities: list[dict[str, Any]] = []
    for capability in profile.capabilities:
        entities.append(
            {
                "id": f"{device_key}.{capability}",
                "name": f"{device_name} {format_capability_name(capability)}",
                "capabilities": [capability],
            }
        )
    return entities


def metric_units(profile_id: str, metric_names: list[str]) -> dict[str, str]:
    profile = PROFILE_DEFINITIONS[normalize_profile_id(profile_id)]
    return {
        name: profile.metric_units[name]
        for name in metric_names
        if name in profile.metric_units
    }


def format_capability_name(capability: str) -> str:
    return capability.replace("_", " ").title()


def _copy_if_present(
    metrics: dict[str, Any],
    packet: Mapping[str, Any],
    packet_key: str,
    metric_key: str,
) -> None:
    if packet_key in packet and packet.get(packet_key) is not None:
        metrics[metric_key] = packet.get(packet_key)


def _copy_first_present(
    metrics: dict[str, Any],
    packet: Mapping[str, Any],
    packet_keys: tuple[str, ...],
    metric_key: str,
) -> None:
    for packet_key in packet_keys:
        if packet_key in packet and packet.get(packet_key) is not None:
            metrics[metric_key] = packet.get(packet_key)
            return


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "open", "wet"}
