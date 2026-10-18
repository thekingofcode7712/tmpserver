#!/usr/bin/env python3
import json
import cgi
import io
import mimetypes
import os
import re
import shlex
import shutil
import subprocess
import time
import tempfile
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HOST = "127.0.0.1"
PORT = int(os.environ.get("TMP_AGENT_PORT", "8787"))
SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "").strip().lower()
ALLOWED_ORIGINS = {
    origin.strip().rstrip("/")
    for origin in os.environ.get("ALLOWED_ORIGIN", "https://thekingofcode7712.github.io").split(",")
    if origin.strip()
}
ALLOWED_ORIGINS.update({"https://tmpserver.com", "https://www.tmpserver.com"})
PUBLIC_HOSTNAME = os.environ.get("PUBLIC_HOSTNAME", "140.238.70.11")
STARTED = time.time()
NETWORK_SAMPLE = None
USERNAME_RE = re.compile(r"^[A-Za-z0-9_\.]{3,16}$")
CONSOLE_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,240}$")
COMPOSE_FILE = "/opt/tmpserver/minecraft/compose.yml"
BACKUP_SCRIPT = "/usr/local/bin/tmpserver-minecraft-backup"
CLOUD_ROOT = "/opt/tmpserver/cloud"
WEBSITES_ROOT = "/opt/tmpserver/websites"
WEBSITES_INDEX = os.path.join(WEBSITES_ROOT, "sites.json")
CADDYFILE = "/etc/caddy/Caddyfile"
MAX_UPLOAD = 50 * 1024 * 1024
os.makedirs(CLOUD_ROOT, exist_ok=True)
os.makedirs(WEBSITES_ROOT, exist_ok=True)


def json_bytes(value):
    return json.dumps(value, separators=(",", ":")).encode()


def run(command, timeout=15):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def network_state():
    global NETWORK_SAMPLE
    counters = {}
    try:
        with open("/proc/net/dev", "r", encoding="utf-8") as file:
            for line in file:
                if ":" not in line:
                    continue
                interface, values = line.split(":", 1)
                interface = interface.strip()
                fields = values.split()
                if interface == "lo" or len(fields) < 16:
                    continue
                counters[interface] = {"rxBytes": int(fields[0]), "rxPackets": int(fields[1]), "rxDropped": int(fields[3]), "txBytes": int(fields[8]), "txPackets": int(fields[9]), "txDropped": int(fields[11])}
    except (OSError, ValueError):
        return {"interface": "—", "linkMbps": 0, "sampleSeconds": 0, "rxBytes": 0, "txBytes": 0, "rxBytesPerSecond": 0, "txBytesPerSecond": 0, "rxPacketsPerSecond": 0, "txPacketsPerSecond": 0, "rxDropped": 0, "txDropped": 0}
    interface = next(iter(counters), "—")
    try:
        with open(f"/sys/class/net/{interface}/speed", "r", encoding="utf-8") as file:
            link_mbps = max(0, int(file.read().strip()))
    except (OSError, ValueError):
        link_mbps = 0
    current = counters.get(interface, {"rxBytes": 0, "rxPackets": 0, "rxDropped": 0, "txBytes": 0, "txPackets": 0, "txDropped": 0})
    now = time.monotonic()
    previous = NETWORK_SAMPLE
    elapsed = now - previous["time"] if previous else 0
    if previous and elapsed > 0 and previous["interface"] == interface:
        rx_rate = max(0, current["rxBytes"] - previous["rxBytes"]) / elapsed
        tx_rate = max(0, current["txBytes"] - previous["txBytes"]) / elapsed
        rx_packets_rate = max(0, current["rxPackets"] - previous["rxPackets"]) / elapsed
        tx_packets_rate = max(0, current["txPackets"] - previous["txPackets"]) / elapsed
    else:
        rx_rate = tx_rate = rx_packets_rate = tx_packets_rate = 0
    NETWORK_SAMPLE = {"time": now, "interface": interface, **current}
    return {"interface": interface, "linkMbps": link_mbps, "sampleSeconds": round(elapsed, 1), **current, "rxBytesPerSecond": round(rx_rate, 1), "txBytesPerSecond": round(tx_rate, 1), "rxPacketsPerSecond": round(rx_packets_rate, 1), "txPacketsPerSecond": round(tx_packets_rate, 1)}


