import { fmt } from "../api";

// Live alerts feed: scans, auto-trades, kill switch, drawdown, system events.
const LEVELS = {
  info: "text-slate-300 border-ink-600",
  success: "text-up border-up/40",
  warning: "text-yellow-400 border-yellow-500/40",
  danger: "text-down border-down/50",
};

export default function AlertsFeed({ alerts }) {
  const rows = alerts || [];
  return (
    <div className="card">
      <div className="card-title">Alerts &amp; Activity ({rows.length})</div>
      <div className="space-y-2 max-h-[32rem] overflow-y-auto">
        {rows.length === 0 && <p className="text-slate-500 text-sm">No activity yet.</p>}
        {rows.map((a) => (
          <div key={a.id} className={`border-l-2 pl-3 py-1 ${LEVELS[a.level] || LEVELS.info}`}>
            <div className="flex justify-between text-xs text-slate-500">
              <span className="uppercase">{a.kind}</span>
              <span>{fmt.time(a.ts)}</span>
            </div>
            <div className="text-sm">{a.message}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
