
## No sample data
- [x] Remove all hard-coded service, uptime, utilization, log, activity, alert, and user-count fixture values from the live data module.
- [x] Block the dashboard and lifecycle controls until a real persistent host supervisor is connected.
- [ ] Connect a persistent Linux host agent and replace the empty live-data boundary with authenticated real metrics, logs, uptime, user counts, deployments, and service controls.

## Live VM connection and Minecraft users
- [x] Connect the Pages dashboard to a real Ubuntu 24.04 host agent over HTTPS, validate Supabase sessions server-side, expose actual memory/disk/container health, and allow authenticated Java or Bedrock whitelist additions through Geyser/Floodgate.
- [ ] Replace the temporary Cloudflare Quick Tunnel with a named tunnel or user-owned DNS/TLS endpoint so the Pages-to-VM URL remains stable across VM restarts.
