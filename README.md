# Prowlarr Sync Download Clients

This mod mirrors Prowlarr download clients into connected apps using each app's existing Prowlarr `syncLevel`.

Use it with `DOCKER_MODS=linuxserver/mods:prowlarr-sync-download-clients`

If adding multiple mods, separate them with `|`, such as `DOCKER_MODS=linuxserver/mods:prowlarr-sync-download-clients|linuxserver/mods:universal-package-install`

## Assumptions

- App integrations already exist in Prowlarr.
- The LinuxServer Prowlarr container has its config mounted at `/config`.

## Supported Apps

- Sonarr: `/api/v3`
- Radarr: `/api/v3`
- Lidarr: `/api/v1`
- Readarr: `/api/v1`
- Whisparr: `/api/v3`

## Detected But Not Syncable

- LazyLibrarian
- Mylar

These are detected explicitly, but their published APIs do not expose Servarr-style `/downloadclient` and `/tag` endpoints, so the mod logs and skips them for download-client sync.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `PROWLARR_SYNC_ENABLED` | `true` | Enables or disables the sync loop. |
| `PROWLARR_SYNC_URL` | `http://127.0.0.1:9696` | Local Prowlarr URL used by the mod. |
| `PROWLARR_SYNC_API_KEY` | unset | Prowlarr API key. If unset, the mod reads `/config/config.xml`. |
| `PROWLARR_SYNC_INTERVAL` | `300` | Seconds to wait between sync passes. |
| `PROWLARR_SYNC_TIMEOUT` | `15` | Per-request HTTP timeout in seconds. |
| `PROWLARR_SYNC_MANAGED_TAG` | `prowlarr-sync-download-clients` | Tag added to downstream clients managed by this mod. |
| `PROWLARR_SYNC_LOG_LEVEL` | `info` | Python log level for the sync service. |

## Sync Semantics

- `disabled`: skip the app entirely.
- `addOnly`: create missing managed download clients, but do not update or delete existing ones.
- `fullSync`: create, update, and remove only the download clients tagged as managed by this mod.

## Ownership Rule

Only download clients with the managed tag are reconciled destructively. Untagged or manually created clients in Sonarr, Radarr, Lidarr, Readarr, and Whisparr are left alone.

## Operation

The mod waits for Prowlarr to become reachable, performs an initial sync, and then repeats every `PROWLARR_SYNC_INTERVAL` seconds.
