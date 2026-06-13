"""Constants for the pCloud integration."""

import logging
from collections.abc import Callable

from homeassistant.util.hass_dict import HassKey

DOMAIN = "pcloud"

LOGGER = logging.getLogger(__package__)

# OAuth2
OAUTH2_AUTHORIZE = "https://my.pcloud.com/oauth2/authorize"
OAUTH2_TOKEN = "https://api.pcloud.com/oauth2_token"

# pCloud's oauth2_token response has no expires_in/refresh_token - tokens are
# effectively non-expiring unless the user revokes app access. A long
# expires_in is injected so HA's OAuth2 flow validation passes, and refresh
# is a no-op that just renews this timestamp.
TOKEN_EXPIRES_IN = 10 * 365 * 24 * 60 * 60  # 10 years

# Extra data captured from the OAuth redirect (not present in the
# oauth2_token response) and persisted alongside the token.
CONF_HOSTNAME = "hostname"
CONF_LOCATIONID = "locationid"
DEFAULT_API_HOST = "api.pcloud.com"

# Config entry options
CONF_BACKUP_PATH = "backup_path"
CONF_PERMANENT_DELETE = "permanent_delete"

DEFAULT_BACKUP_PATH = "/backups/homeassistant"
DEFAULT_PERMANENT_DELETE = False

DATA_BACKUP_AGENT_LISTENERS: HassKey[list[Callable[[], None]]] = HassKey(
    f"{DOMAIN}.backup_agent_listeners"
)
