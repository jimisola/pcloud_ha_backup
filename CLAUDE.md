# pcloud_ha_backup — agent notes

Native pCloud backup location for Home Assistant. See [README.md](README.md) for the
user-facing description, install, and configuration. This file is implementation
guidance for agents — non-obvious facts and decisions that took real research/grilling
to nail down. Don't re-derive these; re-derivation has produced wrong answers before.

**Status: implemented (v0.1.0), not yet released/published to HACS.**

## Naming

- **Domain**: `pcloud` (matches `google_drive`/`webdav`/`onedrive`/`dropbox` —
  bare service name, even though those are backup-only). This is `manifest.json`
  `domain`, the config-entry storage key, and the package name under
  `custom_components/`. Effectively permanent once released.
- **Repo / HACS listing name**: `pcloud_ha_backup` — independent of domain, can be
  renamed freely.

## Reference integrations (in `home-assistant/core`)

- **`homeassistant/components/webdav/`** — primary template for `backup.py`.
  `{name}.tar` + `{name}.metadata.json` pairs, `CONF_BACKUP_PATH` (same name we use),
  short-TTL metadata cache, `@handle_backup_errors` decorator. Mirror
  `_list_cached_metadata_files`, `_find_backup_by_id`, caching, decorator pattern.
- **`homeassistant/components/google_drive/`** — template for OAuth:
  `application_credentials.py`, `config_flow.py` (`AbstractOAuth2FlowHandler`),
  `__init__.py` runtime_data wiring. **Swap Google's refresh-token model for
  pCloud's** (below) — don't copy refresh logic.

## Python version

