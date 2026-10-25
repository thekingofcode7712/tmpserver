
## Independent websites and external links
- [ ] Let the owner add any absolute HTTP or HTTPS website link to the Websites panel, whether or not it is routed through or hosted on this server; show it as a safe outbound link without deployment or lifecycle controls.
- [ ] Preserve hosted-site records and behavior, keep external links out of Caddy routing and host telemetry, and let the owner remove either entry type; hosted deletion removes a live Caddy route before files are removed, and failures leave the site record/files intact with an actionable error.
- [ ] Let the owner set an external link's simulated status to Running, Updating, Down, Maintenance, or Unknown; label it as visual-only, browser-local, not a live check, and not a host action.

## Cloud storage and Minecraft backups
- [ ] Use the stable host-agent URL for the GitHub Pages build, configurable by a repository variable; never bake in an ephemeral Quick Tunnel URL. Document the Pages configuration and rebuild requirement.
- [ ] Store Cloud files on the host's configured persistent disk, create the Cloud directory automatically, and support owner-only upload/download/delete without a fixed app per-file upload-size cap using chunked transfer; show real free space and report disk-full/network errors. Actual filesystem/network limits still apply.
- [ ] Run the same installed executable backup script for manual Cloud backup, controlled lifecycle operations, settings changes, and a persistent daily 09:00 UTC systemd timer. Write one atomically replaced `minecraft-latest.tar.gz` in the configured Cloud folder; resume a missed schedule after host downtime, restore Paper world saving on success/failure, and surface errors rather than claiming a backup succeeded.

## Minecraft server settings
- [ ] Let the owner edit view distance (2–32 chunks), simulation distance (2–32 chunks), maximum players (1–1000), and whitelist enforcement from Settings; validate every submitted value before stopping the server.
- [ ] Create a backup while the server is running, stop Paper only after the backup succeeds, apply the Compose settings, then restart and confirm the updated values. If backup/apply/restart or refresh fails, show the specific error and do not show an unconditional success message.
