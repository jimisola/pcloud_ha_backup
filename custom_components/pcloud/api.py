"""Thin async client for the pCloud HTTP API.

Only calls pCloud's officially documented HTTP API (https://docs.pcloud.com/)
directly via aiohttp - there is no official Python SDK, so no third-party
pCloud package is used.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Callable
from typing import Any

import aiohttp

# Generous timeout: backups can be large and uploads/downloads are streamed.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(connect=10, total=43200)

_CHUNK_SIZE = 2**20  # 1 MiB

# https://docs.pcloud.com/errors/ - codes that mean the access token is
# invalid/expired/revoked and the config entry needs reauth.
_AUTH_ERROR_CODES = {1000, 2000}

# Codes that mean the requested file/folder/parent does not exist.
_NOT_FOUND_ERROR_CODES = {2002, 2005, 2009}


class PCloudApiError(Exception):
    """Raised when the pCloud API returns a non-zero result code."""

    def __init__(self, result: int, error: str | None = None) -> None:
        """Initialize the error."""
        self.result = result
        self.error = error
        super().__init__(f"pCloud API error {result}: {error}")


class PCloudAuthError(PCloudApiError):
    """Raised when the access token is invalid, expired, or revoked."""


class PCloudNotFoundError(PCloudApiError):
    """Raised when a requested file or folder does not exist on pCloud."""


def _raise_for_result(payload: dict[str, Any]) -> None:
    """Raise an appropriate exception if the pCloud API call failed."""
    result = payload.get("result", 0)
    if result == 0:
        return
    error = payload.get("error")
    if result in _AUTH_ERROR_CODES:
        raise PCloudAuthError(result, error)
    if result in _NOT_FOUND_ERROR_CODES:
        raise PCloudNotFoundError(result, error)
    raise PCloudApiError(result, error)


class PCloudClient:
    """Thin async client for the pCloud HTTP API used by the backup agent."""

    def __init__(
        self, session: aiohttp.ClientSession, host: str, access_token: str
    ) -> None:
        """Initialize the client.

        `host` is the data-center host returned on the OAuth redirect
        (`api.pcloud.com` or `eapi.pcloud.com`) and must be reused for every
        call - pCloud accounts are pinned to one region.
        """
        self._session = session
        self._host = host
        self._access_token = access_token

    def _url(self, method: str) -> str:
        return f"https://{self._host}/{method}"

    async def _call(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Call a pCloud JSON API method and return its decoded payload."""
        query = dict(params or {})
        query["access_token"] = self._access_token
        async with self._session.get(self._url(method), params=query) as resp:
            resp.raise_for_status()
            payload: dict[str, Any] = await resp.json(content_type=None)
        _raise_for_result(payload)
        return payload

    async def async_get_user_info(self) -> dict[str, Any]:
        """Return account info for the authenticated user.

        Also serves as a token-validity check.
        """
        return await self._call("userinfo")

    async def async_ensure_folder(self, path: str) -> None:
        """Ensure that `path` exists, creating any missing segments.

        `createfolderifnotexists` only ever creates a single level - it
        errors if the parent doesn't exist yet - so this walks the path from
        the root, creating (or confirming) each segment in turn.
        """
        segments = [segment for segment in path.split("/") if segment]
        current = ""
        for segment in segments:
            current = f"{current}/{segment}"
            await self._call("createfolderifnotexists", {"path": current})

    async def async_list_files(self, path: str) -> list[str]:
        """Return the names of the files (not folders) directly inside `path`."""
        try:
            payload = await self._call("listfolder", {"path": path})
        except PCloudNotFoundError:
            return []
        contents = payload.get("metadata", {}).get("contents", [])
        return [entry["name"] for entry in contents if not entry.get("isfolder")]

    async def async_download_iter(self, path: str) -> AsyncIterator[bytes]:
        """Return an async iterator yielding the bytes of the file at `path`."""
        link = await self._call("getfilelink", {"path": path})
        host = link["hosts"][0]
        url = f"https://{host}{link['path']}"
        session = self._session

        async def _iterator() -> AsyncIterator[bytes]:
            async with session.get(url, timeout=REQUEST_TIMEOUT) as resp:
                resp.raise_for_status()
                async for chunk in resp.content.iter_chunked(_CHUNK_SIZE):
                    yield chunk

        return _iterator()

    async def async_upload_iter(
        self,
        stream: AsyncIterator[bytes],
        path: str,
        *,
        content_length: int | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> None:
        """Upload the bytes from `stream` to `path`, overwriting any existing file."""
        folder_path, _, filename = path.rpartition("/")
        folder_path = folder_path or "/"

        async def _tracked() -> AsyncIterator[bytes]:
            uploaded = 0
            async for chunk in stream:
                uploaded += len(chunk)
                if progress is not None:
                    progress(uploaded, content_length or uploaded)
                yield chunk

        form = aiohttp.FormData()
        form.add_field(
            "file",
            _tracked(),
            filename=filename,
            content_type="application/octet-stream",
        )

        params = {"path": folder_path, "access_token": self._access_token}
        async with self._session.post(
            self._url("uploadfile"),
            params=params,
            data=form,
            timeout=REQUEST_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            payload: dict[str, Any] = await resp.json(content_type=None)
        _raise_for_result(payload)

    async def async_clean(self, path: str, *, permanent: bool = False) -> None:
        """Delete the file at `path`.

        Idempotent: a missing file is treated as already deleted. If
        `permanent` is True, the file is also removed from Trash so it no
        longer counts against the account's quota.
        """
        try:
            payload = await self._call("deletefile", {"path": path})
        except PCloudNotFoundError:
            return

        if permanent:
            fileid = payload["metadata"]["fileid"]
            with contextlib.suppress(PCloudNotFoundError):
                await self._call("trash_clear", {"fileid": fileid})
