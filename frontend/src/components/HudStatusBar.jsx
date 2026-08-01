import { useEffect, useState } from "react";

// Thin system-readout strip under the header: blinking status nodes + UTC clock.
function Node({ ok = true, warn = false, label, value }) {
  const c = warn ? "text-down" : ok ? "text-up" : "text-slate-500";
  return (
    <span className="flex items-center gap-1.5 whitespace-nowrap">
      <span className={`${c} ${ok || warn ? "animate-blink" : ""} text-[8px]`}>●</span>
      <span className="text-slate-500">{label}</span>
      <span className="text-slate-200">{value}</span>
    </span>
  );
}

export default function HudStatusBar({ mode, positions, scan, alerts, portfolio }) {
  const [clock, setClock] = useState("");
  useEffect(() => {
    const tick = () => setClock(new Date().toISOString().slice(11, 19));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  const nPos = positions?.length ?? "—";
  const rows = scan?.rows || [];
  const nSignals = rows.filter((r) => (r.composite || {}).direction !== "flat").length;
  const gates = (alerts || []).filter((a) => a.kind === "gate").length;
  const live = mode?.is_live;
  const killed = mode?.kill_switch_active;

  const equity = portfolio?.total_value;
  const pnl = portfolio?.todays_pnl;
  return (
    <div className="card py-2 px-4 flex flex-wrap items-center gap-x-6 gap-y-1 text-[11px] font-mono uppercase tracking-wider">
      <Node ok={!killed} warn={killed} label="SYS" value={killed ? "HALTED" : "ONLINE"} />
      <Node ok warn={live} label="MODE" value={live ? "LIVE" : "PAPER"} />
      {equity != null && (
        <span className="flex items-center gap-1.5 whitespace-nowrap">
          <span className="text-slate-500">EQUITY</span>
          <span className="text-slate-200 tabular-nums">{Number(equity).toFixed(2)}</span>
          {pnl != null && (
            <span className={`tabular-nums ${pnl >= 0 ? "text-up" : "text-down"}`}>
              {pnl >= 0 ? "+" : ""}{Number(pnl).toFixed(2)}
            </span>
          )}
        </span>
      )}
      <Node ok={nPos !== "—"} label="POSITIONS" value={nPos} />
      <Node ok={rows.length > 0} label="SIGNALS" value={`${nSignals}/${rows.length || "—"}`} />
      <Node ok label="GATES" value={gates} />
      <span className="ml-auto text-accent/80 tabular-nums tracking-[0.2em]">{clock} UTC</span>
    </div>
  );
}
