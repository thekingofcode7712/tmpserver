# Secure host-agent setup

The dashboard only reports live data when `VITE_HOST_API_URL` is configured and the separate Python host agent is running on the Linux machine that owns Docker. The agent binds to `127.0.0.1:8787`; do not expose that port directly on the router or in Docker. Put a Cloudflare Tunnel route and a Cloudflare Access policy in front of it, and keep the Supabase owner-token check enabled as a second gate.

## 1. Confirm the Compose values on the Linux host

In the server directory, run:

```bash
cd ~/server-stack
docker-compose -p minecraft-server config --services
```

Use the exact Compose filename, project name, and Minecraft **service key** shown by your installation. The values discussed for your setup were `minecraft-server` and `mc_crossplay_server`; confirm them before applying the example. `TMP_SERVER_MINECRAFT_SERVICE` is the service name in YAML, not necessarily `container_name`.

## 2. Install the agent files

After merging this pull request or pulling its branch to the server's `app` directory, the agent script is expected at `/home/<your-linux-user>/server-stack/app/host-agent.py`. Review `ops/tmpserver-host-agent@.service` and change `WorkingDirectory`, `ExecStart`, and `ReadWritePaths` if your paths differ.

Create the private environment file from the example:

```bash
sudo install -o root -g root -m 600 \
  ~/server-stack/app/ops/host-agent.env.example \
  /etc/tmpserver-host-agent.env
sudoedit /etc/tmpserver-host-agent.env
```

Set the actual values. In particular:

- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, and `OWNER_EMAIL` must match the same Supabase project and owner used by the dashboard. Use only the browser-safe anon/publishable key, never a service-role key.
- `ALLOWED_ORIGINS` must be the exact browser origin of your dashboard, including `https://` but with no path or trailing slash. If you use more than one dashboard origin, separate exact origins with commas.
- Set `TMP_SERVER_COMPOSE_FILE`, `TMP_SERVER_COMPOSE_PROJECT`, and `TMP_SERVER_MINECRAFT_SERVICE` to the verified Compose values. For the discussed layout, that may be `/home/<your-linux-user>/server-stack/docker-compose.yml`, `minecraft-server`, and `mc_crossplay_server`.
- Set `PUBLIC_HOSTNAME` to the address players should use. It is display information; it does not configure router forwarding, DNS, Geyser, or Cloudflare.
- Leave `TMP_SERVER_BACKUP_SCRIPT` unset unless that script exists and you have tested it. Start and stop can work without it; restart/update/settings/backup actions fail safely when the backup script is not configured or fails.

Keep `/etc/tmpserver-host-agent.env` root-owned and mode `600`; do not commit it or paste its contents into GitHub. The anon key is not an admin secret, but the file also contains private account configuration.

## 3. Start it under systemd

The template runs as the selected regular Linux user with the Docker group, not as root. Being in the `docker` group is effectively root-equivalent on the host, so only use the owner-controlled dashboard and secure the Cloudflare Access policy carefully.

```bash
sudo cp ~/server-stack/app/ops/tmpserver-host-agent@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now "tmpserver-host-agent@$(id -un).service"
sudo systemctl status "tmpserver-host-agent@$(id -un).service" --no-pager
sudo journalctl -u "tmpserver-host-agent@$(id -un).service" -n 80 --no-pager
```

Check that it listens only on loopback and that the minimal health response works:

```bash
ss -ltn | grep ':8787'
curl -fsS http://127.0.0.1:8787/api/health
```

The listener should show `127.0.0.1:8787`, not `0.0.0.0:8787`. `/api/health` deliberately returns no host metrics. `/api/state` must return `401` without a valid Supabase bearer token.

## 4. Add a protected Cloudflare Tunnel hostname

Create a separate hostname for the agent, such as `agent.<your-domain>`, and route it to `http://127.0.0.1:8787` using the management mode for your existing Tunnel:

- For a dashboard-managed Tunnel, add a published application route for that hostname.
- For a locally managed Tunnel, add its hostname ingress rule before the final catch-all rule.

Create a Cloudflare Access self-hosted application for that agent hostname and allow only your own identity. Do not create a public bypass rule. The dashboard sends credentialed browser requests to this hostname, so sign in to the Access-protected agent hostname in the same browser session before testing. Do not add a Docker `ports:` mapping for `8787` and do not forward it on your router.

## 5. Point the dashboard to the agent

Add this one new line to the existing `.env` file that your `web-app` Compose service already loads; do not replace the Supabase settings already there:

```dotenv
VITE_HOST_API_URL=https://agent.<your-domain>
```

Use the actual HTTPS agent hostname and no trailing slash. Do **not** use `localhost` here: the browser would try to contact the visitor's computer, not your Linux server. Keep `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, and `VITE_SUPABASE_OWNER_EMAIL` configured for the frontend as before.

Restart only the web app so it receives the new variable:

```bash
cd ~/server-stack
docker-compose -p minecraft-server up -d --force-recreate web-app
```

If you serve a prebuilt static bundle instead of `pnpm dev`, rebuild the frontend after setting `VITE_HOST_API_URL`; Vite embeds `VITE_*` values into the browser bundle.

## 6. Verify

1. Open the agent hostname in a browser and complete the Cloudflare Access check.
2. Sign in to the dashboard with the configured Supabase owner email.
3. The dashboard should display live host state. If it does not, inspect `journalctl -u tmpserver-host-agent` and the browser network request to `/api/state`; the agent requires an allowed dashboard `Origin` and a valid Supabase access token.
4. If the Minecraft card is degraded, confirm the exact Compose service name and that the container image supports `rcon-cli` and has RCON enabled. The agent now resolves the container through `docker compose ps -q` rather than assuming a fixed container name.

The agent grants both host data access and host mutations only to the configured owner email. CORS is an origin restriction, not authentication; keep the Supabase token check and Cloudflare Access enabled. Website deployment/lifecycle features that edit Caddy configuration require a separately designed, narrow Caddy permission setup; this unit does not grant broad `sudo` access for them.
