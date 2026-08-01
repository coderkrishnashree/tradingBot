import { useEffect, useMemo, useRef, useState } from "react";

// ─────────────────────────────────────────────────────────────────────────────
// THE DECISION UNIVERSE
// Every symbol is a galaxy; every AI decision is a star orbiting it.
//   color  = action  (green buy / red short / amber close / dim blue hold)
//   size   = confidence
//   halo   = executed
//   orbit  = age (newest stars closest to the galactic core)
// Drag to fly, scroll to warp (zoom), hover a star to scan it, click to open
// the full debate. Pure canvas — handles thousands of stars at 60fps.
// ─────────────────────────────────────────────────────────────────────────────

const ACTION_COLOR = {
  buy: "0,255,163",
  short: "255,59,92",
  sell: "255,59,92",
  close: "245,158,11",
  hold: "120,160,190",
};
const GOLDEN = 2.39996;

function hash(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}

// Build world-space layout: symbol galaxies on a golden-angle spiral,
// each decision a star spiralling outward from its core by recency.
function buildUniverse(items) {
  const bySym = new Map();
  for (const d of items) {                       // items are newest-first
    const sym = d.symbol || "??";
    if (!bySym.has(sym)) bySym.set(sym, []);
    const arr = bySym.get(sym);
    if (arr.length < 400) arr.push(d);           // cap per galaxy for perf
  }
  // Bigger galaxies get inner orbits of the universe.
  const symbols = [...bySym.keys()].sort((a, b) => bySym.get(b).length - bySym.get(a).length);
  const galaxies = [];
  const stars = [];
  symbols.forEach((sym, i) => {
    const a = i * GOLDEN + (hash(sym) % 100) / 300;
    const R = 150 * Math.sqrt(i + 0.45);
    const cx = Math.cos(a) * R;
    const cy = Math.sin(a) * R * 0.82;           // slight ellipse, more cinematic
    galaxies.push({ sym, short: sym.split("/")[0], x: cx, y: cy, n: bySym.get(sym).length });
    bySym.get(sym).forEach((d, j) => {
      const baseA = (hash(d.filename || String(d.id)) % 6283) / 1000;
      const r = 16 + 5.2 * Math.sqrt(j) * 2.1;
      const conf = Number(d.confidence) || 0;    // 0..1
      stars.push({
        d,
        gx: cx, gy: cy,
        baseA: baseA + j * 0.48,
        r,
        omega: (0.02 + (j % 7) * 0.004) / (4 + r * 0.05),  // inner orbits faster
        size: 1.3 + conf * 2.6,
        rgb: ACTION_COLOR[(d.action || "hold").toLowerCase()] || ACTION_COLOR.hold,
        executed: d.status === "executed",
        tw: (hash(d.filename || "x") % 628) / 100,
      });
    });
  });
  // Static background dust
  const dust = Array.from({ length: 420 }, (_, i) => ({
    x: ((hash("dx" + i) % 2000) - 1000) * 1.6,
    y: ((hash("dy" + i) % 2000) - 1000) * 1.3,
    s: 0.4 + (hash("ds" + i) % 10) / 9,
    tw: (hash("dt" + i) % 628) / 100,
  }));
  return { galaxies, stars, dust };
}

