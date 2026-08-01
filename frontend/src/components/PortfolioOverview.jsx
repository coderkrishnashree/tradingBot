import { fmt } from "../api";
import { SkeletonStat } from "./Skeleton";
import Ticker from "./Ticker";

function Metric({ label, value, formatter, prefix = "", color, accent }) {
  return (
    <div className="metric relative overflow-hidden">
      {accent && <div className={`absolute left-0 top-0 h-full w-1 ${accent}`}
                      style={{ boxShadow: "0 0 10px currentColor" }} />}
      <div className="text-[11px] font-display uppercase tracking-[0.2em] text-slate-500">{label}</div>
      <div className={`stat-big mt-2 ${color || "text-slate-100"}`}>
        {value == null ? "—" : <>{prefix}<Ticker value={value} format={formatter} /></>}
      </div>
    </div>
  );
}

// Big-number row: total value, available balance, today's P&L, all-time P&L.
export default function PortfolioOverview({ portfolio }) {
  if (!portfolio) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => <SkeletonStat key={i} />)}
      </div>
    );
  }
  const p = portfolio;
  const col = (n) => (n == null ? "" : n >= 0 ? "text-up" : "text-down");
  const arrow = (n) => (n == null ? "" : n >= 0 ? "▲ " : "▼ ");
  const signed = (n) => `${n >= 0 ? "+" : ""}${fmt.usdt(n)}`;
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <Metric label="Total Value" value={p.total_value} formatter={fmt.usdt} accent="bg-accent text-accent" />
      <Metric label="Available Balance" value={p.available_balance} formatter={fmt.usdt} />
      <Metric label="Today's P&L" value={p.todays_pnl} formatter={signed}
              prefix={arrow(p.todays_pnl)} color={col(p.todays_pnl)}
              accent={p.todays_pnl >= 0 ? "bg-up text-up" : "bg-down text-down"} />
      <Metric label="All-Time P&L" value={p.all_time_pnl} formatter={signed}
              prefix={arrow(p.all_time_pnl)} color={col(p.all_time_pnl)}
              accent={p.all_time_pnl >= 0 ? "bg-up text-up" : "bg-down text-down"} />
    </div>
  );
}
