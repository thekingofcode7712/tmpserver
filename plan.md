
## VM Cloud storage and Minecraft connection details
Cloud files are stored persistently on the configured host path (default `~/.local/share/tmpserver/cloud`) and exposed through owner-authenticated list, streamed upload, download, and delete endpoints. Cloud file uploads have no fixed per-file application cap; actual capacity is limited by available host storage and the network path. The dashboard displays the real VM address `140.238.70.11` with Java port `25565` and Bedrock port `19132`. The previous 10-player cap was removed; the server now accepts up to 1000 configured players, which is the practical limit for this VM rather than an unsafe claim of infinite capacity.

## Rolling Minecraft backup
The host creates `minecraft-latest.tar.gz` in its configured Cloud storage path atomically after a Paper `save-all flush`. The same file is overwritten before controlled stop, restart, or update operations and by an enabled systemd shutdown target hook, so the Cloud section exposes one current backup rather than an unbounded archive list.

## Owner-only Minecraft keep inventory and manual backups
The live Paper server includes `TMPKeepInventory`, a small event plugin keyed to the owner's Floodgate UUID so only `.BroodyFoil99867` keeps inventory, levels, and experience after death. The Cloud section has an authenticated **Back up Minecraft** action that runs `save-all flush`, atomically overwrites `minecraft-latest.tar.gz`, and refreshes the file listing.

## General website links and large VM storage uploads
The Websites panel keeps hosted static sites as a distinct type and adds link-only records for arbitrary absolute HTTP/HTTPS URLs. Link-only entries are stored in the existing website index, open as safe external links, and never create Caddy routes, hosting directories, or VM service telemetry. Existing records without a kind remain hosted sites. Each external link can also display a selectable Running, Updating, Down, Maintenance, or Unknown simulated state; the state is stored in browser local storage and is labeled as visual-only, not a live check or host operation.

Cloud files and hosted-site ZIPs remain owner-only and are uploaded in bounded 8 MiB chunks; neither has a fixed per-file application-size cap. Cloud files finalize atomically, and ZIP deployments validate archive paths before atomically replacing a site's public directory. The UI displays used and available host storage. Real host filesystem capacity, network availability, and any proxy/account transport limits still apply; ZIP archives also retain path and 10,000-entry safety checks.
