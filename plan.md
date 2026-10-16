

## Live-data boundary
TMP Server must not render fixture services, telemetry, uptime, users, logs, alerts, or simulated lifecycle results. Until a real supervisor agent is connected through `VITE_HOST_API_URL`, the authenticated UI stops at an explicit no-live-host state. Real metrics and controls will be sourced from the persistent Linux host agent only.
