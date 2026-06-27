import { useEffect, useState } from "react";
import { api, fmt } from "../api";

const ALL_TF = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];

function Toggle({ on, onClick, label, danger }) {
  return (
    <button
      onClick={onClick}
      className={`btn ${on ? (danger ? "bg-down text-white" : "bg-up text-black") : "bg-ink-700 text-slate-300"}`}
    >
      {label}: {on ? "ON" : "OFF"}
    </button>
  );
}

// Control panel for the always-on mechanical loop (no Claude tokens).
export default function AutomationPanel({ status, mode, onRefresh }) {
  const [form, setForm] = useState(null);
  const [msg, setMsg] = useState(null);

  const [analyzeMsg, setAnalyzeMsg] = useState(null);

  useEffect(() => {
    if (status && !form) {
      setForm({
        scan_enabled: status.scan_enabled,
        auto_trade: status.auto_trade,
        auto_trade_confidence: status.auto_trade_confidence,
        auto_analyze: status.auto_analyze ?? false,
        ai_gated: status.ai_gated ?? false,
        ai_timeout_sec: status.ai_timeout_sec ?? 1200,
        scan_interval_min: status.scan_interval_min,
        scan_timeframes: status.scan_timeframes?.length ? status.scan_timeframes : ["15m", "1h", "4h", "1d"],
        daily_loss_limit_pct: status.daily_loss_limit_pct ?? 0,
        min_minutes_between_trades: status.min_minutes_between_trades ?? 0,
      });
    }
  }, [status, form]);

  async function runAnalyzeNow() {
    setAnalyzeMsg(null);
    try {
      const r = await api.runAnalyze();
      setAnalyzeMsg({ ok: r.started, text: r.message });
    } catch (e) {
      setAnalyzeMsg({ ok: false, text: e.message });
    }
  }

  if (!form) return <div className="card"><div className="card-title">Automation</div><p className="text-slate-500 text-sm">loading…</p></div>;

  function toggleTf(tf) {
    const has = form.scan_timeframes.includes(tf);
    setForm({
      ...form,
      scan_timeframes: has ? form.scan_timeframes.filter((x) => x !== tf) : [...form.scan_timeframes, tf],
    });
  }

  async function save() {
    setMsg(null);
    try {
      await api.saveAutomation(form);
      setMsg({ ok: "Saved." });
      onRefresh?.();
    } catch (e) {
      setMsg({ error: e.message });
    }
  }

  const summary = status.last_summary;

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="card-title">Automation — 30-min Mechanical Loop</div>

        {form.auto_trade && (
          <div className={`mb-3 p-2 rounded text-sm ${mode?.is_live ? "bg-down/20 text-down" : "bg-up/15 text-up"}`}>
            Auto-trade is ON — orders place automatically in <b>{mode?.mode}</b> mode when a pair’s
            confidence ≥ {form.auto_trade_confidence}%.
          </div>
        )}

        <div className="flex flex-wrap gap-3 mb-4">
          <Toggle on={form.scan_enabled} label="Scanning" onClick={() => setForm({ ...form, scan_enabled: !form.scan_enabled })} />
          <Toggle on={form.auto_trade} danger label="Auto-trade" onClick={() => setForm({ ...form, auto_trade: !form.auto_trade })} />
          <Toggle on={form.ai_gated} label="AI-gated" onClick={() => setForm({ ...form, ai_gated: !form.ai_gated })} />
          <Toggle on={form.auto_analyze} danger label="Auto-run AI" onClick={() => setForm({ ...form, auto_analyze: !form.auto_analyze })} />
        </div>

        <div className={`mb-4 p-3 rounded-lg text-sm border ${form.ai_gated ? "bg-accent/10 border-accent/40 text-slate-200" : "bg-ink-900 border-ink-600 text-slate-400"}`}>
          <b className={form.ai_gated ? "text-accent" : "text-slate-300"}>AI-gated decisions:</b>{" "}
          {form.ai_gated
            ? "ON — the screener only finds candidates; the AI agent debate decides and its confidence triggers the trade. Needs Claude Code running (non-root)."
            : "OFF — the mechanical screener's math score decides trades directly (agents not involved)."}
        </div>

        <div className="mb-4 p-3 rounded-lg bg-ink-900 border border-ink-600">
          <div className="text-xs text-slate-400 mb-2">
            <b className="text-slate-200">Auto-run AI</b> = the dashboard's “cron”. When ON, the
            backend runs the multi-agent debate (<code>claude -p /analyze</code>) every scan
            interval, on your Claude Code subscription (no API key). Headless &amp; unattended —
            keep it in paper until you trust it.
          </div>
          <div className="flex items-center gap-3">
            <button onClick={runAnalyzeNow} disabled={!status.ai_available || status.ai_running}
              className="btn bg-accent hover:bg-blue-600 text-white">
              {status.ai_running ? "AI running…" : "▶ Run AI analysis now"}
            </button>
            <span className={`text-xs ${status.ai_available ? "text-slate-500" : "text-down"}`}>
              {status.ai_available ? "claude CLI detected" : "claude CLI not found — install + /login"}
            </span>
          </div>
          {analyzeMsg && (
            <p className={`text-sm mt-2 ${analyzeMsg.ok ? "text-up" : "text-down"}`}>{analyzeMsg.text}</p>
          )}
        </div>

        <label className="block mb-3">
          <span className="text-xs text-slate-400">Auto-trade confidence threshold: <b className="text-slate-200">{form.auto_trade_confidence}%</b></span>
          <input type="range" min="0" max="100" step="1" value={form.auto_trade_confidence}
            onChange={(e) => setForm({ ...form, auto_trade_confidence: Number(e.target.value) })}
            className="w-full" />
          <span className="text-xs text-slate-500">Pairs scoring at or above this auto-trade. (Your 60–70% range is typical.)</span>
        </label>

        <div className="grid grid-cols-2 gap-3 mb-3">
          <label className="block">
            <span className="text-xs text-slate-400">Scan interval (minutes)</span>
            <input type="number" min="1" max="1440" className="input" value={form.scan_interval_min}
              onChange={(e) => setForm({ ...form, scan_interval_min: Number(e.target.value) })} />
          </label>
          <label className="block">
            <span className="text-xs text-slate-400">AI debate timeout (minutes)</span>
            <input type="number" min="2" max="60" className="input"
              value={Math.round((form.ai_timeout_sec || 1200) / 60)}
              onChange={(e) => setForm({ ...form, ai_timeout_sec: Math.max(120, Number(e.target.value) * 60) })} />
            <span className="text-xs text-slate-500">8 agents + web search can need 8–15 min.</span>
          </label>
        </div>

        <div className="grid grid-cols-2 gap-3 mb-3">
          <label className="block">
            <span className="text-xs text-slate-400">Daily loss limit (%)</span>
            <input type="number" min="0" max="100" step="0.5" className="input"
              value={form.daily_loss_limit_pct}
              onChange={(e) => setForm({ ...form, daily_loss_limit_pct: Number(e.target.value) })} />
            <span className="text-xs text-slate-500">0 = off. Halts trading if down this % today.</span>
          </label>
          <label className="block">
            <span className="text-xs text-slate-400">Min minutes between trades / pair</span>
            <input type="number" min="0" max="1440" step="1" className="input"
              value={form.min_minutes_between_trades}
              onChange={(e) => setForm({ ...form, min_minutes_between_trades: Number(e.target.value) })} />
            <span className="text-xs text-slate-500">0 = off. Curbs fee churn from re-entries.</span>
          </label>
        </div>

        <div className="mb-3">
          <span className="text-xs text-slate-400">Timeframes scanned (all selected are analyzed per pair)</span>
          <div className="flex flex-wrap gap-2 mt-1">
            {ALL_TF.map((tf) => (
              <button key={tf} onClick={() => toggleTf(tf)}
                className={`btn text-xs py-1 ${form.scan_timeframes.includes(tf) ? "bg-accent text-white" : "bg-ink-700 text-slate-400"}`}>
                {tf}
              </button>
            ))}
          </div>
        </div>

        <button onClick={save} disabled={form.scan_timeframes.length === 0}
          className="btn w-full bg-accent hover:bg-blue-600 text-white">
          Save automation
        </button>
        {form.scan_timeframes.length === 0 && (
          <p className="text-sm mt-2 text-down">Select at least one timeframe to scan.</p>
        )}
        {msg && <p className={`text-sm mt-2 ${msg.error ? "text-down" : "text-up"}`}>{msg.error || msg.ok}</p>}
      </div>

      <div className="card">
        <div className="card-title">Loop Status</div>
        <div className="grid grid-cols-2 gap-3 text-sm font-mono">
          <div><span className="text-slate-500">running</span><br />{status.running ? "yes" : "no"}</div>
          <div><span className="text-slate-500">next scan in</span><br />{status.cycle_running ? "scanning…" : status.seconds_to_next != null ? `${status.seconds_to_next}s` : "—"}</div>
          <div><span className="text-slate-500">last run</span><br />{status.last_run ? fmt.clock(status.last_run) : "—"}</div>
          <div><span className="text-slate-500">mode</span><br />{status.mode}</div>
        </div>
        {summary && (
          <div className="mt-3 text-sm">
            <div className="text-slate-400">Last cycle:</div>
            <div className="text-up">traded: {(summary.traded || []).join(", ") || "none"}</div>
            {summary.skipped?.length > 0 && (
              <div className="text-slate-500 mt-1">skipped: {summary.skipped.length} (see Alerts)</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
