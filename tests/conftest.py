"""Common fixtures for the pCloud tests."""

import time
from collections.abc import AsyncIterator, Generator
from json import dumps
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pcloud.const import (
    CONF_BACKUP_PATH,
    CONF_HOSTNAME,
    CONF_LOCATIONID,
    CONF_PERMANENT_DELETE,
    DEFAULT_BACKUP_PATH,
    DEFAULT_PERMANENT_DELETE,
    DOMAIN,
    TOKEN_EXPIRES_IN,
)

from .const import BACKUP_METADATA, MOCK_LIST_FILES

CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret"
TEST_USERID = "12345"
TEST_EMAIL = "user@example.com"
TEST_HOSTNAME = "api.pcloud.com"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations for all tests."""


@pytest.fixture(autouse=True)
async def setup_credentials(hass: HomeAssistant) -> None:
    """Set up application credentials for the pCloud OAuth app."""
    assert await async_setup_component(hass, "application_credentials", {})
    await async_import_client_credential(
        hass, DOMAIN, ClientCredential(CLIENT_ID, CLIENT_SECRET)
    )


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Override async_setup_entry."""
    with patch(
        "custom_components.pcloud.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        yield mock_setup_entry


@pytest.fixture(name="expires_at")
def mock_expires_at() -> float:
    """Return a far-future token expiry."""
    return time.time() + TOKEN_EXPIRES_IN


@pytest.fixture
def mock_config_entry(expires_at: float) -> MockConfigEntry:
    """Return the default mocked config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=TEST_EMAIL,
        unique_id=TEST_USERID,
        data={
            "auth_implementation": DOMAIN,
            CONF_HOSTNAME: TEST_HOSTNAME,
            CONF_LOCATIONID: 1,
            "token": {
                "access_token": "mock-access-token",
                "token_type": "bearer",
                "uid": int(TEST_USERID),
                "expires_in": TOKEN_EXPIRES_IN,
                "expires_at": expires_at,
            },
        },
        options={
            CONF_BACKUP_PATH: DEFAULT_BACKUP_PATH,
            CONF_PERMANENT_DELETE: DEFAULT_PERMANENT_DELETE,
        },
        entry_id="01JKXV07ASC62D620DGYNG2R8H",
    )


async def _download_mock(path: str) -> AsyncIterator[bytes]:
    """Mock the download function."""
    if path.endswith(".json"):
        yield dumps(BACKUP_METADATA).encode()
        return

    yield b"backup data"


@pytest.fixture(name="pcloud_client")
def mock_pcloud_client() -> Generator[AsyncMock]:
    """Mock the pCloud API client."""
    with (
        patch(
            "custom_components.pcloud.PCloudClient", autospec=True
        ) as mock_client_cls,
        patch("custom_components.pcloud.config_flow.PCloudClient", new=mock_client_cls),
    ):
        client = mock_client_cls.return_value
        client.async_get_user_info.return_value = {
            "userid": int(TEST_USERID),
            "email": TEST_EMAIL,
        }
        client.async_ensure_folder.return_value = None
        client.async_list_files.return_value = MOCK_LIST_FILES
        client.async_download_iter.side_effect = _download_mock
        client.async_upload_iter.return_value = None
        client.async_clean.return_value = None
        yield client