export default function DebatesGalaxy({ items, onPick, loading, onRefresh, total }) {
  const canvasRef = useRef(null);
  const world = useMemo(() => buildUniverse(items || []), [items]);
  const view = useRef({ tx: 0, ty: 0, scale: 0.9, drag: null });
  const hoverRef = useRef(null);
  const [tip, setTip] = useState(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf, w, h, dpr;

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas.clientWidth; h = canvas.clientHeight;
      canvas.width = w * dpr; canvas.height = h * dpr;
    };
    resize();
    window.addEventListener("resize", resize);

    const toScreen = (x, y) => {
      const v = view.current;
      return [w / 2 + (x + v.tx) * v.scale, h / 2 + (y + v.ty) * v.scale];
    };

    const frame = (t) => {
      const v = view.current;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      // nebulae
      for (const [nx, ny, nr, col] of [
        [-320, -180, 500, "0,229,255"], [380, 240, 560, "120,60,255"], [60, -420, 420, "0,255,163"],
      ]) {
        const [sx, sy] = toScreen(nx, ny);
        const g = ctx.createRadialGradient(sx, sy, 0, sx, sy, nr * v.scale);
        g.addColorStop(0, `rgba(${col},0.055)`);
        g.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, w, h);
      }

      // background dust
      for (const p of world.dust) {
        const [sx, sy] = toScreen(p.x, p.y);
        if (sx < -20 || sx > w + 20 || sy < -20 || sy > h + 20) continue;
        const a = 0.16 + 0.22 * (0.5 + 0.5 * Math.sin(p.tw + t / 1400));
        ctx.fillStyle = `rgba(180,220,255,${a})`;
        ctx.fillRect(sx, sy, p.s, p.s);
      }

      // galaxies: core + faint orbit rings + label
      for (const g of world.galaxies) {
        const [sx, sy] = toScreen(g.x, g.y);
        if (sx < -260 || sx > w + 260 || sy < -260 || sy > h + 260) continue;
        const maxR = (16 + 5.2 * Math.sqrt(Math.min(g.n, 400)) * 2.1) * v.scale;
        ctx.strokeStyle = "rgba(0,229,255,0.07)";
        ctx.lineWidth = 1;
        for (const rr of [0.45, 0.75, 1]) {
          ctx.beginPath(); ctx.arc(sx, sy, maxR * rr, 0, Math.PI * 2); ctx.stroke();
        }
        ctx.beginPath();
        ctx.arc(sx, sy, 4.5, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(125,249,255,0.95)";
        ctx.shadowColor = "rgba(0,229,255,1)"; ctx.shadowBlur = 14;
        ctx.fill(); ctx.shadowBlur = 0;
        ctx.font = "600 11px Orbitron, monospace";
        ctx.fillStyle = "rgba(148,190,210,0.85)";
        ctx.textAlign = "center";
        ctx.fillText(`${g.short} · ${g.n}`, sx, sy - maxR - 8);
      }

      // stars
      const tt = reduced ? 0 : t;
      const hov = hoverRef.current;
      for (const s of world.stars) {
        const a = s.baseA + tt * s.omega * 0.001;
        const x = s.gx + Math.cos(a) * s.r;
        const y = s.gy + Math.sin(a) * s.r * 0.86;
        const [sx, sy] = toScreen(x, y);
        s._sx = sx; s._sy = sy;
        if (sx < -10 || sx > w + 10 || sy < -10 || sy > h + 10) continue;
        const twk = 0.65 + 0.35 * Math.sin(s.tw + t / 800);
        const size = s.size * Math.max(0.7, Math.min(v.scale, 1.8));
        const isHov = hov === s;
        ctx.beginPath();
        ctx.arc(sx, sy, isHov ? size + 2 : size, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${s.rgb},${isHov ? 1 : 0.5 + 0.45 * twk})`;
        ctx.shadowColor = `rgba(${s.rgb},0.95)`;
        ctx.shadowBlur = (s.executed ? 12 : 6) * twk + (isHov ? 8 : 0);
        ctx.fill();
        ctx.shadowBlur = 0;
        if (s.executed) {                        // halo ring = real order
          ctx.beginPath();
          ctx.arc(sx, sy, size + 3.5, 0, Math.PI * 2);
          ctx.strokeStyle = `rgba(${s.rgb},0.5)`;
          ctx.lineWidth = 1;
          ctx.stroke();
        }
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);

    // ── interactions ──
    const pos = (e) => {
      const r = canvas.getBoundingClientRect();
      return [e.clientX - r.left, e.clientY - r.top];
    };
    const down = (e) => {
      const [x, y] = pos(e);
      view.current.drag = { x, y, moved: false };
    };
    const move = (e) => {
      const [x, y] = pos(e);
      const v = view.current;
      if (v.drag) {
        const dx = x - v.drag.x, dy = y - v.drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 3) v.drag.moved = true;
        v.tx += dx / v.scale; v.ty += dy / v.scale;
        v.drag.x = x; v.drag.y = y;
        setTip(null);
        return;
      }
      // hover scan
      let best = null, bd = 144;
      for (const s of world.stars) {
        const dx = s._sx - x, dy = s._sy - y;
        const d2 = dx * dx + dy * dy;
        if (d2 < bd) { bd = d2; best = s; }
      }
      hoverRef.current = best;
      canvas.style.cursor = best ? "pointer" : "grab";
      if (best) {
        const d = best.d;
        setTip({
          x: Math.min(x + 14, w - 190), y: Math.max(y - 10, 8),
          sym: d.symbol, action: (d.action || "").toUpperCase(),
          conf: d.confidence, status: d.status, ts: d.ts, rgb: best.rgb,
        });
      } else setTip(null);
    };
    const up = (e) => {
      const v = view.current;
      const wasDrag = v.drag?.moved;
      v.drag = null;
      if (!wasDrag && hoverRef.current) onPick?.(hoverRef.current.d.filename);
    };
    const wheel = (e) => {
      e.preventDefault();
      const v = view.current;
      const [x, y] = pos(e);
      const k = e.deltaY < 0 ? 1.12 : 0.89;
      const ns = Math.max(0.28, Math.min(3.2, v.scale * k));
      // zoom toward cursor
      const wx = (x - w / 2) / v.scale - v.tx;
      const wy = (y - h / 2) / v.scale - v.ty;
      v.tx = (x - w / 2) / ns - wx;
      v.ty = (y - h / 2) / ns - wy;
      v.scale = ns;
    };
    const leave = () => { hoverRef.current = null; setTip(null); view.current.drag = null; };

    canvas.addEventListener("mousedown", down);
    canvas.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    canvas.addEventListener("wheel", wheel, { passive: false });
    canvas.addEventListener("mouseleave", leave);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      canvas.removeEventListener("mousedown", down);
      canvas.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      canvas.removeEventListener("wheel", wheel);
      canvas.removeEventListener("mouseleave", leave);
    };
  }, [world, onPick]);

  return (
    <div className="card p-0 overflow-hidden relative">
      <canvas ref={canvasRef} className="w-full block" style={{ height: "68vh", cursor: "grab" }} />

      {/* HUD overlay */}
      <div className="absolute top-3 left-4 right-4 flex items-start justify-between pointer-events-none">
        <div>
          <div className="card-title mb-1">Decision Universe</div>
          <div className="text-[10px] font-mono text-slate-500">
            {items?.length || 0} of {total ?? "—"} decisions loaded · drag to fly · scroll to warp · click a star
          </div>
        </div>
        <button onClick={onRefresh} disabled={loading}
                className="btn pointer-events-auto text-xs bg-accent/15 text-accent ring-1 ring-accent/40 hover:bg-accent/25">
          {loading ? "◈ mapping…" : "⟳ re-scan"}
        </button>
      </div>
      <div className="absolute bottom-3 left-4 flex gap-4 text-[10px] font-mono text-slate-500 pointer-events-none">
        <span><span className="text-up">●</span> buy</span>
        <span><span className="text-down">●</span> short</span>
        <span style={{ color: "#f59e0b" }}>● close</span>
        <span className="text-slate-400">● hold</span>
        <span className="text-accent/70">◦ halo = executed</span>
        <span>size = confidence</span>
      </div>

      {/* scan tooltip */}
      {tip && (
        <div className="absolute pointer-events-none px-3 py-2 rounded-md text-[11px] font-mono
                        bg-ink-950/90 border backdrop-blur-sm"
             style={{ left: tip.x, top: tip.y, borderColor: `rgba(${tip.rgb},0.5)`,
                      boxShadow: `0 0 14px rgba(${tip.rgb},0.25)` }}>
          <div style={{ color: `rgb(${tip.rgb})` }} className="font-bold">{tip.action} {tip.sym}</div>
          <div className="text-slate-400">conf {Number(tip.conf ?? 0).toFixed(2)} · {tip.status}</div>
          <div className="text-slate-600">{tip.ts ? new Date(tip.ts).toLocaleString() : ""}</div>
        </div>
      )}

      {loading && (!items || items.length === 0) && (
        <div className="absolute inset-0 flex items-center justify-center text-accent font-display
                        uppercase tracking-[0.3em] text-sm animate-pulse">
          ◈ Mapping the universe…
        </div>
      )}
    </div>
  );
}
