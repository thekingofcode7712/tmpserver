import { useEffect, useMemo, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import {
  Activity as ActivityIcon,
  AlertTriangle,
  Archive,
  ArrowUpRight,
  Box,
  Boxes,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  CloudCog,
  Cpu,
  Database,
  FileClock,
  Filter,
  HardDrive,
  LayoutDashboard,
  LockKeyhole,
  LogOut,
  MemoryStick,
  Menu,
  MoreHorizontal,
  Network,
  Play,
  Plus,
  RefreshCw,
  Search,
  Server,
  Settings2,
  ShieldCheck,
  Square,
  TerminalSquare,
  Trash2,
  TriangleAlert,
  Users,
  X,
  Zap,
} from "lucide-react";
import {
  initialActivity,
  initialLogs,
  initialServices,
  type Activity,
  type HostState,
  type Service,
  type ServiceKind,
  type ServiceState,
  utilization,
} from "@/lib/tmp-data";
import { isAllowedSession, isOwnerSession, ownerEmail, sessionLabel, supabase, supabaseConfigured } from "@/lib/supabase";

const staticPages = import.meta.env.VITE_STATIC_ONLY === "true";
const hostApiUrl = (import.meta.env.VITE_HOST_API_URL as string | undefined)?.trim() ?? "";

type NavKey = "overview" | "services" | "nodes" | "logs" | "alerts" | "settings";

const navItems: { id: NavKey; label: string; icon: typeof LayoutDashboard; count?: string }[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "services", label: "Services", icon: Boxes },
  { id: "nodes", label: "Nodes", icon: Server },
  { id: "logs", label: "Logs", icon: FileClock },
  { id: "alerts", label: "Alerts", icon: TriangleAlert },
];

