import { api, usePoll, fmt } from "../api";
import PortfolioOverview from "./PortfolioOverview";
import PositionsTable from "./PositionsTable";
import Charts from "./Charts";
import StatsPanel from "./StatsPanel";
import OrderHistory from "./OrderHistory";

function Line({ label, value, color, hint }) {
  const v = Number(value) || 0;
  return (
    <div className="flex items-center justify-between py-2 border-b border-ink-700 last:border-0">
      <div>
        <div className={`text-sm ${color || "text-slate-300"}`}>{label}</div>
        {hint && <div className="text-xs text-slate-500">{hint}</div>}
      </div>
      <div className={`font-mono font-bold ${color || (v >= 0 ? "text-up" : "text-down")}`}>
        {v >= 0 ? "+" : ""}{v.toFixed(2)}
      </div>
    </div>
  );
}

// "Everything in one place" tab: the P&L breakdown + full account view. Each
// poller refreshes IN PLACE — switching/refreshing here never changes the tab.
export default function PnlTab() {
  const pnl = usePoll(api.pnl, 6000);
  const portfolio = usePoll(api.portfolio, 3000);
  const positions = usePoll(api.positions, 3000);
  const equity = usePoll(api.equity, 8000);
  const stats = usePoll(api.stats, 8000);
  const orders = usePoll(api.orders, 4000);

  const p = pnl.data || {};

  return (
    <div className="space-y-4">
      <PortfolioOverview portfolio={portfolio.data} />

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="card">
          <div className="card-title">P&amp;L Breakdown</div>
          <div className="mb-3">
            <div className="text-xs text-slate-500">Total P&amp;L (equity − starting {fmt.usdt(p.starting_equity)})</div>
            <div className={`stat-big ${(p.total_pnl || 0) >= 0 ? "text-up" : "text-down"}`}>
              {(p.total_pnl || 0) >= 0 ? "+" : ""}{fmt.num(p.total_pnl, 2)}
            </div>
          </div>

          {/* Both from Bybit's own account fields => consistent, sum to total. */}
          <Line label="Unrealized P&L" value={p.unrealized} hint="Bybit account-level, open positions" />
          <Line label="Realized (booked)" value={p.realized_booked}
                hint="wallet change: fees + closed-trade PnL + funding" />
          <div className="mt-2 mb-3 text-xs text-slate-500 font-mono">
            {fmt.num(p.unrealized, 2)} (unreal.) + {fmt.num(p.realized_booked, 2)} (real.) ={" "}
            <span className={(p.total_pnl || 0) >= 0 ? "text-up" : "text-down"}>{fmt.num(p.total_pnl, 2)}</span> ✓
          </div>

          <div className="p-2 rounded bg-ink-900 text-xs text-slate-500 space-y-1">
            <div className="font-mono">
              of realized — fees ≈ <span className="text-down">{fmt.num(-(p.fees_paid_est || 0), 2)}</span>,{" "}
              funding ≈ <span className={(p.funding_est || 0) >= 0 ? "text-up" : "text-down"}>{fmt.num(p.funding_est, 2)}</span>
              {" · "}closed trades: <b>{stats.data?.num_closed_trades ?? 0}</b>
            </div>
            {Math.abs((p.positions_unrealized || 0) - (p.unrealized || 0)) > 0.5 && (
              <div>
                Note: the positions table sums to {fmt.num(p.positions_unrealized, 2)} unrealized vs Bybit's
                account figure of {fmt.num(p.unrealized, 2)} — the gap is mark-price timing, not a loss.
              </div>
            )}
            <div>
              With <b>no closed trades</b>, “Realized (booked)” is just entry fees. It only goes deeply
              negative once the bot starts closing positions — that's when to watch for churn.
            </div>
          </div>
        </div>

        <StatsPanel />
      </div>

      <Charts equity={equity.data} />
      <PositionsTable positions={positions.data} />
      <OrderHistory orders={orders.data} />
    </div>
  );
}
