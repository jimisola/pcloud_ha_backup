## pCloud Backup

Adds **pCloud** as a native Home Assistant **backup location** ([Settings → System →
Backups](https://www.home-assistant.io/common-tasks/general/#defining-backup-locations)),
authenticated via OAuth2 in your browser — works correctly with 2FA-enabled pCloud
accounts.

### Features

- pCloud appears as a selectable backup location.
- Upload/download with progress reporting.
- Works with Home Assistant's automatic backup retention (copies/days).
- Configurable destination folder (default `/backups/homeassistant`).
- Choice of conservative (Trash) or permanent delete for pruned backups.

### Setup

You'll need to register your own pCloud OAuth app and add it under
**Settings → Devices & Services → Application Credentials** before adding this
integration — see the [README](https://github.com/jimisola/pcloud_ha_backup#setup)
for the redirect URI and step-by-step instructions.