def auth_user(handler):
    header = handler.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:].strip()
    if not token:
        return None
    request = Request(f"{SUPABASE_URL}/auth/v1/user", headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}"})
    try:
        with urlopen(request, timeout=8) as response:
            user = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None
    email = str(user.get("email", "")).strip().lower()
    app_metadata = user.get("app_metadata") or {}
    if email == OWNER_EMAIL or app_metadata.get("tmpserver_access") is True:
        return user
    return None


def host_state():
    with open("/proc/uptime", "r", encoding="utf-8") as file:
        uptime = float(file.read().split()[0])
    mem = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as file:
        for line in file:
            key, value = line.split(":", 1)
            mem[key] = int(value.strip().split()[0]) * 1024
    total = mem.get("MemTotal", 0)
    available = mem.get("MemAvailable", 0)
    disk = shutil.disk_usage("/")
    network = network_state()
    health_code, health, _ = run(["docker", "inspect", "--format", "{{.State.Health.Status}}", "tmpserver-minecraft"])
    if health_code != 0:
        health = "unknown"
    list_code, list_output, _ = run(["docker", "exec", "tmpserver-minecraft", "rcon-cli", "list"])
    player_match = re.search(r"There are\s+(\d+)\s+of a max of\s+(\d+)\s+players online", list_output, re.IGNORECASE)
    online_players = int(player_match.group(1)) if player_match else 0
    max_players = int(player_match.group(2)) if player_match else 0
    ps_code, ps_out, _ = run(["docker", "ps", "--format", "{{.Names}}|{{.Status}}|{{.Ports}}"])
    services = []
    if ps_code == 0:
        for row in ps_out.splitlines():
            name, status, ports = (row.split("|", 2) + ["", ""])[:3]
            services.append({"name": name, "status": status, "ports": ports})
    for site in read_websites():
        services.append({"name": site["name"], "status": "running" if site.get("active") else "stopped", "ports": f"HTTPS · {site['domain']}", "kind": "Web app", "domain": site["domain"], "files": website_state(site)["files"], "bytes": website_state(site)["bytes"]})
    return {
        "host": {"hostname": os.uname().nodename, "os": "Ubuntu 24.04", "architecture": os.uname().machine, "uptimeSeconds": round(uptime), "agentUptimeSeconds": round(time.time() - STARTED)},
        "memory": {"totalBytes": total, "availableBytes": available, "usedPercent": round((total - available) / total * 100, 1) if total else 0},
        "disk": {"totalBytes": disk.total, "freeBytes": disk.free, "usedPercent": round((disk.total - disk.free) / disk.total * 100, 1) if disk.total else 0},
        "network": network,
        "minecraft": {"container": "tmpserver-minecraft", "health": health, "portJava": 25565, "portBedrock": 19132, "onlinePlayers": online_players, "maxPlayers": max_players, "publicHostname": PUBLIC_HOSTNAME},
        "services": services,
    }


def safe_cloud_path(value):
    candidate = os.path.normpath(str(value or "").strip().lstrip("/"))
    if not candidate or candidate == "." or candidate.startswith("..") or "/../" in f"/{candidate}/" or "\\" in candidate:
        return None
    full = os.path.realpath(os.path.join(CLOUD_ROOT, candidate))
    return full if full == CLOUD_ROOT or full.startswith(CLOUD_ROOT + os.sep) else None


def cloud_files():
    result = []
    for root, _, names in os.walk(CLOUD_ROOT):
        for name in names:
            full = os.path.join(root, name)
            relative = os.path.relpath(full, CLOUD_ROOT).replace(os.sep, "/")
            stat = os.stat(full)
            result.append({"path": relative, "name": name, "size": stat.st_size, "modified": int(stat.st_mtime)})
    return sorted(result, key=lambda item: item["path"].lower())
def website_slug(value):
    slug = re.sub(r"[^a-z0-9-]+", "-", str(value or "").strip().lower()).strip("-")
    return slug[:48] or None
def website_domain(value):
    domain = str(value or "").strip().lower().rstrip(".")
    if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain):
        return None
    return domain
