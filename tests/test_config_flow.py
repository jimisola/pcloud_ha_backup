"""Test the pCloud config flow."""

from unittest.mock import AsyncMock, MagicMock

from aiohttp.test_utils import make_mocked_request

from custom_components.pcloud.api import PCloudApiError
from custom_components.pcloud.const import (
    CONF_BACKUP_PATH,
    CONF_HOSTNAME,
    CONF_LOCATIONID,
    CONF_PERMANENT_DELETE,
    DEFAULT_BACKUP_PATH,
    DEFAULT_PERMANENT_DELETE,
    DOMAIN,
    OAUTH2_TOKEN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from .conftest import TEST_EMAIL, TEST_HOSTNAME, TEST_USERID


async def _start_oauth_flow(
    hass: HomeAssistant,
    current_request: MagicMock,
    aioclient_mock: AiohttpClientMocker,
    *,
    context: dict,
    hostname: str = TEST_HOSTNAME,
    locationid: int = 1,
) -> dict:
    """Run the external OAuth steps and return the flow result before entry creation."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context=context)

    assert result["type"] is FlowResultType.EXTERNAL_STEP
    assert result["url"].startswith("https://my.pcloud.com/oauth2/authorize")

    return await _complete_oauth_flow(
        hass, result, current_request, aioclient_mock, hostname=hostname, locationid=locationid
    )


async def _complete_oauth_flow(
    hass: HomeAssistant,
    result: dict,
    current_request: MagicMock,
    aioclient_mock: AiohttpClientMocker,
    *,
    hostname: str = TEST_HOSTNAME,
    locationid: int = 1,
) -> dict:
    """Complete an in-progress external OAuth step and return the flow result."""
    # Simulate the OAuth redirect callback request, which carries pCloud's
    # `hostname`/`locationid` query params that async_step_auth captures.
    current_request.get.return_value = make_mocked_request(
        "GET",
        f"/auth/external/callback?code=abcd&hostname={hostname}&locationid={locationid}",
        headers=current_request.get.return_value.headers,
    )

    aioclient_mock.post(
        OAUTH2_TOKEN,
        json={
            "access_token": "mock-access-token",
            "token_type": "bearer",
            "uid": int(TEST_USERID),
        },
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "state": {
                "flow_id": result["flow_id"],
                "redirect_uri": "https://example.com/auth/external/callback",
            },
            "code": "abcd",
        },
    )
    assert result["type"] is FlowResultType.EXTERNAL_STEP_DONE

    return await hass.config_entries.flow.async_configure(result["flow_id"])


async def test_full_flow(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    current_request_with_host: None,
    current_request: MagicMock,
    pcloud_client: AsyncMock,
) -> None:
    """Test the full OAuth2 + backup-path config flow."""
    result = await _start_oauth_flow(
        hass,
        current_request,
        aioclient_mock,
        context={"source": SOURCE_USER},
        hostname="eapi.pcloud.com",
        locationid=2,
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "backup_path"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BACKUP_PATH: "/custom/backups"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == TEST_EMAIL
    assert result["data"][CONF_HOSTNAME] == "eapi.pcloud.com"
    assert result["data"][CONF_LOCATIONID] == 2
    assert result["data"]["token"]["access_token"] == "mock-access-token"
    assert result["options"] == {
        CONF_BACKUP_PATH: "/custom/backups",
        CONF_PERMANENT_DELETE: DEFAULT_PERMANENT_DELETE,
    }

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.unique_id == TEST_USERID


async def test_full_flow_default_backup_path(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    current_request_with_host: None,
    current_request: MagicMock,
    pcloud_client: AsyncMock,
) -> None:
    """Test accepting the default backup path."""
    result = await _start_oauth_flow(
        hass,
        current_request,
        aioclient_mock,
        context={"source": SOURCE_USER},
    )

    assert result["step_id"] == "backup_path"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BACKUP_PATH: DEFAULT_BACKUP_PATH}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_BACKUP_PATH] == DEFAULT_BACKUP_PATH


async def test_cannot_connect(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    current_request_with_host: None,
    current_request: MagicMock,
    pcloud_client: AsyncMock,
) -> None:
    """Test aborting when userinfo can't be fetched."""
    pcloud_client.async_get_user_info.side_effect = PCloudApiError(2000, "boom")

    result = await _start_oauth_flow(
        hass,
        current_request,
        aioclient_mock,
        context={"source": SOURCE_USER},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_already_configured(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    current_request_with_host: None,
    current_request: MagicMock,
    pcloud_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test aborting when the account is already configured."""
    mock_config_entry.add_to_hass(hass)

    result = await _start_oauth_flow(
        hass,
        current_request,
        aioclient_mock,
        context={"source": SOURCE_USER},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    current_request_with_host: None,
    current_request: MagicMock,
    pcloud_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the reauth flow updates the existing entry."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.EXTERNAL_STEP

    result = await _complete_oauth_flow(hass, result, current_request, aioclient_mock)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data["token"]["access_token"] == "mock-access-token"


async def test_reauth_wrong_account(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    current_request_with_host: None,
    current_request: MagicMock,
    pcloud_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test reauth aborts if the account doesn't match the existing entry."""
    mock_config_entry.add_to_hass(hass)
    pcloud_client.async_get_user_info.return_value = {
        "userid": int(TEST_USERID) + 1,
        "email": "other@example.com",
    }

    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.EXTERNAL_STEP

    result = await _complete_oauth_flow(hass, result, current_request, aioclient_mock)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"


async def test_options_flow(
    hass: HomeAssistant,
    pcloud_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the options flow updates the backup path and delete mode."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_BACKUP_PATH: "new/path", CONF_PERMANENT_DELETE: True},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        CONF_BACKUP_PATH: "/new/path",
        CONF_PERMANENT_DELETE: True,
    }