function Logo() {
  return <div className="brand"><span className="brand-mark"><span /></span><span><strong>TMP</strong><em>SERVER</em></span></div>;
}

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index > 1 ? 1 : 0)} ${units[index]}`;
}

function formatUptime(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  const days = Math.floor(seconds / 86400); const hours = Math.floor((seconds % 86400) / 3600); const minutes = Math.floor((seconds % 3600) / 60);
  return days ? `${days}d ${hours}h` : hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

function StatusDot({ state }: { state: ServiceState }) {
  return <span className={`status-dot ${state}`} aria-label={state} />;
}

function StateBadge({ state }: { state: ServiceState }) {
  const labels: Record<ServiceState, string> = { running: "Running", stopped: "Stopped", degraded: "Degraded", restarting: "Restarting" };
  return <span className={`state-badge ${state}`}><StatusDot state={state} />{labels[state]}</span>;
}

function MetricCard({ label, value, suffix, detail, tone = "blue", icon: Icon, children }: { label: string; value: string; suffix?: string; detail: string; tone?: string; icon: typeof Cpu; children?: React.ReactNode }) {
  return <div className="metric-card">
    <div className="metric-head"><span>{label}</span><span className={`metric-icon ${tone}`}><Icon size={15} /></span></div>
    <div className="metric-value">{value}<small>{suffix}</small></div>
    <div className="metric-detail">{detail}</div>
    {children}
  </div>;
}

function TinySparkline({ color = "#39d9ff", points = utilization }: { color?: string; points?: number[] }) {
  const path = points.map((value, index) => `${index === 0 ? "M" : "L"} ${index * 8} ${38 - value * 0.32}`).join(" ");
  return <svg className="sparkline" viewBox="0 0 184 44" preserveAspectRatio="none" aria-hidden="true"><path d={`${path} L 184 44 L 0 44 Z`} fill={`${color}12`} /><path d={path} fill="none" stroke={color} strokeWidth="1.7" /></svg>;
}

function ServiceIcon({ kind }: { kind: ServiceKind }) {
  const Icon = kind === "Minecraft" ? Box : kind === "Database" ? Database : kind === "Proxy" ? Network : kind === "Web app" ? CloudCog : Archive;
  return <span className="service-icon"><Icon size={16} /></span>;
}

function ConfigGate() {
  return <div className="gate-wrap"><div className="gate-card">
    <div className="gate-mark"><LockKeyhole size={26} /></div>
    <p className="eyebrow">TMP SERVER / SETUP REQUIRED</p>
    <h1>Connect your private control plane.</h1>
    <p className="gate-copy">Supabase credentials are not configured in this environment. TMP Server stays locked rather than creating a fake session or exposing service controls.</p>
    <div className="config-list">
      <div><code>VITE_SUPABASE_URL</code><span>Project URL</span></div>
      <div><code>VITE_SUPABASE_ANON_KEY</code><span>Browser-safe anon key</span></div>
      <div><code>VITE_SUPABASE_OWNER_EMAIL</code><span>Single owner allowlist</span></div>
    </div>
    <div className="gate-foot"><ShieldCheck size={15} /> No public registration · owner allowlist required</div>
  </div></div>;
}

function LoginGate({ session, onRefresh }: { session: Session | null; onRefresh: () => void }) {
  const [email, setEmail] = useState(ownerEmail);
  const [otpSent, setOtpSent] = useState(false);
  const [otp, setOtp] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const denied = Boolean(session && !isOwnerSession(session));

  async function sendMagicLink(event: React.FormEvent) {
    event.preventDefault();
    if (!supabase || !email) return;
    const normalizedEmail = email.trim().toLowerCase();
    setEmail(normalizedEmail);
    setBusy(true); setError("");
    const result = await supabase.auth.signInWithOtp({ email: normalizedEmail, options: { shouldCreateUser: false, emailRedirectTo: undefined } });
    setBusy(false);
    if (result.error) setError(result.error.message);
    else setOtpSent(true);
  }

  async function verifyOtp(event: React.FormEvent) {
    event.preventDefault();
    const normalizedEmail = email.trim().toLowerCase();
    const normalizedOtp = otp.replace(/\s/g, "");
    if (!supabase || !normalizedEmail || normalizedOtp.length < 6) return;
    setBusy(true); setError("");
    const result = await supabase.auth.verifyOtp({ email: normalizedEmail, token: normalizedOtp, type: "email" });
    setBusy(false);
    if (result.error) setError(result.error.message);
    else onRefresh();
  }

  async function signOut() {
    await supabase?.auth.signOut();
    onRefresh();
  }

  return <div className="gate-wrap"><div className="gate-card login-card">
    <div className="gate-mark"><LockKeyhole size={26} /></div>
    <p className="eyebrow">TMP SERVER / OWNER ACCESS</p>
    <h1>Private infrastructure, by design.</h1>
    {denied ? <>
      <p className="gate-copy danger-copy">This Supabase account is not the TMP Server owner or an invited member. The session has no access to the control plane.</p>
      <button className="button secondary full" onClick={signOut}><LogOut size={15} /> Sign out and try another account</button>
    </> : otpSent ? <>
      <p className="gate-copy">A verification code was sent to <b>{email}</b>. Enter the complete code below to continue. This console never exposes a public sign-up flow.</p>
      <form onSubmit={verifyOtp}><label className="field-label">Email verification code<input inputMode="numeric" autoComplete="one-time-code" value={otp} onChange={event => setOtp(event.target.value.replace(/\D/g, ""))} placeholder="123456" required /></label>{error && <p className="form-error">{error}</p>}<button className="button primary full" disabled={busy}>{busy ? "Verifying…" : "Verify code"}<ShieldCheck size={15} /></button><button type="button" className="button secondary full otp-back" onClick={() => { setOtpSent(false); setOtp(""); setError(""); }}>Use a different email</button></form>
    </> : <form onSubmit={sendMagicLink}>
      <label className="field-label">Owner or invited member email</label>
      <div className="input-row"><input type="email" value={email} onChange={event => setEmail(event.target.value)} placeholder="owner@example.com" required /><button className="button primary" disabled={busy}>{busy ? "Sending code…" : "Send email code"}<ArrowUpRight size={15} /></button></div>
      {error && <p className="form-error">{error}</p>}
      <p className="form-hint"><ShieldCheck size={14} /> Access is restricted to the configured owner or an invited member account.</p>
    </form>}
  </div></div>;
}

function HostUnavailable() {
  return <div className="gate-wrap"><div className="gate-card login-card">
    <div className="gate-mark"><Server size={26} /></div>
    <p className="eyebrow">TMP SERVER / NO LIVE HOST</p>
    <h1>Connect a real service host.</h1>
    <p className="gate-copy">No supervisor agent is connected, so TMP Server is withholding service state, uptime, metrics, logs, user counts, and lifecycle controls. This screen will not show sample data.</p>
    <div className="config-list">
      <div><code>HOST AGENT</code><span>Not connected</span></div>
      <div><code>LIVE METRICS</code><span>Unavailable</span></div>
      <div><code>HOST CONTROLS</code><span>Disabled</span></div>
    </div>
    <div className="gate-foot"><ShieldCheck size={15} /> Connect a persistent Linux host with the TMP supervisor before enabling production controls.</div>
  </div></div>;
}

function MinecraftConsole({ command, setCommand, output, busy, error, onClose, onSubmit }: { command: string; setCommand: (value: string) => void; output: string[]; busy: boolean; error: string; onClose: () => void; onSubmit: (event: React.FormEvent) => void }) {
  return <><div className="drawer-head"><div><p className="eyebrow">MINECRAFT CONSOLE</p><h2>Live server console</h2></div><button className="icon-button" onClick={onClose}><X size={18} /></button></div><div className="console-warning"><ShieldCheck size={16} /><span>Commands run as the authenticated TMP operator through RCON. Never paste passwords or secrets.</span></div><div className="console-output">{output.length ? output.map((line, index) => <div key={`${index}-${line}`}><span>&gt;</span>{line}</div>) : <span className="console-empty">No commands sent this session.</span>}</div><form className="console-form" onSubmit={onSubmit}><input value={command} onChange={event => setCommand(event.target.value)} placeholder="say Hello from TMP Server" maxLength={240} autoFocus /><button className="button primary" type="submit" disabled={busy}><TerminalSquare size={15} /> {busy ? "Sending…" : "Send"}</button></form>{error && <p className="form-error">{error}</p>}</>;
}

function MinecraftPanel({ username, setUsername, busy, error, notice, onClose, onSubmit }: { username: string; setUsername: (value: string) => void; busy: boolean; error: string; notice: string; onClose: () => void; onSubmit: (event: React.FormEvent) => void }) {
  return <><div className="drawer-head"><div><p className="eyebrow">MINECRAFT ACCESS</p><h2>Manage players</h2></div><button className="icon-button" onClick={onClose}><X size={18} /></button></div><form className="add-form" onSubmit={onSubmit}><div className="invite-hero"><span className="invite-icon"><Users size={20} /></span><p>Add a Java or Bedrock username to the live Paper whitelist. Floodgate handles Bedrock identity mapping.</p></div><label className="field-label">Minecraft username<input value={username} onChange={event => setUsername(event.target.value)} placeholder="YourJavaName" pattern="[A-Za-z0-9_.]{3,16}" required /></label>{error && <p className="form-error">{error}</p>}{notice && <p className="form-success">{notice}</p>}<div className="add-policy"><div><b>Live VM command</b><span>This sends an authenticated request to the connected Ubuntu VM and runs the whitelist command through the Minecraft container.</span></div><ShieldCheck size={17} /></div><button className="button primary full" type="submit" disabled={busy}><Users size={15} /> {busy ? "Updating whitelist…" : "Add to whitelist"}</button></form></>;
}

function InvitePanel({ email, setEmail, busy, error, onClose, onSubmit }: { email: string; setEmail: (value: string) => void; busy: boolean; error: string; onClose: () => void; onSubmit: (event: React.FormEvent) => void }) {
  return <><div className="drawer-head"><div><p className="eyebrow">TEAM ACCESS</p><h2>Invite member</h2></div><button className="icon-button" onClick={onClose}><X size={18} /></button></div><form className="add-form" onSubmit={onSubmit}><div className="invite-hero"><span className="invite-icon"><Users size={20} /></span><p>Invite a trusted operator to TMP Server. Supabase sends the email and marks the account as an approved member; public registration stays disabled.</p></div><label className="field-label">Member email<input type="email" value={email} onChange={event => setEmail(event.target.value)} placeholder="operator@example.com" required /></label>{error && <p className="form-error">{error}</p>}<div className="add-policy"><div><b>Member access only</b><span>Invited users can sign in, inspect services, and use the control plane. The owner remains the only account allowed to send invites.</span></div><ShieldCheck size={17} /></div><button className="button primary full" type="submit" disabled={busy}><Users size={15} /> {busy ? "Sending invite…" : "Send Supabase invite"}</button></form></>;
}

function Home() {
  const [session, setSession] = useState<Session | null>(null);
  const [authReady, setAuthReady] = useState(!supabaseConfigured);
  const [nav, setNav] = useState<NavKey>("overview");
  const [services, setServices] = useState<Service[]>(initialServices);
  const [activity, setActivity] = useState<Activity[]>(initialActivity);
  const [selected, setSelected] = useState<Service | null>(initialServices[0]);
  const [drawer, setDrawer] = useState<"service" | "add" | "invite" | "minecraft" | "console" | null>(null);
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  const [logFilter, setLogFilter] = useState("all");
  const [newService, setNewService] = useState({ name: "", kind: "Web app" as ServiceKind, port: "8088", domain: "" });
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteBusy, setInviteBusy] = useState(false);
  const [inviteError, setInviteError] = useState("");
  const [hostState, setHostState] = useState<HostState | null>(null);
  const [hostError, setHostError] = useState("");
  const [minecraftUsername, setMinecraftUsername] = useState("");
  const [minecraftBusy, setMinecraftBusy] = useState(false);
  const [minecraftError, setMinecraftError] = useState("");
  const [minecraftNotice, setMinecraftNotice] = useState("");
  const [consoleCommand, setConsoleCommand] = useState("");
  const [consoleOutput, setConsoleOutput] = useState<string[]>([]);
  const [consoleBusy, setConsoleBusy] = useState(false);
  const [consoleError, setConsoleError] = useState("");

  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getSession().then(({ data }) => { setSession(data.session); setAuthReady(true); });
    const { data: listener } = supabase.auth.onAuthStateChange((_event, nextSession) => { setSession(nextSession); setAuthReady(true); });
    return () => listener.subscription.unsubscribe();
  }, []);

  useEffect(() => { if (notice) { const timer = window.setTimeout(() => setNotice(""), 3400); return () => window.clearTimeout(timer); } }, [notice]);

  useEffect(() => {
    if (!hostApiUrl || !session) return;
    let active = true;
    async function loadHostState() {
      try {
        const response = await fetch(`${hostApiUrl}/api/state`, { headers: { Authorization: `Bearer ${session?.access_token ?? ""}` } });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.error ?? "Host agent rejected the session.");
        if (active) {
          const state = payload as HostState;
          const minecraft: Service = { id: "minecraft", name: "Minecraft", kind: "Minecraft", state: state.minecraft.health === "healthy" ? "running" : "degraded", health: state.minecraft.health === "healthy" ? 100 : 0, cpu: -1, memory: -1, memoryLimit: 3072, port: state.minecraft.portJava, domain: undefined, uptime: formatUptime(state.host.uptimeSeconds), restarts: 0, boot: true, checkEvery: "live health", restartPolicy: "unless-stopped", dependencies: [], accent: "green", description: `Paper + Geyser · Java ${state.minecraft.portJava} · Bedrock ${state.minecraft.portBedrock}` };
          setHostState(state); setServices([minecraft]); setSelected(minecraft); setHostError("");
        }
      } catch (error) { if (active) setHostError(error instanceof Error ? error.message : "Unable to reach host agent."); }
    }
    loadHostState();
    const timer = window.setInterval(loadHostState, 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, [session]);

  const visibleServices = useMemo(() => services.filter(service => `${service.name} ${service.kind}`.toLowerCase().includes(search.toLowerCase())), [services, search]);
  const running = services.filter(service => service.state === "running").length;
  const degraded = services.filter(service => service.state === "degraded").length;

  async function controlMinecraft(operation: "start" | "stop" | "restart" | "update") {
    if (!hostApiUrl || !supabase || !window.confirm(`${operation[0].toUpperCase()}${operation.slice(1)} the live Minecraft server?`)) return;
    setNotice(`${operation[0].toUpperCase()}${operation.slice(1)} request sent…`);
    try {
      const { data } = await supabase.auth.getSession();
      const response = await fetch(`${hostApiUrl}/api/minecraft/lifecycle`, { method: "POST", headers: { "content-type": "application/json", Authorization: `Bearer ${data.session?.access_token ?? ""}` }, body: JSON.stringify({ action: operation }) });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error ?? "Minecraft lifecycle request failed.");
      setHostState(payload.state as HostState); setNotice(`Minecraft ${operation} completed.`); setDrawer(null);
    } catch (error) { setNotice(error instanceof Error ? error.message : "Minecraft lifecycle request failed."); }
  }

  async function sendMinecraftCommand(event: React.FormEvent) {
    event.preventDefault();
    const command = consoleCommand.trim();
    if (!hostApiUrl || !supabase || !command) return;
    setConsoleBusy(true); setConsoleError("");
    try {
      const { data } = await supabase.auth.getSession();
      const response = await fetch(`${hostApiUrl}/api/minecraft/command`, { method: "POST", headers: { "content-type": "application/json", Authorization: `Bearer ${data.session?.access_token ?? ""}` }, body: JSON.stringify({ command }) });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error ?? "Console command failed.");
      setConsoleOutput(current => [...current, `$ ${command}`, payload.output || "(command accepted)"]); setConsoleCommand("");
    } catch (error) { setConsoleError(error instanceof Error ? error.message : "Console command failed."); }
    finally { setConsoleBusy(false); }
  }

  function operate(service: Service, operation: "start" | "stop" | "restart" | "update") {
    if (service.kind === "Minecraft") { void controlMinecraft(operation); return; }
    if (operation !== "start" && !window.confirm(`${operation[0].toUpperCase()}${operation.slice(1)} ${service.name}?`)) return;
    const nextState: ServiceState = operation === "stop" ? "stopped" : operation === "restart" || operation === "update" ? "restarting" : "running";
    const tone: Activity["tone"] = operation === "stop" ? "warning" : operation === "update" ? "success" : "info";
    setServices(current => current.map(item => item.id === service.id ? { ...item, state: nextState, restarts: operation === "restart" || operation === "update" ? item.restarts + 1 : item.restarts } : item));
    const message = operation === "update" ? "update recorded · image pull + rolling restart pending host binding" : `${operation} recorded · production supervisor binding pending`;
    setActivity(current => [{ id: Date.now(), time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }), service: service.name, message, tone }, ...current].slice(0, 6));
    setNotice(`${operation[0].toUpperCase()}${operation.slice(1)} queued for ${service.name}`);
    setSelected({ ...service, state: nextState, restarts: operation === "restart" || operation === "update" ? service.restarts + 1 : service.restarts });
  }

  async function sendInvite(event: React.FormEvent) {
    event.preventDefault();
    if (!supabase || !inviteEmail.trim()) return;
    if (staticPages) {
      setInviteError("Member invitations require the Manus-hosted backend; GitHub Pages is a static frontend only.");
      return;
    }
    setInviteBusy(true); setInviteError("");
    try {
      const { data } = await supabase.auth.getSession();
      const response = await fetch("/api/owner/invite", { method: "POST", headers: { "content-type": "application/json", Authorization: `Bearer ${data.session?.access_token ?? ""}` }, body: JSON.stringify({ email: inviteEmail.trim().toLowerCase() }) });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error ?? "Invite failed.");
      setNotice(`Invite sent to ${inviteEmail.trim().toLowerCase()}`); setInviteEmail(""); setDrawer(null);
    } catch (error) {
      setInviteError(error instanceof Error ? error.message : "Invite failed.");
    } finally { setInviteBusy(false); }
  }

  async function manageMinecraftUser(event: React.FormEvent) {
    event.preventDefault();
    const username = minecraftUsername.trim();
    if (!hostApiUrl || !supabase || !/^[A-Za-z0-9_.]{3,16}$/.test(username)) { setMinecraftError("Enter a valid Minecraft username (3–16 letters, numbers, underscore, or dot)."); return; }
    setMinecraftBusy(true); setMinecraftError(""); setMinecraftNotice("");
    try {
      const { data } = await supabase.auth.getSession();
      const response = await fetch(`${hostApiUrl}/api/minecraft/whitelist`, { method: "POST", headers: { "content-type": "application/json", Authorization: `Bearer ${data.session?.access_token ?? ""}` }, body: JSON.stringify({ action: "add", username }) });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error ?? "Whitelist update failed.");
      setMinecraftNotice(`${username} was added to the live whitelist.`); setMinecraftUsername("");
    } catch (error) { setMinecraftError(error instanceof Error ? error.message : "Whitelist update failed."); }
    finally { setMinecraftBusy(false); }
  }

  function addService(event: React.FormEvent) {
    event.preventDefault();
    if (!newService.name.trim()) return;
    const normalizedId = newService.name.trim().toLowerCase().replace(/[^a-z0-9-]/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "");
    const normalizedDomain = newService.domain.trim().toLowerCase();
    if (!normalizedId || services.some(item => item.id === normalizedId)) { setNotice("A service with that name already exists"); return; }
    if (normalizedDomain && !/^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/i.test(normalizedDomain)) { setNotice("Enter a valid hostname, for example app.example.com"); return; }
    const service: Service = { id: normalizedId, name: newService.name.trim(), kind: newService.kind, state: "stopped", health: 0, cpu: 0, memory: 0, memoryLimit: 1024, port: Number(newService.port) || 8088, domain: normalizedDomain || undefined, uptime: "—", restarts: 0, boot: false, checkEvery: "30 sec", restartPolicy: "on-failure · 5 / 10m", dependencies: [], accent: "blue", description: "New service · awaiting host binding" };
    setServices(current => [...current, service]);
    setActivity(current => [{ id: Date.now(), time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }), service: service.name, message: "registry entry created · host binding pending", tone: "info" }, ...current]);
    setNewService({ name: "", kind: "Web app", port: "8088", domain: "" }); setDrawer(null); setNotice(`${service.name} added to registry`);
  }

  if (!authReady) return <div className="loading-screen"><div className="loading-orbit" /><span>Checking owner session…</span></div>;
  if (!supabaseConfigured) return <ConfigGate />;
  if (!session || !isAllowedSession(session)) return <LoginGate session={session} onRefresh={() => setSession(null)} />;
  if (!hostApiUrl) return <HostUnavailable />;
  if (!hostState) return <div className="loading-screen"><div className="loading-orbit" /><span>{hostError || "Connecting to live host…"}</span></div>;

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="sidebar-top"><Logo /><button className="mobile-menu"><Menu size={18} /></button></div>
      <div className="node-switcher"><span className="node-pulse" /><span><b>tmp-node-01</b><small>standalone · primary</small></span><ChevronDown size={14} /></div>
      <nav className="nav-group">
        <p className="nav-caption">CONTROL PLANE</p>
        {navItems.map(item => <button key={item.id} className={`nav-item ${nav === item.id ? "active" : ""}`} onClick={() => setNav(item.id)}><item.icon size={16} /><span>{item.label}</span>{item.count && <b>{item.count}</b>}</button>)}
      </nav>
      <div className="sidebar-tree"><p className="nav-caption">FLEET</p><div className="tree-line"><ChevronDown size={13} /><Server size={14} /><span>tmp-node-01</span><span className="tree-live">online</span></div><div className="tree-children"><div><StatusDot state="running" /> live containers <b>{hostState.services.length}</b></div><div><StatusDot state="running" /> minecraft <b>{hostState.minecraft.health}</b></div><div><StatusDot state="degraded" /> agent <b>{hostState.host.architecture}</b></div></div></div>
      <div className="sidebar-bottom"><button className="nav-item"><Settings2 size={16} /><span>Settings</span></button><div className="owner-chip"><div className="avatar">{(session.user.email?.[0] ?? "O").toUpperCase()}</div><span><b>{session.user.email?.split("@")[0] ?? "member"}</b><small>{sessionLabel(session)} / online</small></span><MoreHorizontal size={16} /></div></div>
    </aside>
    <main className="main-content">
      <header className="topbar"><div className="breadcrumbs"><span>Cluster</span><ChevronRight size={14} /><b>tmp-node-01</b><span className="slash">/</span><strong>{nav === "overview" ? "Overview" : nav[0].toUpperCase() + nav.slice(1)}</strong></div><div className="top-actions"><div className="heartbeat"><span className="heartbeat-dot" /> live · VM agent</div><button className="icon-button" title="Help"><CircleHelp size={17} /></button><button className="icon-button" title="Sign out" onClick={() => supabase?.auth.signOut()}><LogOut size={17} /></button></div></header>
      <div className="content-scroll"><section className="page-heading"><div><p className="eyebrow">CONTROL PLANE / PRIVATE HOST</p><h1>{nav === "overview" ? "Overview" : nav === "services" ? "Services" : nav === "logs" ? "Log stream" : nav === "alerts" ? "Owner alerts" : "Node telemetry"}</h1><p className="page-subtitle">Live host state from the connected Ubuntu supervisor.{staticPages && <><br /><span>GitHub Pages shell · commands run on the authenticated VM agent</span></>}</p></div><div className="heading-actions"><button className="button secondary" onClick={() => setDrawer("minecraft")}><Users size={15} /> Minecraft users</button><button className="button secondary" onClick={() => setDrawer("console")}><TerminalSquare size={15} /> Console</button><button className="button secondary" onClick={() => window.location.reload()}><RefreshCw size={15} /> Refresh</button>{staticPages ? <span className="backend-note">Live agent connected</span> : <><button className="button secondary" onClick={() => setDrawer("invite")}><Users size={15} /> Invite member</button>{isOwnerSession(session) && <button className="button primary" onClick={() => setDrawer("add")}><Plus size={16} /> Add service</button>}</>}</div></section>
        <div className="security-strip"><ShieldCheck size={15} /><span><b>Owner access active</b> · Supabase session verified against the configured allowlist</span><span className="strip-end">authenticated VM agent connected · no browser shell access</span></div>
        <section className="metric-grid"><MetricCard label="LIVE SERVICES" value={`${running}`} suffix={` / ${services.length}`} detail={`${degraded} degraded`} tone="cyan" icon={ActivityIcon} /><MetricCard label="ONLINE PLAYERS" value={`${hostState.minecraft.onlinePlayers}`} suffix={` / ${hostState.minecraft.maxPlayers || "—"}`} detail="Live RCON count" icon={Users} /><MetricCard label="MEMORY" value={`${hostState.memory.usedPercent}`} suffix="%" detail={`${formatBytes(hostState.memory.totalBytes - hostState.memory.availableBytes)} used · ${formatBytes(hostState.memory.totalBytes)} total`} tone="violet" icon={MemoryStick}><div className="meter"><span style={{ width: `${hostState.memory.usedPercent}%` }} /></div></MetricCard><MetricCard label="STORAGE" value={`${hostState.disk.usedPercent}`} suffix="%" detail={`${formatBytes(hostState.disk.freeBytes)} free`} tone="amber" icon={HardDrive}><div className="meter amber"><span style={{ width: `${hostState.disk.usedPercent}%` }} /></div></MetricCard></section>
        <section className="main-grid"><div className="panel service-panel"><div className="panel-header"><div><p className="eyebrow">SERVICE REGISTRY</p><h2>Running services <span>{visibleServices.length} visible</span></h2></div><div className="panel-tools"><div className="search-input"><Search size={14} /><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Filter services" /></div><button className="icon-button"><Filter size={16} /></button><button className="icon-button"><MoreHorizontal size={16} /></button></div></div><div className="table-wrap"><table><thead><tr><th>SERVICE</th><th>STATE</th><th>HEALTH</th><th>CPU</th><th>MEMORY</th><th>UPTIME</th><th /></tr></thead><tbody>{visibleServices.map(service => <tr key={service.id} className={selected?.id === service.id ? "selected-row" : ""} onClick={() => { setSelected(service); setDrawer("service"); }}><td><div className="service-name"><ServiceIcon kind={service.kind} /><span><b>{service.name}</b><small>{service.domain ? `${service.domain} · ` : ""}{service.description}</small></span></div></td><td><StateBadge state={service.state} /></td><td><div className="health-cell"><span className="health-bar"><i className={service.health < 80 ? "warning" : ""} style={{ width: `${service.health}%` }} /></span><small>{service.health}%</small></div></td><td className="mono">{service.cpu < 0 ? "—" : `${service.cpu}%`}</td><td><div className="memory-cell"><span>{service.memory < 0 ? "—" : `${service.memory}%`}</span><span className="memory-bar"><i style={{ width: `${Math.max(0, service.memory)}%` }} /></span></div></td><td className="mono muted">{service.uptime}</td><td><button className="row-menu" onClick={event => { event.stopPropagation(); setSelected(service); setDrawer("service"); }}><MoreHorizontal size={16} /></button></td></tr>)}</tbody></table></div><div className="panel-footer"><span><span className="green-dot" /> {running + 20} running</span><span><span className="amber-dot" /> {degraded + 1} attention</span><button className="text-button" onClick={() => setNav("services")}>Open full registry <ArrowUpRight size={14} /></button></div></div>
          <div className="side-stack"><div className="panel node-panel"><div className="panel-header compact"><div><p className="eyebrow">NODE TELEMETRY</p><h2>tmp-node-01</h2></div><span className="online-pill"><span /> live telemetry</span></div><div className="node-meta"><span><HardDrive size={14} /> Ubuntu 24.04 LTS</span><span><Network size={14} /> {hostState.host.architecture} · public VM</span></div><div className="util-chart"><div className="chart-axis"><span>80%</span><span>40%</span><span>0%</span></div><TinySparkline color="#39d9ff" /><div className="chart-labels"><span>12h ago</span><span>6h ago</span><span>now</span></div></div><div className="node-stat-row"><div><span>UPTIME</span><b>{formatUptime(hostState.host.uptimeSeconds)}</b><small>host uptime</small></div><div><span>MEMORY</span><b>{hostState.memory.usedPercent}%</b><small>used</small></div><div><span>DISK</span><b>{hostState.disk.usedPercent}%</b><small>used</small></div></div></div><div className="panel alert-panel"><div className="panel-header compact"><div><p className="eyebrow">OWNER ALERTS</p><h2>Attention queue <span className="count-badge">0</span></h2></div><button className="icon-button" onClick={() => setNav("alerts")}><ArrowUpRight size={16} /></button></div><div className="empty-state"><ShieldCheck size={18} /><p>No live alerts reported by the host agent.</p></div></div></div></section>
        <section className="bottom-grid"><div className="panel activity-panel"><div className="panel-header compact"><div><p className="eyebrow">EVENT STREAM</p><h2>Recent operations</h2></div><button className="icon-button"><MoreHorizontal size={16} /></button></div><div className="activity-list">{activity.slice(0, 5).map(item => <div className="activity-item" key={item.id}><span className={`activity-marker ${item.tone}`} /><span className="activity-time">{item.time}</span><span className="activity-service">{item.service}</span><span className="activity-message">{item.message}</span></div>)}</div></div><div className="panel log-panel"><div className="panel-header compact"><div><p className="eyebrow">LOG STREAM</p><h2>Latest output</h2></div><div className="log-controls"><select value={logFilter} onChange={event => setLogFilter(event.target.value)}><option value="all">All services</option><option value="paperless-ngx">paperless-ngx</option><option value="minecraft-survival">minecraft-survival</option></select><TerminalSquare size={15} /></div></div><div className="log-list">{initialLogs.filter(log => logFilter === "all" || log.service === logFilter).map(log => <div className="log-line" key={`${log.time}-${log.service}`}><span>{log.time}</span><b className={log.level === "WARN" ? "warn" : "info"}>{log.level}</b><strong>{log.service}</strong><p>{log.message}</p></div>)}</div></div></section>
      </div>
    </main>
    {drawer && <div className="drawer-backdrop" onClick={() => setDrawer(null)}><aside className="drawer" onClick={event => event.stopPropagation()}>{drawer === "service" && selected ? <><div className="drawer-head"><div><p className="eyebrow">SERVICE INSPECTOR</p><h2>{selected.name}</h2></div><button className="icon-button" onClick={() => setDrawer(null)}><X size={18} /></button></div><div className="drawer-status"><ServiceIcon kind={selected.kind} /><div><StateBadge state={selected.state} /><p>{selected.description}</p></div></div><div className="drawer-actions"><button className="button primary" onClick={() => operate(selected, "start")}><Play size={14} /> Start</button><button className="button secondary" onClick={() => operate(selected, "restart")}><RefreshCw size={14} /> Restart</button><button className="button secondary" onClick={() => operate(selected, "update")}><CloudCog size={14} /> Update</button><button className="button danger-button" onClick={() => operate(selected, "stop")}><Square size={13} /> Stop</button></div><div className="detail-section"><p className="eyebrow">RUNTIME</p><div className="detail-grid"><div><span>PORT</span><b>{selected.port}</b></div><div><span>UPTIME</span><b>{selected.uptime}</b></div><div><span>RESTARTS</span><b>{selected.restarts}</b></div><div><span>HEALTH</span><b>{selected.health}%</b></div></div></div><div className="detail-section"><p className="eyebrow">DOMAIN ROUTE</p><div className="route-row"><div><span>HOSTNAME</span><b>{selected.domain ?? "not linked"}</b></div>{selected.domain && <a href={`https://${selected.domain}`} target="_blank" rel="noreferrer"><ArrowUpRight size={15} /> Open</a>}</div><p className="route-help">Production TLS and reverse-proxy binding are pending host supervisor setup.</p></div><div className="detail-section"><p className="eyebrow">RECOVERY POLICY</p><div className="policy-row"><span>Boot startup</span><b>{selected.boot ? "enabled" : "disabled"}</b></div><div className="policy-row"><span>Health check</span><b>{selected.checkEvery}</b></div><div className="policy-row"><span>Restart policy</span><b>{selected.restartPolicy}</b></div><div className="policy-row"><span>Dependencies</span><b>{selected.dependencies.length ? selected.dependencies.join(", ") : "none"}</b></div></div><div className="drawer-note"><ShieldCheck size={15} /><span>Start, stop, restart, and update actions are recorded in the preview registry. Bind them to a server-side allowlisted supervisor before enabling production host mutations; direct host commands never reach the browser.</span></div></> : drawer === "console" ? <MinecraftConsole command={consoleCommand} setCommand={setConsoleCommand} output={consoleOutput} busy={consoleBusy} error={consoleError} onClose={() => setDrawer(null)} onSubmit={sendMinecraftCommand} /> : drawer === "minecraft" ? <MinecraftPanel username={minecraftUsername} setUsername={setMinecraftUsername} busy={minecraftBusy} error={minecraftError} notice={minecraftNotice} onClose={() => setDrawer(null)} onSubmit={manageMinecraftUser} /> : drawer === "invite" ? <InvitePanel email={inviteEmail} setEmail={setInviteEmail} busy={inviteBusy} error={inviteError} onClose={() => setDrawer(null)} onSubmit={sendInvite} /> : <><div className="drawer-head"><div><p className="eyebrow">SERVICE REGISTRY</p><h2>Add service</h2></div><button className="icon-button" onClick={() => setDrawer(null)}><X size={18} /></button></div><form className="add-form" onSubmit={addService}><label className="field-label">Service name<input value={newService.name} onChange={event => setNewService({ ...newService, name: event.target.value })} placeholder="my-service" required /></label><label className="field-label">Service type<select value={newService.kind} onChange={event => setNewService({ ...newService, kind: event.target.value as ServiceKind })}><option>Web app</option><option>Container</option><option>Database</option><option>Proxy</option><option>Minecraft</option></select></label><label className="field-label">Internal port<input type="number" min="1" max="65535" value={newService.port} onChange={event => setNewService({ ...newService, port: event.target.value })} /></label><label className="field-label">Domain route <span className="field-help">Optional hostname</span><input value={newService.domain} onChange={event => setNewService({ ...newService, domain: event.target.value })} placeholder="service.example.com" /></label><div className="add-policy"><div><b>Safe defaults applied</b><span>boot startup off · on-failure recovery · 30s health checks</span></div><ShieldCheck size={17} /></div><button className="button primary full" type="submit"><Plus size={15} /> Add to registry</button></form></>}</aside></div>}
    {notice && <div className="toast"><ShieldCheck size={15} /><span>{notice}</span></div>}
  </div>;
}

export default Home;
