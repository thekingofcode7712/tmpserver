#!/usr/bin/env python3
import json
try:
    import cgi
except ImportError:  # Python 3.13 removed the deprecated cgi module.
    cgi = None
import errno
import mimetypes
import os
import re
import threading
import uuid
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

HOST = "127.0.0.1"  # Keep the privileged agent off public interfaces; expose it only through a protected tunnel.
PORT = int(os.environ.get("TMP_AGENT_PORT", "8787"))
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
OWNER_EMAIL = os.environ.get("OWNER_EMAIL", "").strip().lower()
ALLOWED_ORIGINS = {
    origin.strip().rstrip("/")
    for origin in os.environ.get("ALLOWED_ORIGINS", os.environ.get("ALLOWED_ORIGIN", "")).split(",")
    if origin.strip()
}
if not SUPABASE_URL or not SUPABASE_ANON_KEY or not OWNER_EMAIL:
    raise RuntimeError("Set SUPABASE_URL, SUPABASE_ANON_KEY, and OWNER_EMAIL before starting the host agent.")
if not ALLOWED_ORIGINS:
    raise RuntimeError("Set ALLOWED_ORIGINS to the exact HTTPS origin of the dashboard.")
if any(parsed.scheme != "https" or not parsed.netloc or parsed.path or parsed.query or parsed.fragment for parsed in map(urlparse, ALLOWED_ORIGINS)):
    raise RuntimeError("ALLOWED_ORIGINS entries must be exact HTTPS origins with no path.")

PUBLIC_HOSTNAME = os.environ.get("PUBLIC_HOSTNAME", "not-configured").strip()
STARTED = time.time()
NETWORK_SAMPLE = None
USERNAME_RE = re.compile(r"^[A-Za-z0-9_\.]{3,16}$")
CONSOLE_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,240}$")
COMPOSE_FILE = os.path.abspath(os.path.expanduser(os.environ.get("TMP_SERVER_COMPOSE_FILE", "")))
if not COMPOSE_FILE or not os.path.isfile(COMPOSE_FILE):
    raise RuntimeError("Set TMP_SERVER_COMPOSE_FILE to the existing Compose YAML file for your Minecraft server.")
COMPOSE_PROJECT = os.environ.get("TMP_SERVER_COMPOSE_PROJECT", "").strip()
MINECRAFT_SERVICE = os.environ.get("TMP_SERVER_MINECRAFT_SERVICE", "minecraft").strip()
COMPOSE_COMMAND_SETTING = os.environ.get("TMP_COMPOSE_COMMAND", "docker compose").strip()
if COMPOSE_COMMAND_SETTING not in {"docker compose", "docker-compose"}:
    raise RuntimeError("TMP_COMPOSE_COMMAND must be either 'docker compose' or 'docker-compose'.")
COMPOSE_COMMAND = ["docker-compose"] if COMPOSE_COMMAND_SETTING == "docker-compose" else ["docker", "compose"]
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", MINECRAFT_SERVICE):
    raise RuntimeError("TMP_SERVER_MINECRAFT_SERVICE must be a valid Compose service name.")
if COMPOSE_PROJECT and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", COMPOSE_PROJECT):
    raise RuntimeError("TMP_SERVER_COMPOSE_PROJECT must be a valid Compose project name.")
BACKUP_SCRIPT = os.path.abspath(os.path.expanduser(os.environ["TMP_SERVER_BACKUP_SCRIPT"])) if os.environ.get("TMP_SERVER_BACKUP_SCRIPT", "").strip() else ""
BACKUP_TIMEOUT_SECONDS = 6 * 60 * 60
DATA_ROOT = os.path.abspath(os.path.expanduser(os.environ.get("TMP_AGENT_DATA_ROOT", "~/.local/share/tmpserver")))
CLOUD_ROOT = os.path.abspath(os.path.expanduser(os.environ.get("TMP_AGENT_CLOUD_ROOT", os.path.join(DATA_ROOT, "cloud"))))
WEBSITES_ROOT = os.path.abspath(os.path.expanduser(os.environ.get("TMP_AGENT_WEBSITES_ROOT", os.path.join(DATA_ROOT, "websites"))))
WEBSITES_INDEX = os.path.join(WEBSITES_ROOT, "sites.json")
CADDYFILE = os.environ.get("TMP_AGENT_CADDYFILE", "/etc/caddy/Caddyfile")
CADDY_SYNC_SCRIPT = os.path.abspath(os.path.expanduser(os.environ.get("TMP_AGENT_CADDY_SYNC_SCRIPT", "/usr/local/bin/tmpserver-caddy-sync")))
CLOUD_UPLOAD_CHUNK_SIZE = 8 * 1024 * 1024
CLOUD_UPLOADS_ROOT = os.path.join(CLOUD_ROOT, ".tmpserver-uploads")
CLOUD_UPLOAD_LOCK = threading.RLock()
CADDY_SYNC_LOCK = threading.Lock()
MINECRAFT_JOB_LOCK = threading.RLock()
MINECRAFT_OPERATION_LOCK = threading.Lock()
MINECRAFT_JOBS = {}
os.makedirs(CLOUD_ROOT, exist_ok=True)
os.makedirs(WEBSITES_ROOT, exist_ok=True)
os.makedirs(CLOUD_UPLOADS_ROOT, mode=0o700, exist_ok=True)


def compose_cmd(*args):
    prefix = [*COMPOSE_COMMAND]
    if COMPOSE_PROJECT:
        prefix.extend(["-p", COMPOSE_PROJECT])
    prefix.extend(["-f", COMPOSE_FILE])
    return [*prefix, *args]


def minecraft_container_id():
    if not MINECRAFT_SERVICE:
        return ""
    code, output, _ = run(compose_cmd("ps", "-q", MINECRAFT_SERVICE), timeout=15)
    return output.splitlines()[0].strip() if code == 0 and output.strip() else ""


def wait_for_minecraft_ready(timeout=300):
    deadline = time.monotonic() + timeout
    last_error = "RCON is not ready yet."
    while time.monotonic() < deadline:
        container_id = minecraft_container_id()
        if container_id:
            code, stdout, stderr = run(["docker", "exec", container_id, "rcon-cli", "list"], timeout=10)
            if code == 0:
                return
            last_error = stderr[-500:] or stdout[-500:] or last_error
        time.sleep(3)
    raise RuntimeError(f"Minecraft did not become ready within {timeout} seconds. {last_error}")


