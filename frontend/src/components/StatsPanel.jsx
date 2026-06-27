import { fmt } from "../api";

// Strategy performance metrics computed by the backend (stats.py).
export default function StatsPanel({ stats }) {
  const s = stats || {};
  const items = [
    { label: "Total Return", value: fmt.pct(s.total_return_pct), color: s.total_return_pct >= 0 ? "text-up" : "text-down" },
    { label: "Win Rate", value: fmt.pct(s.win_rate_pct) },
    { label: "Sharpe", value: fmt.num(s.sharpe, 2) },
    { label: "Max Drawdown", value: fmt.pct(s.max_drawdown_pct), color: "text-down" },
    { label: "Closed Trades", value: s.num_closed_trades ?? "—" },
  ];
  return (
    <div className="card">
      <div className="card-title">Strategy Stats</div>
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {items.map((it) => (
          <div key={it.label}>
            <div className="text-xs text-slate-500">{it.label}</div>
            <div className={`text-xl font-mono font-bold ${it.color || "text-slate-100"}`}>
              {it.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
