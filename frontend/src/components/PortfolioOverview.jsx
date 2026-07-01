import { fmt } from "../api";
import { SkeletonStat } from "./Skeleton";

function Metric({ label, value, color, accent }) {
  return (
    <div className="metric relative overflow-hidden">
      {accent && <div className={`absolute left-0 top-0 h-full w-1 ${accent}`} />}
      <div className="text-[11px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={`stat-big mt-2 ${color || "text-slate-100"}`}>{value}</div>
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
  const sign = (n) => (n == null ? "" : n >= 0 ? "+" : "");
  const col = (n) => (n == null ? "" : n >= 0 ? "text-up" : "text-down");
  const arrow = (n) => (n == null ? "" : n >= 0 ? "▲ " : "▼ ");
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <Metric label="Total Value" value={fmt.usdt(p.total_value)} accent="bg-accent" />
      <Metric label="Available Balance" value={fmt.usdt(p.available_balance)} />
      <Metric label="Today's P&L"
        value={p.todays_pnl == null ? "—" : `${arrow(p.todays_pnl)}${sign(p.todays_pnl)}${fmt.usdt(p.todays_pnl)}`}
        color={col(p.todays_pnl)} accent={p.todays_pnl >= 0 ? "bg-up" : "bg-down"} />
      <Metric label="All-Time P&L"
        value={p.all_time_pnl == null ? "—" : `${arrow(p.all_time_pnl)}${sign(p.all_time_pnl)}${fmt.usdt(p.all_time_pnl)}`}
        color={col(p.all_time_pnl)} accent={p.all_time_pnl >= 0 ? "bg-up" : "bg-down"} />
    </div>
  );
}
