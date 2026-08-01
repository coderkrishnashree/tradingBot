import { useMemo } from "react";
import { useChart } from "../chart";
import { useTheme, tokenRGB } from "../theme";

// Live signal orbit: every scanned pair is a body in orbit. Strong signals
// pull toward the center; color = direction (up green / down rose / grey
// flat). A sweep rotates continuously. Clicking a body opens its chart.
function hashAngle(sym) {
  let h = 0;
  for (let i = 0; i < sym.length; i++) h = (h * 31 + sym.charCodeAt(i)) >>> 0;
  return (h % 3600) / 3600 * Math.PI * 2;
}

export default function RadarScope({ scan }) {
  const openChart = useChart();
  const { theme } = useTheme();
  const A = (a) => tokenRGB("--accent", a);
  const upC = tokenRGB("--up", 1);
  const downC = tokenRGB("--down", 1);
  const rows = scan?.rows || [];

  const blips = useMemo(() => rows.map((r) => {
    const comp = r.composite || {};
    const conf = Number(comp.confidence_pct) || 0;
    const dir = comp.direction;
    const a = hashAngle(r.symbol || "");
    const radius = 18 + (1 - Math.min(conf, 100) / 100) * 72;   // strong → center
    return {
      symbol: r.symbol,
      short: (r.symbol || "").split("/")[0],
      x: 100 + Math.cos(a) * radius,
      y: 100 + Math.sin(a) * radius,
      dir,
      conf,
      color: dir === "long" ? upC : dir === "short" ? downC : "#64748b",
    };
  }), [rows, theme]);

  return (
    <div className="card" key={theme}>
      <div className="card-title">Signal Orbit</div>
      <div className="relative mx-auto" style={{ width: "min(100%, 260px)", aspectRatio: "1" }}>
        <svg viewBox="0 0 200 200" className="w-full h-full">
          {/* orbit rings + crosshair */}
          {[30, 55, 80].map((r) => (
            <circle key={r} cx="100" cy="100" r={r} fill="none"
                    stroke={A(0.15)} strokeWidth="1" />
          ))}
          <circle cx="100" cy="100" r="92" fill="none" stroke={A(0.3)} strokeWidth="1.2" />
          <line x1="8" y1="100" x2="192" y2="100" stroke={A(0.1)} strokeWidth="1" />
          <line x1="100" y1="8" x2="100" y2="192" stroke={A(0.1)} strokeWidth="1" />

          {/* rotating sweep */}
          <g className="radar-sweep">
            <path d="M 100 100 L 100 8 A 92 92 0 0 1 147 21 Z" fill={A(0.10)} />
            <line x1="100" y1="100" x2="100" y2="8" stroke={A(0.55)}
                  strokeWidth="1.5" style={{ filter: `drop-shadow(0 0 4px ${A(0.9)})` }} />
          </g>

          {/* bodies */}
          {blips.map((b) => (
            <g key={b.symbol} className="cursor-pointer"
               onClick={() => openChart(b.symbol)}>
              <circle cx={b.x} cy={b.y} r="3" fill={b.color}
                      style={{ filter: `drop-shadow(0 0 4px ${b.color})` }}>
                <animate attributeName="opacity" values="1;0.35;1" dur="2.2s"
                         repeatCount="indefinite" />
              </circle>
              <text x={b.x + 5} y={b.y + 3} fontSize="6.5" fill="#94a3b8"
                    fontFamily="'JetBrains Mono', monospace">{b.short}</text>
              <title>{`${b.symbol} — ${b.dir || "flat"} ${b.conf.toFixed(0)}%`}</title>
            </g>
          ))}
        </svg>
      </div>
      <div className="flex justify-center gap-4 mt-1 text-[10px] font-mono text-slate-500">
        <span><span className="text-up">●</span> long</span>
        <span><span className="text-down">●</span> short</span>
        <span><span className="text-slate-500">●</span> flat</span>
        <span className="text-accent/70">center = strong</span>
      </div>
    </div>
  );
}
