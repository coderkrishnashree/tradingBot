import { useEffect, useState } from "react";
import { api, usePoll, fmt } from "../api";
import { SkeletonRow } from "./Skeleton";

const AGENTS = [
  ["research", "🔍 Research"], ["macro", "🌐 Macro"], ["sentiment", "📰 Sentiment"],
  ["bull", "🐂 Bull"], ["bear", "🐻 Bear"], ["quant", "🧮 Quant"],
  ["risk", "🛡️ Risk"], ["portfolio", "⚖️ Portfolio"],
];

function statusColor(s) {
  return s === "executed" ? "text-up"
    : s === "resting" ? "text-yellow-400"
    : s === "failed" || s === "rejected" ? "text-down"
    : s === "approved" ? "text-accent" : "text-slate-400";
}

function DecisionModal({ name, onClose }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const [open, setOpen] = useState("portfolio");
  useEffect(() => {
    let alive = true;
    api.decisionFile(name).then((x) => alive && setD(x)).catch((e) => alive && setErr(e.message));
    return () => { alive = false; };
  }, [name]);
  const fd = d?.final_decision || {};
  const t = d?.transcript || {};
  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-ink-800 border border-ink-600 rounded-2xl p-4 w-full max-w-2xl max-h-[85vh] overflow-y-auto shadow-2xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <div className="font-bold">Decision · {d ? fmt.time(d.timestamp) : "…"}</div>
          <button onClick={onClose} className="btn text-xs py-1 bg-ink-700 hover:bg-ink-600 text-slate-200">✕</button>
        </div>
        {err && <div className="text-down text-sm">{err}</div>}
        {!d && !err && <div className="text-slate-500 text-sm">loading…</div>}
        {d && (
          <>
            <div className="mb-3 p-2 rounded bg-ink-900 font-mono text-sm flex flex-wrap gap-x-4 gap-y-1">
              <span className="text-accent font-bold">{(fd.action || "").toUpperCase()} {fd.symbol}</span>
              <span>size {fmt.num(fd.size, 1)}%</span>
              <span>entry {fmt.num(fd.entry, 2)}</span>
              <span className="text-down">stop {fmt.num(fd.stop_loss, 2)}</span>
              <span className="text-up">tp {fmt.num(fd.take_profit, 2)}</span>
              <span>conf {fmt.num(fd.confidence, 2)}</span>
            </div>
            <p className="text-sm text-slate-300 mb-3">{fd.rationale}</p>
            <div className="space-y-2">
              {AGENTS.map(([k, label]) => t[k] && (
                <div key={k} className="border border-ink-700 rounded-lg overflow-hidden">
                  <button onClick={() => setOpen(open === k ? null : k)}
                    className="w-full text-left px-3 py-2 text-sm font-semibold bg-ink-700/40 hover:bg-ink-700 flex justify-between">
                    <span>{label}</span><span>{open === k ? "−" : "+"}</span>
                  </button>
                  {open === k && <pre className="px-3 py-2 text-sm text-slate-300 whitespace-pre-wrap font-sans">{t[k]}</pre>}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// Full history of every decision the agents have produced.
export default function DecisionsHistory() {
  const decisions = usePoll(api.decisions, 8000);
  const [selected, setSelected] = useState(null);
  const rows = decisions.data || [];

  return (
    <div className="card">
      <div className="card-title">All Decisions ({rows.length})</div>
      <div className="overflow-x-auto max-h-80 overflow-y-auto">
        <table className="w-full">
          <thead className="sticky top-0 bg-ink-800"><tr>
            <th className="th">Time</th><th className="th">Action</th><th className="th">Symbol</th>
            <th className="th">Conf.</th><th className="th">Status</th>
          </tr></thead>
          <tbody>
            {decisions.loading && rows.length === 0 && <SkeletonRow cols={5} />}
            {!decisions.loading && rows.length === 0 && (
              <tr><td className="td text-slate-500" colSpan={5}>No decisions yet — run /analyze.</td></tr>
            )}
            {rows.map((d) => (
              <tr key={d.id} className="hover:bg-ink-700/40 cursor-pointer" onClick={() => setSelected(d.filename)}>
                <td className="td text-slate-400">{fmt.time(d.ts)}</td>
                <td className={`td font-bold ${d.action === "buy" ? "text-up" : d.action === "short" || d.action === "sell" ? "text-down" : "text-slate-300"}`}>
                  {(d.action || "").toUpperCase()}
                </td>
                <td className="td">{d.symbol}</td>
                <td className="td">{fmt.num(d.confidence, 2)}</td>
                <td className={`td ${statusColor(d.status)}`}>{d.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="text-xs text-slate-500 mt-2">Click any row to read the full agent debate.</div>
      {selected && <DecisionModal name={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
