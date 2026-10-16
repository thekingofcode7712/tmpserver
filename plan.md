

## GitHub Pages migration
The repository includes a GitHub Actions Pages workflow that builds the Vite frontend under `/tmpserver/`, injects only browser-safe Supabase values from GitHub Actions secrets, and deploys `dist/public`. The Pages build is read-only for backend actions; the Manus-hosted backend remains the operational control plane.
