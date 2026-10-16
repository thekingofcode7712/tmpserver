# TMP Server delivery worklist

## Owner-only Supabase access
- [ ] Configure Supabase Auth with no public registration.
- [ ] Configure the owner identity allowlist and enforce it server-side across every route and action.
- [x] Keep the app in a configuration gate until Supabase public values are present; never invent a logged-in preview user.

## Proxmox-inspired operations console
- [x] Provide a dense Proxmox-inspired admin-console shell with navigation tree, summary panels, compact tables, status indicators, and responsive desktop-first layouts.
- [x] Show host overview, active service count, recovery posture, service health, resource telemetry, operational events, logs, and owner alerts.

## Service registry and lifecycle
- [x] Provide a service registry model for adding, configuring, organizing, and removing many hosted services, including connection details, startup policy, and resource limits.
- [x] Provide start, stop, restart, and inspect controls with confirmations/clear operation results in the activity feed.
- [x] Provide owner-facing start/turn-on, stop/turn-off, restart, and update controls with visible operation results.
- [ ] Connect lifecycle actions to a server-side allowlisted supervisor (systemd/Docker/Podman) instead of browser-local state.

## Minecraft supervision
- [x] Give the Minecraft service dedicated status visibility, health-check state, restart count, uptime, and recovery policy display.
- [ ] Connect the Minecraft service to a persistent host with boot startup, crash detection, supervised restart, dependency ordering, and backoff enforcement.

## Monitoring, logs, and recovery
- [x] Show service availability, uptime, process state, health, and recent operational events for a roughly 30-service fleet.
- [x] Show host and per-service CPU, memory, disk, network activity, and historical utilization trends.
- [x] Provide centralized live/historical logs with service filter, text search, severity cues, timestamps, and controlled retrieval UI.
- [ ] Replace fixture telemetry with signed server-side host metrics and durable historical storage.
- [x] Model automation policies for boot startup, health-check intervals, restart limits, backoff, dependency ordering, and failure handling.

## Owner notifications and security boundary
- [x] Add owner-alert presentation for unhealthy services, repeated crashes, resource threshold breaches, and recovery events.
- [ ] Configure the server-side owner notification transport and delivery destination.
- [ ] Keep secrets server-side, record an audit trail, and prevent direct browser access to privileged host commands.
- [ ] Add end-to-end verification for Supabase JWT validation, owner authorization, allowlisted operations, notification dispatch, and audit records.

## Hosting readiness
- [ ] Deploy the control plane to an always-on environment and connect it to a persistent Linux host/container node; the default sandbox is not a 24/7 Minecraft host.
- [ ] Configure firewall/IP allowlisting, backups, disk thresholds, resource limits, and health probes before production use.

## Domain routing
- [x] Allow a service to store an optional hostname and show its linked route in the registry and inspector.
- [ ] Connect hostname routes to the server-side reverse proxy and TLS manager with domain ownership validation.

## Web app hosting
- [x] Include a first-class Web app service type with port, health policy, restart policy, dependency metadata, and optional domain route.

## Acceptance hardening
- [x] Label fixture telemetry and pending host bindings explicitly in the preview.
- [x] Confirm stop, restart, and update actions before recording them in the preview registry.
- [x] Normalize and validate service IDs/hostnames and reject duplicate service IDs in the add-service flow.

## Member invitations
- [x] Allow the owner to invite additional users by email through Supabase without enabling public registration.
- [x] Keep the Supabase service-role key server-side and protect the invite endpoint with the owner session.
- [ ] Apply the same Supabase member authorization to every future host-control and data procedure on the server.

## Email OTP authentication
- [x] Replace magic-link wording and flow with six-digit Supabase email OTP entry and verification for the owner and invited members.
