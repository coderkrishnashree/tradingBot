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
  const orders = usePoll(api.orders, 4000);

  const p = pnl.data || {};

  return (
    <div className="space-y-4">
      <PortfolioOverview portfolio={portfolio.data} />

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="card">
          <div className="card-title">P&amp;L Breakdown</div>
          <div className="mb-3">
            <div className="text-xs text-slate-500">Total trading P&amp;L (realized + unrealized · deposits excluded)</div>
            <div className={`stat-big ${(p.total_pnl || 0) >= 0 ? "text-up" : "text-down"}`}>
              {(p.total_pnl || 0) >= 0 ? "+" : ""}{fmt.num(p.total_pnl, 2)} USDT
            </div>
          </div>

          <Line label="Unrealized P&L" value={p.unrealized} hint="open positions, marked to market" />
          <Line label="Realized P&L" value={p.realized_booked}
                hint={`closed trades — net of fees & funding (${p.num_closed ?? 0} closed)`} />
          <div className="mt-2 mb-3 text-xs text-slate-500 font-mono">
            {fmt.num(p.unrealized, 2)} (unreal.) + {fmt.num(p.realized_booked, 2)} (real.) ={" "}
            <span className={(p.total_pnl || 0) >= 0 ? "text-up" : "text-down"}>{fmt.num(p.total_pnl, 2)}</span> ✓
          </div>

          <div className="p-2 rounded bg-ink-900 text-xs text-slate-500">
            Total Value above includes deposits/withdrawals; this P&amp;L does not — it's purely what
            your trading made or lost. Realized is Bybit's closed-PnL (already net of fees &amp; funding).
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
