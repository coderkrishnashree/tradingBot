import { useMemo } from "react";

// EXECUTION LOG · LIVE — the reel's terminal feed, driven by the alerts
// stream. Newest first, mono, level-colored with a text tag (never color
// alone). Rendered in the universe theme's Overview.
const LEVEL = {
  success: { cls: "text-up", tag: "OK " },
  warning: { cls: "text-down", tag: "WRN" },
  danger: { cls: "text-down", tag: "ERR" },
  info: { cls: "text-slate-400", tag: "INF" },
};

export default function ExecutionLog({ alerts, limit = 14 }) {
  const rows = useMemo(() => (alerts || []).slice(0, limit), [alerts, limit]);
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-2">
        <div className="card-title mb-0">Execution Log</div>
        <span className="flex items-center gap-1.5 text-[10px] font-mono text-accent">
          <span className="h-1.5 w-1.5 rounded-full bg-accent animate-blink" /> LIVE
        </span>
      </div>
      <div className="font-mono text-[11px] leading-relaxed max-h-56 overflow-y-auto space-y-0.5">
        {rows.length === 0 && <div className="text-slate-600">awaiting events…</div>}
        {rows.map((a) => {
          const lv = LEVEL[a.level] || LEVEL.info;
          const time = a.ts ? new Date(a.ts).toLocaleTimeString([], { hour12: false }) : "--:--:--";
          return (
            <div key={a.id ?? `${a.ts}-${a.message}`} className="flex gap-2 items-baseline">
              <span className="text-slate-600 shrink-0">{time}</span>
              <span className={`${lv.cls} shrink-0`}>{lv.tag}</span>
              <span className="text-accent2/80 shrink-0">[{a.kind || "sys"}]</span>
              <span className="text-slate-300 truncate">{a.message}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
