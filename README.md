# ABB ChargerSync for Home Assistant

<img src="custom_components/abb_chargersync/brand/logo.png" alt="ABB" width="160">

Unofficial Home Assistant integration for ABB Terra AC wallboxes. It talks to the same
cloud API and remote-control relay the ABB ChargerSync app uses, so the charger only needs
to be online and bound to your ChargerSync account. Not affiliated with ABB.

## Disclaimer

The protocol was reverse engineered by decompiling the ABB ChargerSync Android app, and the
integration was written with AI assistance (Claude Fable 5.1). It was then tested manually
on a Terra AC wallbox. Use at your own risk.

ABB and the ABB logo are trademarks of ABB Ltd. The brand images in `custom_components/abb_chargersync/brand/`
are the same ones Home Assistant's brands repository already serves for ABB integrations and are used only to
identify the product this integration talks to.

## Features

- Live status (idle, plugged in, charging, paused, fault, ...)
- Power, per-phase voltage and current, session energy and duration
- Start and stop charging (switch and buttons)
- Max charging current slider (the app's load-balancing setting)
- Online, charging and plugged-in binary sensors
- Firmware and hardware version on the device page
- Session reports (PDF, CSV or Excel) e-mailed by ABB, like the app's export
- Charger settings from the app: free vending (charge without RFID), daily charging
  schedule window, and the cable lock for a stuck cable

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

## Settings

These mirror the app's device settings and need the relay connection:

| Entity | App screen | Notes |
|---|---|---|
| Free vending (switch) | Free vending | Charge without presenting an RFID card |
| Charging schedule (switch), Schedule start / end (time) | Free vending schedule | Daily window in which charging is allowed. Times are stored on the charger in UTC with whole-hour offsets, exactly like the app. Editing the times while the schedule is off keeps them for the next enable. |
| Cable lock (switch) | Cable stuck | Forces the connector lock closed or open |
| Max charging current (number) | Load balance | Current limit in amps |
| Energy plan (select), Energy price / On-, Mid-, Off-peak price (number), peak start/end (time), Currency (select) | Energy plan | Cloud-side tariff used for the cost statistics. "Flat price" uses the energy price; "Time of use" uses the three peak windows. The six window times are disabled by default. |
| Firmware (update) | Firmware update | Shows the installed version and the version ABB offers, with release notes. Installing is not possible from Home Assistant: the app only flashes firmware over a direct Bluetooth link, never through the cloud relay. |

Not implemented: firmware installation (Bluetooth only, see above), network setup, solar or
grid-meter charging modes (need extra hardware), and RFID card management.

## Session reports

The ChargerSync app cannot download statistics directly. Its export asks the ABB cloud to
generate the file and e-mail it to the account address, and this integration does the same.

- The **Request monthly report** button on the charger device requests a PDF for the current
  month, sent to your ChargerSync account e-mail.
- The `abb_chargersync.request_report` action gives full control: date range (defaults to the
  current month), format (`pdf`, `csv`, `excel`), a different recipient and a company-car-only
  filter. It returns the recipient and range it requested, so it can be used in automations,
  for example on the first day of each month for the previous month.

```yaml
action: abb_chargersync.request_report
data:
  device_id: 83b4da61fa8a53d60acc2604387572c1
  start_date: "2026-08-01"
  end_date: "2026-08-31"
  format: pdf
```

## Development

Unit tests cover the binary protocol and the cloud/relay clients against fake servers:

```
pip install -r requirements-test.txt
pytest
```

To exercise the real cloud without Home Assistant:

```
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
