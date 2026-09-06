"""Constants for the ABB ChargerSync integration."""

DOMAIN = "abb_chargersync"
PLATFORMS = ["sensor", "binary_sensor", "number", "switch", "button", "time"]

CONF_SCAN_INTERVAL = "scan_interval"
CONF_USE_RELAY = "use_relay"

DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 10
MANUFACTURER = "ABB"

SERVICE_REQUEST_REPORT = "request_report"
ATTR_START_DATE = "start_date"
ATTR_END_DATE = "end_date"
ATTR_FORMAT = "format"
ATTR_EMAIL = "email"
ATTR_COMPANY_ONLY = "company_only"
REPORT_FORMATS = ["pdf", "csv", "excel"]
