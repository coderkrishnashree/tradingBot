import { useState } from "react";
import { api, usePoll, fmt } from "../api";

const PERIODS = [
  { key: "today", label: "Today" },
  { key: "1w", label: "1 week" },
  { key: "1m", label: "1 month" },
  { key: "all", label: "All time" },
  { key: "custom", label: "Custom" },
];

// Strategy performance, filterable by period. Win rate / closed / profit factor
// come from Bybit's realized closed trades; return/Sharpe/DD from the equity curve.
export default function StatsPanel() {
  const [period, setPeriod] = useState("all");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const params = period === "custom" ? { period, start, end } : { period };
  const stats = usePoll(() => api.stats(params), 8000, [period, start, end]);
  const s = stats.data || {};

  const items = [
    { label: "Total Return", value: fmt.pct(s.total_return_pct), color: s.total_return_pct >= 0 ? "text-up" : "text-down" },
    { label: "Realized P&L", value: s.realized_pnl == null ? "—" : `${fmt.signed(s.realized_pnl)} USDT`, color: (s.realized_pnl || 0) >= 0 ? "text-up" : "text-down" },
    { label: "Win Rate", value: fmt.pct(s.win_rate_pct, 1) },
    { label: "Profit Factor", value: s.profit_factor ?? "—", color: (s.profit_factor || 0) >= 1 ? "text-up" : "text-down" },
    { label: "Sharpe", value: fmt.num(s.sharpe, 2) },
    { label: "Max Drawdown", value: fmt.pct(s.max_drawdown_pct), color: "text-down" },
    { label: "Closed Trades", value: s.num_closed_trades ?? 0 },
  ];

  return (
    <div className="card">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div className="card-title mb-0">Strategy Stats</div>
        <div className="flex flex-wrap items-center gap-1">
          {PERIODS.map((p) => (
            <button key={p.key} onClick={() => setPeriod(p.key)}
              className={`btn text-xs py-1 ${period === p.key ? "bg-accent text-white" : "bg-ink-700 text-slate-400"}`}>
              {p.label}
            </button>
          ))}
          {period === "custom" && (
            <span className="flex items-center gap-1 ml-1">
              <input type="date" className="input py-1 text-xs w-auto" value={start} onChange={(e) => setStart(e.target.value)} />
              <span className="text-slate-500 text-xs">→</span>
              <input type="date" className="input py-1 text-xs w-auto" value={end} onChange={(e) => setEnd(e.target.value)} />
            </span>
          )}
        </div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
        {items.map((it) => (
          <div key={it.label}>
            <div className="text-xs text-slate-500">{it.label}</div>
            <div className={`text-xl font-mono font-bold ${it.color || "text-slate-100"}`}>{it.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
