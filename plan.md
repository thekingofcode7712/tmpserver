
## VM Cloud storage and Minecraft connection details
Cloud files are stored persistently on `/opt/tmpserver/cloud` and exposed through authenticated list, upload, download, and delete endpoints with a 50 MB per-file safety limit. The dashboard displays the real VM address `140.238.70.11` with Java port `25565` and Bedrock port `19132`. The previous 10-player cap was removed; the server now accepts up to 1000 configured players, which is the practical limit for this VM rather than an unsafe claim of infinite capacity.

## Rolling Minecraft backup
The host creates `/opt/tmpserver/cloud/minecraft-latest.tar.gz` atomically after a Paper `save-all flush`. The same file is overwritten before controlled stop, restart, or update operations and by an enabled systemd shutdown target hook, so the Cloud section exposes one current backup rather than an unbounded archive list.
