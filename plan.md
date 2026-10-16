

## Live-data boundary
TMP Server must not render fixture services, telemetry, uptime, users, logs, alerts, or simulated lifecycle results. Until a real supervisor agent is connected through `VITE_HOST_API_URL`, the authenticated UI stops at an explicit no-live-host state. Real metrics and controls will be sourced from the persistent Linux host agent only.

## Live VM supervisor bridge
The GitHub Pages shell now polls a real host agent on the Ubuntu 24.04 VM for authenticated state and exposes a Minecraft Access drawer. The agent validates Supabase bearer sessions server-side, returns actual host memory/disk/container health, and executes only allowlisted Minecraft whitelist mutations through the Paper container. The current public transport is a temporary Cloudflare Quick Tunnel; a named Cloudflare Tunnel or user-owned DNS name should replace it for permanent operation because Quick Tunnel URLs can change after a VM restart.