def run_backup(timeout=None):
    if not BACKUP_SCRIPT:
        return 1, "", "Set TMP_SERVER_BACKUP_SCRIPT to an installed world-backup script before using backup-dependent actions."
    if not os.path.isfile(BACKUP_SCRIPT) or not os.access(BACKUP_SCRIPT, os.X_OK):
        return 1, "", "Configured world-backup script is missing or not executable."
    try:
        command = ["timeout", "--signal=TERM", "--kill-after=300s", f"{BACKUP_TIMEOUT_SECONDS}s", BACKUP_SCRIPT]
        return run(command, timeout=timeout or BACKUP_TIMEOUT_SECONDS + 360)
    except (OSError, subprocess.SubprocessError) as error:
        return 1, "", str(error)


def _execute_minecraft_job(job_id, operation):
    try:
        with MINECRAFT_OPERATION_LOCK:
            result = operation()
        status, error = "succeeded", ""
    except Exception as exception:
        result, status, error = {}, "failed", str(exception)
    with MINECRAFT_JOB_LOCK:
        job = MINECRAFT_JOBS.get(job_id)
        if job:
            job.update({"status": status, "error": error, "result": result, "finished": int(time.time())})


def start_minecraft_job(kind, operation):
    now = int(time.time())
    with MINECRAFT_JOB_LOCK:
        for job_id, job in list(MINECRAFT_JOBS.items()):
            if job.get("status") != "running" and job.get("started", 0) < now - 24 * 60 * 60:
                MINECRAFT_JOBS.pop(job_id, None)
        for job_id, job in MINECRAFT_JOBS.items():
            if job.get("status") == "running":
                if kind == "backup" and job.get("kind") == "backup":
                    return job_id
                raise RuntimeError("Another Minecraft backup or settings operation is already in progress.")
        job_id = uuid.uuid4().hex
        MINECRAFT_JOBS[job_id] = {"kind": kind, "status": "running", "error": "", "result": {}, "started": now, "finished": 0}
        while len(MINECRAFT_JOBS) > 50:
            oldest = min(MINECRAFT_JOBS, key=lambda key: MINECRAFT_JOBS[key].get("started", 0))
            if MINECRAFT_JOBS[oldest].get("status") == "running":
                break
            MINECRAFT_JOBS.pop(oldest, None)
        threading.Thread(target=_execute_minecraft_job, args=(job_id, operation), daemon=True).start()
        return job_id


def minecraft_job_snapshot(job_id):
    with MINECRAFT_JOB_LOCK:
        job = MINECRAFT_JOBS.get(job_id)
        return dict(job) if job else None


def backup_job_operation():
    code, stdout, stderr = run_backup(timeout=None)
    if code != 0:
        raise RuntimeError(stderr[-1000:] or stdout[-1000:] or "Backup script exited unsuccessfully.")
    return {"output": stdout[-1000:]}


def apply_minecraft_settings_job(settings):
    backup_code, backup_stdout, backup_stderr = run_backup(timeout=None)
    if backup_code != 0:
        raise RuntimeError("Minecraft backup failed; settings were not changed. " + (backup_stderr[-800:] or backup_stdout[-800:]))
    stop_code, stop_stdout, stop_stderr = run(compose_cmd("stop", MINECRAFT_SERVICE), timeout=60)
    if stop_code != 0:
        raise RuntimeError("Minecraft could not be stopped safely; settings were not changed. " + (stop_stderr[-800:] or stop_stdout[-800:]))
    try:
        applied = update_minecraft_settings(settings)
    except Exception as error:
        start_code, start_stdout, start_stderr = run(compose_cmd("up", "-d", MINECRAFT_SERVICE), timeout=120)
        if start_code != 0:
            raise RuntimeError(f"Settings were not applied ({error}); Minecraft could not be restarted: {(start_stderr or start_stdout)[-800:]}") from error
        raise RuntimeError(f"Settings were not applied: {error}") from error
    start_code, start_stdout, start_stderr = run(compose_cmd("up", "-d", MINECRAFT_SERVICE), timeout=120)
    if start_code != 0:
        raise RuntimeError("Settings were written, but Minecraft failed to restart. " + (start_stderr[-800:] or start_stdout[-800:]))
    wait_for_minecraft_ready()
    return {"settings": applied, "output": (stop_stdout + "\n" + start_stdout)[-1000:]}


def apply_minecraft_lifecycle_job(action):
    if action in {"restart", "update"}:
        backup_code, backup_stdout, backup_stderr = run_backup(timeout=None)
        if backup_code != 0:
            raise RuntimeError("Minecraft backup failed; lifecycle action was not run. " + (backup_stderr[-800:] or backup_stdout[-800:]))
    if action == "update":
        code, stdout, stderr = run(compose_cmd("pull", MINECRAFT_SERVICE), timeout=180)
        if code == 0:
            code, stdout2, stderr2 = run(compose_cmd("up", "-d", MINECRAFT_SERVICE), timeout=120)
            stdout, stderr = f"{stdout}\n{stdout2}", f"{stderr}\n{stderr2}"
    else:
        compose_action = ("up", "-d", MINECRAFT_SERVICE) if action == "start" else (action, MINECRAFT_SERVICE)
        code, stdout, stderr = run(compose_cmd(*compose_action), timeout=120)
    if code != 0:
        raise RuntimeError("Minecraft lifecycle command failed. " + (stderr[-800:] or stdout[-800:]))
    if action in {"start", "restart", "update"}:
        wait_for_minecraft_ready()
    return {"action": action, "state": host_state(), "output": stdout[-1000:]}


def json_bytes(value):
    return json.dumps(value, separators=(",", ":")).encode()


def run(command, timeout=15):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def read_json_payload(handler, maximum=16 * 1024):
    length = int(handler.headers.get("Content-Length", "0"))
    if length < 0 or length > maximum:
        raise ValueError("JSON request body is too large.")
    raw = handler.rfile.read(length)
    if len(raw) != length:
        raise ValueError("JSON request body was incomplete.")
    return json.loads(raw or b"{}")


