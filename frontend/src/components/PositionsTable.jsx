import { fmt } from "../api";
import { SkeletonRow } from "./Skeleton";
import { PairLink } from "../chart.jsx";

// P&L (USDT) if a price level is hit, for the given side & size (contracts).
function pnlAt(level, entry, size, side) {
  if (!level || !entry || !size) return null;
  return (level - entry) * size * (side === "long" ? 1 : -1);
}
const pct = (lvl, ref) => (lvl && ref ? ` (${((lvl / ref - 1) * 100).toFixed(1)}%)` : "");

// Open positions pulled live from Bybit. Click a symbol for its live chart.
export default function PositionsTable({ positions }) {
  const loading = positions == null;
  const rows = positions || [];

  return (
    <div className="card">
      <div className="card-title">Open Positions ({rows.length})</div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr>
              <th className="th">Symbol</th><th className="th">Side</th><th className="th">Size</th>
              <th className="th">Value (USDT)</th><th className="th">Entry</th><th className="th">Mark</th>
              <th className="th">Stop loss</th><th className="th">Take profit</th>
              <th className="th">uPnL</th><th className="th">Liq.</th>
            </tr>
          </thead>
          <tbody>
            {loading && <><SkeletonRow cols={10} /><SkeletonRow cols={10} /></>}
            {!loading && rows.length === 0 && (
              <tr><td className="td text-slate-500" colSpan={10}>No open positions.</td></tr>
            )}
            {rows.map((p, i) => {
              const value = p.size && p.mark_price ? p.size * p.mark_price : null;
              const slPnl = pnlAt(p.stop_loss, p.entry_price, p.size, p.side);
              const tpPnl = pnlAt(p.take_profit, p.entry_price, p.size, p.side);
              return (
                <tr key={i} className="hover:bg-ink-700/40">
                  <td className="td"><PairLink symbol={p.symbol} entry={p.entry_price} side={p.side} /></td>
                  <td className={`td font-bold ${p.side === "long" ? "text-up" : "text-down"}`}>{(p.side || "").toUpperCase()}</td>
                  <td className="td">{fmt.num(p.size, 4)}</td>
                  <td className="td">{value ? fmt.num(value, 2) : "—"}</td>
                  <td className="td">{fmt.num(p.entry_price, 2)}</td>
                  <td className="td">{fmt.num(p.mark_price, 2)}</td>
                  <td className="td text-down">
                    {p.stop_loss ? <>{fmt.num(p.stop_loss, 2)}<span className="text-slate-500">{pct(p.stop_loss, p.mark_price)}</span>
                      {slPnl != null && <div className="text-xs">{fmt.signed(slPnl)} USDT</div>}</> : "—"}
                  </td>
                  <td className="td text-up">
                    {p.take_profit ? <>{fmt.num(p.take_profit, 2)}<span className="text-slate-500">{pct(p.take_profit, p.mark_price)}</span>
                      {tpPnl != null && <div className="text-xs">{fmt.signed(tpPnl)} USDT</div>}</> : "—"}
                  </td>
                  <td className={`td ${p.unrealized_pnl >= 0 ? "text-up" : "text-down"}`}>{fmt.signed(p.unrealized_pnl)}</td>
                  <td className="td text-slate-400">{fmt.num(p.liquidation_price, 2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {!loading && rows.length > 0 && (
        <div className="text-xs text-slate-500 mt-2">Click a symbol for its live chart. SL/TP show the price and the P&L if hit.</div>
      )}
    </div>
  );
}
