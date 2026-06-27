import { useEffect, useState } from "react";
import { Line } from "react-chartjs-2";
import { api, fmt } from "../api";
import { Skeleton } from "./Skeleton";

const TFS = ["5m", "15m", "1h", "4h", "1d"];

// Modal price chart for a symbol. Opened by clicking a position/trade row.
// Draws recent closes plus a dashed line at the position entry (if provided).
export default function SymbolChart({ symbol, entry, side, onClose }) {
  const [tf, setTf] = useState("15m");
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    setData(null); setErr(null);
    api.ohlcv(symbol, tf, 120)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(e.message));
    return () => { alive = false; };
  }, [symbol, tf]);

  const candles = data?.candles || [];
  const labels = candles.map((c) => fmt.time(c.t));
  const closes = candles.map((c) => c.c);
  const last = closes.length ? closes[closes.length - 1] : null;
  const up = last != null && entry != null ? last >= entry : true;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div className="bg-ink-800 border border-ink-600 rounded-2xl p-4 w-full max-w-3xl shadow-2xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="font-bold text-lg">{symbol}</div>
            <div className="text-xs text-slate-500">
              {side && <span className={`mr-2 font-semibold ${side === "long" ? "text-up" : "text-down"}`}>{side.toUpperCase()}</span>}
              {entry != null && <>entry {fmt.num(entry, 4)} · </>}
              last {last != null ? fmt.num(last, 4) : "—"}
            </div>
          </div>
          <div className="flex items-center gap-1">
            {TFS.map((t) => (
              <button key={t} onClick={() => setTf(t)}
                className={`btn text-xs py-1 ${tf === t ? "bg-accent text-white" : "bg-ink-700 text-slate-400"}`}>{t}</button>
            ))}
            <button onClick={onClose} className="btn text-xs py-1 bg-ink-700 hover:bg-ink-600 text-slate-200 ml-2">✕</button>
          </div>
        </div>

        <div className="h-72">
          {err && <div className="h-full flex items-center justify-center text-down text-sm">{err}</div>}
          {!data && !err && <Skeleton className="h-full w-full" />}
          {data && (
            <Line
              data={{
                labels,
                datasets: [
                  {
                    data: closes,
                    borderColor: up ? "#22c55e" : "#ef4444",
                    backgroundColor: up ? "rgba(34,197,94,0.10)" : "rgba(239,68,68,0.10)",
                    fill: true, tension: 0.2, borderWidth: 2, pointRadius: 0,
                  },
                  ...(entry != null ? [{
                    data: closes.map(() => entry),
                    borderColor: "#94a3b8", borderDash: [6, 6], borderWidth: 1,
                    pointRadius: 0, fill: false,
                  }] : []),
                ],
              }}
              options={{
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { mode: "index", intersect: false } },
                scales: {
                  x: { ticks: { color: "#64748b", maxTicksLimit: 6 }, grid: { color: "#161f2e" } },
                  y: { ticks: { color: "#64748b" }, grid: { color: "#161f2e" } },
                },
              }}
            />
          )}
        </div>
        {entry != null && (
          <div className="text-xs text-slate-500 mt-2">Dashed line = your entry ({fmt.num(entry, 4)}).</div>
        )}
      </div>
    </div>
  );
}
