from __future__ import annotations

from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request
from pydantic import BaseModel, ConfigDict

from piphi_runtime_kit_python import (
    IntegrationCommandRequest,
    IntegrationDiscoveryRequest,
    IntegrationDiscoveryResponse,
    IntegrationEventListResponse,
    RuntimeConfig,
    RuntimeConfigApplyResponse,
    RuntimeConfigRemoveResponse,
    RuntimeConfigSnapshot,
    RuntimeConfigSyncResponse,
    RuntimeDiagnosticsResponse,
    RuntimeHealthResponse,
    build_config_apply_response,
    build_discovery_response,
    build_event_list_response,
    build_local_event_record,
    create_runtime_starter,
    runtime_lifespan,
    schedule_telemetry_delivery,
    validate_typed_configs,
)
from piphi_runtime_kit_python.fastapi import sync_runtime_auth_from_fastapi_payload

from .profiles import (
    PROFILE_DEFINITIONS,
    build_entities,
    extract_metrics,
    format_capability_name,
    infer_profile_id,
    list_profiles,
    metric_units,
    normalize_profile_id,
)

INTEGRATION_ID = "piphi-network-433mhz"
INTEGRATION_NAME = "PiPhi Network 433MHz Devices"
INTEGRATION_VERSION = "0.1.0"
MAX_DISCOVERY_CACHE = 200

starter = create_runtime_starter(
    integration_id=INTEGRATION_ID,
    integration_name=INTEGRATION_NAME,
    version=INTEGRATION_VERSION,
)
runtime = starter.runtime
registry = starter.registry
telemetry = starter.telemetry_client
config_sync = starter.config_sync
recent_seen_devices: OrderedDict[str, dict[str, Any]] = OrderedDict()


class Rtl433DeviceConfig(RuntimeConfig):
    profile: str
    model: str
    station_id: str
    channel: str | None = None
    alias: str | None = None


