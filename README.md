# piphi-network-433mhz

Beginner-friendly PiPhi integration for `rtl_433` compatible 433MHz devices.

This package uses `piphi-runtime-kit-python` to provide the main PiPhi runtime.
It is designed to work with a separate `rtl_433` helper that listens for radio
packets and forwards decoded JSON into the runtime.

The runtime can consume packets in two ways:

- direct HTTP posts to `/ingest/rtl433`
- optional MQTT subscription to the shared source topic

## What this integration does

- accepts passive `rtl_433` packets through `/ingest/rtl433`
- keeps a cache of recently seen devices for discovery
- lets users configure a discovered device by profile and identity fields
- exposes PiPhi routes for config, discovery, entities, state, events, and health
- publishes normalized telemetry back to PiPhi Core

## Supported starter profiles

The initial scaffold includes a small profile system so the integration starts
generic instead of weather-only.

- `weather_basic`
- `contact_sensor`
- `leak_sensor`
- `generic_sensor`

You can add more profiles over time as you support more `rtl_433` device
families.

## Project layout

- `src/manifest.json` PiPhi integration manifest
- `src/behaviors.json` optional behavior metadata for PiPhi UI
- `src/piphi_network_433mhz/app.py` FastAPI runtime
- `src/piphi_network_433mhz/profiles.py` device profile inference and metric mapping
- `tests/` small starter tests

## Local development

This repo expects a sibling checkout of `piphi-runtime-kit-python`.

Install dependencies with PDM:

```bash
pdm install -G dev
```

Run the runtime locally:

```bash
pdm run dev
```

The runtime starts on `http://127.0.0.1:8090`.

## Important routes

- `GET /health`
- `GET /diagnostics`
- `POST /discover`
- `POST /config`
- `POST /config/sync`
- `POST /deconfigure/{config_id}`
- `GET /entities`
- `GET /state`
- `GET /events`
- `POST /command`
- `POST /ingest/rtl433`

## Optional MQTT Source Subscription

If you enable MQTT for the bridge, this runtime can also subscribe to the
shared source topic instead of relying only on direct helper HTTP posts.

Shared packet topic:

```text
piphi/sources/rtl433/packets
```

Useful environment variables:

- `RTL433_MQTT_ENABLED=true`
- `MQTT_HOSTNAME=127.0.0.1`
- `MQTT_PORT=1883`
- `MQTT_TOPIC_ROOT=piphi/sources/rtl433`

This runtime uses the packet envelope's `packet` field and then runs the same
normalization path as the HTTP ingest route.

## Example packet ingest

```bash
curl -X POST http://127.0.0.1:8090/ingest/rtl433 \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "Nexus-TH",
    "id": 42,
    "channel": 1,
    "temperature_C": 22.8,
    "humidity": 49,
    "battery_ok": 1
  }'
```

## Notes

- This scaffold focuses on the main runtime, not the helper container itself.
- The manifest includes an example `rtl433_ingest` extension/helper so Core can
  model the sidecar relationship.
- Linux is the initial target because `rtl_433` helper containers fit that path
  best.

## Hardware access notes

The main runtime does not talk to SDR hardware directly.
That work belongs to the `rtl433_ingest` helper container.

For real RTL-SDR use on Linux, the helper usually needs:

- `rtl_433` installed inside the helper container
- host USB access to the SDR dongle
- `network_mode: "host"`
- `privileged: true`
- an explicit USB device mapping such as `/dev/bus/usb`

This scaffold now shows that device mapping directly in `src/manifest.json`.
That makes the SDR requirement visible in the manifest instead of hiding it in
setup docs alone.
