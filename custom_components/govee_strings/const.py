"""Constants for the Govee Strings (LAN) integration."""

from typing import Final

DOMAIN: Final = "govee_strings"

# Govee LAN API. Devices answer on LISTEN_PORT, which govee_light_local also binds,
# so this integration replaces that one rather than running beside it.
MULTICAST_ADDRESS: Final = "239.255.255.250"
SCAN_PORT: Final = 4001
LISTEN_PORT: Final = 4002
COMMAND_PORT: Final = 4003