Target **3.14** (HA's single supported minor, ADR-0020; HA 2026.3 moved to 3.14).
Modern async/typing, no compat shims.

## pCloud API gotchas (load-bearing — verified against docs.pcloud.com)

- **OAuth redirect carries region info that the token exchange does not**:
  `https://my.pcloud.com/oauth2/authorize` redirect to `redirect_uri` includes `code`,
  `state`, `locationid` (1=US, 2=EU), `hostname` (`api.pcloud.com` /
  `eapi.pcloud.com`). The subsequent `oauth2_token` exchange (always against
  `api.pcloud.com`) returns ONLY `access_token`, `token_type`, `uid` — no
  `hostname`/`locationid`. HA's stock `LocalOAuth2Implementation` would silently drop
  them. **Fix**: custom `AbstractOAuth2Implementation` overrides
  `async_resolve_external_data(external_data)` to read
  `external_data["hostname"]`/`["locationid"]` (HA passes through the full redirect
  query dict) and merge into the returned token dict so they persist in
  `entry.data["token"]`. Every `api.py` call must target the stored `hostname`.
- **No refresh token / no expiry** in `oauth2_token` response. Not formally documented
  as non-expiring — treat as an inference. Custom `AbstractOAuth2Implementation` needs
  a no-op `async_refresh_token` returning the stored token with a far-future
  `expires_at`. Any `401` from `api.py` → `ConfigEntryAuthFailed` (reauth flow) is the
  real safety net.
- **`createfolderifnotexists` is single-level only** — errors with code `2002`
  ("Parent directory doesn't exist") if the parent path doesn't exist yet. It will
  NOT create `/backups/homeassistant` in one call on a fresh account.
  `async_ensure_folder` must split `CONF_BACKUP_PATH` into segments and call
  `createfolderifnotexists` once per level, walking from root, threading each level's
  returned `folderid` as the parent for the next call.
- **`trash_clear` accepts a `fileid`** to remove one specific item from Trash (or
  `folderid=0` to empty all of Trash — never use that). Same `fileid` as returned by
  `deletefile`/`uploadfile`.
- API auth: `?access_token=<token>` or `Authorization: Bearer`. Methods used:
  `uploadfile`, `getfilelink`, `deletefile`, `listfolder`, `createfolderifnotexists`,
  `userinfo`, `trash_clear`.

## Config: `CONF_BACKUP_PATH` and `CONF_PERMANENT_DELETE`

- `CONF_BACKUP_PATH` default `/backups/homeassistant`. Set as a **step in the config
  flow after the OAuth callback** (pre-filled, normalized: leading `/`, no trailing
  `/`) — mirrors webdav's precedent of including it in initial setup, adapted to fit
  after OAuth. Also editable later via `OptionsFlow`. `entry.add_update_listener`
  triggers reload on change (re-`createfolderifnotexists`, re-list/upload/etc. use
  new path). Changing the path does not migrate old backups (document in README).
- `CONF_PERMANENT_DELETE` (bool, default `False`) — also in `OptionsFlow`. `False`:
  `async_delete` calls `deletefile` only (Trash if account has it enabled — recoverable
  safety net, delayed quota recovery). `True`: `deletefile` then
  `trash_clear(fileid=<same id>)` — permanent, immediate quota recovery, matches
  google_drive's permanent-delete precedent. Both modes idempotent
  (`BackupNotFound` if already gone).

## Retention correctness requirements

HA's backup manager owns retention (copies/days) and calls
`agent.async_delete_backup(backup_id)` — the agent does no pruning itself. For this to
work:

1. `async_list_backups()` returns the **exact, stable `backup_id`** HA assigned
   (persisted verbatim, never invented) and the **original `AgentBackup.date`**
   (creation time, not upload time) — used for cross-agent matching and
   `days`-based retention.
2. `async_delete_backup(backup_id)` is idempotent, raises `BackupNotFound` if
   already gone.
3. `async_get_backup(backup_id)` returns the full `AgentBackup` or `BackupNotFound`.
4. Persist the **entire `AgentBackup`** (backup_id, date, name, size, protected,
   addons, folders, homeassistant_included, homeassistant_version,
   database_included, extra_metadata) verbatim via `as_dict()`/`from_dict()` in a
   companion `.metadata.json`. Don't recompute `date` or any other field — drift
   breaks cross-agent matching/retention.

## Components to build (`custom_components/pcloud/`)

1. `manifest.json` — `domain: pcloud`, `dependencies: [application_credentials]`,
   `config_flow: true`, `iot_class: cloud_polling`, `requirements: []`. `version`
   field is plain SemVer, no `v` prefix.
2. `application_credentials.py` — `async_get_authorization_server()`; default US
   authorize host, resolve data host from `locationid` post-exchange.
3. `config_flow.py` — `AbstractOAuth2FlowHandler` subclass. On finish: `userinfo` →
   unique_id = pCloud user id → backup-path step → store
   `{token, hostname/locationid, email, backup_path}`. Reauth. `OptionsFlow` for
   `CONF_BACKUP_PATH` + `CONF_PERMANENT_DELETE`.
4. `__init__.py` — build API client, validate via `userinfo`, `async_ensure_folder`,
   `entry.runtime_data`, register backup-agent listeners,
   `entry.add_update_listener` for reload-on-options-change.
5. `api.py` — async aiohttp client, `requirements: []` (no third-party pCloud lib —
   none official exists for Python; community libs rejected on
   security/maintenance/adoption grounds; sync + don't stream `open_stream` cleanly
   anyway). Methods: `async_get_user_info`, `async_list_backups`,
   `async_upload(open_stream, metadata, on_progress)`,
   `async_download(file_id) -> AsyncIterator[bytes]`,
   `async_delete(file_id, *, permanent: bool)`, `async_ensure_folder`. Serializes
   `AgentBackup` to/from companion `.metadata.json`.
6. `backup.py` — `async_get_backup_agents`, `async_register_backup_agents_listener`
   (copy google_drive's listener pattern), `PCloudBackupAgent(BackupAgent)` with all 5
   required methods (`async_upload_backup` wraps `open_stream` for progress;
   `async_download_backup` via `getfilelink` + `ChunkAsyncStreamIterator`;
   `async_delete_backup` passes `permanent=entry.options[CONF_PERMANENT_DELETE]`).
   Map pCloud/aiohttp/timeout errors → `BackupAgentError`/`BackupNotFound`.
7. `const.py`, `strings.json`/`translations/en.json`.
8. Repo scaffolding — `hacs.json`
   (`{"name": "pCloud Backup", "render_readme": true, "homeassistant": "2026.3.0"}`),
   `info.md`, LICENSE, `.github/` (hassfest + HACS validation actions). Brand icon
   goes to `home-assistant/brands` separately, not this repo.
9. `tests/` — see Testing.

## Testing

Use `pytest-homeassistant-custom-component`, mock at the `api.py` client boundary
(AsyncMock), not raw `aiohttp`.

- `tests/conftest.py` — `mock_config_entry` (token, hostname/locationid,
  `CONF_BACKUP_PATH`, `CONF_PERMANENT_DELETE`) + `mock_pcloud_client` fixture.
- `tests/test_backup.py` — via `tests/components/backup/common.py` helpers +
  `hass_ws_client`/`hass_client`: `backup/info`, `backup/details` (incl.
  `BackupNotFound`), upload (progress events), download (streamed bytes), delete
  (assert `permanent=` flag matches `CONF_PERMANENT_DELETE`, idempotent
  `BackupNotFound`), and error-mapping incl. 401 → reauth.
- `tests/test_config_flow.py` — OAuth flow incl. region/`locationid` capture, the
  post-OAuth backup-path step, reauth, `OptionsFlow` for both options.
- `tests/test_api.py` — mocked HTTP (e.g. `aioresponses`) for
  `uploadfile`/`getfilelink`/`deletefile`/`trash_clear`/`listfolder`/
  `createfolderifnotexists`/`userinfo`, pCloud `result` error codes, and the
  `permanent=True` two-call sequence.
- `tests/test_init.py` — setup/unload, folder-ensure, listener
  registration/cleanup, options-update reload.

## Verification checklist (manual, end to end)

See README "Setup" for the user-facing version. As a developer:

1. Copy `custom_components/pcloud/` into a dev HA instance (or HACS custom repo),
   restart.
2. Register pCloud OAuth app + Application Credentials, add integration, complete
   OAuth **with 2FA enabled**, confirm/edit backup-path step.
3. Confirm pCloud appears in Settings → System → Backups.
4. Create a backup; confirm `.tar`+`.metadata.json` land in `CONF_BACKUP_PATH` on
   pCloud (correct region/host).
5. List/download/restore; delete with `CONF_PERMANENT_DELETE=False` (lands in Trash)
   and `=True` (gone from Trash).
6. `hassfest` + HACS validation pass; no agent errors in logs.
7. Reauth: invalidate token, confirm reauth recovers without 2FA friction.

## Out of scope (v1)

pCloud Crypto Folder, HA-core submission, non-OAuth/paste-token auth.

## Repo conventions

- Always work on a branch, open a PR — never push directly to `main`.
- Conventional Commits for commits and PR titles.
- `manifest.json` `version` and release tags: plain `MAJOR.MINOR.PATCH`, no `v`
  prefix.
