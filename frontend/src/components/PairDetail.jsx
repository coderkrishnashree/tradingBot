import { useEffect, useState } from "react";
import { api, fmt } from "../api";

// Per-pair detail: indicators + signal score per timeframe, and the composite.
export default function PairDetail({ symbol, onClose }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.scanSymbol(symbol).then(setData).catch((e) => setErr(e.message));
  }, [symbol]);

  return (
    <div className="card border-accent/40">
      <div className="flex items-center justify-between mb-3">
        <div className="card-title mb-0 text-accent">{symbol} — detail</div>
        <button onClick={onClose} className="btn bg-ink-700 hover:bg-ink-600 text-slate-200 text-xs py-1">
          ✕ close
        </button>
      </div>
      {err && <p className="text-down text-sm">{err}</p>}
      {!data && !err && <p className="text-slate-500 text-sm">loading…</p>}
      {data && (
        <>
          <div className="mb-3 font-mono text-sm">
            composite:{" "}
            <span className={data.row.composite.direction === "long" ? "text-up" : data.row.composite.direction === "short" ? "text-down" : "text-slate-400"}>
              {data.row.composite.direction} {fmt.num(data.row.composite.confidence_pct, 0)}%
            </span>{" "}
            · aligned {data.row.composite.aligned ? "✓" : "—"} · last {fmt.num(data.row.last, 4)}
          </div>

          {/* Market structure + relations + extra indicators */}
          {(() => {
            const s = data.row.structure || {};
            const ir = data.row.indicators_ref || {};
            const cell = (label, val) => (
              <div className="bg-ink-900 rounded-lg p-2">
                <div className="text-[11px] text-slate-500">{label}</div>
                <div className="font-mono text-sm">{val}</div>
              </div>
            );
            const pct = (n) => (n == null ? "—" : `${(n * 100).toFixed(3)}%`);
            return (
              <div className="grid grid-cols-3 sm:grid-cols-4 gap-2 mb-3">
                {cell("Funding", s.funding_rate == null ? "—" : pct(s.funding_rate))}
                {cell("Open Int.", s.open_interest == null ? "—" : fmt.num(s.open_interest, 0))}
                {cell("Long/Short", s.long_short_ratio ?? "—")}
                {cell("OB imbalance", s.orderbook_imbalance ?? "—")}
                {cell("Struct. bias", s.structure_bias ?? "—")}
                {cell("BTC corr.", data.row.btc_correlation ?? "—")}
                {cell("Rel. strength", data.row.relative_strength_pct == null ? "—" : `${data.row.relative_strength_pct}%`)}
                {cell("ADX", ir.adx ?? "—")}
                {cell("Stoch", ir.stoch ?? "—")}
                {cell("BB %B", ir.bb_pctb ?? "—")}
                {cell("VWAP dist", ir.vwap_dist_pct == null ? "—" : `${ir.vwap_dist_pct}%`)}
                {cell("Divergence", ir.divergence ?? "none")}
              </div>
            );
          })()}

          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="th">TF</th>
                  <th className="th">Score</th>
                  <th className="th">Dir</th>
                  <th className="th">RSI</th>
                  <th className="th">Trend</th>
                  <th className="th">MACD</th>
                  <th className="th">ATR%</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.row.per_tf).map(([tf, v]) => (
                  <tr key={tf} className="hover:bg-ink-700/40">
                    <td className="td">{tf}</td>
                    <td className={`td ${v.score > 0.1 ? "text-up" : v.score < -0.1 ? "text-down" : "text-slate-400"}`}>
                      {fmt.num(v.score, 2)}
                    </td>
                    <td className="td">{v.direction}</td>
                    <td className="td">{fmt.num(v.rsi, 1)}</td>
                    <td className="td">{v.trend}</td>
                    <td className="td">{fmt.num(v.macd, 4)}</td>
                    <td className="td">{fmt.num(v.atr_pct, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
