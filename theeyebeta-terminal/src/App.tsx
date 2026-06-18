import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useState } from "react";
import { useAuth } from "./auth/AuthContext";
import { useAdminEvents } from "./hooks/useAdminEvents";
import { OverviewPanel } from "./panels/OverviewPanel";
import { PlaceholderPanel } from "./panels/PlaceholderPanel";
import { MarketPanel } from "./panels/MarketPanel";
import { TradingPanel } from "./panels/TradingPanel";
import { SignalsPanel } from "./panels/SignalsPanel";
import { RiskPanel } from "./panels/RiskPanel";
import { AuditPanel } from "./panels/AuditPanel";
import { PipelinesPanel } from "./panels/PipelinesPanel";
import { StatusDot } from "./components/StatusDot";
import { OPENAPI_PATHS } from "./api/openapi-schema";

const navItems = [
  { path: "/overview", label: "OVERVIEW" },
  { path: "/market", label: "MARKET" },
  { path: "/trading", label: "TRADING" },
  { path: "/signals", label: "SIGNALS" },
  { path: "/risk", label: "RISK" },
  { path: "/audit", label: "AUDIT" },
  { path: "/pipelines", label: "PIPELINES" },
  { path: "/data", label: "DATA" },
  { path: "/admin", label: "ADMIN" }
];

function Login() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setMessage("");
    try {
      if (mfaToken) {
        await auth.verifyMfa(mfaToken, totp);
        navigate("/overview", { replace: true });
        return;
      }
      const result = await auth.login(username, password, totp || undefined);
      if (result.status === "authenticated") {
        navigate("/overview", { replace: true });
      } else if (result.status === "mfa_required") {
        setMfaToken(result.mfaToken);
        setMessage("MASTER_ADMIN MFA required");
      } else {
        setMessage("MFA enrollment required by backend before terminal access");
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Authentication failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex h-screen min-w-[1280px] items-center justify-center bg-terminal-bg">
      <form
        onSubmit={submit}
        className="w-[420px] border border-terminal-border bg-terminal-panel p-4"
      >
        <div className="mb-4 border-b border-terminal-border pb-3">
          <h1 className="text-lg font-semibold uppercase tracking-wide text-terminal-primary">
            TheEyeBeta MASTER_ADMIN
          </h1>
          <p className="mt-1 text-xs uppercase tracking-wide text-terminal-muted">
            JWT memory session / httpOnly refresh / audited operator surface
          </p>
        </div>
        <label className="mb-3 block text-xs uppercase text-terminal-muted">
          Email
          <input
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
            className="mt-1 h-8 w-full border border-terminal-border bg-terminal-bg px-2 font-mono text-sm text-terminal-text outline-none focus:border-terminal-primary"
          />
        </label>
        <label className="mb-3 block text-xs uppercase text-terminal-muted">
          Password
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            type="password"
            autoComplete="current-password"
            className="mt-1 h-8 w-full border border-terminal-border bg-terminal-bg px-2 font-mono text-sm text-terminal-text outline-none focus:border-terminal-primary"
          />
        </label>
        {mfaToken ? (
          <label className="mb-3 block text-xs uppercase text-terminal-muted">
            TOTP
            <input
              value={totp}
              onChange={(event) => setTotp(event.target.value)}
              autoComplete="one-time-code"
              className="mt-1 h-8 w-full border border-terminal-border bg-terminal-bg px-2 font-mono text-sm text-terminal-text outline-none focus:border-terminal-primary"
            />
          </label>
        ) : null}
        {message ? (
          <div className="mb-3 border border-terminal-secondary p-2 text-xs text-terminal-secondary">
            {message}
          </div>
        ) : null}
        <button
          type="submit"
          disabled={submitting}
          className="h-8 w-full border border-terminal-primary bg-terminal-bg text-xs font-semibold uppercase text-terminal-primary hover:shadow-neon disabled:opacity-40"
        >
          {mfaToken ? "Verify MFA" : "Login"}
        </button>
      </form>
    </main>
  );
}

function TerminalShell() {
  const auth = useAuth();
  const location = useLocation();
  const events = useAdminEvents(auth.token);

  if (!auth.token) return <Navigate to="/login" replace />;

  return (
    <div className="grid h-screen min-w-[1280px] grid-rows-[40px_1fr_28px] bg-terminal-bg text-terminal-text">
      <header className="flex items-center justify-between border-b border-terminal-border bg-terminal-panel px-3">
        <div className="flex items-center gap-3">
          <span className="font-mono text-sm font-bold text-terminal-primary">
            THEEYEBETA://TERMINAL
          </span>
          <span className="font-mono text-xs uppercase text-terminal-secondary">{auth.role}</span>
        </div>
        <div className="flex items-center gap-4 text-xs uppercase text-terminal-muted">
          <span className="font-mono">{OPENAPI_PATHS.length} DataAPI paths</span>
          <span className="flex items-center gap-2">
            <StatusDot
              status={events.state === "connected" ? "ok" : "warn"}
              pulse={events.state === "connected"}
            />
            WS {events.state}
          </span>
          <button
            className="text-terminal-primary hover:shadow-neon"
            onClick={() => void auth.logout()}
          >
            LOGOUT
          </button>
        </div>
      </header>
      <div className="grid min-h-0 grid-cols-[200px_1fr]">
        <aside className="border-r border-terminal-border bg-terminal-panel">
          <nav className="flex flex-col p-2">
            {navItems.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                className={({ isActive }) =>
                  `mb-1 border border-transparent px-2 py-2 text-xs font-semibold uppercase tracking-wide ${
                    isActive
                      ? "border-terminal-primary text-terminal-primary shadow-neon"
                      : "text-terminal-muted hover:border-terminal-border hover:text-terminal-text"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </aside>
        <main className="min-h-0 overflow-hidden p-2">
          <Routes location={location}>
            <Route path="/overview" element={<OverviewPanel />} />
            <Route path="/market" element={<MarketPanel />} />
            <Route path="/trading" element={<TradingPanel />} />
            <Route path="/signals" element={<SignalsPanel />} />
            <Route path="/risk" element={<RiskPanel />} />
            <Route path="/audit" element={<AuditPanel />} />
            <Route path="/pipelines" element={<PipelinesPanel />} />
            <Route path="/data" element={<PlaceholderPanel title="DATA" />} />
            <Route path="/admin" element={<PlaceholderPanel title="ADMIN" />} />
            <Route path="*" element={<Navigate to="/overview" replace />} />
          </Routes>
        </main>
      </div>
      <footer className="flex items-center justify-between border-t border-terminal-border bg-terminal-panel px-3 font-mono text-[11px] uppercase text-terminal-muted">
        <span>{auth.username ?? "operator"}</span>
        <span>{events.events[0]?.type ?? "no live events"}</span>
        <span>{new Date().toISOString()}</span>
      </footer>
    </div>
  );
}

export function App() {
  const auth = useAuth();
  if (!auth.bootstrapped) {
    return (
      <div className="flex h-screen items-center justify-center bg-terminal-bg font-mono text-terminal-primary">
        BOOTSTRAPPING TERMINAL...
      </div>
    );
  }
  return (
    <Routes>
      <Route path="/login" element={auth.token ? <Navigate to="/overview" replace /> : <Login />} />
      <Route path="/*" element={<TerminalShell />} />
    </Routes>
  );
}
