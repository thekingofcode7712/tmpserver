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
  network: { interface: string; linkMbps: number; sampleSeconds: number; rxBytes: number; txBytes: number; rxBytesPerSecond: number; txBytesPerSecond: number; rxPacketsPerSecond: number; txPacketsPerSecond: number; rxDropped: number; txDropped: number };
  minecraft: { container: string; health: string; portJava: number; portBedrock: number; onlinePlayers: number; maxPlayers: number; publicHostname: string };
  services: { name: string; status: string; ports: string; kind?: ServiceKind; domain?: string; files?: number; bytes?: number }[];
};

export type CloudFile = { path: string; name: string; size: number; modified: number };
export type Website = { kind?: "hosted" | "external"; name: string; slug: string; domain?: string; url?: string; active: boolean; created: number; updated: number; files: number; bytes: number };
export type SettingsSnapshot = { host: HostState["host"]; minecraft: { viewDistance: number; simulationDistance: number; maxPlayers: number; whitelist: boolean }; agent: { status: string; uptimeSeconds: number }; backup: { present: boolean; bytes: number; modified: number }; permissions: { owner: boolean }; admin: { storage: { filesystem: string; mount: string; totalBytes: number; usedBytes: number; freeBytes: number; usedPercent: number }[]; docker: { version: string; root: string; cpus: number; memoryBytes: number }; firewall: { active: boolean; defaultIncoming: string; rules: string[] }; capabilities: { kvm: boolean; lxcInstalled: boolean; docker: boolean; nativeVmManagement: boolean }; failedUnits: string[] } };

// Live data is intentionally empty until a real supervisor agent is connected.
// Never populate these arrays with representative values: the dashboard must not
// present simulated uptime, metrics, logs, or service state as production facts.
export const initialServices: Service[] = [];
export const initialActivity: Activity[] = [];
export const initialLogs: LogEntry[] = [];
export const utilization: number[] = [];
