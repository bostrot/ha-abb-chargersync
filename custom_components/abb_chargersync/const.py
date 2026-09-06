"""Constants for the ABB ChargerSync integration."""

DOMAIN = "abb_chargersync"
PLATFORMS = ["sensor", "binary_sensor", "number", "switch", "button"]

CONF_SCAN_INTERVAL = "scan_interval"
CONF_USE_RELAY = "use_relay"

DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 10
MANUFACTURER = "ABB"
