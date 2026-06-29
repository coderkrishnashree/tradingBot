import { fmt } from "../api";
import { SkeletonRow } from "./Skeleton";
import { PairLink } from "../chart.jsx";

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
              <th className="th">Entry</th><th className="th">Mark</th><th className="th">uPnL</th><th className="th">Liq.</th>
            </tr>
          </thead>
          <tbody>
            {loading && <><SkeletonRow cols={7} /><SkeletonRow cols={7} /></>}
            {!loading && rows.length === 0 && (
              <tr><td className="td text-slate-500" colSpan={7}>No open positions.</td></tr>
            )}
            {rows.map((p, i) => (
              <tr key={i} className="hover:bg-ink-700/40">
                <td className="td"><PairLink symbol={p.symbol} entry={p.entry_price} side={p.side} /></td>
                <td className={`td font-bold ${p.side === "long" ? "text-up" : "text-down"}`}>{(p.side || "").toUpperCase()}</td>
                <td className="td">{fmt.num(p.size, 4)}</td>
                <td className="td">{fmt.num(p.entry_price, 2)}</td>
                <td className="td">{fmt.num(p.mark_price, 2)}</td>
                <td className={`td ${p.unrealized_pnl >= 0 ? "text-up" : "text-down"}`}>{fmt.signed(p.unrealized_pnl)}</td>
                <td className="td text-slate-400">{fmt.num(p.liquidation_price, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!loading && rows.length > 0 && (
        <div className="text-xs text-slate-500 mt-2">Click a symbol to open its live chart.</div>
      )}
    </div>
  );
}
