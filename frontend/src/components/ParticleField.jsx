import { useEffect, useRef } from "react";
import { useTheme, tokenRGB } from "../theme";

// Floating data-motes: multicolor market dust (profit green, loss red, neon
// magenta, signal teal, white) drifting in depth over the black void — the
// reel look. Near motes are bigger, brighter and faster (parallax). Universe
// theme only; a static frame under prefers-reduced-motion.
export default function ParticleField() {
  const ref = useRef(null);
  const { theme } = useTheme();

  useEffect(() => {
    if (theme !== "universe") return;
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let w, h, dpr, raf;
    let motes = [];

    const trip = (name) => tokenRGB(name, 1).slice(5, -3);
    // Weighted palette — mostly dim white/teal dust, punctuated by neon marks.
    const PALETTE = [
      ["226,232,240", 5],          // white dust
      [trip("--accent-2"), 3],     // teal
      [trip("--up"), 2],           // mint
      [trip("--down"), 2],         // red
      [trip("--accent"), 2],       // magenta
      ["245,158,11", 1],           // amber
    ].flatMap(([c, n]) => Array(n).fill(c));

    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas.clientWidth; h = canvas.clientHeight;
      canvas.width = w * dpr; canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const n = w < 640 ? 110 : 240;
      if (motes.length !== n) {
        motes = Array.from({ length: n }, (_, i) => {
          const z = 0.25 + Math.random() * 0.75;        // depth 0..1 (near=1)
          return {
            x: Math.random() * w,
            y: Math.random() * h,
            z,
            vx: (Math.random() - 0.5) * 0.22 * z,
            vy: (Math.random() - 0.5) * 0.16 * z,
            r: (0.6 + Math.random() * 1.7) * z,
            c: PALETTE[i % PALETTE.length],
            tw: Math.random() * Math.PI * 2,
            ts: 0.5 + Math.random() * 1.4,
          };
        });
      }
    }

    function frame(t) {
      ctx.clearRect(0, 0, w, h);
      for (const m of motes) {
        m.x += m.vx; m.y += m.vy;
        if (m.x < -6) m.x = w + 6; else if (m.x > w + 6) m.x = -6;
        if (m.y < -6) m.y = h + 6; else if (m.y > h + 6) m.y = -6;
        const tw = 0.4 + 0.6 * (0.5 + 0.5 * Math.sin(m.tw + (t / 1000) * m.ts));
        const a = (0.25 + 0.6 * m.z) * tw;
        ctx.beginPath();
        ctx.arc(m.x, m.y, m.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${m.c},${a})`;
        ctx.shadowColor = `rgba(${m.c},0.9)`;
        ctx.shadowBlur = 5 * m.z * tw;
        ctx.fill();
        ctx.shadowBlur = 0;
      }
      if (!reduced) raf = requestAnimationFrame(frame);
    }

    resize();
    window.addEventListener("resize", resize);
    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, [theme]);

  if (theme !== "universe") return null;
  return (
    <canvas
      ref={ref}
      aria-hidden="true"
      className="fixed inset-0 w-full h-full pointer-events-none"
      style={{ zIndex: -1 }}
    />
  );
}
