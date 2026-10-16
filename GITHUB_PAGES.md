# TMP Server on GitHub Pages

This repository contains a GitHub Actions workflow at `.github/workflows/deploy-pages.yml`. Every push to `main` builds the Vite frontend and deploys `dist/public` to GitHub Pages.

## Repository secrets

Add these three Actions secrets in **Settings → Secrets and variables → Actions**:

- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_ANON_KEY`
- `VITE_SUPABASE_OWNER_EMAIL`

The Supabase service-role key must **not** be added to GitHub Actions or the Pages bundle.

## Scope

GitHub Pages is a static frontend host. Supabase email OTP login works from the Pages build when the Supabase project allows the Pages origin. The server-side invite endpoint, owner notifications, host supervisor, Minecraft lifecycle, telemetry, and service mutations remain on the Manus-hosted backend. The Pages build labels itself read-only and does not expose backend action buttons.

The default repository Pages URL will be:

`https://thekingofcode7712.github.io/tmpserver/`

The `tmpserver.manus.space` hostname is not automatically available on GitHub Pages. It would require a supported custom-domain configuration and DNS control for that hostname.