def host_os_name():
    try:
        with open("/etc/os-release", "r", encoding="utf-8") as file:
            for line in file:
                if line.startswith("PRETTY_NAME="):
                    return shlex.split(line.partition("=")[2])[0]
    except (OSError, ValueError, IndexError):
        pass
    return os.name


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
    container_id = minecraft_container_id()
    health_code, health, _ = run(["docker", "inspect", "--format", "{{.State.Health.Status}}", container_id]) if container_id else (1, "", "Minecraft service is not running")
    if health_code != 0:
        health = "unknown"
    list_code, list_output, _ = run(["docker", "exec", container_id, "rcon-cli", "list"]) if container_id else (1, "", "Minecraft service is not running")
    player_match = re.search(r"There are\s+(\d+)\s+of a max of\s+(\d+)\s+players online", list_output, re.IGNORECASE)
    online_players = int(player_match.group(1)) if player_match else 0
    max_players = int(player_match.group(2)) if player_match else 0
    ps_code, ps_out, _ = run(["docker", "ps", "--format", "{{.ID}}|{{.Names}}|{{.Status}}|{{.Ports}}"])
    services = []
    if ps_code == 0:
        for row in ps_out.splitlines():
            short_id, name, status, ports = (row.split("|", 3) + ["", "", "", ""])[:4]
            is_minecraft = bool(container_id and (container_id.startswith(short_id) or short_id.startswith(container_id)))
            services.append({"name": name, "status": status, "ports": ports, **({"kind": "Minecraft"} if is_minecraft else {})})
    for site in read_websites():
        if site.get("kind", "hosted") != "hosted":
            continue
        site_state = website_state(site)
        services.append({"name": site["name"], "status": "running" if site.get("active") else "stopped", "ports": f"HTTPS · {site['domain']}", "kind": "Web app", "domain": site["domain"], "files": site_state["files"], "bytes": site_state["bytes"]})
    return {
        "host": {"hostname": os.uname().nodename, "os": host_os_name(), "architecture": os.uname().machine, "uptimeSeconds": round(uptime), "agentUptimeSeconds": round(time.time() - STARTED)},
        "memory": {"totalBytes": total, "availableBytes": available, "usedPercent": round((total - available) / total * 100, 1) if total else 0},
        "disk": {"totalBytes": disk.total, "freeBytes": disk.free, "usedPercent": round((disk.total - disk.free) / disk.total * 100, 1) if disk.total else 0},
        "network": network,
        "minecraft": {"container": MINECRAFT_SERVICE, "health": health, "portJava": 25565, "portBedrock": 19132, "onlinePlayers": online_players, "maxPlayers": max_players, "publicHostname": PUBLIC_HOSTNAME},
        "services": services,
    }


def safe_cloud_path(value):
    candidate = os.path.normpath(str(value or "").strip().lstrip("/"))
    reserved = os.path.basename(CLOUD_UPLOADS_ROOT)
    if not candidate or candidate == "." or candidate.startswith("..") or "\\" in candidate or reserved in candidate.split(os.sep):
        return None
    full = os.path.realpath(os.path.join(CLOUD_ROOT, candidate))
    uploads_root = os.path.realpath(CLOUD_UPLOADS_ROOT)
    if full == uploads_root or full.startswith(uploads_root + os.sep):
        return None
    return full if full == CLOUD_ROOT or full.startswith(CLOUD_ROOT + os.sep) else None


def cloud_files():
    result = []
    for root, directories, names in os.walk(CLOUD_ROOT):
        directories[:] = [directory for directory in directories if not (root == CLOUD_ROOT and directory == os.path.basename(CLOUD_UPLOADS_ROOT))]
        for name in names:
            full = os.path.join(root, name)
            try:
                relative = os.path.relpath(full, CLOUD_ROOT).replace(os.sep, "/")
                stat = os.stat(full)
            except OSError:
                continue
            result.append({"path": relative, "name": name, "size": stat.st_size, "modified": int(stat.st_mtime)})
    return sorted(result, key=lambda item: item["path"].lower())


def cloud_upload_directory(upload_id):
    if not re.fullmatch(r"[a-f0-9]{32}", str(upload_id or "")):
        return None
    return os.path.join(CLOUD_UPLOADS_ROOT, upload_id)


def read_cloud_upload(upload_id):
    directory = cloud_upload_directory(upload_id)
    if not directory or not os.path.isdir(directory):
        return None
    try:
        with open(os.path.join(directory, "upload.json"), "r", encoding="utf-8") as file:
            metadata = json.load(file)
        if not isinstance(metadata, dict) or not isinstance(metadata.get("size"), int) or isinstance(metadata.get("size"), bool) or metadata["size"] < 0:
            return None
        purpose = metadata.get("purpose", "cloud")
        if purpose == "cloud":
            if not safe_cloud_path(metadata.get("path")):
                return None
        elif purpose == "website-deploy":
            slug = str(metadata.get("siteSlug", ""))
            if not re.fullmatch(r"[a-z0-9-]{1,48}", slug) or not any(site.get("slug") == slug and site.get("kind", "hosted") == "hosted" for site in read_websites()):
                return None
        else:
            return None
        return directory, metadata
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def create_upload_session(metadata):
    size = metadata.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ValueError("Upload size must be a non-negative whole number.")
    if size > shutil.disk_usage(CLOUD_ROOT).free:
        raise OSError(errno.ENOSPC, "Not enough free host storage for this file.")
    upload_id = uuid.uuid4().hex
    directory = cloud_upload_directory(upload_id)
    os.mkdir(directory, 0o700)
    metadata = {**metadata, "created": int(time.time())}
    try:
        with open(os.path.join(directory, "upload.json"), "x", encoding="utf-8") as file:
            json.dump(metadata, file)
        with open(os.path.join(directory, "payload.bin"), "xb") as file:
            file.truncate(size)
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return upload_id, metadata


def create_cloud_upload(path_value, size):
    target = safe_cloud_path(path_value)
    if not target or os.path.isdir(target):
        raise ValueError("Choose a file name and a safe path inside Cloud storage.")
    relative = os.path.relpath(target, CLOUD_ROOT).replace(os.sep, "/")
    return create_upload_session({"purpose": "cloud", "path": relative, "size": size})


