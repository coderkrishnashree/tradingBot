import { useMemo, useState } from "react";
import { api, usePoll, fmt } from "../api";
import { PairLink } from "../chart.jsx";

function Pager({ page, pages, setPage }) {
  if (pages <= 1) return null;
  return (
    <div className="flex items-center justify-end gap-2 mt-3 text-sm">
      <button className="btn bg-ink-700 hover:bg-ink-600 text-slate-200 py-1"
        disabled={page === 0} onClick={() => setPage(page - 1)}>← Prev</button>
      <span className="text-slate-400 font-mono">page {page + 1} / {pages}</span>
      <button className="btn bg-ink-700 hover:bg-ink-600 text-slate-200 py-1"
        disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>Next →</button>
    </div>
  );
}

// Dedicated Trades tab: current (open) trades + paginated closed-trade history.
export default function TradesTab() {
  const trades = usePoll(api.trades, 5000);
  const [page, setPage] = useState(0);
  const PER = 12;

  const open = trades.data?.open || [];
  const closed = trades.data?.closed || [];

  const pages = Math.max(1, Math.ceil(closed.length / PER));
  const pageRows = useMemo(
    () => closed.slice(page * PER, page * PER + PER),
    [closed, page]
  );

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="card-title">Current Trades ({open.length})</div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead><tr>
              <th className="th">Symbol</th><th className="th">Side</th><th className="th">Size</th>
              <th className="th">Value (USDT)</th><th className="th">Entry</th><th className="th">Mark</th>
              <th className="th">Stop loss</th><th className="th">Take profit</th>
              <th className="th">uPnL</th><th className="th">Lev</th><th className="th">Liq.</th>
            </tr></thead>
            <tbody>
              {open.length === 0 && <tr><td className="td text-slate-500" colSpan={11}>No open trades.</td></tr>}
              {open.map((t, i) => {
                const value = t.size && t.mark ? t.size * t.mark : null;
                const slPnl = (t.stop_loss && t.entry && t.size) ? (t.stop_loss - t.entry) * t.size * (t.side === "long" ? 1 : -1) : null;
                const tpPnl = (t.take_profit && t.entry && t.size) ? (t.take_profit - t.entry) * t.size * (t.side === "long" ? 1 : -1) : null;
                return (
                  <tr key={i} className="hover:bg-ink-700/40">
                    <td className="td"><PairLink symbol={t.symbol} entry={t.entry} side={t.side} /></td>
                    <td className={`td font-bold ${t.side === "long" ? "text-up" : "text-down"}`}>{(t.side || "").toUpperCase()}</td>
                    <td className="td">{fmt.num(t.size, 4)}</td>
                    <td className="td">{value ? fmt.num(value, 2) : "—"}</td>
                    <td className="td">{fmt.num(t.entry, 2)}</td>
                    <td className="td">{fmt.num(t.mark, 2)}</td>
                    <td className="td text-down">
                      {t.stop_loss ? <>{fmt.num(t.stop_loss, 2)}<span className="text-slate-500"> ({((t.stop_loss / t.mark - 1) * 100).toFixed(1)}%)</span>
                        {slPnl != null && <div className="text-xs">{fmt.signed(slPnl)} USDT</div>}</> : "—"}
                    </td>
                    <td className="td text-up">
                      {t.take_profit ? <>{fmt.num(t.take_profit, 2)}<span className="text-slate-500"> ({((t.take_profit / t.mark - 1) * 100).toFixed(1)}%)</span>
                        {tpPnl != null && <div className="text-xs">{fmt.signed(tpPnl)} USDT</div>}</> : "—"}
                    </td>
                    <td className={`td ${t.unrealized >= 0 ? "text-up" : "text-down"}`}>{fmt.signed(t.unrealized)}</td>
                    <td className="td text-slate-400">{t.leverage ? `${t.leverage}x` : "—"}</td>
                    <td className="td text-slate-400">{fmt.num(t.liquidation, 2)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="flex items-center justify-between mb-2">
          <div className="card-title mb-0">Closed Trades ({closed.length})</div>
          <span className="text-xs text-slate-500">realized P&amp;L per closed position</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead><tr>
              <th className="th">Closed</th><th className="th">Symbol</th><th className="th">Side</th>
              <th className="th">Qty</th><th className="th">Entry</th><th className="th">Exit</th><th className="th">Realized</th>
            </tr></thead>
            <tbody>
              {closed.length === 0 && (
                <tr><td className="td text-slate-500" colSpan={7}>
                  No closed trades yet — they appear here once positions are closed.
                </td></tr>
              )}
              {pageRows.map((t, i) => (
                <tr key={i} className="hover:bg-ink-700/40">
                  <td className="td text-slate-400">{fmt.timeMs(t.closed_at)}</td>
                  <td className="td"><PairLink symbol={t.symbol} /></td>
                  <td className={`td font-bold ${t.side === "Buy" || t.side === "long" ? "text-up" : "text-down"}`}>{t.side}</td>
                  <td className="td">{fmt.num(t.qty, 4)}</td>
                  <td className="td">{fmt.num(t.entry, 4)}</td>
                  <td className="td">{fmt.num(t.exit, 4)}</td>
                  <td className={`td font-bold ${t.realized >= 0 ? "text-up" : "text-down"}`}>{fmt.signed(t.realized)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pager page={page} pages={pages} setPage={setPage} />
      </div>
    </div>
  );
}
