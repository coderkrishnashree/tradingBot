import { useEffect, useState } from "react";
import { api, usePoll, fmt } from "../api";
import { Skeleton } from "./Skeleton";

const AGENTS = [
  ["research", "🔍 Research", "text-slate-300"],
  ["macro", "🌐 Macro / Positioning", "text-cyan-400"],
  ["sentiment", "📰 Sentiment / News", "text-purple-400"],
  ["analyst", "⚡ Desk Analyst (lite)", "text-accent"],
  ["bull", "🐂 Bull", "text-up"],
  ["bear", "🐻 Bear", "text-down"],
  ["quant", "🧮 Quant (devil's advocate)", "text-orange-400"],
  ["risk", "🛡️ Risk Manager", "text-yellow-400"],
  ["portfolio", "⚖️ Portfolio Manager", "text-accent"],
];

function actionColor(a) {
  a = (a || "").toLowerCase();
  return a === "buy" ? "text-up" : a === "short" || a === "sell" ? "text-down" : "text-slate-300";
}

// All AI debates, readable: pick a pair/decision up top, see every agent in one
// table side by side with the final decision.
function LiveAI() {
  const log = usePoll(api.analyzeLog, 2500);
  const running = log.data?.running;
  const [busy, setBusy] = useState(false);
  async function runNow() {
    setBusy(true);
    try { await api.runAnalyze(); log.refresh(); } catch (e) { alert(e.message); }
    finally { setBusy(false); }
  }
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-2">
        <div className="card-title mb-0">
          Live AI {running && <span className="text-accent animate-pulse">● running…</span>}
        </div>
        <button onClick={runNow} disabled={busy || running}
          className="btn bg-accent hover:bg-blue-600 text-white text-sm">
          {running ? "running…" : busy ? "starting…" : "▶ Run analysis now"}
        </button>
      </div>
      <pre className="bg-ink-900 border border-ink-600 rounded-lg p-3 text-xs text-slate-300 font-mono max-h-80 overflow-auto whitespace-pre-wrap">
{log.data?.log?.trim() || "No debate has run yet. Click “Run analysis now” or wait for the auto loop."}
      </pre>
      <p className="text-xs text-slate-500 mt-1">
        Live output from the headless agent debate (Claude Code). Updates every few seconds while running.
      </p>
    </div>
  );
}

export default function DebatesTab() {
  const decisions = usePoll(api.decisions, 8000);
  const list = decisions.data || [];
  const [picked, setPicked] = useState(null);     // filename the user selected
  const [detail, setDetail] = useState(null);
  const [err, setErr] = useState(null);

  const current = picked || list[0]?.filename;     // default to the latest

  useEffect(() => {
    if (!current) { setDetail(null); return; }
    let alive = true; setDetail(null); setErr(null);
    api.decisionFile(current)
      .then((d) => alive && setDetail(d))
      .catch((e) => alive && setErr(e.message));
    return () => { alive = false; };
  }, [current]);

  const fd = detail?.final_decision || {};
  const t = detail?.transcript || {};

  return (
    <div className="space-y-4">
      <LiveAI />

      {/* Switcher */}
      <div className="card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="card-title mb-0">Agent Debates</div>
            <div className="text-xs text-slate-500 mt-1">
              The AI debate behind each decision. The mechanical screener's auto-trades don't
              produce a debate — these appear when <code className="text-accent">/analyze</code> runs
              (AI-gated trades or manual).
            </div>
          </div>
          <label className="text-sm text-slate-400">
            Pair / decision:&nbsp;
            <select className="input inline-block max-w-md mt-1" value={current || ""}
              onChange={(e) => setPicked(e.target.value)}>
              {list.length === 0 && <option>no debates yet</option>}
              {list.map((d) => (
                <option key={d.filename} value={d.filename}>
                  {fmt.time(d.ts)} · {(d.action || "").toUpperCase()} {d.symbol} · conf {fmt.num(d.confidence, 2)} · {d.status}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {!current && (
        <div className="card text-slate-500 text-sm">
          No debates yet. Turn on <b>AI-gated</b> (Automation) or run <code className="text-accent">/analyze</code> in Claude Code.
        </div>
      )}
      {err && <div className="card text-down text-sm">{err}</div>}
      {current && !detail && !err && <div className="card"><Skeleton className="h-64 w-full" /></div>}

      {detail && (
        <>
          {/* Final decision */}
          <div className="card">
            <div className="card-title">Final Decision — {detail.symbol}</div>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-1 font-mono text-sm">
              <span className={`px-2 py-1 rounded bg-ink-900 font-bold ${actionColor(fd.action)}`}>
                {(fd.action || "").toUpperCase()} {fd.symbol}
              </span>
              <span>size <b>{fmt.num(fd.size, 1)}%</b></span>
              <span>entry <b>{fmt.num(fd.entry, 2)}</b></span>
              <span className="text-down">stop <b>{fmt.num(fd.stop_loss, 2)}</b></span>
              <span className="text-up">tp <b>{fmt.num(fd.take_profit, 2)}</b></span>
              <span>confidence <b>{fmt.num(fd.confidence, 2)}</b></span>
              <span className="text-slate-500">{fmt.time(detail.timestamp)}</span>
            </div>
            <p className="text-sm text-slate-300 mt-2">{fd.rationale}</p>
          </div>

          {/* All agents in one table */}
          <div className="card">
            <div className="card-title">The Debate — every agent</div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr>
                    <th className="th w-52">Agent</th>
                    <th className="th">Analysis</th>
                  </tr>
                </thead>
                <tbody>
                  {AGENTS.filter(([k]) => t[k]).map(([k, label, color]) => (
                    <tr key={k} className="border-t border-ink-700 align-top">
                      <td className={`td font-semibold ${color} align-top whitespace-nowrap`}>{label}</td>
                      <td className="td text-slate-300 whitespace-pre-wrap font-sans leading-relaxed">{t[k]}</td>
                    </tr>
                  ))}
                  {AGENTS.every(([k]) => !t[k]) && (
                    <tr><td className="td text-slate-500" colSpan={2}>This decision has no agent transcript.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
