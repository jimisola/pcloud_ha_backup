"""Support for pCloud backup."""

from collections.abc import AsyncIterator, Callable, Coroutine
from functools import wraps
from time import time
from typing import Any, Concatenate

import aiohttp
from homeassistant.components.backup import (
    AgentBackup,
    BackupAgent,
    BackupAgentError,
    BackupNotFound,
    OnProgressCallback,
    suggested_filename,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.json import json_dumps
from homeassistant.util.async_ import gather_with_limited_concurrency
from homeassistant.util.json import JSON_DECODE_EXCEPTIONS, json_loads_object

from . import PCloudConfigEntry
from .api import PCloudApiError, PCloudAuthError
from .const import (
    CONF_BACKUP_PATH,
    CONF_PERMANENT_DELETE,
    DATA_BACKUP_AGENT_LISTENERS,
    DEFAULT_BACKUP_PATH,
    DEFAULT_PERMANENT_DELETE,
    DOMAIN,
    LOGGER,
)

CACHE_TTL = 300
METADATA_DOWNLOAD_CONCURRENCY = 4


async def async_get_backup_agents(hass: HomeAssistant) -> list[BackupAgent]:
    """Return a list of backup agents."""
    entries: list[PCloudConfigEntry] = hass.config_entries.async_loaded_entries(DOMAIN)
    return [PCloudBackupAgent(hass, entry) for entry in entries]


@callback
def async_register_backup_agents_listener(
    hass: HomeAssistant,
    *,
    listener: Callable[[], None],
    **kwargs: Any,
) -> Callable[[], None]:
    """Register a listener to be called when agents are added or removed.

    :return: A function to unregister the listener.
    """
    hass.data.setdefault(DATA_BACKUP_AGENT_LISTENERS, []).append(listener)

    @callback
    def remove_listener() -> None:
        """Remove the listener."""
        hass.data[DATA_BACKUP_AGENT_LISTENERS].remove(listener)
        if not hass.data[DATA_BACKUP_AGENT_LISTENERS]:
            del hass.data[DATA_BACKUP_AGENT_LISTENERS]

    return remove_listener


def handle_backup_errors[R, **P](
    func: Callable[Concatenate[PCloudBackupAgent, P], Coroutine[Any, Any, R]],
) -> Callable[Concatenate[PCloudBackupAgent, P], Coroutine[Any, Any, R]]:
    """Handle backup errors."""

    @wraps(func)
    async def wrapper(self: PCloudBackupAgent, *args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await func(self, *args, **kwargs)
        except PCloudAuthError as err:
            raise BackupAgentError("Authentication error") from err
        except (PCloudApiError, aiohttp.ClientError) as err:
            LOGGER.debug("Full error: %s", err, exc_info=True)
            raise BackupAgentError(f"Backup operation failed: {err}") from err
        except TimeoutError as err:
            LOGGER.error("Error during backup in %s: Timeout", func.__name__)
            raise BackupAgentError("Backup operation timed out") from err

    return wrapper


def suggested_filenames(backup: AgentBackup) -> tuple[str, str]:
    """Return the suggested filenames for the backup and metadata."""
    base_name = suggested_filename(backup).rsplit(".", 1)[0]
    return f"{base_name}.tar", f"{base_name}.metadata.json"


class PCloudBackupAgent(BackupAgent):
    """Backup agent interface."""

    domain = DOMAIN

    def __init__(self, hass: HomeAssistant, entry: PCloudConfigEntry) -> None:
        """Initialize the pCloud backup agent."""
        super().__init__()
        self._hass = hass
        self._entry = entry
        self._client = entry.runtime_data
        self.name = entry.title
        self.unique_id = entry.entry_id
        self._cache_metadata_files: dict[str, AgentBackup] = {}
        self._cache_expiration = time()

    @property
    def _backup_path(self) -> str:
        """Return the configured pCloud folder for backups."""
        return self._entry.options.get(CONF_BACKUP_PATH, DEFAULT_BACKUP_PATH)

    @handle_backup_errors
    async def async_download_backup(
        self,
        backup_id: str,
        **kwargs: Any,
    ) -> AsyncIterator[bytes]:
        """Download a backup file.

        :param backup_id: The ID of the backup that was returned in async_list_backups.
        :return: An async iterator that yields bytes.
        """
        backup = await self._find_backup_by_id(backup_id)

        return await self._client.async_download_iter(
            f"{self._backup_path}/{suggested_filename(backup)}"
        )

    @handle_backup_errors
    async def async_upload_backup(
        self,
        *,
        open_stream: Callable[[], Coroutine[Any, Any, AsyncIterator[bytes]]],
        backup: AgentBackup,
        on_progress: OnProgressCallback,
        **kwargs: Any,
    ) -> None:
        """Upload a backup.

        :param open_stream: A function returning an async iterator that yields bytes.
        :param backup: Metadata about the backup that should be uploaded.
        """
        (filename_tar, filename_meta) = suggested_filenames(backup)

        await self._client.async_upload_iter(
            await open_stream(),
            f"{self._backup_path}/{filename_tar}",
            content_length=backup.size,
            progress=lambda current, total: on_progress(bytes_uploaded=current),
        )

        LOGGER.debug("Uploaded backup to %s", f"{self._backup_path}/{filename_tar}")

        async def _metadata_stream() -> AsyncIterator[bytes]:
            yield json_dumps(backup.as_dict()).encode("utf-8")

        await self._client.async_upload_iter(
            _metadata_stream(),
            f"{self._backup_path}/{filename_meta}",
        )

        LOGGER.debug(
            "Uploaded metadata file for %s", f"{self._backup_path}/{filename_meta}"
        )

        # reset cache
        self._cache_expiration = time()

    @handle_backup_errors
    async def async_delete_backup(
        self,
        backup_id: str,
        **kwargs: Any,
    ) -> None:
        """Delete a backup file.

        :param backup_id: The ID of the backup that was returned in async_list_backups.
        """
        backup = await self._find_backup_by_id(backup_id)

        (filename_tar, filename_meta) = suggested_filenames(backup)
        permanent = self._entry.options.get(
            CONF_PERMANENT_DELETE, DEFAULT_PERMANENT_DELETE
        )

        await self._client.async_clean(
            f"{self._backup_path}/{filename_tar}", permanent=permanent
        )
        await self._client.async_clean(
            f"{self._backup_path}/{filename_meta}", permanent=permanent
        )

        LOGGER.debug("Deleted backup at %s", f"{self._backup_path}/{filename_tar}")

        # reset cache
        self._cache_expiration = time()

    @handle_backup_errors
    async def async_list_backups(self, **kwargs: Any) -> list[AgentBackup]:
        """List backups."""
        return list((await self._list_cached_metadata_files()).values())

    @handle_backup_errors
    async def async_get_backup(
        self,
        backup_id: str,
        **kwargs: Any,
    ) -> AgentBackup:
        """Return a backup."""
        return await self._find_backup_by_id(backup_id)

    async def _list_cached_metadata_files(self) -> dict[str, AgentBackup]:
        """List metadata files with a cache."""
        if time() <= self._cache_expiration:
            return self._cache_metadata_files

        async def _download_metadata(file_name: str) -> AgentBackup | None:
            """Download a metadata file."""
            path = f"{self._backup_path}/{file_name}"
            iterator = await self._client.async_download_iter(path)
            metadata_bytes = bytearray()
            async for chunk in iterator:
                metadata_bytes.extend(chunk)
            try:
                return AgentBackup.from_dict(json_loads_object(metadata_bytes))
            except (*JSON_DECODE_EXCEPTIONS, KeyError, TypeError, ValueError) as err:
                LOGGER.warning(
                    "Skipping invalid backup metadata file %s: %s", path, err
                )
                return None

        async def _list_metadata_files() -> dict[str, AgentBackup]:
            """List metadata files."""
            files = await self._client.async_list_files(self._backup_path)
            metadata_contents = await gather_with_limited_concurrency(
                METADATA_DOWNLOAD_CONCURRENCY,
                *(
                    _download_metadata(file_name)
                    for file_name in files
                    if file_name.endswith(".metadata.json")
                ),
            )
            return {
                metadata_content.backup_id: metadata_content
                for metadata_content in metadata_contents
                if metadata_content
            }

        self._cache_metadata_files = await _list_metadata_files()
        self._cache_expiration = time() + CACHE_TTL
        return self._cache_metadata_files

    async def _find_backup_by_id(self, backup_id: str) -> AgentBackup:
        """Find a backup by its backup ID on remote."""
        metadata_files = await self._list_cached_metadata_files()
        if metadata_file := metadata_files.get(backup_id):
            return metadata_file

        raise BackupNotFound(f"Backup {backup_id} not found")