def create_site_deploy_upload(slug, size):
    site = next((entry for entry in read_websites() if entry.get("slug") == slug), None)
    if not site or site.get("kind", "hosted") != "hosted":
        raise ValueError("ZIP deployment requires an existing hosted site.")
    return create_upload_session({"purpose": "website-deploy", "siteSlug": slug, "size": size})


def cleanup_stale_cloud_uploads(max_age_seconds=24 * 60 * 60):
    cutoff = time.time() - max_age_seconds
    try:
        entries = os.scandir(CLOUD_UPLOADS_ROOT)
    except OSError:
        return
    with entries:
        for entry in entries:
            if not entry.is_dir(follow_symlinks=False):
                continue
            try:
                if entry.stat(follow_symlinks=False).st_mtime < cutoff:
                    shutil.rmtree(entry.path, ignore_errors=True)
            except OSError:
                continue


cleanup_stale_cloud_uploads()
def website_slug(value):
    slug = re.sub(r"[^a-z0-9-]+", "-", str(value or "").strip().lower()).strip("-")
    return slug[:48] or None
def website_domain(value):
    domain = str(value or "").strip().lower().rstrip(".")
    if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain):
        return None
    return domain

def website_url(value):
    candidate = str(value or "").strip()
    if not candidate or any(ord(character) < 32 or character.isspace() for character in candidate):
        return None
    try:
        parsed = urlparse(candidate)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return None
        parsed.port  # Force validation of an explicit port.
    except ValueError:
        return None
    return candidate

def normalized_website_url(value):
    parsed = urlparse(value)
    return parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower()).geturl()
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


def make_website_content_readable(public_root):
    if os.path.islink(public_root) or os.path.islink(os.path.dirname(public_root)):
        raise ValueError("Static website directories may not be symbolic links.")
    root_real = os.path.realpath(public_root)
    websites_real = os.path.realpath(WEBSITES_ROOT)
    try:
        if os.path.commonpath((websites_real, root_real)) != websites_real:
            raise ValueError("Website content path escapes the configured website directory.")
    except ValueError as error:
        raise ValueError("Website content path escapes the configured website directory.") from error
    os.makedirs(DATA_ROOT, exist_ok=True)
    os.chmod(DATA_ROOT, 0o711)
    if os.path.isdir(CLOUD_ROOT):
        os.chmod(CLOUD_ROOT, 0o700)
    os.chmod(WEBSITES_ROOT, 0o755)
    os.chmod(os.path.dirname(public_root), 0o755)
    for current, directories, files in os.walk(root_real, followlinks=False):
        for name in directories:
            path = os.path.join(current, name)
            if os.path.islink(path):
                raise ValueError("Static website content may not contain symbolic links.")
            os.chmod(path, 0o755)
        for name in files:
            path = os.path.join(current, name)
            if os.path.islink(path):
                raise ValueError("Static website content may not contain symbolic links.")
            os.chmod(path, 0o644)
        os.chmod(current, 0o755)


def website_state(site):
    kind = site.get("kind", "hosted")
    if kind == "external":
        return {**site, "kind": "external", "active": False, "files": 0, "bytes": 0}
    public_root = os.path.join(WEBSITES_ROOT, site["slug"], "public")
    files = sum(len(names) for _, _, names in os.walk(public_root)) if os.path.isdir(public_root) else 0
    byte_count = sum(os.path.getsize(os.path.join(root, name)) for root, _, names in os.walk(public_root) for name in names) if os.path.isdir(public_root) else 0
    return {**site, "kind": "hosted", "files": files, "bytes": byte_count}
def deploy_website_archive(site, archive_source):
    if site.get("kind", "hosted") != "hosted" or not re.fullmatch(r"[a-z0-9-]{1,48}", str(site.get("slug", ""))):
        raise ValueError("ZIP deployment requires an existing hosted site.")
    site_root = os.path.join(WEBSITES_ROOT, site["slug"])
    os.makedirs(site_root, exist_ok=True)
    target_root = os.path.join(site_root, "public")
    new_root = os.path.join(site_root, ".public-new")
    old_root = os.path.join(site_root, ".public-old")
    if not os.path.isdir(target_root) and os.path.isdir(old_root):
        os.replace(old_root, target_root)
    else:
        shutil.rmtree(old_root, ignore_errors=True)
    shutil.rmtree(new_root, ignore_errors=True)

    with tempfile.TemporaryDirectory(prefix=".tmpserver-deploy-", dir=site_root) as workspace:
        extract_root = os.path.join(workspace, "unzipped")
        os.mkdir(extract_root)
        try:
            with zipfile.ZipFile(archive_source) as archive:
                members = archive.infolist()
                if len(members) > 10000:
                    raise ValueError("ZIP contains too many files (maximum 10,000 entries).")
                expanded_size = sum(member.file_size for member in members)
                if expanded_size > shutil.disk_usage(site_root).free:
                    raise OSError(errno.ENOSPC, "Not enough free host storage to extract and deploy this ZIP.")
                safe_root = os.path.realpath(extract_root)
                for member in members:
                    member_path = os.path.realpath(os.path.join(extract_root, member.filename))
                    try:
                        within_root = os.path.commonpath([safe_root, member_path]) == safe_root
                    except ValueError:
                        within_root = False
                    if not within_root:
                        raise ValueError("ZIP contains an unsafe path.")
                archive.extractall(extract_root)
        except zipfile.BadZipFile as error:
            raise ValueError("The uploaded file is not a valid ZIP archive.") from error

        candidate = extract_root
        if not os.path.isfile(os.path.join(candidate, "index.html")):
            children = [name for name in os.listdir(candidate) if os.path.isdir(os.path.join(candidate, name))]
            if len(children) == 1 and os.path.isfile(os.path.join(candidate, children[0], "index.html")):
                candidate = os.path.join(candidate, children[0])
            else:
                raise ValueError("ZIP must contain index.html at its root or in one top-level folder.")
        os.replace(candidate, new_root)

    if os.path.isdir(target_root):
        os.replace(target_root, old_root)
    try:
        os.replace(new_root, target_root)
    except Exception:
        if os.path.isdir(old_root) and not os.path.exists(target_root):
            os.replace(old_root, target_root)
        raise
    shutil.rmtree(old_root, ignore_errors=True)
    make_website_content_readable(target_root)


