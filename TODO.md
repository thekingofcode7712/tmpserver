
## Independent sites and external links
- [ ] Let the owner add any absolute HTTP or HTTPS website link to the Websites panel, whether or not it is routed through or hosted on this server; show it as a safe outbound link without deployment or lifecycle controls.
- [ ] Preserve existing hosted-site records and behavior, and keep external links out of Caddy routing and host-service telemetry.
- [ ] Let the owner set an external link's simulated status to Running, Updating, Down, Maintenance, or Unknown; label it as visual-only, browser-local, not a live check, and not a host action.

## VM cloud storage uploads
- [ ] Remove arbitrary per-file application upload-size caps for Cloud files and hosted-site ZIP deployments; support large files with streamed 8 MiB chunks; show real host free space and report disk-full conditions. Actual filesystem/network capacity still applies, and ZIP path plus 10,000-entry safety checks remain.
- [ ] Keep Cloud upload/download/delete authenticated and owner-only, path-safe, and atomic so interrupted or failed uploads do not replace existing files.
