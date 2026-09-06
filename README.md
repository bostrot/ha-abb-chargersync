# ABB ChargerSync for Home Assistant

Unofficial Home Assistant integration for ABB Terra AC wallboxes. It talks to the same
cloud API and remote-control relay the ABB ChargerSync app uses, so the charger only needs
to be online and bound to your ChargerSync account. Not affiliated with ABB.

## Features

- Live status (idle, plugged in, charging, paused, fault, ...)
- Power, per-phase voltage and current, session energy and duration
- Start and stop charging (switch and buttons)
- Max charging current slider (the app's load-balancing setting)
- Online, charging and plugged-in binary sensors
- Firmware and hardware version on the device page

## Installation

### HACS

1. HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/bostrot/ha-abb-chargersync` with category *Integration*
3. Install and restart Home Assistant

### Manual

Copy `custom_components/abb_chargersync` into your `config/custom_components/` folder and
restart Home Assistant.

## Setup

Settings → Devices & services → Add integration → **ABB ChargerSync (Terra AC)**, then sign in
with your ChargerSync e-mail and password. Every charger bound to the account is added.

Options: polling interval (default 30 s, minimum 10 s) and whether to use the relay for live
data. Without the relay only cloud metadata and cloud start/stop are available.

## Testing outside Home Assistant

```
pip install aiohttp cryptography
python3 tools/probe.py you@example.com 'password'
```

The probe logs in, lists chargers, connects to the relay and prints decoded status frames.

## Protocol

See [docs/protocol.md](docs/protocol.md) for the REST endpoints, the relay WebSocket and the
binary frame format.

## Notes

- Unofficial API. ABB can change or shut it down at any time.
- The app allows one relay connection per charger. Using the app while Home Assistant is
  polling may interrupt either side.

## License

MIT
