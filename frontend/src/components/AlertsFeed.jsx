import { fmt } from "../api";

const DOT = { info: "bg-slate-500", success: "bg-up", warning: "bg-yellow-400", danger: "bg-down" };
const TEXT = { info: "text-slate-300", success: "text-up", warning: "text-yellow-400", danger: "text-down" };

// Live activity feed: scans, auto-trades, closes, kill switch, drawdown, system.
export default function AlertsFeed({ alerts }) {
  const rows = alerts || [];
  return (
    <div className="card">
      <div className="flex items-center justify-between">
        <div className="card-title">Alerts &amp; Activity ({rows.length})</div>
        <a
          href="/api/report/24h"
          target="_blank"
          rel="noreferrer"
          className="mb-3 rounded-lg border border-white/10 px-3 py-1 text-xs text-slate-300 hover:bg-white/[0.06]"
          title="Full 24h diagnostic report: config, scans, decisions, orders, why-no-trade tally — copy-paste the whole page for debugging"
        >
          24h report ↗
        </a>
      </div>
      <div className="space-y-1 max-h-[34rem] overflow-y-auto -mx-1 px-1">
        {rows.length === 0 && <p className="text-slate-500 text-sm">No activity yet.</p>}
        {rows.map((a) => (
          <div key={a.id} className="flex gap-3 rounded-xl px-3 py-2 hover:bg-white/[0.03]">
            <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${DOT[a.level] || DOT.info}`} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2 text-[11px] text-slate-500">
                <span className="uppercase tracking-wider">{a.kind}</span>
                <span className="font-mono">{fmt.time(a.ts)}</span>
              </div>
              <div className={`text-sm ${TEXT[a.level] || TEXT.info}`}>{a.message}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
