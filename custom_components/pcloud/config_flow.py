"""Config flow for the pCloud integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN
from homeassistant.core import callback
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.http import current_request

from .api import PCloudApiError, PCloudClient
from .const import (
    CONF_BACKUP_PATH,
    CONF_HOSTNAME,
    CONF_LOCATIONID,
    CONF_PERMANENT_DELETE,
    DEFAULT_API_HOST,
    DEFAULT_BACKUP_PATH,
    DEFAULT_PERMANENT_DELETE,
    DOMAIN,
    LOGGER,
)


def _normalize_path(path: str) -> str:
    """Normalize a pCloud path to start with a single leading slash."""
    return "/" + path.strip("/")


class OAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle a config flow for pCloud."""

    DOMAIN = DOMAIN
    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        super().__init__()
        self._hostname = DEFAULT_API_HOST
        self._locationid: int | None = None
        self._oauth_data: dict[str, Any] = {}
        self._email: str | None = None

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return LOGGER

    async def async_step_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Capture pCloud's region from the OAuth redirect.

        `hostname`/`locationid` are query parameters on the redirect to
        redirect_uri but are not part of the oauth2_token response, so they
        must be read from the callback request here before HA's standard
        flow drops them.
        """
        if user_input is not None and (request := current_request.get()) is not None:
            if hostname := request.query.get(CONF_HOSTNAME):
                self._hostname = hostname
            if locationid := request.query.get(CONF_LOCATIONID):
                self._locationid = int(locationid)
        return await super().async_step_auth(user_input)

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Perform reauth upon an API authentication error."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm reauth dialog."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Validate the token and continue to the backup-path step."""
        data[CONF_HOSTNAME] = self._hostname
        data[CONF_LOCATIONID] = self._locationid

        client = PCloudClient(
            async_get_clientsession(self.hass),
            self._hostname,
            data[CONF_TOKEN][CONF_ACCESS_TOKEN],
        )
        try:
            user_info = await client.async_get_user_info()
        except PCloudApiError:
            LOGGER.exception("Error validating pCloud credentials")
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(str(user_info["userid"]))

        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data=data
            )

        self._abort_if_unique_id_configured()
        self._oauth_data = data
        self._email = user_info["email"]
        return await self.async_step_backup_path()

    async def async_step_backup_path(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the pCloud folder to use for backups."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._email or "pCloud",
                data=self._oauth_data,
                options={
                    CONF_BACKUP_PATH: _normalize_path(user_input[CONF_BACKUP_PATH]),
                    CONF_PERMANENT_DELETE: DEFAULT_PERMANENT_DELETE,
                },
            )

        return self.async_show_form(
            step_id="backup_path",
            data_schema=vol.Schema(
                {vol.Required(CONF_BACKUP_PATH, default=DEFAULT_BACKUP_PATH): str}
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PCloudOptionsFlow:
        """Return the options flow."""
        return PCloudOptionsFlow()


class PCloudOptionsFlow(OptionsFlow):
    """Handle pCloud options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the backup path and delete-mode options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_BACKUP_PATH: _normalize_path(user_input[CONF_BACKUP_PATH]),
                    CONF_PERMANENT_DELETE: user_input[CONF_PERMANENT_DELETE],
                }
            )

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_BACKUP_PATH,
                        default=options.get(CONF_BACKUP_PATH, DEFAULT_BACKUP_PATH),
                    ): str,
                    vol.Required(
                        CONF_PERMANENT_DELETE,
                        default=options.get(
                            CONF_PERMANENT_DELETE, DEFAULT_PERMANENT_DELETE
                        ),
                    ): bool,
                }
            ),
        )
