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
MAX_UPLOAD = 50 * 1024 * 1024
os.makedirs(CLOUD_ROOT, exist_ok=True)


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
                counters[interface] = {"rxBytes": int(fields[0]), "rxPackets": int(fields[1]), "txBytes": int(fields[8]), "txPackets": int(fields[9])}
    except (OSError, ValueError):
        return {"interface": "—", "linkMbps": 0, "rxBytes": 0, "txBytes": 0, "rxBytesPerSecond": 0, "txBytesPerSecond": 0, "rxPacketsPerSecond": 0, "txPacketsPerSecond": 0}
    interface = next(iter(counters), "—")
    try:
        with open(f"/sys/class/net/{interface}/speed", "r", encoding="utf-8") as file:
            link_mbps = max(0, int(file.read().strip()))
    except (OSError, ValueError):
        link_mbps = 0
    current = counters.get(interface, {"rxBytes": 0, "rxPackets": 0, "txBytes": 0, "txPackets": 0})
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
    return {"interface": interface, "linkMbps": link_mbps, **current, "rxBytesPerSecond": round(rx_rate, 1), "txBytesPerSecond": round(tx_rate, 1), "rxPacketsPerSecond": round(rx_packets_rate, 1), "txPacketsPerSecond": round(tx_packets_rate, 1)}


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
        if self.path not in {"/api/minecraft/whitelist", "/api/minecraft/command", "/api/minecraft/lifecycle", "/api/minecraft/backup"}:
            self.send_json(404, {"error": "not found"})
            return
        if not auth_user(self):
            self.send_json(401, {"error": "owner or invited member session required"})
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
