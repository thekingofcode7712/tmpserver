export type ServiceState = "running" | "stopped" | "degraded" | "restarting";
export type ServiceKind = "Minecraft" | "Container" | "Web app" | "Database" | "Proxy";

export type Service = {
  id: string;
  name: string;
  kind: ServiceKind;
  state: ServiceState;
  health: number;
  cpu: number;
  memory: number;
  memoryLimit: number;
  port: number;
  domain?: string;
  uptime: string;
  restarts: number;
  boot: boolean;
  checkEvery: string;
  restartPolicy: string;
  dependencies: string[];
  accent: string;
  description: string;
};

export type Activity = {
  id: number;
  time: string;
  service: string;
  message: string;
  tone: "info" | "success" | "warning" | "danger";
};

export const initialServices: Service[] = [
  {
    id: "minecraft-survival",
    name: "minecraft-survival",
    kind: "Minecraft",
    state: "running",
    health: 100,
    cpu: 18,
    memory: 63,
    memoryLimit: 8192,
    port: 25565,
    domain: "mc.tmpserver.local",
    uptime: "17d 04h",
    restarts: 0,
    boot: true,
    checkEvery: "15 sec",
    restartPolicy: "on-failure · 5 / 10m",
    dependencies: ["postgres-main"],
    accent: "cyan",
    description: "Paper 1.21.4 · survival node",
  },
  {
    id: "traefik-edge",
    name: "traefik-edge",
    kind: "Proxy",
    state: "running",
    health: 100,
    cpu: 3,
    memory: 8,
    memoryLimit: 512,
    port: 443,
    domain: "edge.tmpserver.local",
    uptime: "21d 12h",
    restarts: 0,
    boot: true,
    checkEvery: "30 sec",
    restartPolicy: "always · 3s backoff",
    dependencies: [],
    accent: "blue",
    description: "TLS ingress · 14 routes",
  },
  {
    id: "postgres-main",
    name: "postgres-main",
    kind: "Database",
    state: "running",
    health: 100,
    cpu: 12,
    memory: 41,
    memoryLimit: 4096,
    port: 5432,
    domain: "db.tmpserver.internal",
    uptime: "34d 02h",
    restarts: 0,
    boot: true,
    checkEvery: "15 sec",
    restartPolicy: "always · 5s backoff",
    dependencies: [],
    accent: "violet",
    description: "PostgreSQL 16 · primary",
  },
  {
    id: "vaultwarden",
    name: "vaultwarden",
    kind: "Web app",
    state: "running",
    health: 98,
    cpu: 5,
    memory: 14,
    memoryLimit: 1024,
    port: 8080,
    domain: "vault.tmpserver.local",
    uptime: "11d 17h",
    restarts: 0,
    boot: true,
    checkEvery: "30 sec",
    restartPolicy: "on-failure · 5 / 10m",
    dependencies: ["postgres-main"],
    accent: "amber",
    description: "Password vault · protected route",
  },
  {
    id: "paperless-ngx",
    name: "paperless-ngx",
    kind: "Web app",
    state: "degraded",
    health: 72,
    cpu: 27,
    memory: 71,
    memoryLimit: 2048,
    port: 8000,
    domain: "docs.tmpserver.local",
    uptime: "02d 08h",
    restarts: 2,
    boot: true,
    checkEvery: "30 sec",
    restartPolicy: "on-failure · 5 / 10m",
    dependencies: ["postgres-main"],
    accent: "orange",
    description: "Document archive · queue lag",
  },
  {
    id: "tmp-web-app",
    name: "tmp-web-app",
    kind: "Web app",
    state: "running",
    health: 100,
    cpu: 4,
    memory: 18,
    memoryLimit: 1024,
    port: 8081,
    domain: "app.tmpserver.local",
    uptime: "06d 13h",
    restarts: 0,
    boot: true,
    checkEvery: "30 sec",
    restartPolicy: "on-failure · 5 / 10m",
    dependencies: ["postgres-main"],
    accent: "blue",
    description: "Owner web app · HTTPS route",
  },
  {
    id: "gitea",
    name: "gitea",
    kind: "Web app",
    state: "running",
    health: 100,
    cpu: 7,
    memory: 24,
    memoryLimit: 2048,
    port: 3000,
    domain: "git.tmpserver.local",
    uptime: "28d 05h",
    restarts: 0,
    boot: true,
    checkEvery: "30 sec",
    restartPolicy: "always · 3s backoff",
    dependencies: ["postgres-main"],
    accent: "green",
    description: "Git service · internal only",
  },
  {
    id: "uptime-kuma",
    name: "uptime-kuma",
    kind: "Container",
    state: "running",
    health: 100,
    cpu: 2,
    memory: 9,
    memoryLimit: 512,
    port: 3001,
    domain: "status.tmpserver.local",
    uptime: "28d 05h",
    restarts: 0,
    boot: true,
    checkEvery: "60 sec",
    restartPolicy: "always · 3s backoff",
    dependencies: [],
    accent: "pink",
    description: "Monitoring · 42 probes",
  },
];

export const initialActivity: Activity[] = [
  { id: 1, time: "21:51:44", service: "paperless-ngx", message: "health check latency above 800ms", tone: "warning" },
  { id: 2, time: "21:47:18", service: "minecraft-survival", message: "health check passed · 42 players max", tone: "success" },
  { id: 3, time: "21:41:03", service: "vaultwarden", message: "backup snapshot completed", tone: "info" },
  { id: 4, time: "21:36:27", service: "paperless-ngx", message: "worker restarted by recovery policy", tone: "danger" },
  { id: 5, time: "21:29:11", service: "tmp-node-01", message: "disk usage crossed 70% threshold", tone: "warning" },
];

export const initialLogs = [
  { time: "21:51:44.201", level: "WARN", service: "paperless-ngx", message: "consumer latency 842ms (threshold 800ms)" },
  { time: "21:51:16.838", level: "INFO", service: "minecraft-survival", message: "autosave completed in 184ms" },
  { time: "21:50:02.442", level: "INFO", service: "traefik-edge", message: "renewed certificate for 3 routes" },
  { time: "21:49:37.037", level: "INFO", service: "postgres-main", message: "checkpoint complete: wrote 31 buffers" },
  { time: "21:48:09.115", level: "WARN", service: "tmp-node-01", message: "disk usage 72% · notify owner" },
];

export const utilization = [42, 46, 44, 58, 51, 53, 49, 63, 58, 61, 57, 66, 60, 62, 64, 59, 68, 65, 71, 67, 69, 63, 61, 64];
