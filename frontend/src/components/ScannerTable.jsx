import { useState } from "react";
import { api, fmt } from "../api";
import PairDetail from "./PairDetail";
import { PairLink } from "../chart.jsx";

// Colour a signal score in [-1,1]: green long, red short, gray flat.
function scoreCell(score) {
  const s = Number(score) || 0;
  const mag = Math.min(1, Math.abs(s));
  const bg =
    s > 0.1 ? `rgba(34,197,94,${0.15 + mag * 0.45})`
    : s < -0.1 ? `rgba(239,68,68,${0.15 + mag * 0.45})`
    : "rgba(100,116,139,0.15)";
  return (
    <td className="td text-center" style={{ background: bg }}>
      {s.toFixed(2)}
    </td>
  );
}

function ConfBar({ pct, direction }) {
  const color = direction === "long" ? "bg-up" : direction === "short" ? "bg-down" : "bg-slate-500";
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-2 rounded bg-ink-700 overflow-hidden">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono">{fmt.num(pct, 0)}%</span>
    </div>
  );
}

// The multi-timeframe scanner table: rows = pairs, columns = timeframes.
export default function ScannerTable({ scan, onRefresh }) {
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState(null);
  const [tradeMsg, setTradeMsg] = useState(null);
  const rows = scan?.rows || [];
  const tfs = scan?.timeframes || [];

  async function rescan() {
    setBusy(true);
    try { await api.runScan(); onRefresh?.(); } finally { setBusy(false); }
  }

  async function tradeNow(sym) {
    if (!window.confirm(`Place a mechanical trade on ${sym} in the active mode?`)) return;
    setBusy(true);
    setTradeMsg(null);
    try {
      const r = await api.tradeManual(sym);
      setTradeMsg({ sym, ...r });
      onRefresh?.();
    } catch (e) {
      setTradeMsg({ sym, ok: false, message: e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="card-title mb-0">Multi-Timeframe Scanner</div>
            <div className="text-xs text-slate-500 mt-1">
              {scan?.generated_at ? `scanned ${fmt.time(scan.generated_at)} · ${scan.data_source}` : "no scan yet"}
            </div>
          </div>
          <button onClick={rescan} disabled={busy} className="btn bg-accent hover:bg-blue-600 text-white">
            {busy ? "Scanning…" : "↻ Scan now"}
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th className="th">Symbol</th>
                <th className="th">Confidence</th>
                <th className="th">Dir</th>
                <th className="th text-center">Aligned</th>
                <th className="th">AI</th>
                {tfs.map((tf) => <th key={tf} className="th text-center">{tf}</th>)}
                <th className="th"></th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr><td className="td text-slate-500" colSpan={6 + tfs.length}>No scan data — click “Scan now”.</td></tr>
              )}
              {rows.map((r) => {
                const c = r.composite;
                return (
                  <tr key={r.symbol} className="hover:bg-ink-700/40">
                    <td className="td whitespace-nowrap">
                      <PairLink symbol={r.symbol} />
                      <button className="text-xs text-slate-500 hover:text-slate-200 ml-1"
                        title="indicator details" onClick={() => setSelected(r.symbol)}>ⓘ</button>
                    </td>
                    <td className="td"><ConfBar pct={c.confidence_pct} direction={c.direction} /></td>
                    <td className={`td font-bold ${c.direction === "long" ? "text-up" : c.direction === "short" ? "text-down" : "text-slate-400"}`}>
                      {c.direction}
                    </td>
                    <td className="td text-center">{c.aligned ? "✓" : "—"}</td>
                    <td className="td whitespace-nowrap">
                      {r.ai ? (
                        <span className={r.ai.action === "buy" ? "text-up" : r.ai.action === "short" || r.ai.action === "sell" ? "text-down" : "text-slate-300"}>
                          {(r.ai.action || "").toUpperCase()} {fmt.num((r.ai.confidence || 0) * 100, 0)}%
                        </span>
                      ) : <span className="text-slate-600">—</span>}
                    </td>
                    {tfs.map((tf) => scoreCell(r.per_tf[tf]?.score))}
                    <td className="td">
                      <button
                        onClick={() => tradeNow(r.symbol)}
                        disabled={busy || c.direction === "flat"}
                        className="btn bg-ink-700 hover:bg-ink-600 text-slate-200 text-xs py-1"
                      >
                        Trade
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-slate-500 mt-2">
          Cells are per-timeframe signal scores in [−1,+1] (green bullish, red bearish). Confidence
          is the timeframe-weighted blend; “Aligned” means every timeframe agrees.
        </p>
        {tradeMsg && (
          <p className={`text-sm mt-2 ${tradeMsg.ok ? "text-up" : "text-down"}`}>
            {tradeMsg.sym}: {tradeMsg.message}
          </p>
        )}
      </div>

      {selected && <PairDetail symbol={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