def reload_caddy(sites):
    pending = os.path.join(WEBSITES_ROOT, ".tmpserver-caddy-sites.json")
    temporary = None
    try:
        with CADDY_SYNC_LOCK:
            fd, temporary = tempfile.mkstemp(prefix=".tmpserver-caddy-sites-", dir=WEBSITES_ROOT, text=True)
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(sites, file)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, pending)
            temporary = None
            if not os.path.isfile(CADDY_SYNC_SCRIPT) or not os.access(CADDY_SYNC_SCRIPT, os.X_OK):
                return False, "Install the root-owned Caddy sync helper and exact sudoers rule from ops/ before changing hosted routes."
            code, stdout, stderr = run(["sudo", "-n", CADDY_SYNC_SCRIPT], timeout=60)
            if code != 0:
                detail = stderr[-800:] or stdout[-800:]
                return False, detail or "Caddy sync helper failed; the site entry was not changed."
            return True, ""
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    finally:
        if temporary and os.path.exists(temporary):
            os.remove(temporary)
        try:
            os.remove(pending)
        except FileNotFoundError:
            pass
def owner_user(user):
    return bool(user and str(user.get("email", "")).strip().lower() == OWNER_EMAIL)


def minecraft_settings():
    values = {"viewDistance": 0, "simulationDistance": 0, "maxPlayers": 0, "whitelist": False}
    try:
        with open(COMPOSE_FILE, "r", encoding="utf-8") as file:
            text = file.read()
        for key, pattern in [
            ("viewDistance", r"(?m)^\s*VIEW_DISTANCE:\s*['\"]?(\d+)['\"]?\s*(?:#.*)?$"),
            ("simulationDistance", r"(?m)^\s*SIMULATION_DISTANCE:\s*['\"]?(\d+)['\"]?\s*(?:#.*)?$"),
            ("maxPlayers", r"(?m)^\s*MAX_PLAYERS:\s*['\"]?(\d+)['\"]?\s*(?:#.*)?$"),
        ]:
            match = re.search(pattern, text)
            if match:
                values[key] = int(match.group(1))
        values["whitelist"] = bool(re.search(r"(?mi)^\s*ENABLE_WHITELIST:\s*['\"]?true['\"]?\s*(?:#.*)?$", text))
    except (OSError, ValueError):
        pass
    return values


def validate_minecraft_settings(payload):
    if not isinstance(payload, dict):
        raise ValueError("Minecraft settings must be a JSON object.")
    parsed = {}
    for key, label, minimum, maximum in [
        ("viewDistance", "View distance", 2, 32),
        ("simulationDistance", "Simulation distance", 2, 32),
        ("maxPlayers", "Maximum players", 1, 1000),
    ]:
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError(f"{label} must be a whole number.")
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{label} must be a whole number.")
        if isinstance(value, str) and str(number) != value.strip():
            raise ValueError(f"{label} must be a whole number.")
        if not minimum <= number <= maximum:
            raise ValueError(f"{label} must be between {minimum} and {maximum}.")
        parsed[key] = number
    whitelist = payload.get("whitelist", minecraft_settings()["whitelist"])
    if not isinstance(whitelist, bool):
        raise ValueError("Whitelist enforcement must be true or false.")
    parsed["whitelist"] = whitelist
    with open(COMPOSE_FILE, "r", encoding="utf-8") as file:
        compose_text = file.read()
    for key, value_pattern in [
        ("VIEW_DISTANCE", r"\d+"),
        ("SIMULATION_DISTANCE", r"\d+"),
        ("MAX_PLAYERS", r"\d+"),
        ("ENABLE_WHITELIST", r"(?i:true|false)"),
    ]:
        pattern = re.compile(rf"(?m)^\s*{key}:\s*(?P<quote>['\"]?){value_pattern}(?P=quote)\s*(?:#.*)?$")
        if len(list(pattern.finditer(compose_text))) != 1:
            raise ValueError(f"Minecraft compose file must contain exactly one supported {key} setting.")
    return parsed


