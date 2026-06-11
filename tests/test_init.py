"""Test pCloud component setup."""

from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pcloud.api import PCloudApiError, PCloudAuthError
from custom_components.pcloud.const import (
    CONF_BACKUP_PATH,
    CONF_PERMANENT_DELETE,
    DEFAULT_BACKUP_PATH,
    DEFAULT_PERMANENT_DELETE,
)

from . import setup_integration


async def test_load_unload_entry(
    hass: HomeAssistant,
    pcloud_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test loading and unloading the config entry."""
    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    pcloud_client.async_ensure_folder.assert_awaited_once_with(DEFAULT_BACKUP_PATH)
    assert mock_config_entry.runtime_data is pcloud_client

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_auth_failed_starts_reauth(
    hass: HomeAssistant,
    pcloud_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that an auth error during setup triggers reauth."""
    pcloud_client.async_ensure_folder.side_effect = PCloudAuthError(
        1000, "Log in required"
    )

    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_cannot_access_backup_path(
    hass: HomeAssistant,
    pcloud_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test setup retries when the backup path can't be created."""
    pcloud_client.async_ensure_folder.side_effect = PCloudApiError(
        2003, "Access denied"
    )

    await setup_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_options_update_reloads_entry(
    hass: HomeAssistant,
    pcloud_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that updating options reloads the entry."""
    await setup_integration(hass, mock_config_entry)
    assert mock_config_entry.state is ConfigEntryState.LOADED

    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={
            CONF_BACKUP_PATH: "/new/path",
            CONF_PERMANENT_DELETE: DEFAULT_PERMANENT_DELETE,
        },
    )
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    pcloud_client.async_ensure_folder.assert_any_call("/new/path")