def read_websites():
    try:
        with open(WEBSITES_INDEX, "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []
def write_websites(sites):
    temp = f"{WEBSITES_INDEX}.tmp"
    with open(temp, "w", encoding="utf-8") as file:
        json.dump(sites, file, indent=2)
    os.replace(temp, WEBSITES_INDEX)
def website_state(site):
    public_root = os.path.join(WEBSITES_ROOT, site["slug"], "public")
    return {**site, "files": sum(len(names) for _, _, names in os.walk(public_root)) if os.path.isdir(public_root) else 0, "bytes": sum(os.path.getsize(os.path.join(root, name)) for root, _, names in os.walk(public_root) for name in names) if os.path.isdir(public_root) else 0}
def reload_caddy(sites):
    try:
        with open(CADDYFILE, "r", encoding="utf-8") as file:
            base = file.read().split("\n# TMP_SERVER_WEBSITES\n", 1)[0].rstrip()
        blocks = []
        for site in sites:
            if site.get("active"):
                root = os.path.join(WEBSITES_ROOT, site["slug"], "public")
                blocks.append(f"{site['domain']} {{\n    root * {root}\n    encode gzip\n    file_server\n}}")
        content = base + "\n\n# TMP_SERVER_WEBSITES\n" + ("\n\n".join(blocks) if blocks else "") + "\n"
        fd, path = tempfile.mkstemp(prefix="tmpserver-caddy-", text=True)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(content)
        code, stdout, stderr = run(["caddy", "validate", "--config", path, "--adapter", "caddyfile"], timeout=20)
        if code != 0:
            os.remove(path)
            return False, stderr[-500:] or stdout[-500:]
        shutil.copyfile(path, CADDYFILE)
        os.remove(path)
        code, stdout, stderr = run(["systemctl", "reload", "caddy"], timeout=20)
        return code == 0, stderr[-500:] or stdout[-500:]
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
def owner_user(user):
    return bool(user and str(user.get("email", "")).strip().lower() == OWNER_EMAIL)
def minecraft_settings():
    values = {"viewDistance": 0, "simulationDistance": 0, "maxPlayers": 0, "whitelist": False}
    try:
        with open(os.path.join(os.path.dirname(COMPOSE_FILE), "compose.yml"), "r", encoding="utf-8") as file:
            text = file.read()
        for key, pattern in [("viewDistance", r"VIEW_DISTANCE:\s*(\d+)"), ("simulationDistance", r"SIMULATION_DISTANCE:\s*(\d+)"), ("maxPlayers", r"MAX_PLAYERS:\s*(\d+)")]:
            match = re.search(pattern, text)
            if match:
                values[key] = int(match.group(1))
        values["whitelist"] = bool(re.search(r"ENABLE_WHITELIST:\s*true", text, re.IGNORECASE))
    except (OSError, ValueError):
        pass
    return values
def update_minecraft_settings(payload):
    try:
        view_distance = int(payload.get("viewDistance"))
        simulation_distance = int(payload.get("simulationDistance"))
        max_players = int(payload.get("maxPlayers"))
    except (TypeError, ValueError):
        raise ValueError("Minecraft settings must be whole numbers.")
    if not 2 <= view_distance <= 32:
        raise ValueError("View distance must be between 2 and 32 chunks.")
    if not 2 <= simulation_distance <= 32:
        raise ValueError("Simulation distance must be between 2 and 32 chunks.")
    if not 1 <= max_players <= 1000:
        raise ValueError("Max players must be between 1 and 1000.")
    with open(COMPOSE_FILE, "r", encoding="utf-8") as file:
        text = file.read()
    replacements = [(r"(?m)^(\s*VIEW_DISTANCE:\s*)\d+", rf"\g<1>{view_distance}"), (r"(?m)^(\s*SIMULATION_DISTANCE:\s*)\d+", rf"\g<1>{simulation_distance}"), (r"(?m)^(\s*MAX_PLAYERS:\s*)\d+", rf"\g<1>{max_players}")]
    for pattern, replacement in replacements:
        text, count = re.subn(pattern, replacement, text, count=1)
        if count != 1:
            raise ValueError("Minecraft compose file is missing a supported setting.")
    backup_path = f"{COMPOSE_FILE}.settings.bak"
    shutil.copy2(COMPOSE_FILE, backup_path)
    with open(COMPOSE_FILE, "w", encoding="utf-8") as file:
        file.write(text)
    return minecraft_settings()
def admin_snapshot():
    storage = []
    code, output, _ = run(["df", "-P", "-B1", "/", CLOUD_ROOT, "/opt/tmpserver/websites"])
    if code == 0:
        for line in output.splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 6:
                try:
                    total, used, free = int(fields[1]), int(fields[2]), int(fields[3])
                    storage.append({"filesystem": fields[0], "mount": fields[5], "totalBytes": total, "usedBytes": used, "freeBytes": free, "usedPercent": round(used / total * 100, 1) if total else 0})
                except ValueError:
                    continue
    firewall = {"active": False, "defaultIncoming": "unknown", "rules": []}
    code, output, _ = run(["ufw", "status", "verbose"])
    if code == 0:
        firewall["active"] = output.startswith("Status: active")
        match = re.search(r"Default:\s+([^,]+),", output)
        firewall["defaultIncoming"] = match.group(1).strip() if match else "unknown"
        for line in output.splitlines():
            if re.match(r"^\d", line.strip()):
                firewall["rules"].append(line.strip())
    docker_version = "unknown"
    docker_root = "unknown"
    docker_cpus = 0
    docker_memory = 0
    code, output, _ = run(["docker", "info", "--format", "{{.ServerVersion}}|{{.DockerRootDir}}|{{.NCPU}}|{{.MemTotal}}"])
    if code == 0:
        fields = output.split("|")
        if len(fields) == 4:
            docker_version, docker_root = fields[0], fields[1]
            try:
                docker_cpus, docker_memory = int(fields[2]), int(fields[3])
            except ValueError:
                pass
    failed_units = []
    code, output, _ = run(["systemctl", "--failed", "--no-legend"])
    if code == 0:
        failed_units = [line.split()[0] for line in output.splitlines() if line.split()]
    return {"storage": storage, "docker": {"version": docker_version, "root": docker_root, "cpus": docker_cpus, "memoryBytes": docker_memory}, "firewall": firewall, "capabilities": {"kvm": os.path.exists("/dev/kvm"), "lxcInstalled": shutil.which("lxc") is not None, "docker": docker_version != "unknown", "nativeVmManagement": False}, "failedUnits": failed_units}


class Handler(BaseHTTPRequestHandler):
    server_version = "TMPHostAgent/1.0"

    def log_message(self, format, *args):
        return

    def send_json(self, status, payload):
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", self.cors_origin())
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path):
        size = os.path.getsize(path)
        content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(path)}"')
        self.send_header("Access-Control-Allow-Origin", self.cors_origin())
        self.send_header("Vary", "Origin")
        self.end_headers()
        with open(path, "rb") as file:
            shutil.copyfileobj(file, self.wfile)

    def cors_origin(self):
        origin = self.headers.get("Origin", "").rstrip("/")
        return origin if origin in ALLOWED_ORIGINS else "https://tmpserver.com"

    def do_OPTIONS(self):
        self.send_json(204, {})

    def do_GET(self):
        if self.path == "/api/health":
            self.send_json(200, {"ok": True, "service": "tmpserver-host-agent", "state": host_state()})
            return
        if self.path == "/api/cloud/files":
            if not auth_user(self):
                self.send_json(401, {"error": "authenticated Supabase session required"})
                return
            self.send_json(200, {"files": cloud_files(), "usedBytes": sum(item["size"] for item in cloud_files())})
            return
        if self.path == "/api/websites":
            if not auth_user(self):
                self.send_json(401, {"error": "authenticated Supabase session required"})
                return
            self.send_json(200, {"sites": [website_state(site) for site in read_websites()]})
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/cloud/download":
            if not auth_user(self):
                self.send_json(401, {"error": "authenticated Supabase session required"})
                return
            path = safe_cloud_path(parse_qs(parsed.query).get("path", [""])[0])
            if not path or not os.path.isfile(path):
                self.send_json(404, {"error": "file not found"})
                return
            self.send_file(path)
            return
        if self.path == "/api/state":
            if not auth_user(self):
                self.send_json(401, {"error": "authenticated Supabase session required"})
                return
            self.send_json(200, host_state())
            return
        if self.path == "/api/settings":
            user = auth_user(self)
            if not user:
                self.send_json(401, {"error": "authenticated Supabase session required"})
                return
            backup_path = os.path.join(CLOUD_ROOT, "minecraft-latest.tar.gz")
            backup_stat = os.stat(backup_path) if os.path.isfile(backup_path) else None
            self.send_json(200, {"host": host_state()["host"], "minecraft": minecraft_settings(), "agent": {"status": "connected", "uptimeSeconds": round(time.time() - STARTED)}, "backup": {"present": bool(backup_stat), "bytes": backup_stat.st_size if backup_stat else 0, "modified": int(backup_stat.st_mtime) if backup_stat else 0}, "permissions": {"owner": owner_user(user)}, "admin": admin_snapshot()})
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path in {"/api/cloud/upload", "/api/cloud/delete"}:
            if not auth_user(self):
                self.send_json(401, {"error": "owner or invited member session required"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > MAX_UPLOAD:
                    self.send_json(413, {"error": "file is larger than the 50 MB limit"})
                    return
                if self.path.endswith("/upload"):
                    content_type = self.headers.get("Content-Type", "")
                    _, params = cgi.parse_header(content_type)
                    body = self.rfile.read(length)
                    form = cgi.FieldStorage(fp=io.BytesIO(body), headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type, "CONTENT_LENGTH": str(length)})
                    item = form["file"] if "file" in form else None
                    target = safe_cloud_path(form.getfirst("path", "") if "path" in form else (item.filename if item else ""))
                    if not item or not target:
                        self.send_json(400, {"error": "choose a file and a safe path"})
                        return
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with open(target, "wb") as file:
                        shutil.copyfileobj(item.file, file)
                    self.send_json(200, {"ok": True, "file": next(item for item in cloud_files() if os.path.realpath(os.path.join(CLOUD_ROOT, item["path"])) == target)})
                    return
                payload = json.loads(self.rfile.read(length))
                target = safe_cloud_path(payload.get("path"))
                if not target or not os.path.isfile(target):
                    self.send_json(404, {"error": "file not found"})
                    return
                os.remove(target)
                self.send_json(200, {"ok": True, "path": payload.get("path")})
                return
            except Exception as error:
                self.send_json(400, {"error": f"cloud operation failed: {error}"})
                return
        website_match = re.fullmatch(r"/api/websites/([a-z0-9-]+)/(deploy|lifecycle|delete)", self.path)
        if self.path not in {"/api/minecraft/whitelist", "/api/minecraft/command", "/api/minecraft/lifecycle", "/api/minecraft/backup", "/api/minecraft/settings", "/api/websites"} and not website_match:
            self.send_json(404, {"error": "not found"})
            return
        if not auth_user(self):
            self.send_json(401, {"error": "owner or invited member session required"})
            return
        if self.path == "/api/minecraft/settings":
            user = auth_user(self)
            if not owner_user(user):
                self.send_json(403, {"error": "Only the configured TMP Server owner can change Minecraft settings."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                stop_code, stop_stdout, stop_stderr = run(["docker", "compose", "-f", COMPOSE_FILE, "stop", "minecraft"], timeout=60)
                if stop_code != 0:
                    self.send_json(502, {"error": "Minecraft could not be stopped safely; settings were not changed.", "detail": stop_stderr[-300:] or stop_stdout[-300:]})
                    return
                backup_code, backup_stdout, backup_stderr = run([BACKUP_SCRIPT], timeout=240)
                if backup_code != 0:
                    run(["docker", "compose", "-f", COMPOSE_FILE, "up", "-d", "minecraft"], timeout=90)
                    self.send_json(502, {"error": "Minecraft backup failed; settings were not applied.", "detail": backup_stderr[-300:] or backup_stdout[-300:]})
                    return
                try:
                    settings = update_minecraft_settings(payload)
                except (OSError, ValueError) as error:
                    run(["docker", "compose", "-f", COMPOSE_FILE, "up", "-d", "minecraft"], timeout=90)
                    raise error
                stop_code, stop_stdout2, stop_stderr2 = run(["docker", "compose", "-f", COMPOSE_FILE, "up", "-d", "minecraft"], timeout=90)
                stop_stdout = f"{stop_stdout}\n{stop_stdout2}"; stop_stderr = f"{stop_stderr}\n{stop_stderr2}"
                if stop_code != 0:
                    self.send_json(502, {"error": "Minecraft restart failed after settings change.", "detail": stop_stderr[-300:] or stop_stdout[-300:]})
                    return
                self.send_json(200, {"ok": True, "settings": settings, "state": host_state()})
                return
            except (OSError, ValueError, json.JSONDecodeError) as error:
                self.send_json(400, {"error": str(error)})
                return
        if self.path == "/api/websites" or website_match:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > MAX_UPLOAD + 4096:
                    self.send_json(413, {"error": "website upload is larger than the 50 MB limit"})
                    return
                sites = read_websites()
                if website_match and website_match.group(2) == "deploy":
                    content_type = self.headers.get("Content-Type", "")
                    if "multipart/form-data" not in content_type:
                        self.send_json(400, {"error": "Upload a ZIP file using multipart/form-data."})
                        return
                    form = cgi.FieldStorage(fp=io.BytesIO(self.rfile.read(length)), headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type, "CONTENT_LENGTH": str(length)})
                    item = form["file"] if "file" in form else None
                    slug = website_match.group(1)
                    site = next((entry for entry in sites if entry["slug"] == slug), None)
                    if not item or not site or not str(item.filename or "").lower().endswith(".zip"):
                        self.send_json(400, {"error": "Choose a ZIP file for an existing website."})
                        return
                    target_root = os.path.join(WEBSITES_ROOT, slug, "public")
                    with tempfile.TemporaryDirectory(prefix="tmpserver-site-") as temp_root:
                        archive_path = os.path.join(temp_root, "site.zip")
                        with open(archive_path, "wb") as archive_file:
                            shutil.copyfileobj(item.file, archive_file)
                        with zipfile.ZipFile(archive_path) as archive:
                            members = archive.infolist()
                            if len(members) > 10000 or any(member.file_size > MAX_UPLOAD for member in members):
                                self.send_json(413, {"error": "ZIP contains too many or too-large files."})
                                return
                            for member in members:
                                member_path = os.path.realpath(os.path.join(temp_root, "unzipped", member.filename))
                                safe_root = os.path.realpath(os.path.join(temp_root, "unzipped"))
                                if not member_path.startswith(safe_root + os.sep):
                                    self.send_json(400, {"error": "ZIP contains an unsafe path."})
                                    return
                            archive.extractall(os.path.join(temp_root, "unzipped"))
                        extracted = os.path.join(temp_root, "unzipped")
                        candidate = os.path.join(extracted, "index.html")
                        if not os.path.isfile(candidate):
                            children = [name for name in os.listdir(extracted) if os.path.isdir(os.path.join(extracted, name))]
                            if len(children) == 1 and os.path.isfile(os.path.join(extracted, children[0], "index.html")):
                                extracted = os.path.join(extracted, children[0])
                            else:
                                self.send_json(400, {"error": "ZIP must contain index.html at its root."})
                                return
                        new_root = os.path.join(target_root, ".new")
                        shutil.rmtree(new_root, ignore_errors=True)
                        shutil.copytree(extracted, new_root)
                        old_root = os.path.join(target_root, ".old")
                        shutil.rmtree(old_root, ignore_errors=True)
                        if os.path.isdir(target_root):
                            os.rename(target_root, old_root)
                        os.rename(new_root, target_root)
                        shutil.rmtree(old_root, ignore_errors=True)
                    site["updated"] = int(time.time())
                    write_websites(sites)
                    self.send_json(200, {"ok": True, "site": website_state(site)})
                    return
                payload = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/websites":
                    name = str(payload.get("name", "")).strip()
                    slug = website_slug(payload.get("slug") or name)
                    domain = website_domain(payload.get("domain"))
                    if not name or not slug or not domain:
                        self.send_json(400, {"error": "Enter a site name and a valid domain."})
                        return
                    if any(site["slug"] == slug or site["domain"] == domain for site in sites):
                        self.send_json(409, {"error": "A website with that name or domain already exists."})
                        return
                    os.makedirs(os.path.join(WEBSITES_ROOT, slug, "public"), exist_ok=True)
                    site = {"name": name[:80], "slug": slug, "domain": domain, "active": False, "created": int(time.time()), "updated": int(time.time())}
                    sites.append(site)
                    write_websites(sites)
                    self.send_json(201, {"ok": True, "site": website_state(site)})
                    return
                slug, action = website_match.group(1), website_match.group(2)
                site = next((item for item in sites if item["slug"] == slug), None)
                if not site:
                    self.send_json(404, {"error": "Website not found."})
                    return
                if action == "lifecycle":
                    operation = str(payload.get("action", "")).strip().lower()
                    if operation not in {"start", "stop"}:
                        self.send_json(400, {"error": "Website action must be start or stop."})
                        return
                    site["active"] = operation == "start"
                    site["updated"] = int(time.time())
                    ok, detail = reload_caddy(sites)
                    if not ok:
                        site["active"] = not site["active"]
                        self.send_json(502, {"error": "Caddy rejected the website route.", "detail": detail})
                        return
                    write_websites(sites)
                    self.send_json(200, {"ok": True, "site": website_state(site)})
                    return
                if action == "delete":
                    ok, detail = reload_caddy([item for item in sites if item["slug"] != slug])
                    if not ok:
                        self.send_json(502, {"error": "Could not remove the website route.", "detail": detail})
                        return
                    shutil.rmtree(os.path.join(WEBSITES_ROOT, slug), ignore_errors=True)
                    write_websites([item for item in sites if item["slug"] != slug])
                    self.send_json(200, {"ok": True, "slug": slug})
                    return
                self.send_json(400, {"error": "Unsupported website operation."})
                return
            except (OSError, ValueError, json.JSONDecodeError) as error:
                self.send_json(400, {"error": f"Website operation failed: {error}"})
                return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            username = str(payload.get("username", "")).strip()
            action = str(payload.get("action", "add")).strip().lower()
            command = str(payload.get("command", "")).strip()
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "invalid JSON"})
            return
        if self.path == "/api/minecraft/backup":
            code, stdout, stderr = run([BACKUP_SCRIPT], timeout=240)
            if code != 0:
                self.send_json(502, {"error": "Minecraft backup failed", "detail": stderr[-300:] or stdout[-300:]})
                return
            self.send_json(200, {"ok": True, "action": "backup", "output": stdout[-1000:]})
            return
        if self.path == "/api/minecraft/whitelist":
            if not USERNAME_RE.fullmatch(username):
                self.send_json(400, {"error": "Minecraft username must be 3–16 letters, numbers, underscore, or dot"})
                return
            if action not in {"add", "remove"}:
                self.send_json(400, {"error": "action must be add or remove"})
                return
            command_args = ["whitelist", action, username]
        elif self.path == "/api/minecraft/command":
            if not CONSOLE_RE.fullmatch(command) or not command:
                self.send_json(400, {"error": "Enter one Minecraft command under 240 characters"})
                return
            try:
                command_args = shlex.split(command.lstrip("/"))
            except ValueError:
                self.send_json(400, {"error": "Invalid command quoting"})
                return
            if not command_args:
                self.send_json(400, {"error": "Command cannot be empty"})
                return
        else:
            lifecycle = action
            if lifecycle not in {"start", "stop", "restart", "update"}:
                self.send_json(400, {"error": "action must be start, stop, restart, or update"})
                return
            if lifecycle in {"stop", "restart", "update"}:
                backup_code, backup_stdout, backup_stderr = run([BACKUP_SCRIPT], timeout=240)
                if backup_code != 0:
                    self.send_json(502, {"error": "Minecraft backup failed; lifecycle action was not run", "detail": backup_stderr[-300:] or backup_stdout[-300:]})
                    return
            if lifecycle == "update":
                code, stdout, stderr = run(["docker", "compose", "-f", COMPOSE_FILE, "pull", "minecraft"], timeout=180)
                if code == 0:
                    code, stdout2, stderr2 = run(["docker", "compose", "-f", COMPOSE_FILE, "up", "-d", "minecraft"], timeout=60)
                    stdout = f"{stdout}\n{stdout2}"; stderr = f"{stderr}\n{stderr2}"
            else:
                compose_action = "up -d" if lifecycle == "start" else lifecycle
                code, stdout, stderr = run(["docker", "compose", "-f", COMPOSE_FILE, *compose_action.split(), "minecraft"], timeout=45)
            if code != 0:
                self.send_json(502, {"error": "Minecraft lifecycle command failed", "detail": stderr[-300:]})
                return
            self.send_json(200, {"ok": True, "action": lifecycle, "state": host_state()})
            return
        code, stdout, stderr = run(["docker", "exec", "tmpserver-minecraft", "rcon-cli", *command_args])
        if code != 0:
            self.send_json(502, {"error": "Minecraft command failed", "detail": stderr[-300:]})
            return
        self.send_json(200, {"ok": True, "action": action if self.path.endswith("whitelist") else "command", "username": username if self.path.endswith("whitelist") else None, "output": stdout[-1000:]})


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
