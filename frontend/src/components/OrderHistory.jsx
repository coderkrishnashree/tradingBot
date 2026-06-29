import { useMemo, useState } from "react";
import { fmt } from "../api";
import { SkeletonRow } from "./Skeleton";
import { PairLink } from "../chart.jsx";

const COLUMNS = [
  { key: "ts", label: "Time" },
  { key: "mode", label: "Mode" },
  { key: "symbol", label: "Symbol" },
  { key: "side", label: "Side" },
  { key: "order_type", label: "Type" },
  { key: "qty", label: "Qty" },
  { key: "avg_fill_price", label: "Fill" },
  { key: "status", label: "Status" },
  { key: "pnl", label: "PnL" },
];

// Trade/order history — sortable (click a header) and filterable (text box).
export default function OrderHistory({ orders }) {
  const [filter, setFilter] = useState("");
  const [sortKey, setSortKey] = useState("ts");
  const [asc, setAsc] = useState(false);

  const rows = useMemo(() => {
    let r = orders || [];
    if (filter.trim()) {
      const f = filter.toLowerCase();
      r = r.filter((o) =>
        [o.symbol, o.side, o.status, o.mode].some((v) => (v || "").toLowerCase().includes(f))
      );
    }
    r = [...r].sort((a, b) => {
      const x = a[sortKey], y = b[sortKey];
      if (x == null) return 1;
      if (y == null) return -1;
      return (x > y ? 1 : x < y ? -1 : 0) * (asc ? 1 : -1);
    });
    return r;
  }, [orders, filter, sortKey, asc]);

  function toggleSort(key) {
    if (key === sortKey) setAsc(!asc);
    else { setSortKey(key); setAsc(false); }
  }

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <div className="card-title mb-0">Order History ({rows.length})</div>
        <input
          className="input max-w-xs"
          placeholder="filter symbol / side / status…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>
      <div className="overflow-x-auto max-h-80 overflow-y-auto">
        <table className="w-full">
          <thead className="sticky top-0 bg-ink-800">
            <tr>
              {COLUMNS.map((c) => (
                <th key={c.key} className="th cursor-pointer select-none" onClick={() => toggleSort(c.key)}>
                  {c.label} {sortKey === c.key ? (asc ? "▲" : "▼") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {orders == null && <><SkeletonRow cols={COLUMNS.length} /><SkeletonRow cols={COLUMNS.length} /></>}
            {orders != null && rows.length === 0 && (
              <tr><td className="td text-slate-500" colSpan={COLUMNS.length}>No orders yet.</td></tr>
            )}
            {rows.map((o) => (
              <tr key={o.id} className="hover:bg-ink-700/40">
                <td className="td text-slate-400">{fmt.time(o.ts)}</td>
                <td className="td">
                  <span className={o.mode === "live" ? "text-down" : "text-up"}>{o.mode}</span>
                </td>
                <td className="td"><PairLink symbol={o.symbol} /></td>
                <td className={`td font-bold ${o.side === "buy" ? "text-up" : "text-down"}`}>{o.side}</td>
                <td className="td text-slate-400">{o.order_type}</td>
                <td className="td">{fmt.num(o.qty, 4)}</td>
                <td className="td">{fmt.num(o.avg_fill_price, 2)}</td>
                <td className="td">{o.status}</td>
                <td className={`td ${o.pnl >= 0 ? "text-up" : "text-down"}`}>
                  {o.pnl == null ? "—" : fmt.signed(o.pnl)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
