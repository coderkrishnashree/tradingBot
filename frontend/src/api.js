// Thin wrapper around the backend REST API + a polling hook.
// Everything calls "/api/..." which Vite proxies to FastAPI on :8000.
import { useEffect, useRef, useState, useCallback } from "react";

async function req(path, opts = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const msg = body?.detail
      ? typeof body.detail === "string"
        ? body.detail
        : JSON.stringify(body.detail)
      : `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return body;
}

export const api = {
  mode: () => req("/mode"),
  goLive: (confirmation) =>
    req("/mode/live", { method: "POST", body: JSON.stringify({ confirmation }) }),
  goPaper: () => req("/mode/paper", { method: "POST" }),
  kill: () => req("/kill", { method: "POST" }),
  killReset: () => req("/kill/reset", { method: "POST" }),

  portfolio: () => req("/portfolio"),
  pnl: () => req("/pnl"),
  positions: () => req("/positions"),
  orders: () => req("/orders"),
  trades: () => req("/trades"),
  equity: () => req("/equity"),
  stats: () => req("/stats"),

  getConfig: () => req("/config"),
  saveConfig: (cfg) => req("/config", { method: "PUT", body: JSON.stringify(cfg) }),

  decisions: () => req("/decisions"),
  decisionFile: (name) => req(`/decisions/file?name=${encodeURIComponent(name)}`),
  ohlcv: (symbol, timeframe = "15m", limit = 120) =>
    req(`/ohlcv?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}&limit=${limit}`),
  latestTranscript: () => req("/transcript/latest"),
  decisionAction: (filename, approve) =>
    req("/decisions/action", {
      method: "POST",
      body: JSON.stringify({ filename, approve }),
    }),

  // Scanner + automation + alerts + claude
  scan: () => req("/scan"),
  scanSymbol: (sym) => req(`/scan/${sym}`),
  runScan: () => req("/scan/run", { method: "POST" }),
  automation: () => req("/automation"),
  saveAutomation: (cfg) => req("/automation", { method: "POST", body: JSON.stringify(cfg) }),
  alerts: () => req("/alerts"),
  claudeStatus: () => req("/claude/status"),
  tradeManual: (sym) => req(`/trade/manual/${sym}`, { method: "POST" }),
  runAnalyze: () => req("/analyze/run", { method: "POST" }),
  analyzeLog: () => req("/analyze/log"),
};

// Poll a fetcher on an interval. Returns { data, error, loading, refresh }.
export function usePoll(fetcher, intervalMs = 4000, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const savedFetcher = useRef(fetcher);
  savedFetcher.current = fetcher;

  const refresh = useCallback(async () => {
    try {
      const d = await savedFetcher.current();
      setData(d);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, intervalMs);
    return () => clearInterval(id);
  }, [refresh, intervalMs]);

  return { data, error, loading, refresh };
}

// Formatting helpers.
export const fmt = {
  // Account is USDT-denominated, so we format as USDT (not USD $).
  usdt: (n) =>
    n == null
      ? "—"
      : `${Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USDT`,
  num: (n, d = 2) => (n == null ? "—" : Number(n).toFixed(d)),
  pct: (n, d = 2) => (n == null ? "—" : `${Number(n).toFixed(d)}%`),
  signed: (n) =>
    n == null ? "—" : `${n >= 0 ? "+" : ""}${Number(n).toFixed(2)}`,
  // Local PC time (backend stores UTC ISO; these render in the user's timezone).
  time: (iso) =>
    iso
      ? new Date(iso).toLocaleString([], { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" })
      : "—",
  timeMs: (ms) =>
    ms
      ? new Date(Number(ms)).toLocaleString([], { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" })
      : "—",
  clock: (iso) => (iso ? new Date(iso).toLocaleTimeString() : "—"),
};
