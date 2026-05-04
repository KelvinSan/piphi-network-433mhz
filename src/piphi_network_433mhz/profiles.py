from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping


@dataclass(frozen=True)
class ProfileDefinition:
    id: str
    name: str
    description: str
    capabilities: tuple[str, ...]
    metric_units: dict[str, str]


PROFILE_DEFINITIONS: dict[str, ProfileDefinition] = {
    "auto": ProfileDefinition(
        id="auto",
        name="Auto-detect",
        description="Let PiPhi infer the useful readings from each decoded radio packet.",
        capabilities=(),
        metric_units={},
    ),
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

PACKET_IDENTITY_KEYS = {
    "brand",
    "channel",
    "device",
    "device_id",
    "family",
    "id",
    "mic",
    "model",
    "mod",
    "protocol",
    "station_id",
    "subtype",
    "time",
    "type",
}

CANONICAL_METRIC_KEYS = {
    "temperature_C": "temperature_c",
    "temperature_F": "temperature_f",
    "humidity": "humidity_percent",
    "humidity_percent": "humidity_percent",
    "wind_avg_km_h": "wind_speed_kph",
    "wind_speed_km_h": "wind_speed_kph",
    "wind_speed_kph": "wind_speed_kph",
    "rain_mm": "rain_total_mm",
    "rain_total_mm": "rain_total_mm",
    "rssi": "signal_rssi",
    "snr": "signal_rssi",
    "pressure_hPa": "pressure_hpa",
    "pressure_Pa": "pressure_pa",
    "battery_mV": "battery_mv",
    "battery_ok": "battery_ok",
}

KNOWN_METRIC_UNITS = {
    "temperature_c": "C",
    "temperature_f": "F",
    "humidity_percent": "%",
    "wind_speed_kph": "km/h",
    "rain_total_mm": "mm",
    "rain_rate_mm_h": "mm/h",
    "signal_rssi": "dBm",
    "pressure_hpa": "hPa",
    "pressure_pa": "Pa",
    "battery_mv": "mV",
    "lux": "lx",
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
    return "auto"


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


def extract_metrics(packet: Mapping[str, Any], profile_id: str = "auto") -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    consumed_keys: set[str] = set()

    _copy_if_present(metrics, packet, "temperature_C", "temperature_c", consumed_keys)
    _copy_if_present(metrics, packet, "temperature_F", "temperature_f", consumed_keys)
    _copy_if_present(metrics, packet, "humidity", "humidity_percent", consumed_keys)
    _copy_first_present(
        metrics,
        packet,
        ("wind_avg_km_h", "wind_speed_km_h", "wind_speed_kph"),
        "wind_speed_kph",
        consumed_keys,
    )
    _copy_first_present(metrics, packet, ("rain_mm", "rain_total_mm"), "rain_total_mm", consumed_keys)

    if "contact_open" in packet:
        metrics["contact_open"] = _as_bool(packet.get("contact_open"))
        consumed_keys.add("contact_open")
    elif "state" in packet and str(packet.get("state", "")).lower() in {"open", "closed"}:
        metrics["contact_open"] = str(packet.get("state", "")).lower() == "open"
        consumed_keys.add("state")

    for leak_key in ("leak", "water", "moisture"):
        if leak_key in packet:
            metrics["leak_detected"] = _as_bool(packet.get(leak_key))
            consumed_keys.add(leak_key)
            break

    _copy_if_present(metrics, packet, "battery_ok", "battery_ok", consumed_keys)
    _copy_first_present(metrics, packet, ("rssi", "snr"), "signal_rssi", consumed_keys)

    for packet_key, value in packet.items():
        if packet_key in consumed_keys:
            continue
        metric_key = normalize_metric_key(packet_key)
        if not metric_key or metric_key in metrics:
            continue
        metric_value = _safe_metric_value(value)
        if metric_value is not None:
            metrics[metric_key] = metric_value

    return metrics


def build_entities(
    device_name: str,
    device_key: str,
    profile_id: str,
    metric_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    profile = PROFILE_DEFINITIONS[normalize_profile_id(profile_id)]
    capability_names = list(profile.capabilities)
    for metric_name in metric_names or []:
        if metric_name not in capability_names:
            capability_names.append(metric_name)

    entities: list[dict[str, Any]] = []
    for capability in capability_names:
        entities.append(
            {
                "id": f"{device_key}.{capability}",
                "name": f"{device_name} {format_capability_name(capability)}",
                "capabilities": [capability],
            }
        )
    return entities


def metric_units(profile_id: str, metric_names: list[str]) -> dict[str, str]:
    return {
        name: KNOWN_METRIC_UNITS[name]
        for name in metric_names
        if name in KNOWN_METRIC_UNITS
    }


def format_capability_name(capability: str) -> str:
    return capability.replace("_", " ").title()


def _copy_if_present(
    metrics: dict[str, Any],
    packet: Mapping[str, Any],
    packet_key: str,
    metric_key: str,
    consumed_keys: set[str],
) -> None:
    if packet_key in packet and packet.get(packet_key) is not None:
        metrics[metric_key] = packet.get(packet_key)
        consumed_keys.add(packet_key)


def _copy_first_present(
    metrics: dict[str, Any],
    packet: Mapping[str, Any],
    packet_keys: tuple[str, ...],
    metric_key: str,
    consumed_keys: set[str],
) -> None:
    for packet_key in packet_keys:
        if packet_key in packet and packet.get(packet_key) is not None:
            metrics[metric_key] = packet.get(packet_key)
            consumed_keys.add(packet_key)
            return


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "open", "wet"}


def normalize_metric_key(packet_key: str) -> str | None:
    if packet_key in CANONICAL_METRIC_KEYS:
        return CANONICAL_METRIC_KEYS[packet_key]

    normalized = re.sub(r"[^0-9a-zA-Z]+", "_", packet_key).strip("_").lower()
    if not normalized or normalized in PACKET_IDENTITY_KEYS:
        return None
    if normalized.startswith(("unknown", "debug", "flags")):
        return None

    return normalized


def _safe_metric_value(value: Any) -> bool | int | float | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return None
