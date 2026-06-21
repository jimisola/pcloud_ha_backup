> **Archived.** This backup location was never actually tried/verified end-to-end.
> Relevant parts have been migrated to
> [HAS-pCloud-Backup](https://github.com/ghotso/HAS-pCloud-Backup) — please use that
> project instead.

# pCloud Backup for Home Assistant

A [HACS](https://hacs.xyz/)-installable custom integration that registers **pCloud**
as a native Home Assistant **backup location** (the `BackupAgent` platform introduced
in HA 2025.1), authenticated via **OAuth2** in your browser.

## Why

pCloud's WebDAV gateway and `console-client` (`pcloudcc`)/rclone authenticate with a
plain username/password and have no slot for a 2FA code, so they don't work well with
2FA-enabled pCloud accounts. This integration uses pCloud's OAuth2 login instead — 2FA
happens on pCloud's own page in your browser, and Home Assistant only ever stores a
bearer token.

## Status

🚧 In development — design complete, implementation in progress. Not yet published to
the HACS default store.

## Features

- pCloud appears as a selectable backup location in
  **Settings → System → Backups**.
- Backups upload/download with progress reporting.
- Home Assistant's automatic backup retention (copies/days) works correctly —
  backups are listed with their original metadata and pruned via this integration.
- Configurable destination folder on pCloud (default `/backups/homeassistant`).
- Choice of conservative (Trash) or permanent delete when retention removes old
  backups.

## Installation

### Via HACS (custom repository)

1. In HACS, go to the **⋮** menu → *Custom repositories*.
2. Add this repository's URL with category **Integration**.
3. Install **pCloud Backup**, then restart Home Assistant.

### Manual

Copy `custom_components/pcloud/` into your Home Assistant config's
`custom_components/` directory and restart.

## Setup

1. **Create a pCloud OAuth app**: as a custom (non-core) integration, this component
   has no shared/built-in client credentials — you register your own app in pCloud's
   developer console and add it to Home Assistant under
   **Settings → Devices & Services → Application Credentials**.
   - Set the redirect URI to `https://my.home-assistant.io/redirect/oauth`.
2. In Home Assistant, go to **Settings → Devices & Services → Add Integration** and
   search for **pCloud**.
3. Complete the OAuth login (and 2FA, if enabled) on pCloud's site.
4. Confirm or edit the **backup folder path** (default `/backups/homeassistant`).
5. pCloud now appears as a backup location in
   **Settings → System → Backups**.

## Configuration options

After setup, use the integration's **Configure** button to change:

- **Backup folder path** — the pCloud folder backups are stored in (default
  `/backups/homeassistant`). Changing this does **not** move existing backups —
  backups in the old folder become invisible until the path is changed back.
- **Permanently delete old backups** (default off) — controls what happens when Home
  Assistant's retention policy removes an old backup:
  - **Off (default)**: the file is moved to pCloud's Trash, recoverable until pCloud
    auto-purges it. Safer if your retention policy is misconfigured, but trashed
    files still count against your pCloud quota until purged.
  - **On**: the file is permanently deleted immediately, freeing quota right away.

## Limitations / out of scope (v1)

- pCloud's client-side encrypted "Crypto Folder" is not supported.
- No non-OAuth (paste-token) authentication.
- Submission to the HA core / HACS default store is a possible future step, not part
  of v1.

## License

MIT
