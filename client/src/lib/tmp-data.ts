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

export type LogEntry = {
  time: string;
  level: "INFO" | "WARN" | "ERROR";
  service: string;
  message: string;
};

export type HostState = {
  host: { hostname: string; os: string; architecture: string; uptimeSeconds: number; agentUptimeSeconds: number };
  memory: { totalBytes: number; availableBytes: number; usedPercent: number };
  disk: { totalBytes: number; freeBytes: number; usedPercent: number };
  network: { interface: string; linkMbps: number; rxBytes: number; txBytes: number; rxBytesPerSecond: number; txBytesPerSecond: number; rxPacketsPerSecond: number; txPacketsPerSecond: number };
  minecraft: { container: string; health: string; portJava: number; portBedrock: number; onlinePlayers: number; maxPlayers: number; publicHostname: string };
  services: { name: string; status: string; ports: string }[];
};

export type CloudFile = { path: string; name: string; size: number; modified: number };

// Live data is intentionally empty until a real supervisor agent is connected.
// Never populate these arrays with representative values: the dashboard must not
// present simulated uptime, metrics, logs, or service state as production facts.
export const initialServices: Service[] = [];
export const initialActivity: Activity[] = [];
export const initialLogs: LogEntry[] = [];
export const utilization: number[] = [];
