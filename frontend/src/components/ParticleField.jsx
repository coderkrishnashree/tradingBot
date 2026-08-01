import { useEffect, useRef } from "react";
import { useTheme, tokenRGB } from "../theme";

// Deep-space starfield: three parallax layers of drifting stars in starlight
// white, nebula violet and star cyan, plus an occasional shooting star.
// Rendered only in the universe theme. Static single frame when the user
// prefers reduced motion.
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
    let stars = [];
    let meteor = null;
    let nextMeteor = 4000;

    const COLORS = [
      "226,232,255",                                   // starlight
      tokenRGB("--accent", 1).slice(5, -3),            // violet "r,g,b"
      tokenRGB("--accent-2", 1).slice(5, -3),          // cyan
    ];

    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas.clientWidth; h = canvas.clientHeight;
      canvas.width = w * dpr; canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const n = w < 640 ? 90 : 190;
      if (stars.length !== n) {
        stars = Array.from({ length: n }, (_, i) => {
          const layer = i % 3;                          // 0 far … 2 near
          return {
            x: Math.random() * w,
            y: Math.random() * h,
            v: 0.015 + layer * 0.03,                    // parallax drift
            r: 0.4 + layer * 0.55 + Math.random() * 0.7,
            c: COLORS[i % 7 === 0 ? 1 : i % 11 === 0 ? 2 : 0],
            tw: Math.random() * Math.PI * 2,
            ts: 0.6 + Math.random() * 1.2,              // twinkle speed
          };
        });
      }
    }

    function frame(t) {
      ctx.clearRect(0, 0, w, h);
      for (const s of stars) {
        s.x -= s.v; s.y += s.v * 0.35;
        if (s.x < -4) { s.x = w + 4; s.y = Math.random() * h; }
        if (s.y > h + 4) s.y = -4;
        const tw = 0.45 + 0.55 * (0.5 + 0.5 * Math.sin(s.tw + (t / 1000) * s.ts));
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${s.c},${0.75 * tw})`;
        ctx.shadowColor = `rgba(${s.c},0.9)`;
        ctx.shadowBlur = s.r * 4 * tw;
        ctx.fill();
        ctx.shadowBlur = 0;
      }

      // shooting star
      if (!reduced) {
        if (!meteor && t > nextMeteor) {
          const fromTop = Math.random() > 0.5;
          meteor = {
            x: Math.random() * w * 0.7 + w * 0.2,
            y: fromTop ? -10 : Math.random() * h * 0.3,
            vx: -(3.5 + Math.random() * 3),
            vy: 2 + Math.random() * 2,
            life: 1,
          };
          nextMeteor = t + 6000 + Math.random() * 9000;
        }
        if (meteor) {
          meteor.x += meteor.vx; meteor.y += meteor.vy;
          meteor.life -= 0.016;
          const grad = ctx.createLinearGradient(
            meteor.x, meteor.y, meteor.x - meteor.vx * 14, meteor.y - meteor.vy * 14);
          grad.addColorStop(0, `rgba(226,232,255,${0.9 * meteor.life})`);
          grad.addColorStop(1, "rgba(226,232,255,0)");
          ctx.strokeStyle = grad;
          ctx.lineWidth = 1.6;
          ctx.beginPath();
          ctx.moveTo(meteor.x, meteor.y);
          ctx.lineTo(meteor.x - meteor.vx * 14, meteor.y - meteor.vy * 14);
          ctx.stroke();
          if (meteor.life <= 0 || meteor.x < -60 || meteor.y > h + 60) meteor = null;
        }
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