class Rtl433Packet(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str | None = None
    id: str | int | None = None
    channel: str | int | None = None


def build_device_key(model: str | None, station_id: Any, channel: Any = None) -> str:
    model_part = str(model or "unknown")
    station_part = str(station_id or "unknown")
    channel_part = str(channel) if channel not in (None, "") else "na"
    return f"{model_part}::{station_part}::{channel_part}"


def extract_station_id(packet: dict[str, Any]) -> str:
    for key in ("id", "device_id", "device", "sid", "unit"):
        value = packet.get(key)
        if value not in (None, ""):
            return str(value)
    return "unknown"


def extract_channel(packet: dict[str, Any]) -> str | None:
    for key in ("channel", "subtype"):
        value = packet.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def make_registry_entry(config: Rtl433DeviceConfig) -> dict[str, Any]:
    profile_id = normalize_profile_id(config.profile)
    device_key = build_device_key(config.model, config.station_id, config.channel)
    return {
        "config_id": config.config_id or config.id,
        "device_id": device_key,
        "container_id": config.container_id,
        "integration_id": config.integration_id or INTEGRATION_ID,
        "profile": profile_id,
        "model": config.model,
        "station_id": config.station_id,
        "channel": config.channel,
        "alias": config.alias,
    }


def append_runtime_event(
    *,
    event_type: str,
    device: dict[str, Any],
    payload: dict[str, Any] | None = None,
    severity: str = "info",
) -> None:
    registry.append_event(
        build_local_event_record(
            event_type=event_type,
            device=device,
            payload=payload,
            source=INTEGRATION_ID,
            severity=severity,
        )
    )


async def apply_config(config: Rtl433DeviceConfig) -> None:
    entry = make_registry_entry(config)
    registry.set(config.id, entry)
    registry.update_state(
        config.id,
        {
            "profile": entry["profile"],
            "model": entry["model"],
            "station_id": entry["station_id"],
            "channel": entry["channel"],
            "alias": entry["alias"],
            "last_packet_at": None,
        },
    )
    append_runtime_event(
        event_type="rtl433.config.applied",
        device=entry,
        payload={
            "profile": entry["profile"],
            "model": entry["model"],
            "station_id": entry["station_id"],
            "channel": entry["channel"],
        },
    )


async def remove_config(config_id: str) -> bool:
    removed = registry.remove(config_id)
    if removed is None:
        return False
    append_runtime_event(
        event_type="rtl433.config.removed",
        device=removed,
        payload={"config_id": config_id},
    )
    return True


def remember_discovered_device(packet: dict[str, Any]) -> dict[str, Any]:
    profile_id = infer_profile_id(packet)
    model = str(packet.get("model") or "Unknown rtl_433 Device")
    station_id = extract_station_id(packet)
    channel = extract_channel(packet)
    device_key = build_device_key(model, station_id, channel)
    metrics = extract_metrics(packet, profile_id)
    record = {
        "id": device_key,
        "device_id": device_key,
        "profile": profile_id,
        "profile_name": PROFILE_DEFINITIONS[profile_id].name,
        "model": model,
        "station_id": station_id,
        "channel": channel,
        "alias": model,
        "last_seen_at": now_iso(),
        "preview_metrics": metrics,
    }
    recent_seen_devices[device_key] = record
    recent_seen_devices.move_to_end(device_key)
    while len(recent_seen_devices) > MAX_DISCOVERY_CACHE:
        recent_seen_devices.popitem(last=False)
    return record


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with runtime_lifespan(runtime):
        yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health() -> RuntimeHealthResponse:
    return starter.health_response(
        metadata={
            "active_configs": len(registry.ids()),
            "recent_discovery_count": len(recent_seen_devices),
            "supported_profile_count": len(PROFILE_DEFINITIONS),
        }
    )


@app.get("/diagnostics")
async def diagnostics() -> RuntimeDiagnosticsResponse:
    return starter.diagnostics_response(
        diagnostics={
            "active_config_ids": registry.ids(),
            "recent_event_count": len(registry.recent_events),
            "recent_discovery_count": len(recent_seen_devices),
            "supported_profiles": list_profiles(),
        }
    )


@app.get("/ui-config")
async def ui_config() -> dict[str, Any]:
    return {
        "schema": {
            "title": "433MHz Device Setup",
            "description": "Choose a discovered rtl_433 device and save the identity fields PiPhi should track.",
            "type": "object",
            "required": ["profile", "model", "station_id"],
            "properties": {
                "profile": {
                    "type": "string",
                    "title": "Device Profile",
                    "enum": list(PROFILE_DEFINITIONS.keys()),
                    "enumNames": [profile.name for profile in PROFILE_DEFINITIONS.values()],
                },
                "model": {
                    "type": "string",
                    "title": "rtl_433 Model",
                },
                "station_id": {
                    "type": "string",
                    "title": "Station or Sensor ID",
                },
                "channel": {
                    "type": "string",
                    "title": "Channel",
                },
                "alias": {
                    "type": "string",
                    "title": "Display Name",
                },
            },
        },
        "uiSchema": {
            "profile": {
                "help": "Pick the profile that best matches the discovered device.",
            },
            "model": {
                "placeholder": "Acurite-Tower or Nexus-TH",
            },
            "station_id": {
                "placeholder": "42",
            },
            "channel": {
                "placeholder": "1 or A",
            },
            "alias": {
                "placeholder": "Backyard Weather Sensor",
            },
        },
        "profiles": list_profiles(),
    }


@app.post("/discover", response_model=IntegrationDiscoveryResponse)
async def discover(
    payload: IntegrationDiscoveryRequest | None = None,
) -> IntegrationDiscoveryResponse:
    requested_profile = None
    if payload and payload.inputs:
        requested_profile = payload.inputs.get("profile")

    devices = list(recent_seen_devices.values())
    if requested_profile:
        devices = [device for device in devices if device.get("profile") == requested_profile]
    return build_discovery_response(devices)


@app.post("/config")
async def config(
    payload: Rtl433DeviceConfig,
    request: Request,
) -> RuntimeConfigApplyResponse:
    sync_runtime_auth_from_fastapi_payload(runtime, request, payload)
    await apply_config(payload)
    return build_config_apply_response(
        config_id=payload.config_id or payload.id,
        container_id=payload.container_id,
        metadata={
            "profile": normalize_profile_id(payload.profile),
            "device_key": build_device_key(payload.model, payload.station_id, payload.channel),
        },
    )


@app.post("/config/sync")
async def sync_config(
    snapshot: RuntimeConfigSnapshot,
    request: Request,
) -> RuntimeConfigSyncResponse:
    runtime.auth.sync_from_headers(request.headers, payload_container_id=snapshot.container_id)
    typed_configs = validate_typed_configs(snapshot.configs, Rtl433DeviceConfig)
    return await config_sync.apply_snapshot(
        snapshot=snapshot.model_copy(update={"configs": typed_configs}),
        active_config_ids=registry.ids(),
        apply_config=apply_config,
        remove_config=remove_config,
        get_active_config_ids=registry.ids,
    )


@app.post("/deconfigure/{config_id}")
async def deconfigure(config_id: str) -> RuntimeConfigRemoveResponse:
    removed = await remove_config(config_id)
    return RuntimeConfigRemoveResponse(
        config_id=config_id,
        removed=removed,
        metadata={"remaining_configs": registry.ids()},
    )


@app.get("/entities")
async def entities() -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for entry in registry.entries.values():
        device_name = entry.get("alias") or entry["device_id"]
        payload.extend(
            build_entities(
                device_name=device_name,
                device_key=str(entry["device_id"]),
                profile_id=str(entry.get("profile") or "generic_sensor"),
            )
        )
    return payload


@app.get("/state")
async def state() -> dict[str, Any]:
    return {
        "summary": {
            "active_config_count": len(registry.ids()),
            "recent_event_count": len(registry.recent_events),
            "recent_discovery_count": len(recent_seen_devices),
        },
        "entries": registry.entries,
        "state_snapshots": registry.state_snapshots,
        "recent_seen_devices": list(recent_seen_devices.values())[-25:],
    }


@app.get("/events", response_model=IntegrationEventListResponse)
async def list_events(limit: int = 50) -> IntegrationEventListResponse:
    return build_event_list_response(registry.recent_events[-limit:])


@app.post("/command")
async def command(payload: IntegrationCommandRequest) -> dict[str, Any]:
    if payload.command == "clear_discovery_cache":
        count = len(recent_seen_devices)
        recent_seen_devices.clear()
        return {
            "status": "ok",
            "command": payload.command,
            "result": {"cleared_discovery_records": count},
        }

    return {
        "status": "unsupported",
        "command": payload.command,
        "result": {"message": f"Unsupported command: {payload.command}"},
    }


@app.post("/ingest/rtl433")
async def ingest_rtl433(packet: Rtl433Packet, request: Request) -> dict[str, Any]:
    runtime.auth.sync_from_headers(request.headers)
    payload = packet.model_dump(exclude_none=True)
    discovered = remember_discovered_device(payload)

    matched_configs = 0
    for config_id, entry in registry.entries.items():
        if str(entry.get("device_id")) != discovered["device_id"]:
            continue

        matched_configs += 1
        profile_id = str(entry.get("profile") or "generic_sensor")
        metrics = extract_metrics(payload, profile_id)
        registry.update_state(
            config_id,
            {
                "last_packet_at": now_iso(),
                "model": discovered["model"],
                "station_id": discovered["station_id"],
                "channel": discovered["channel"],
                "profile": profile_id,
                "last_metrics": metrics,
            },
        )

        if metrics:
            schedule_telemetry_delivery(
                process_state=runtime.process_state,
                telemetry_client=telemetry,
                auth_context=runtime.auth,
                device_id=str(entry["device_id"]),
                container_id=entry.get("container_id"),
                metrics=metrics,
                units=metric_units(profile_id, list(metrics.keys())),
            )

        append_runtime_event(
            event_type="rtl433.packet.matched",
            device=entry,
            payload={
                "profile": profile_id,
                "metrics": metrics,
                "model": discovered["model"],
                "station_id": discovered["station_id"],
            },
        )

    if matched_configs == 0:
        append_runtime_event(
            event_type="rtl433.packet.discovered",
            device={
                "config_id": discovered["id"],
                "device_id": discovered["device_id"],
                "integration_id": INTEGRATION_ID,
                "container_id": runtime.auth.container_id or None,
            },
            payload={
                "profile": discovered["profile"],
                "model": discovered["model"],
                "station_id": discovered["station_id"],
                "channel": discovered["channel"],
            },
        )

    return {
        "status": "ok",
        "device_id": discovered["device_id"],
        "profile": discovered["profile"],
        "matched_configs": matched_configs,
        "metric_names": [
            format_capability_name(metric_name)
            for metric_name in extract_metrics(payload, discovered["profile"]).keys()
        ],
    }
