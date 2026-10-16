# TMP Server — implementation plan

## Scope
TMP Server is an owner-only control panel for a private host that can eventually run roughly 30 services, including a supervised Minecraft server. The delivered web project provides the control-plane shell and service-registry interaction model. The sandbox does not provide a persistent host, Docker runtime, Minecraft process, firewall, or Supabase project credentials, so host execution and production Supabase enforcement remain configuration/deployment work rather than being simulated as real infrastructure.

## Architecture
- **Frontend**: React + TypeScript + Tailwind/Vite dashboard in `client/src/`. The console uses Supabase Auth when `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, and `VITE_SUPABASE_OWNER_EMAIL` are configured. Without those public values, the app stays in an explicit configuration gate instead of inventing a login.
- **Backend**: Existing Express + tRPC server. The starter's server-side authentication and admin procedures remain available for protected operations. Owner alerts use the built-in server-side owner notification helper; notification credentials never enter the browser.
- **Service model**: Frontend types and sample state represent service identity, lifecycle state, health checks, resources, restart policy, dependencies, and recent events. The current UI keeps mutations local and clearly labels the host-control layer as pending so no browser action can execute privileged host commands.
- **Production bridge**: A future persistent host adapter should expose an allowlisted service supervisor (systemd/Docker/Podman) behind authenticated server procedures, with no raw shell access. Supabase JWT verification and owner email/subject allowlisting must be added server-side before production use.

## Project structure
- `client/src/pages/Home.tsx`: owner gate, service table, telemetry cards, logs, alerts, and service drawer interactions.
- `client/src/lib/supabase.ts`: optional Supabase browser client and configuration state.
- `client/src/lib/tmp-data.ts`: typed service registry, telemetry, logs, and alert fixtures for the console state.
- `server/routers.ts`: existing authentication plus the owner-notification entry point for future alert dispatch.
- `server/_core/notification.ts`: server-side owner notification transport.
- `public/manus-routes.json`: route manifest for `/` and `/404`.
- `TODO.md`: requirement-backed delivery and deployment worklist.

## Design direction
Three candidate directions considered:
1. **Quiet sysadmin telemetry** (0.08): charcoal control-room canvas, compact blue/cyan telemetry, amber warnings, thin borders, dense but readable tables.
2. **Cobalt command deck** (0.06): brighter navy surfaces, larger cards, more prominent blue gradients.
3. **Paper operations ledger** (0.04): light gray admin workspace, green/amber ink-like status markers, document-first panels.

### Chosen: Quiet sysadmin telemetry
- **Design Movement**: Proxmox-inspired infrastructure console with restrained dark-mode telemetry language.
- **Core Principles**: Information density without clutter; state is always visible; dangerous actions are visually distinct; every alert has an operational next step.
- **Color Philosophy**: Deep graphite and blue-black surfaces reduce glare; cyan marks healthy infrastructure; amber marks attention; red is reserved for failed/restarting states.
- **Layout Paradigm**: Fixed navigation rail plus a broad operations canvas, with a command strip above a split telemetry/service area rather than a centered marketing layout.
- **Signature Elements**: Vertical service tree, compact status dots with uppercase labels, and a thin cyan “pulse” line used for live/healthy telemetry.
- **Interaction Philosophy**: Fast scanning first; clicking a row opens context, while lifecycle actions remain explicit and report their result in the activity feed.
- **Animation**: Only short 150–220ms transitions, subtle status pulse on healthy services, and no looping decorative motion.
- **Typography System**: `IBM Plex Sans` for interface copy with `IBM Plex Mono` for identifiers, metrics, ports, and log output.
- **Brand Essence**: A private operations cockpit for one owner who wants every service accounted for; precise, calm, prepared.
- **Brand Voice**: “Host state, without the guesswork.” / “Recovery policy armed. Waiting for a signal.”
- **Wordmark & Logo**: `TMP` monogram in a rounded square with a single vertical cyan trace, paired with the `TMP Server` wordmark.
- **Signature Brand Color**: Electric cyan `#39d9ff`, used sparingly for live state and focus.

## Required behavior carried forward
- Owner-only access using Supabase authentication, no public registration, authorization across every route and action.
- Dense Proxmox-inspired admin console with navigation tree, summary panels, compact tables, status indicators, and responsive desktop-first behavior.
- Service registry supporting many services, including connection details, startup policy, and resource limits.
- Lifecycle controls for starting, stopping, restarting, and inspecting individual services with clear operation results.
- Always-on Minecraft management with startup, health checks, crash detection, supervised restart behavior, and dedicated status visibility.
- Real-time status dashboard with availability, uptime, process state, health, and recent operational events for roughly 30 services.
- Host and per-service CPU, memory, disk, network, and historical utilization views.
- Centralized log viewer with filtering, search, severity cues, timestamps, and controlled retrieval.
- Automation/recovery policies for boot startup, health interval, restart limits, backoff, dependency ordering, and failure handling.
- Secure server-side control layer that only executes allowlisted operations, protects secrets, records audit events, and prevents direct browser access to privileged host commands.
- Owner notifications for unhealthy services, repeated crashes, resource threshold breaches, and recovery.

## Deployment notes
A persistent Minecraft server and ~30 services cannot run reliably inside the default sandbox or the WebDev app container. Deploy the control plane to a managed/persistent environment and connect it to a separate persistent Linux host or container node with firewall/IP allowlisting, backups, health checks, and restart policies. Configure Supabase project values as browser-safe public variables and server-side JWT/owner allowlist values as protected secrets before enabling mutations.


## Domain routing
Each service carries an optional hostname route, shown in the registry and inspector and captured when a new service is added. In production, the host adapter must validate ownership of the domain, issue/manage TLS, and bind the hostname to the allowlisted reverse proxy; the browser only opens the configured route and never edits proxy configuration directly.


The registry includes a first-class `Web app` kind with port, HTTPS hostname, health interval, restart policy, and dependency metadata, alongside container, proxy, database, and Minecraft services.
