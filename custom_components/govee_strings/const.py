"""Constants for the Govee Strings (LAN) integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "govee_strings"

# Govee LAN API. Devices answer on LISTEN_PORT, which govee_light_local also binds,
# so this integration replaces that one rather than running beside it.
MULTICAST_ADDRESS: Final = "239.255.255.250"
SCAN_PORT: Final = 4001
LISTEN_PORT: Final = 4002
COMMAND_PORT: Final = 4003

CONF_DEVICE_ID: Final = "device_id"
CONF_SKU: Final = "sku"
CONF_IP: Final = "ip"
CONF_BULB_COUNT: Final = "bulb_count"
CONF_ENFORCE_INTERVAL: Final = "enforce_interval"

DEFAULT_ENFORCE_INTERVAL_MIN: Final = 5
MAX_BULBS: Final = 56  # a color frame has room for a 7-byte mask

STATUS_INTERVAL: Final = timedelta(seconds=30)
DISCOVERY_INTERVAL: Final = timedelta(minutes=5)
STATUS_MISSES_UNAVAILABLE: Final = 3
# Pacing between frames to one device. 250 ms is what every hardware test used.
FRAME_INTERVAL_S: Final = 0.25
SCAN_ATTEMPTS: Final = 3
SCAN_WINDOW_S: Final = 3.0

# Models that take a color temperature (from govee-local-api's table, and observed
# devStatus colorTemInKelvin). The H7025 is RGB only.
COLOR_TEMP_SKUS: Final = frozenset({"H7021", "H7038", "H7039"})
MIN_KELVIN: Final = 2000
MAX_KELVIN: Final = 9000

SIGNAL_PATTERNS_UPDATED: Final = f"{DOMAIN}_patterns_updated"
STORAGE_VERSION: Final = 1
STORAGE_KEY_STATE: Final = f"{DOMAIN}.state"
STORAGE_KEY_PATTERNS: Final = f"{DOMAIN}.patterns"
