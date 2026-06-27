import { fmt } from "../api";
import { SkeletonStat } from "./Skeleton";

function Stat({ label, value, color }) {
  return (
    <div className="card">
      <div className="card-title">{label}</div>
      <div className={`stat-big ${color || "text-slate-100"}`}>{value}</div>
    </div>
  );
}

// The big-number row: total value, available balance, today's P&L, all-time P&L.
export default function PortfolioOverview({ portfolio }) {
  if (!portfolio) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => <SkeletonStat key={i} />)}
      </div>
    );
  }
  const p = portfolio;
  const pnlColor = (n) => (n == null ? "" : n >= 0 ? "text-up" : "text-down");
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      <Stat label="Total Value" value={fmt.usdt(p.total_value)} />
      <Stat label="Available Balance" value={fmt.usdt(p.available_balance)} />
      <Stat
        label="Today's P&L"
        value={p.todays_pnl == null ? "—" : `${p.todays_pnl >= 0 ? "+" : ""}${fmt.usdt(p.todays_pnl)}`}
        color={pnlColor(p.todays_pnl)}
      />
      <Stat
        label="All-Time P&L"
        value={p.all_time_pnl == null ? "—" : `${p.all_time_pnl >= 0 ? "+" : ""}${fmt.usdt(p.all_time_pnl)}`}
        color={pnlColor(p.all_time_pnl)}
      />
    </div>
  );
}
