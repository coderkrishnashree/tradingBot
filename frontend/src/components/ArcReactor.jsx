import { fmt } from "../api";
import Ticker from "./Ticker";

// The command-deck centerpiece: concentric counter-rotating holo rings around
// the account's total value, with today's P&L underneath. Pure SVG + CSS.
export default function ArcReactor({ portfolio, mode }) {
  const p = portfolio || {};
  const pnl = p.todays_pnl;
  const live = mode?.is_live;
  const pnlColor = pnl == null ? "text-slate-400" : pnl >= 0 ? "text-up" : "text-down";
  const signed = (n) => `${n >= 0 ? "+" : ""}${fmt.usdt(n)}`;

  return (
    <div className="card flex flex-col items-center justify-center py-6 overflow-hidden">
      <div className="relative" style={{ width: 300, height: 300 }}>
        <svg viewBox="0 0 300 300" className="absolute inset-0 w-full h-full">
          <defs>
            <radialGradient id="coreGlow" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="rgba(0,229,255,0.28)" />
              <stop offset="55%" stopColor="rgba(0,229,255,0.07)" />
              <stop offset="100%" stopColor="rgba(0,229,255,0)" />
            </radialGradient>
          </defs>
          <circle cx="150" cy="150" r="140" fill="url(#coreGlow)" />

          {/* outer ring — slow clockwise, long dashes */}
          <g className="reactor-spin" style={{ animationDuration: "26s" }}>
            <circle cx="150" cy="150" r="132" fill="none" stroke="rgba(0,229,255,0.35)"
                    strokeWidth="1.5" strokeDasharray="60 14 8 14" />
          </g>
          {/* tick ring — counter-clockwise */}
          <g className="reactor-spin-rev" style={{ animationDuration: "40s" }}>
            <circle cx="150" cy="150" r="118" fill="none" stroke="rgba(0,229,255,0.5)"
                    strokeWidth="4" strokeDasharray="2 10" />
          </g>
          {/* mid ring — medium clockwise, arc segments */}
          <g className="reactor-spin" style={{ animationDuration: "14s" }}>
            <circle cx="150" cy="150" r="102" fill="none" stroke="rgba(125,249,255,0.55)"
                    strokeWidth="2" strokeDasharray="140 60 30 60"
                    style={{ filter: "drop-shadow(0 0 6px rgba(0,229,255,0.8))" }} />
          </g>
          {/* inner ring — fast counter-clockwise */}
          <g className="reactor-spin-rev" style={{ animationDuration: "8s" }}>
            <circle cx="150" cy="150" r="86" fill="none" stroke="rgba(0,229,255,0.4)"
                    strokeWidth="1" strokeDasharray="20 8 4 8" />
          </g>
          {/* core */}
          <circle cx="150" cy="150" r="72" fill="rgba(4,16,26,0.72)"
                  stroke="rgba(0,229,255,0.5)" strokeWidth="1.5"
                  style={{ filter: "drop-shadow(0 0 18px rgba(0,229,255,0.5))" }} />
        </svg>

        <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-8">
          <div className="text-[9px] font-display uppercase tracking-[0.3em] text-accent/70">
            Total Value
          </div>
          <div className="font-mono font-bold text-2xl tabular-nums text-slate-100 mt-1 glow-text">
            {p.total_value == null ? "—" : <Ticker value={p.total_value} format={fmt.usdt} />}
          </div>
          <div className={`font-mono text-sm tabular-nums mt-2 ${pnlColor}`}>
            {pnl == null ? "· · ·" : <Ticker value={pnl} format={signed} />}
          </div>
          <div className="text-[9px] font-display uppercase tracking-[0.25em] text-slate-500 mt-0.5">
            Today
          </div>
        </div>
      </div>

      <div className={`mt-2 px-3 py-1 rounded-md text-[10px] font-display font-bold uppercase tracking-[0.3em]
                       ring-1 ${live ? "text-down ring-down/50 bg-down/10" : "text-up ring-up/50 bg-up/10"}`}>
        {live ? "⚠ LIVE CORE" : "SIM CORE"}
      </div>
    </div>
  );
}
