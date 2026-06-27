import { Line } from "react-chartjs-2";
import {
  Chart as ChartJS,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  Filler,
  Tooltip,
} from "chart.js";
import { fmt } from "../api";

ChartJS.register(LineElement, PointElement, LinearScale, CategoryScale, Filler, Tooltip);

const baseOpts = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: { legend: { display: false }, tooltip: { mode: "index", intersect: false } },
  scales: {
    x: { ticks: { color: "#64748b", maxTicksLimit: 6 }, grid: { color: "#161f2e" } },
    y: { ticks: { color: "#64748b" }, grid: { color: "#161f2e" } },
  },
  elements: { point: { radius: 0 } },
};

// Turn the equity snapshots into an equity line + a drawdown line.
function derive(equityRows) {
  const labels = equityRows.map((r) => fmt.time(r.ts));
  const equity = equityRows.map((r) => r.equity);
  let peak = -Infinity;
  const drawdown = equity.map((e) => {
    peak = Math.max(peak, e);
    return peak > 0 ? -((peak - e) / peak) * 100 : 0; // negative %
  });
  return { labels, equity, drawdown };
}

export default function Charts({ equity }) {
  const rows = equity || [];
  const { labels, equity: eq, drawdown } = derive(rows);
  const empty = rows.length === 0;

  return (
    <div className="grid lg:grid-cols-2 gap-4">
      <div className="card">
        <div className="card-title">Equity Curve</div>
        <div className="h-56">
          {empty ? (
            <Empty />
          ) : (
            <Line
              data={{
                labels,
                datasets: [
                  {
                    data: eq,
                    borderColor: "#3b82f6",
                    backgroundColor: "rgba(59,130,246,0.12)",
                    fill: true,
                    tension: 0.25,
                    borderWidth: 2,
                  },
                ],
              }}
              options={baseOpts}
            />
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-title">Drawdown (%)</div>
        <div className="h-56">
          {empty ? (
            <Empty />
          ) : (
            <Line
              data={{
                labels,
                datasets: [
                  {
                    data: drawdown,
                    borderColor: "#ef4444",
                    backgroundColor: "rgba(239,68,68,0.15)",
                    fill: true,
                    tension: 0.25,
                    borderWidth: 2,
                  },
                ],
              }}
              options={baseOpts}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function Empty() {
  return (
    <div className="h-full flex items-center justify-center text-slate-500 text-sm">
      No equity snapshots yet — they accumulate as the portfolio is polled.
    </div>
  );
}
