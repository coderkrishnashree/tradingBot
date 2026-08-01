import { useEffect, useRef, useState } from "react";

// Radial holo gauge: glowing sweep arc + big mono number. `value` in [0, max].
// color: "accent" | "up" | "down" (falls back to accent).
const COLORS = {
  accent: "#00e5ff",
  up: "#00ffa3",
  down: "#ff3b5c",
};

export default function HoloGauge({ value, max = 100, label, display, color = "accent", size = 118 }) {
  const v = Math.max(0, Math.min(1, (Number(value) || 0) / max));
  const [sweep, setSweep] = useState(0);
  const rafRef = useRef();

  // Ease the arc toward the target so updates feel alive, not jumpy.
  useEffect(() => {
    cancelAnimationFrame(rafRef.current);
    const step = () => {
      setSweep((s) => {
        const d = v - s;
        if (Math.abs(d) < 0.002) return v;
        rafRef.current = requestAnimationFrame(step);
        return s + d * 0.12;
      });
    };
    rafRef.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(rafRef.current);
  }, [v]);

  const c = COLORS[color] || COLORS.accent;
  const r = 44;
  const circ = 2 * Math.PI * r;
  const gap = 0.25;                       // bottom gap (fraction of circle)
  const track = circ * (1 - gap);
  const arc = track * sweep;
  const rot = 90 + (gap * 360) / 2;       // open the gap at the bottom

  return (
    <div className="flex flex-col items-center" style={{ width: size }}>
      <div className="relative" style={{ width: size, height: size }}>
        <svg viewBox="0 0 110 110" width={size} height={size}>
          {/* track */}
          <circle cx="55" cy="55" r={r} fill="none" stroke="rgba(0,229,255,0.10)"
                  strokeWidth="6" strokeLinecap="round"
                  strokeDasharray={`${track} ${circ}`}
                  transform={`rotate(${rot} 55 55)`} />
          {/* tick ring */}
          {Array.from({ length: 24 }).map((_, i) => {
            const a = ((rot + (i * (1 - gap) * 360) / 23) * Math.PI) / 180;
            return (
              <line key={i}
                x1={55 + Math.cos(a) * 51} y1={55 + Math.sin(a) * 51}
                x2={55 + Math.cos(a) * 54} y2={55 + Math.sin(a) * 54}
                stroke={i / 23 <= sweep ? c : "rgba(148,163,184,0.25)"}
                strokeWidth="1.5" />
            );
          })}
          {/* value arc with glow */}
          <circle cx="55" cy="55" r={r} fill="none" stroke={c}
                  strokeWidth="6" strokeLinecap="round"
                  strokeDasharray={`${arc} ${circ}`}
                  transform={`rotate(${rot} 55 55)`}
                  style={{ filter: `drop-shadow(0 0 6px ${c})` }} />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-mono font-bold text-xl tabular-nums text-slate-100"
                style={{ textShadow: `0 0 14px ${c}66` }}>
            {display ?? value}
          </span>
        </div>
      </div>
      <div className="text-[10px] font-display uppercase tracking-[0.2em] text-slate-500 -mt-2 text-center">
        {label}
      </div>
    </div>
  );
}
