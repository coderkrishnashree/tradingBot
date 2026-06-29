import { createContext, useContext, useState } from "react";
import SymbolChart from "./components/SymbolChart";

// App-wide chart launcher: any component calls useChart()(symbol) to pop the
// live TradingView candlestick chart. One modal lives at the app root.
const ChartContext = createContext(() => {});

export function ChartProvider({ children }) {
  const [sel, setSel] = useState(null);
  const openChart = (symbol, entry = null, side = null) => setSel({ symbol, entry, side });
  return (
    <ChartContext.Provider value={openChart}>
      {children}
      {sel && <SymbolChart {...sel} onClose={() => setSel(null)} />}
    </ChartContext.Provider>
  );
}

export const useChart = () => useContext(ChartContext);

// A reusable clickable pair symbol used across tables.
export function PairLink({ symbol, entry, side, className = "" }) {
  const openChart = useChart();
  return (
    <button
      onClick={() => openChart(symbol, entry, side)}
      className={`text-accent hover:underline text-left ${className}`}
      title="Open live chart"
    >
      {symbol} <span className="text-slate-600">↗</span>
    </button>
  );
}
