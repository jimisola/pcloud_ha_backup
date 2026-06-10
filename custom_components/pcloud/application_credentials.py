"""application_credentials platform for pCloud."""

from typing import Any

from homeassistant.components.application_credentials import (
    AuthImplementation,
    AuthorizationServer,
    ClientCredential,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_entry_oauth2_flow import (
    AUTH_CALLBACK_PATH,
    MY_AUTH_CALLBACK_PATH,
)

from .const import OAUTH2_AUTHORIZE, OAUTH2_TOKEN, TOKEN_EXPIRES_IN


class PCloudOAuth2Implementation(AuthImplementation):
    """pCloud OAuth2 implementation with non-expiring, non-refreshing tokens."""

    async def async_resolve_external_data(self, external_data: Any) -> dict:
        """Resolve the authorization code to a token.

        pCloud's oauth2_token response has no `expires_in`, which HA's OAuth2
        flow requires to be present.
        """
        token = await super().async_resolve_external_data(external_data)
        token["expires_in"] = TOKEN_EXPIRES_IN
        return token

    async def _async_refresh_token(self, token: dict) -> dict:
        """Return the existing token unchanged.

        pCloud tokens don't expire and there is no refresh_token to use.
        """
        return {**token, "expires_in": TOKEN_EXPIRES_IN}


async def async_get_auth_implementation(
    hass: HomeAssistant, auth_domain: str, credential: ClientCredential
) -> PCloudOAuth2Implementation:
    """Return a custom auth implementation for pCloud."""
    return PCloudOAuth2Implementation(
        hass,
        auth_domain,
        credential,
        AuthorizationServer(
            authorize_url=OAUTH2_AUTHORIZE,
            token_url=OAUTH2_TOKEN,
        ),
    )


async def async_get_description_placeholders(hass: HomeAssistant) -> dict[str, str]:
    """Return description placeholders for the credentials dialog."""
    if "my" in hass.config.components:
        redirect_url = MY_AUTH_CALLBACK_PATH
    else:
        ha_host = hass.config.external_url or "https://YOUR_DOMAIN:PORT"
        redirect_url = f"{ha_host}{AUTH_CALLBACK_PATH}"
    return {
        "redirect_url": redirect_url,
        "more_info_url": "https://github.com/jimisola/pcloud_ha_backup#setup",
        "oauth_creds_url": "https://docs.pcloud.com/my_apps/index.html",
    }
