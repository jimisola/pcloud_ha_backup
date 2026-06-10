"""Test the pCloud API client."""

from collections.abc import AsyncGenerator

import pytest

from custom_components.pcloud.api import (
    PCloudApiError,
    PCloudAuthError,
    PCloudClient,
    PCloudNotFoundError,
)
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

HOST = "api.pcloud.com"
TOKEN = "mock-access-token"


@pytest.fixture(name="client")
async def mock_client(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> AsyncGenerator[PCloudClient]:
    """Return a PCloudClient bound to the aiohttp client mocker."""
    session = aioclient_mock.create_session(hass.loop)
    try:
        yield PCloudClient(session, HOST, TOKEN)
    finally:
        await session.close()


async def test_async_get_user_info(
    client: PCloudClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test fetching account info."""
    aioclient_mock.get(
        f"https://{HOST}/userinfo",
        json={"result": 0, "userid": 12345, "email": "user@example.com"},
    )

    info = await client.async_get_user_info()

    assert info["userid"] == 12345
    assert info["email"] == "user@example.com"
    assert aioclient_mock.mock_calls[0][1].query["access_token"] == TOKEN


async def test_async_ensure_folder_walks_segments(
    client: PCloudClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test that ensure_folder creates each path segment in turn."""
    aioclient_mock.get(
        f"https://{HOST}/createfolderifnotexists",
        json={"result": 0},
    )

    await client.async_ensure_folder("/backups/homeassistant")

    assert aioclient_mock.call_count == 2
    paths = [call[1].query["path"] for call in aioclient_mock.mock_calls]
    assert paths == ["/backups", "/backups/homeassistant"]


async def test_async_list_files(
    client: PCloudClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test listing files filters out folders."""
    aioclient_mock.get(
        f"https://{HOST}/listfolder",
        json={
            "result": 0,
            "metadata": {
                "contents": [
                    {"name": "subfolder", "isfolder": True},
                    {"name": "backup.tar", "isfolder": False},
                ]
            },
        },
    )

    files = await client.async_list_files("/backups/homeassistant")

    assert files == ["backup.tar"]


async def test_async_list_files_missing_folder_returns_empty(
    client: PCloudClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test listing a non-existent folder returns an empty list."""
    aioclient_mock.get(
        f"https://{HOST}/listfolder",
        json={"result": 2005, "error": "Directory does not exist"},
    )

    assert await client.async_list_files("/missing") == []


async def test_async_download_iter(
    client: PCloudClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test downloading a file streams its bytes."""
    aioclient_mock.get(
        f"https://{HOST}/getfilelink",
        json={"result": 0, "hosts": ["p1.pcloud.com"], "path": "/file/at/cdn"},
    )
    aioclient_mock.get(
        "https://p1.pcloud.com/file/at/cdn",
        content=b"backup data",
    )

    iterator = await client.async_download_iter("/backups/homeassistant/backup.tar")
    chunks = bytearray()
    async for chunk in iterator:
        chunks.extend(chunk)

    assert bytes(chunks) == b"backup data"


async def test_async_upload_iter(
    client: PCloudClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test uploading a file posts to uploadfile with the parent folder path."""
    aioclient_mock.post(
        f"https://{HOST}/uploadfile",
        json={"result": 0, "metadata": {"fileid": 1}},
    )

    async def _stream():
        yield b"backup data"

    await client.async_upload_iter(_stream(), "/backups/homeassistant/backup.tar")

    assert aioclient_mock.call_count == 1
    assert aioclient_mock.mock_calls[0][1].query["path"] == "/backups/homeassistant"


async def test_async_clean_default_keeps_in_trash(
    client: PCloudClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test deleting a file without permanent delete only calls deletefile."""
    aioclient_mock.get(
        f"https://{HOST}/deletefile",
        json={"result": 0, "metadata": {"fileid": 42}},
    )

    await client.async_clean("/backups/homeassistant/backup.tar")

    assert aioclient_mock.call_count == 1


async def test_async_clean_permanent_clears_trash(
    client: PCloudClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test permanent delete also clears the trash entry."""
    aioclient_mock.get(
        f"https://{HOST}/deletefile",
        json={"result": 0, "metadata": {"fileid": 42}},
    )
    aioclient_mock.get(
        f"https://{HOST}/trash_clear",
        json={"result": 0},
    )

    await client.async_clean("/backups/homeassistant/backup.tar", permanent=True)

    assert aioclient_mock.call_count == 2
    assert aioclient_mock.mock_calls[1][1].query["fileid"] == "42"


async def test_async_clean_missing_file_is_idempotent(
    client: PCloudClient, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test deleting an already-missing file does not raise."""
    aioclient_mock.get(
        f"https://{HOST}/deletefile",
        json={"result": 2009, "error": "File not found"},
    )

    await client.async_clean("/backups/homeassistant/backup.tar", permanent=True)

    assert aioclient_mock.call_count == 1


@pytest.mark.parametrize(
    ("result", "error", "expected"),
    [
        (1000, "Log in required", PCloudAuthError),
        (2000, "Log in failed", PCloudAuthError),
        (2005, "Directory does not exist", PCloudNotFoundError),
        (5000, "Internal error", PCloudApiError),
    ],
)
async def test_error_code_mapping(
    client: PCloudClient,
    aioclient_mock: AiohttpClientMocker,
    result: int,
    error: str,
    expected: type[PCloudApiError],
) -> None:
    """Test that pCloud result codes map to the right exception types."""
    aioclient_mock.get(
        f"https://{HOST}/userinfo",
        json={"result": result, "error": error},
    )

    with pytest.raises(expected):
        await client.async_get_user_info()
