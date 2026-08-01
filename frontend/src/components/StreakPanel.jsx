import { useMemo } from "react";
import { api, usePoll, fmt } from "../api";
import Ticker from "./Ticker";

// LIVE STREAK — the reel's gamified trader panel: current win streak from the
// newest closed trades, plus a mini bar strip of the last 20 results.
export default function StreakPanel() {
  const trades = usePoll(api.trades, 30000);
  const closed = trades.data?.closed || [];

  const { streak, streakIsWin, last, realized24h } = useMemo(() => {
    let s = 0, isWin = null;
    for (const t of closed) {                    // newest first
      const win = (t.realized || 0) > 0;
      if (isWin === null) { isWin = win; s = 1; continue; }
      if (win === isWin) s += 1; else break;
    }
    const dayAgo = Date.now() - 86400e3;
    const r24 = closed.filter((t) => (t.closed_at || 0) >= dayAgo)
                      .reduce((sum, t) => sum + (t.realized || 0), 0);
    return { streak: s, streakIsWin: isWin, last: closed.slice(0, 20).reverse(), realized24h: r24 };
  }, [closed]);

  const col = streakIsWin ? "text-up" : streakIsWin === false ? "text-down" : "text-slate-500";

  return (
    <div className="card">
      <div className="card-title">Live Streak</div>
      <div className="flex items-end gap-4">
        <div className={`font-mono font-bold text-4xl leading-none ${col} glow-text`}>
          ×{closed.length ? streak : 0}
        </div>
        <div className="text-[11px] font-mono text-slate-400 leading-tight pb-0.5">
          {closed.length === 0 ? "no closed trades yet"
            : streakIsWin ? "consecutive wins" : "consecutive losses"}
          <div className="text-slate-500 mt-0.5">
            24h realized:{" "}
            <span className={realized24h >= 0 ? "text-up" : "text-down"}>
              <Ticker value={realized24h} format={(n) => `${n >= 0 ? "+" : ""}${fmt.num(n, 2)}`} /> USDT
            </span>
          </div>
        </div>
      </div>
      {/* last-20 results strip: up bars = wins, down bars = losses */}
      <div className="flex items-end gap-[3px] h-9 mt-3" aria-label="Last 20 trade results">
        {last.map((t, i) => {
          const win = (t.realized || 0) > 0;
          const mag = Math.min(1, Math.abs(t.realized || 0) / 10);
          return (
            <div key={i}
                 title={`${t.symbol} ${win ? "+" : ""}${fmt.num(t.realized, 2)} USDT`}
                 className={`flex-1 rounded-sm ${win ? "bg-up" : "bg-down"}`}
                 style={{ height: `${25 + mag * 75}%`, opacity: 0.45 + mag * 0.55 }} />
          );
        })}
        {last.length === 0 && <div className="text-[10px] text-slate-600 font-mono">—</div>}
      </div>
    </div>
  );
}
