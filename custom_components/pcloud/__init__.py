"""The pCloud integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import (
    ImplementationUnavailableError,
)

from .api import PCloudApiError, PCloudAuthError, PCloudClient
from .const import (
    CONF_BACKUP_PATH,
    CONF_HOSTNAME,
    DATA_BACKUP_AGENT_LISTENERS,
    DEFAULT_BACKUP_PATH,
    DOMAIN,
)

type PCloudConfigEntry = ConfigEntry[PCloudClient]


async def async_setup_entry(hass: HomeAssistant, entry: PCloudConfigEntry) -> bool:
    """Set up pCloud from a config entry."""
    try:
        implementation = (
            await config_entry_oauth2_flow.async_get_config_entry_implementation(
                hass, entry
            )
        )
    except ImplementationUnavailableError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="oauth2_implementation_unavailable",
        ) from err

    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)
    await session.async_ensure_token_valid()

    client = PCloudClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOSTNAME],
        session.token["access_token"],
    )

    backup_path = entry.options.get(CONF_BACKUP_PATH, DEFAULT_BACKUP_PATH)
    try:
        await client.async_ensure_folder(backup_path)
    except PCloudAuthError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="auth_failed"
        ) from err
    except PCloudApiError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="cannot_access_backup_path"
        ) from err

    entry.runtime_data = client

    def async_notify_backup_listeners() -> None:
        for listener in hass.data.get(DATA_BACKUP_AGENT_LISTENERS, []):
            listener()

    entry.async_on_unload(entry.async_on_state_change(async_notify_backup_listeners))
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_update_options(hass: HomeAssistant, entry: PCloudConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: PCloudConfigEntry) -> bool:
    """Unload a pCloud config entry."""
    return True
