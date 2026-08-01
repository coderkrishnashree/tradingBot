import { useEffect, useRef, useState } from "react";

// Animated number: eases from the previous value to the new one so the big
// stats feel live instead of snapping. `format` renders the interpolated value.
export default function Ticker({ value, format = (n) => n }) {
  const target = Number(value);
  const [shown, setShown] = useState(target);
  const rafRef = useRef();
  const shownRef = useRef(target);

  useEffect(() => {
    if (!Number.isFinite(target)) return;
    cancelAnimationFrame(rafRef.current);
    const from = Number.isFinite(shownRef.current) ? shownRef.current : target;
    const start = performance.now();
    const dur = 600;
    const step = (t) => {
      const k = Math.min(1, (t - start) / dur);
      const eased = 1 - Math.pow(1 - k, 3);
      const v = from + (target - from) * eased;
      shownRef.current = v;
      setShown(v);
      if (k < 1) rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(rafRef.current);
  }, [target]);

  if (!Number.isFinite(target)) return <>{format(value)}</>;
  return <>{format(shown)}</>;
}
