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
import { useTheme, tokenRGB } from "../theme";

ChartJS.register(LineElement, PointElement, LinearScale, CategoryScale, Filler, Tooltip);

// Optional line glow — blur amount comes from options.plugins.holoGlow.blur
// (0 in the table theme: crisp lines, no effects).
const glowPlugin = {
  id: "holoGlow",
  beforeDatasetDraw(chart, args) {
    const blur = chart.options?.plugins?.holoGlow?.blur ?? 0;
    if (!blur) return;
    const c = chart.ctx;
    c.save();
    const ds = chart.data.datasets[args.index] || {};
    c.shadowColor = typeof ds.borderColor === "string" ? ds.borderColor : tokenRGB("--accent", 0.8);
    c.shadowBlur = blur;
  },
  afterDatasetDraw(chart) {
    const blur = chart.options?.plugins?.holoGlow?.blur ?? 0;
    if (blur) chart.ctx.restore();
  },
};
ChartJS.register(glowPlugin);

// "R G B" token triplet → "r,g,b" (for rgba gradients)
const triplet = (name) => tokenRGB(name, 1).slice(5, -3);

// Vertical gradient fill under a line: color → transparent.
function gradientFill(rgb, strong) {
  return (ctx) => {
    const { chart } = ctx;
    const { ctx: c, chartArea } = chart;
    if (!chartArea) return `rgba(${rgb},0.1)`;
    const g = c.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
    g.addColorStop(0, `rgba(${rgb},${strong ? 0.28 : 0.16})`);
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
  const { theme, isUniverse } = useTheme();
  const rows = equity || [];
  const { labels, equity: eq, drawdown } = derive(rows);
  const empty = rows.length === 0;

  const grid = tokenRGB("--accent", 0.06);
  const opts = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      holoGlow: { blur: isUniverse ? 8 : 0 },
      tooltip: {
        mode: "index",
        intersect: false,
        backgroundColor: tokenRGB("--ink-950", 0.92),
        borderColor: tokenRGB("--accent", 0.35),
        borderWidth: 1,
        titleColor: tokenRGB("--accent-2", 1),
        bodyColor: "#e2e8f0",
        titleFont: { family: "'JetBrains Mono', monospace" },
        bodyFont: { family: "'JetBrains Mono', monospace" },
      },
    },
    scales: {
      x: { ticks: { color: "#8494ab", maxTicksLimit: 6 }, grid: { color: grid } },
      y: { ticks: { color: "#8494ab" }, grid: { color: grid } },
    },
    elements: { point: { radius: 0, hoverRadius: 4, hoverBackgroundColor: tokenRGB("--accent", 1) } },
  };

  return (
    <div className="grid lg:grid-cols-2 gap-4" key={theme}>
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
                    borderColor: tokenRGB("--accent", 1),
                    backgroundColor: gradientFill(triplet("--accent"), isUniverse),
                    fill: true,
                    tension: 0.3,
                    borderWidth: 2,
                  },
                ],
              }}
              options={opts}
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
                    borderColor: tokenRGB("--down", 1),
                    backgroundColor: gradientFill(triplet("--down"), isUniverse),
                    fill: true,
                    tension: 0.3,
                    borderWidth: 2,
                  },
                ],
              }}
              options={opts}
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
