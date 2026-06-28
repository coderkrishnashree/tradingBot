import { useEffect, useState } from "react";
import { Line } from "react-chartjs-2";
import {
  Chart as ChartJS, LineElement, PointElement, LinearScale, CategoryScale, Filler, Tooltip,
} from "chart.js";
import { api, fmt } from "../api";

ChartJS.register(LineElement, PointElement, LinearScale, CategoryScale, Filler, Tooltip);

const TFS = ["15m", "30m", "1h", "4h", "1d"];
const PERIODS = [
  { label: "1 month", days: 30 },
  { label: "3 months", days: 90 },
  { label: "6 months", days: 180 },
  { label: "1 year", days: 365 },
];

function Stat({ label, value, color }) {
  return (
    <div className="bg-ink-900 rounded-lg p-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`text-xl font-mono font-bold ${color || "text-slate-100"}`}>{value}</div>
    </div>
  );
}

// Backtest the mechanical screener over history, with a selectable period.
export default function BacktestTab() {
  const [cfg, setCfg] = useState(null);
  const [form, setForm] = useState({
    symbol: "BTC/USDT:USDT", timeframe: "1h", days: 90,
    threshold: 50, sl_pct: 2, tp_pct: 4, size_pct: 5, leverage: 3, fee_pct: 0.055,
  });
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.getConfig().then((c) => {
      setCfg(c);
      setForm((f) => ({
        ...f, symbol: (c.symbol_universe || [])[0] || f.symbol, timeframe: c.timeframe || f.timeframe,
        sl_pct: c.stop_loss_pct, tp_pct: c.take_profit_pct, size_pct: c.position_size_pct, leverage: c.leverage,
      }));
    });
  }, []);

  async function run() {
    setBusy(true); setErr(null); setRes(null);
    try {
      const r = await api.backtest(form);
      if (r.error) setErr(r.error); else setRes(r);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  const s = res?.stats;
  const symbols = cfg?.symbol_universe || [form.symbol];
  const setF = (k, v) => setForm({ ...form, [k]: v });

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="card-title">Backtest — mechanical screener over history</div>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-5 gap-3">
          <label className="block"><span className="text-xs text-slate-400">Symbol</span>
            <select className="input" value={form.symbol} onChange={(e) => setF("symbol", e.target.value)}>
              {symbols.map((x) => <option key={x} value={x}>{x}</option>)}
            </select></label>
          <label className="block"><span className="text-xs text-slate-400">Timeframe</span>
            <select className="input" value={form.timeframe} onChange={(e) => setF("timeframe", e.target.value)}>
              {TFS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select></label>
          <label className="block"><span className="text-xs text-slate-400">Period</span>
            <select className="input" value={form.days} onChange={(e) => setF("days", Number(e.target.value))}>
              {PERIODS.map((p) => <option key={p.days} value={p.days}>{p.label}</option>)}
            </select></label>
          <label className="block"><span className="text-xs text-slate-400">Confidence threshold %</span>
            <input type="number" className="input" min="0" max="100" value={form.threshold} onChange={(e) => setF("threshold", Number(e.target.value))} /></label>
          <label className="block"><span className="text-xs text-slate-400">Leverage</span>
            <input type="number" className="input" min="1" max="50" value={form.leverage} onChange={(e) => setF("leverage", Number(e.target.value))} /></label>
          <label className="block"><span className="text-xs text-slate-400">Stop loss %</span>
            <input type="number" step="0.1" className="input" value={form.sl_pct} onChange={(e) => setF("sl_pct", Number(e.target.value))} /></label>
          <label className="block"><span className="text-xs text-slate-400">Take profit %</span>
            <input type="number" step="0.1" className="input" value={form.tp_pct} onChange={(e) => setF("tp_pct", Number(e.target.value))} /></label>
          <label className="block"><span className="text-xs text-slate-400">Size % equity</span>
            <input type="number" step="0.1" className="input" value={form.size_pct} onChange={(e) => setF("size_pct", Number(e.target.value))} /></label>
          <label className="block"><span className="text-xs text-slate-400">Fee % / side</span>
            <input type="number" step="0.005" className="input" value={form.fee_pct} onChange={(e) => setF("fee_pct", Number(e.target.value))} /></label>
          <div className="flex items-end">
            <button onClick={run} disabled={busy} className="btn w-full bg-accent hover:bg-blue-600 text-white">
              {busy ? "Running…" : "▶ Run backtest"}
            </button>
          </div>
        </div>
        {err && <p className="text-down text-sm mt-2">{err}</p>}
        {busy && <p className="text-slate-500 text-sm mt-2">Fetching history and replaying — can take 10–30s for long periods.</p>}
      </div>

      {s && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
            <Stat label="Total Return" value={fmt.pct(s.total_return_pct)} color={s.total_return_pct >= 0 ? "text-up" : "text-down"} />
            <Stat label="Trades" value={s.num_trades} />
            <Stat label="Win Rate" value={fmt.pct(s.win_rate_pct, 1)} />
            <Stat label="Profit Factor" value={s.profit_factor} color={s.profit_factor >= 1 ? "text-up" : "text-down"} />
            <Stat label="Sharpe" value={s.sharpe} color={s.sharpe >= 1 ? "text-up" : ""} />
            <Stat label="Max Drawdown" value={fmt.pct(s.max_drawdown_pct)} color="text-down" />
            <Stat label="Avg Win" value={fmt.pct(s.avg_win_pct, 2)} color="text-up" />
            <Stat label="Avg Loss" value={fmt.pct(s.avg_loss_pct, 2)} color="text-down" />
          </div>

          <div className="card">
            <div className="card-title">Equity Curve ({fmt.time(res.from)} → {fmt.time(res.to)}, {res.bars} bars)</div>
            <div className="h-64">
              <Line
                data={{
                  labels: res.equity.map((p) => fmt.time(p.t)),
                  datasets: [{
                    data: res.equity.map((p) => p.equity),
                    borderColor: s.total_return_pct >= 0 ? "#22c55e" : "#ef4444",
                    backgroundColor: "rgba(59,130,246,0.10)", fill: true, tension: 0.2, pointRadius: 0, borderWidth: 2,
                  }],
                }}
                options={{
                  responsive: true, maintainAspectRatio: false,
                  plugins: { legend: { display: false } },
                  scales: { x: { ticks: { color: "#64748b", maxTicksLimit: 6 }, grid: { color: "#161f2e" } },
                            y: { ticks: { color: "#64748b" }, grid: { color: "#161f2e" } } },
                }}
              />
            </div>
            <p className="text-xs text-slate-500 mt-2">Starts at 10,000. Fees applied per side; funding not modelled. Fills assume the stop/target is hit intrabar.</p>
          </div>

          <div className="card">
            <div className="card-title">Trades (last {res.trades.length})</div>
            <div className="overflow-x-auto max-h-80 overflow-y-auto">
              <table className="w-full">
                <thead className="sticky top-0 bg-ink-800"><tr>
                  <th className="th">In</th><th className="th">Out</th><th className="th">Dir</th>
                  <th className="th">Entry</th><th className="th">Exit</th><th className="th">Result</th><th className="th">Return</th>
                </tr></thead>
                <tbody>
                  {res.trades.slice().reverse().map((t, i) => (
                    <tr key={i} className="hover:bg-ink-700/40">
                      <td className="td text-slate-400">{fmt.timeMs(t.t_in)}</td>
                      <td className="td text-slate-400">{fmt.timeMs(t.t_out)}</td>
                      <td className={`td font-bold ${t.dir === "long" ? "text-up" : "text-down"}`}>{t.dir.toUpperCase()}</td>
                      <td className="td">{fmt.num(t.entry, 4)}</td>
                      <td className="td">{fmt.num(t.exit, 4)}</td>
                      <td className={`td ${t.result === "tp" ? "text-up" : "text-down"}`}>{t.result.toUpperCase()}</td>
                      <td className={`td ${t.ret_pct >= 0 ? "text-up" : "text-down"}`}>{fmt.pct(t.ret_pct, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
