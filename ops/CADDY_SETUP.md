# Hosted-site Caddy route helper

This setup is only needed for **hosted static websites**. External website links are directory entries and can be added or removed without Caddy. The helper is deliberately root-owned and can apply only validated static-file routes; do not grant the host agent general `sudo`, arbitrary `systemctl`, or direct shell access as root.

When a hosted route is activated, the helper makes the shared data parent traversable only (`0711`), keeps the sibling Cloud backup directory private (`0700`), makes site directories readable (`0755`), and static files read-only/public (`0644`). It rejects symlinks to avoid serving content outside the website tree. Do not put secrets in a site's public ZIP.

The checked-in helper defaults to the current TMPx OS account `triumphant`, its standard Cloud data path, and `/etc/caddy/Caddyfile`. Before installation, edit the constants in `ops/tmpserver-caddy-sync` if the Linux username, `TMP_AGENT_WEBSITES_ROOT`, or `TMP_AGENT_CADDYFILE` differs. The username in `ops/tmpserver-caddy-sync.sudoers` must match the account running the host agent.

With Caddy installed and its Caddyfile at `/etc/caddy/Caddyfile`, install the root-owned helper and its single-command sudoers entry:

```bash
cd ~/server-stack/app
sudo install -o root -g root -m 755 ops/tmpserver-caddy-sync /usr/local/bin/tmpserver-caddy-sync
sudo install -o root -g root -m 440 ops/tmpserver-caddy-sync.sudoers /etc/sudoers.d/tmpserver-caddy-sync
sudo visudo -cf /etc/sudoers.d/tmpserver-caddy-sync
```

Install the updated host-agent unit so its protected service namespace can write only through the helper into Caddy's configuration directory. The helper itself is still the only root command authorized by the sudoers rule.

```bash
sudo install -o root -g root -m 644 ops/tmpserver-host-agent@.service /etc/systemd/system/tmpserver-host-agent@.service
sudo systemctl daemon-reload
sudo systemctl restart tmpserver-host-agent@triumphant.service
sudo systemctl status tmpserver-host-agent@triumphant.service --no-pager
```

The owner-only Websites controls can then add, start, stop, and delete hosted entries. For an active-site deletion, the agent asks the root helper to validate and reload the Caddy route set before removing files. If validation/reload fails, the UI receives the error and the site record/files are retained. External-link deletion does not use the helper. If Caddy is absent, hosted-site route operations cannot succeed, but the Cloud directory, Minecraft controls, and external links remain separate.