def update_minecraft_settings(payload):
    settings = validate_minecraft_settings(payload)
    with open(COMPOSE_FILE, "r", encoding="utf-8") as file:
        text = file.read()
    values = {
        "VIEW_DISTANCE": str(settings["viewDistance"]),
        "SIMULATION_DISTANCE": str(settings["simulationDistance"]),
        "MAX_PLAYERS": str(settings["maxPlayers"]),
        "ENABLE_WHITELIST": "true" if settings["whitelist"] else "false",
    }
    for key, value in values.items():
        value_pattern = r"\d+" if key != "ENABLE_WHITELIST" else r"(?i:true|false)"
        pattern = re.compile(rf"(?m)^(?P<prefix>\s*{key}:\s*)(?P<quote>['\"]?)(?P<value>{value_pattern})(?P=quote)(?P<suffix>\s*(?:#.*)?)$")
        matches = list(pattern.finditer(text))
        if len(matches) != 1:
            raise ValueError(f"Minecraft compose file must contain exactly one supported {key} setting.")
        match = matches[0]
        replacement = f"{match.group('prefix')}{match.group('quote')}{value}{match.group('quote')}{match.group('suffix')}"
        text = text[:match.start()] + replacement + text[match.end():]
    backup_path = f"{COMPOSE_FILE}.settings.bak"
    shutil.copy2(COMPOSE_FILE, backup_path)
    directory = os.path.dirname(COMPOSE_FILE)
    fd, temporary = tempfile.mkstemp(prefix=".tmpserver-compose-", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        shutil.copystat(COMPOSE_FILE, temporary)
        os.replace(temporary, COMPOSE_FILE)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return minecraft_settings()
def admin_snapshot():
    storage = []
    code, output, _ = run(["df", "-P", "-B1", "/", CLOUD_ROOT, WEBSITES_ROOT])
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
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        origin = self.cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
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
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        origin = self.cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Vary", "Origin")
        self.end_headers()
        with open(path, "rb") as file:
            shutil.copyfileobj(file, self.wfile)

    def cors_origin(self):
        origin = self.headers.get("Origin", "").rstrip("/")
        return origin if origin in ALLOWED_ORIGINS else ""

    def require_owner(self):
        user = auth_user(self)
        if not user:
            self.send_json(401, {"error": "authenticated Supabase owner session required"})
            return None
        if not owner_user(user):
            self.send_json(403, {"error": "Only the configured TMP Server owner may access host data."})
            return None
        return user

    def do_OPTIONS(self):
        origin = self.cors_origin()
        if not origin:
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/health":
            self.send_json(200, {"ok": True, "service": "tmpserver-host-agent"})
            return
        if self.path == "/api/cloud/files":
            if not self.require_owner():
                return
            files = cloud_files()
            storage = shutil.disk_usage(CLOUD_ROOT)
            self.send_json(200, {"files": files, "usedBytes": sum(item["size"] for item in files), "availableBytes": storage.free, "totalBytes": storage.total})
            return
        if self.path == "/api/websites":
            if not self.require_owner():
                return
            self.send_json(200, {"sites": [website_state(site) for site in read_websites()]})
            return
        parsed = urlparse(self.path)
        if parsed.path == "/api/cloud/download":
            if not self.require_owner():
                return
            path = safe_cloud_path(parse_qs(parsed.query).get("path", [""])[0])
            if not path or not os.path.isfile(path):
                self.send_json(404, {"error": "file not found"})
                return
            self.send_file(path)
            return
        if self.path == "/api/state":
            if not self.require_owner():
                return
            self.send_json(200, host_state())
            return
        if self.path == "/api/settings":
            user = self.require_owner()
            if not user:
                return
            backup_path = os.path.join(CLOUD_ROOT, "minecraft-latest.tar.gz")
            backup_stat = os.stat(backup_path) if os.path.isfile(backup_path) else None
            self.send_json(200, {"host": host_state()["host"], "minecraft": minecraft_settings(), "agent": {"status": "connected", "uptimeSeconds": round(time.time() - STARTED)}, "backup": {"present": bool(backup_stat), "bytes": backup_stat.st_size if backup_stat else 0, "modified": int(backup_stat.st_mtime) if backup_stat else 0}, "permissions": {"owner": owner_user(user)}, "admin": admin_snapshot()})
            return
        job_match = re.fullmatch(r"/api/minecraft/jobs/([a-f0-9]{32})", urlparse(self.path).path)
        if job_match:
            if not self.require_owner():
                return
            job = minecraft_job_snapshot(job_match.group(1))
            if not job:
                self.send_json(404, {"error": "Minecraft job not found or expired."})
                return
            self.send_json(200, {"ok": True, **job})
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        cloud_upload_match = re.fullmatch(r"/api/cloud/uploads/([a-f0-9]{32})/(chunk/(\d+)|finish|abort)", self.path)
        if self.path in {"/api/cloud/upload", "/api/cloud/upload/start", "/api/cloud/delete"} or cloud_upload_match:
            if not self.require_owner():
                return
            try:
                if self.path == "/api/cloud/upload/start":
                    payload = read_json_payload(self, maximum=4096)
                    upload_id, metadata = create_cloud_upload(payload.get("path"), payload.get("size"))
                    chunk_count = (metadata["size"] + CLOUD_UPLOAD_CHUNK_SIZE - 1) // CLOUD_UPLOAD_CHUNK_SIZE
                    self.send_json(201, {"ok": True, "uploadId": upload_id, "chunkSize": CLOUD_UPLOAD_CHUNK_SIZE, "totalChunks": chunk_count})
                    return
                if cloud_upload_match:
                    upload_id, action, chunk_text = cloud_upload_match.groups()
                    with CLOUD_UPLOAD_LOCK:
                        record = read_cloud_upload(upload_id)
                        if not record:
                            self.send_json(404, {"error": "Upload session not found or expired."})
                            return
                        directory, metadata = record
                        if action == "abort":
                            shutil.rmtree(directory, ignore_errors=True)
                            self.send_json(200, {"ok": True})
                            return
                        if action.startswith("chunk/"):
                            index = int(chunk_text)
                            size = metadata["size"]
                            chunk_count = (size + CLOUD_UPLOAD_CHUNK_SIZE - 1) // CLOUD_UPLOAD_CHUNK_SIZE
                            if index < 0 or index >= chunk_count:
                                self.send_json(400, {"error": "Chunk number is outside this upload."})
                                return
                            expected_length = min(CLOUD_UPLOAD_CHUNK_SIZE, size - index * CLOUD_UPLOAD_CHUNK_SIZE)
                            try:
                                length = int(self.headers.get("Content-Length", "-1"))
                            except ValueError:
                                length = -1
                            if length != expected_length:
                                self.send_json(400, {"error": "Chunk size does not match the expected range."})
                                return
                            if length > CLOUD_UPLOAD_CHUNK_SIZE:
                                self.send_json(413, {"error": "Upload chunk is too large."})
                                return
                            data_path = os.path.join(directory, "payload.bin")
                            marker = os.path.join(directory, f"chunk-{index:08d}.done")
                            try:
                                if not os.path.exists(marker) and shutil.disk_usage(CLOUD_ROOT).free < length:
                                    self.send_json(507, {"error": "Host storage ran out of free space during this upload."})
                                    return
                                try:
                                    os.remove(marker)
                                except FileNotFoundError:
                                    pass
                                remaining = length
                                with open(data_path, "r+b") as file:
                                    file.seek(index * CLOUD_UPLOAD_CHUNK_SIZE)
                                    while remaining:
                                        block = self.rfile.read(min(64 * 1024, remaining))
                                        if not block:
                                            raise ValueError("Upload chunk ended before all bytes arrived.")
                                        file.write(block)
                                        remaining -= len(block)
                                    file.flush()
                                    os.fsync(file.fileno())
                                marker_temp = marker + ".tmp"
                                with open(marker_temp, "w", encoding="ascii") as file:
                                    file.write("ok")
                                os.replace(marker_temp, marker)
                            except OSError as error:
                                if error.errno in {errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)}:
                                    self.send_json(507, {"error": "Host storage ran out of free space during this upload."})
                                    return
                                raise
                            self.send_json(200, {"ok": True, "chunk": index, "totalChunks": chunk_count})
                            return
                        size = metadata["size"]
                        chunk_count = (size + CLOUD_UPLOAD_CHUNK_SIZE - 1) // CLOUD_UPLOAD_CHUNK_SIZE
                        if any(not os.path.isfile(os.path.join(directory, f"chunk-{index:08d}.done")) for index in range(chunk_count)):
                            self.send_json(409, {"error": "Upload is incomplete; some chunks have not arrived."})
                            return
                        data_path = os.path.join(directory, "payload.bin")
                        if not os.path.isfile(data_path) or os.path.getsize(data_path) != size:
                            self.send_json(400, {"error": "Staged upload file is invalid."})
                            return
                        if metadata.get("purpose", "cloud") == "website-deploy":
                            sites = read_websites()
                            site = next((entry for entry in sites if entry.get("slug") == metadata.get("siteSlug") and entry.get("kind", "hosted") == "hosted"), None)
                            if not site:
                                self.send_json(404, {"error": "Hosted site was removed before its ZIP upload completed."})
                                return
                            deploy_website_archive(site, data_path)
                            site["updated"] = int(time.time())
                            write_websites(sites)
                            shutil.rmtree(directory, ignore_errors=True)
                            self.send_json(200, {"ok": True, "site": website_state(site)})
                            return
                        target = safe_cloud_path(metadata.get("path"))
                        if not target or os.path.isdir(target):
                            self.send_json(400, {"error": "Upload target or staged file is invalid."})
                            return
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        os.replace(data_path, target)
                        shutil.rmtree(directory, ignore_errors=True)
                        file_info = next((item for item in cloud_files() if item["path"] == metadata["path"]), None)
                        self.send_json(200, {"ok": True, "file": file_info})
                        return
                if self.path == "/api/cloud/upload":
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 0:
                        self.send_json(400, {"error": "Invalid upload length."})
                        return
                    content_type = self.headers.get("Content-Type", "")
                    if cgi is None:
                        self.send_json(410, {"error": "Use the chunked Cloud upload interface; the legacy multipart endpoint is unavailable on this Python version."})
                        return
                    if "multipart/form-data" not in content_type.lower():
                        self.send_json(400, {"error": "Upload a file using multipart/form-data."})
                        return
                    form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type, "CONTENT_LENGTH": str(length)})
                    item = form["file"] if "file" in form else None
                    relative = (form.getfirst("path", "") if "path" in form else "") or (item.filename if item else "")
                    target = safe_cloud_path(relative)
                    if not item or not target:
                        self.send_json(400, {"error": "Choose a file and a safe path inside Cloud storage."})
                        return
                    if os.path.isdir(target):
                        self.send_json(400, {"error": "The upload target is a directory."})
                        return
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    descriptor, temporary = tempfile.mkstemp(prefix=".tmpserver-upload-", dir=os.path.dirname(target))
                    try:
                        with os.fdopen(descriptor, "wb") as file:
                            shutil.copyfileobj(item.file, file, length=1024 * 1024)
                            file.flush()
                            os.fsync(file.fileno())
                        os.replace(temporary, target)
                    finally:
                        if os.path.exists(temporary):
                            os.remove(temporary)
                    file_info = next((entry for entry in cloud_files() if os.path.realpath(os.path.join(CLOUD_ROOT, entry["path"])) == target), None)
                    self.send_json(200, {"ok": True, "file": file_info})
                    return
                payload = read_json_payload(self, maximum=16 * 1024)
                target = safe_cloud_path(payload.get("path"))
                if not target or not os.path.isfile(target):
                    self.send_json(404, {"error": "file not found"})
                    return
                os.remove(target)
                self.send_json(200, {"ok": True, "path": payload.get("path")})
                return
            except Exception as error:
                status = 507 if isinstance(error, OSError) and error.errno in {errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)} else 400
                self.send_json(status, {"error": f"cloud operation failed: {error}"})
                return
        website_match = re.fullmatch(r"/api/websites/([a-z0-9-]+)/(deploy/start|deploy|lifecycle|delete)", self.path)
        if self.path not in {"/api/minecraft/whitelist", "/api/minecraft/command", "/api/minecraft/lifecycle", "/api/minecraft/backup", "/api/minecraft/settings", "/api/websites"} and not website_match:
            self.send_json(404, {"error": "not found"})
            return
        user = auth_user(self)
        if not user:
            self.send_json(401, {"error": "authenticated Supabase session required"})
            return
        if not owner_user(user):
            self.send_json(403, {"error": "Only the configured TMP Server owner can run host controls."})
            return
        if self.path == "/api/minecraft/settings":
            try:
                payload = read_json_payload(self)
                settings = validate_minecraft_settings(payload)
                job_id = start_minecraft_job("settings", lambda: apply_minecraft_settings_job(settings))
                self.send_json(202, {"ok": True, "jobId": job_id, "status": "running"})
                return
            except RuntimeError as error:
                self.send_json(409, {"error": str(error)})
                return
            except (OSError, ValueError, json.JSONDecodeError) as error:
                self.send_json(400, {"error": str(error)})
                return
        if self.path == "/api/websites" or website_match:
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0:
                    self.send_json(400, {"error": "Invalid website upload length."})
                    return
                sites = read_websites()
                if website_match and website_match.group(2) == "deploy/start":
                    payload = json.loads(self.rfile.read(length) or b"{}")
                    upload_id, metadata = create_site_deploy_upload(website_match.group(1), payload.get("size"))
                    chunk_count = (metadata["size"] + CLOUD_UPLOAD_CHUNK_SIZE - 1) // CLOUD_UPLOAD_CHUNK_SIZE
                    self.send_json(201, {"ok": True, "uploadId": upload_id, "chunkSize": CLOUD_UPLOAD_CHUNK_SIZE, "totalChunks": chunk_count})
                    return
                if website_match and website_match.group(2) == "deploy":
                    content_type = self.headers.get("Content-Type", "")
                    if cgi is None:
                        self.send_json(410, {"error": "Use the chunked ZIP deployment interface; the legacy multipart endpoint is unavailable on this Python version."})
                        return
                    if "multipart/form-data" not in content_type:
                        self.send_json(400, {"error": "Upload a ZIP file using multipart/form-data."})
                        return
                    form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type, "CONTENT_LENGTH": str(length)})
                    item = form["file"] if "file" in form else None
                    slug = website_match.group(1)
                    site = next((entry for entry in sites if entry["slug"] == slug), None)
                    if not item or not site or site.get("kind", "hosted") != "hosted" or not str(item.filename or "").lower().endswith(".zip"):
                        self.send_json(400, {"error": "Choose a ZIP file for an existing website."})
                        return
                    try:
                        deploy_website_archive(site, item.file)
                    except OSError as error:
                        if error.errno in {errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)}:
                            self.send_json(507, {"error": "Not enough free host storage to deploy this ZIP."})
                            return
                        raise
                    site["updated"] = int(time.time())
                    write_websites(sites)
                    self.send_json(200, {"ok": True, "site": website_state(site)})
                    return
                payload = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/websites":
                    name = str(payload.get("name", "")).strip()
                    slug = website_slug(payload.get("slug") or name)
                    kind = str(payload.get("kind", "hosted")).strip().lower()
                    if not name or not slug or kind not in {"hosted", "external"}:
                        self.send_json(400, {"error": "Enter a site name and choose hosted or external link."})
                        return
                    if any(site.get("slug") == slug for site in sites):
                        self.send_json(409, {"error": "A site with that name already exists."})
                        return
                    created = int(time.time())
                    if kind == "external":
                        url = website_url(payload.get("url"))
                        if not url:
                            self.send_json(400, {"error": "Enter a valid absolute HTTP or HTTPS URL."})
                            return
                        normalized_url = normalized_website_url(url)
                        if any(site.get("kind") == "external" and normalized_website_url(site.get("url", "")) == normalized_url for site in sites if site.get("url")):
                            self.send_json(409, {"error": "That external link is already saved."})
                            return
                        site = {"kind": "external", "name": name[:80], "slug": slug, "url": url, "active": False, "created": created, "updated": created}
                    else:
                        domain = website_domain(payload.get("domain"))
                        if not domain:
                            self.send_json(400, {"error": "Enter a valid hosted-site domain."})
                            return
                        if any(site.get("kind", "hosted") == "hosted" and site.get("domain") == domain for site in sites):
                            self.send_json(409, {"error": "A hosted website with that domain already exists."})
                            return
                        os.makedirs(os.path.join(WEBSITES_ROOT, slug, "public"), exist_ok=True)
                        site = {"kind": "hosted", "name": name[:80], "slug": slug, "domain": domain, "active": False, "created": created, "updated": created}
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
                    if site.get("kind", "hosted") != "hosted":
                        self.send_json(400, {"error": "External links do not have a server lifecycle."})
                        return
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
                    remaining = [item for item in sites if item["slug"] != slug]
                    is_hosted = site.get("kind", "hosted") == "hosted"
                    was_active = is_hosted and bool(site.get("active"))
                    if was_active:
                        ok, detail = reload_caddy(remaining)
                        if not ok:
                            self.send_json(502, {"error": "Could not remove the active website route; the site record and files were preserved.", "detail": detail})
                            return
                    site_directory = os.path.join(WEBSITES_ROOT, slug) if is_hosted else ""
                    tombstone = os.path.join(WEBSITES_ROOT, f".deleted-{slug}-{uuid.uuid4().hex}") if is_hosted else ""
                    moved_directory = False
                    try:
                        if is_hosted and os.path.lexists(site_directory):
                            os.replace(site_directory, tombstone)
                            moved_directory = True
                        write_websites(remaining)
                    except OSError as error:
                        if moved_directory and os.path.lexists(tombstone):
                            os.replace(tombstone, site_directory)
                        if was_active:
                            reload_caddy(sites)
                        self.send_json(500, {"error": "Website deletion failed; the site record and files were preserved where possible.", "detail": str(error)})
                        return
                    cleanup_warning = ""
                    if moved_directory:
                        try:
                            if os.path.islink(tombstone) or os.path.isfile(tombstone):
                                os.unlink(tombstone)
                            else:
                                shutil.rmtree(tombstone)
                        except OSError as error:
                            cleanup_warning = f"The website entry was removed, but some files could not be deleted: {error}"
                    self.send_json(200, {"ok": True, "slug": slug, "warning": cleanup_warning})
                    return
                self.send_json(400, {"error": "Unsupported website operation."})
                return
            except (OSError, ValueError, json.JSONDecodeError) as error:
                status = 507 if isinstance(error, OSError) and error.errno in {errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)} else 400
                self.send_json(status, {"error": f"Website operation failed: {error}"})
                return
        try:
            payload = read_json_payload(self)
            username = str(payload.get("username", "")).strip()
            action = str(payload.get("action", "add")).strip().lower()
            command = str(payload.get("command", "")).strip()
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "invalid JSON"})
            return
        if self.path == "/api/minecraft/backup":
            try:
                job_id = start_minecraft_job("backup", backup_job_operation)
            except RuntimeError as error:
                self.send_json(409, {"error": str(error)})
                return
            self.send_json(202, {"ok": True, "action": "backup", "jobId": job_id, "status": "running"})
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
            try:
                job_id = start_minecraft_job(f"lifecycle-{lifecycle}", lambda: apply_minecraft_lifecycle_job(lifecycle))
            except RuntimeError as error:
                self.send_json(409, {"error": str(error)})
                return
            self.send_json(202, {"ok": True, "action": lifecycle, "jobId": job_id, "status": "running"})
            return
        container_id = minecraft_container_id()
        if not container_id:
            self.send_json(409, {"error": "Configured Minecraft Compose service is not running."})
            return
        code, stdout, stderr = run(["docker", "exec", container_id, "rcon-cli", *command_args])
        if code != 0:
            self.send_json(502, {"error": "Minecraft command failed", "detail": stderr[-300:]})
            return
        self.send_json(200, {"ok": True, "action": action if self.path.endswith("whitelist") else "command", "username": username if self.path.endswith("whitelist") else None, "output": stdout[-1000:]})


if __name__ == "__main__":
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
