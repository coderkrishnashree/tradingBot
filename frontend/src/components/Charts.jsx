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

// Neon glow for the line itself — drawn with a canvas shadow, restored after.
const glowPlugin = {
  id: "holoGlow",
  beforeDatasetDraw(chart, args) {
    const c = chart.ctx;
    c.save();
    const ds = chart.data.datasets[args.index] || {};
    c.shadowColor = typeof ds.borderColor === "string" ? ds.borderColor : "rgba(0,229,255,0.8)";
    c.shadowBlur = 8;
  },
  afterDatasetDraw(chart) {
    chart.ctx.restore();
  },
};
ChartJS.register(glowPlugin);

const baseOpts = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { display: false },
    tooltip: {
      mode: "index",
      intersect: false,
      backgroundColor: "rgba(4,16,26,0.92)",
      borderColor: "rgba(0,229,255,0.35)",
      borderWidth: 1,
      titleColor: "#7df9ff",
      bodyColor: "#e2e8f0",
      titleFont: { family: "'Share Tech Mono', monospace" },
      bodyFont: { family: "'Share Tech Mono', monospace" },
    },
  },
  scales: {
    x: { ticks: { color: "#5b7a8c", maxTicksLimit: 6 }, grid: { color: "rgba(0,229,255,0.05)" } },
    y: { ticks: { color: "#5b7a8c" }, grid: { color: "rgba(0,229,255,0.05)" } },
  },
  elements: { point: { radius: 0, hoverRadius: 4, hoverBackgroundColor: "#00e5ff" } },
};

// Vertical gradient fill under a line: color → transparent.
function gradientFill(rgb) {
  return (ctx) => {
    const { chart } = ctx;
    const { ctx: c, chartArea } = chart;
    if (!chartArea) return `rgba(${rgb},0.1)`;
    const g = c.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
    g.addColorStop(0, `rgba(${rgb},0.28)`);
    g.addColorStop(1, `rgba(${rgb},0.0)`);
    return g;
  };
}

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
                    borderColor: "#00e5ff",
                    backgroundColor: gradientFill("0,229,255"),
                    fill: true,
                    tension: 0.3,
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
                    borderColor: "#ff3b5c",
                    backgroundColor: gradientFill("255,59,92"),
                    fill: true,
                    tension: 0.3,
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
