

## Alternatives to Oracle and Google

AWS is a real VM option only as a time-limited free plan. AWS currently advertises up to $200 in credits for up to six months on its Free plan; it is not a permanent free VPS. Azure offers free services for the first 12 months for new accounts, including a small B-series VM allowance, but it is also not permanent free VPS hosting.

Koyeb is easier for a small web service, but its Free Instance is only 512 MB RAM, 0.1 vCPU, and 2 GB SSD, is limited to one per organization, has no persistent volumes, cannot run worker services, and scales to zero after one hour without traffic. Render similarly offers free web services, but they spin down after 15 minutes idle, have ephemeral filesystems, no SSH access, and its free Postgres expires after 30 days. Neither is a VPS and neither is suitable for Minecraft or a host supervisor.

Sources:

- AWS Free Tier: https://aws.amazon.com/free/
- Azure Free Services: https://azure.microsoft.com/en-us/pricing/free-services
- Koyeb instance limits: https://www.koyeb.com/docs/reference/instances
- Render free service limits: https://render.com/docs/free
