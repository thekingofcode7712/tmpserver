# TMP Server on GitHub Pages

The GitHub Actions workflow at `.github/workflows/deploy-pages.yml` builds the Vite frontend and deploys `dist/public` to GitHub Pages. The Pages site is a static frontend, but its owner-only Cloud, website, Minecraft-settings, telemetry, and lifecycle requests go directly to the authenticated host agent; the host agent is still the authority for every protected action.

## Required Actions secrets and variable

Add these Actions secrets in **Settings → Secrets and variables → Actions → Secrets**:

- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_ANON_KEY`
- `VITE_SUPABASE_OWNER_EMAIL`

Add this Actions variable in **Settings → Secrets and variables → Actions → Variables**:

- `VITE_HOST_API_URL` = `https://agent.tmpserver.com`

The workflow defaults to that stable hostname if the variable is unset. Do not use a `trycloudflare.com` Quick Tunnel URL: Quick Tunnel hostnames are temporary and can disconnect Cloud, backups, settings, websites, and telemetry after the URL changes. `VITE_HOST_API_URL` is public configuration, not a secret; the Supabase service-role key must never be added to GitHub Actions or the Pages bundle.

After changing the host-agent URL, re-run the **Deploy TMP Server to GitHub Pages** workflow. Vite embeds `VITE_*` settings in the built JavaScript, so changing a repository variable does not alter an already-deployed bundle.

The agent must allow the exact Pages origin in `ALLOWED_ORIGINS` and must remain reachable at the configured HTTPS hostname. Keep Cloudflare Access and the Supabase owner-token check enabled. Cloud is storage on the Minecraft host's persistent disk, not a separate S3/cloud-provider account; actual free disk and network/proxy limits apply.

## Scope and URL

GitHub Pages serves only the frontend files. It does not run the host agent or Minecraft server. The Pages frontend talks directly to the configured agent hostname for live state and owner-protected actions. The default repository Pages URL is:

`https://thekingofcode7712.github.io/tmpserver/`

The `tmpserver.manus.space` hostname is not automatically available on GitHub Pages. It requires supported custom-domain configuration and DNS control for that hostname.
