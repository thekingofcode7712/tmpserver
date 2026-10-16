#!/usr/bin/env python3
import json
import os
import re
import shutil
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HOST = "127.0.0.1"
PORT = int(os.environ.get("TMP_AGENT_PORT", "8787"))
SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "").strip().lower()
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "https://thekingofcode7712.github.io")
STARTED = time.time()
USERNAME_RE = re.compile(r"^[A-Za-z0-9_\.]{3,16}$")


def json_bytes(value):
    return json.dumps(value, separators=(",", ":")).encode()


def run(command, timeout=15):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


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
    health_code, health, _ = run(["docker", "inspect", "--format", "{{.State.Health.Status}}", "tmpserver-minecraft"])
    if health_code != 0:
        health = "unknown"
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
        "minecraft": {"container": "tmpserver-minecraft", "health": health, "portJava": 25565, "portBedrock": 19132},
        "services": services,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "TMPHostAgent/1.0"

    def log_message(self, format, *args):
        return

    def send_json(self, status, payload):
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_json(204, {})

    def do_GET(self):
        if self.path == "/api/health":
            self.send_json(200, {"ok": True, "service": "tmpserver-host-agent", "state": host_state()})
            return
        if self.path == "/api/state":
            if not auth_user(self):
                self.send_json(401, {"error": "authenticated Supabase session required"})
                return
            self.send_json(200, host_state())
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/minecraft/whitelist":
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
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "invalid JSON"})
            return
        if not USERNAME_RE.fullmatch(username):
            self.send_json(400, {"error": "Minecraft username must be 3–16 letters, numbers, underscore, or dot"})
            return
        if action not in {"add", "remove"}:
            self.send_json(400, {"error": "action must be add or remove"})
            return
        code, stdout, stderr = run(["docker", "exec", "tmpserver-minecraft", "rcon-cli", "whitelist", action, username])
        if code != 0:
            self.send_json(502, {"error": "Minecraft command failed", "detail": stderr[-300:]})
            return
        self.send_json(200, {"ok": True, "action": action, "username": username, "output": stdout[-500:]})


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
