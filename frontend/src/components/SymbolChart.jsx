import { useEffect, useRef, useState } from "react";

// Live candlestick chart via TradingView's free embeddable widget (no API key).
// Maps our ccxt symbol (e.g. "BTC/USDT:USDT") to TradingView's "BYBIT:BTCUSDT.P".
const TV_INTERVAL = { "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D" };

function toTvSymbol(sym) {
  const base = (sym || "").replace(/:USDT$/, "").replace("/", "");
  return `BYBIT:${base}.P`;
}

let _tvPromise;
function loadTradingView() {
  if (window.TradingView) return Promise.resolve();
  if (_tvPromise) return _tvPromise;
  _tvPromise = new Promise((resolve) => {
    const s = document.createElement("script");
    s.src = "https://s3.tradingview.com/tv.js";
    s.async = true;
    s.onload = resolve;
    document.head.appendChild(s);
  });
  return _tvPromise;
}

export default function SymbolChart({ symbol, entry, side, onClose }) {
  const [tf, setTf] = useState("1h");
  const holder = useRef(null);

  useEffect(() => {
    let cancelled = false;
    loadTradingView().then(() => {
      if (cancelled || !holder.current || !window.TradingView) return;
      const id = "tv_" + Math.random().toString(36).slice(2);
      holder.current.innerHTML = "";
      holder.current.id = id;
      // eslint-disable-next-line no-new
      new window.TradingView.widget({
        container_id: id,
        symbol: toTvSymbol(symbol),
        interval: TV_INTERVAL[tf] || "60",
        theme: "dark",
        style: "1",            // candles
        locale: "en",
        timezone: "Etc/UTC",
        autosize: true,
        allow_symbol_change: true,
        hide_side_toolbar: false,
      });
    });
    return () => { cancelled = true; if (holder.current) holder.current.innerHTML = ""; };
  }, [symbol, tf]);

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-ink-800 border border-ink-600 rounded-2xl p-3 w-full max-w-5xl shadow-2xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-2">
          <div className="font-bold text-sm">
            {symbol}
            {side && <span className={`ml-2 ${side === "long" ? "text-up" : "text-down"}`}>{side.toUpperCase()}</span>}
            {entry != null && <span className="text-slate-500 ml-2 font-mono">entry {entry}</span>}
          </div>
          <div className="flex items-center gap-1">
            {Object.keys(TV_INTERVAL).map((t) => (
              <button key={t} onClick={() => setTf(t)}
                className={`btn text-xs py-1 ${tf === t ? "bg-accent text-white" : "bg-ink-700 text-slate-400"}`}>{t}</button>
            ))}
            <button onClick={onClose} className="btn text-xs py-1 bg-ink-700 hover:bg-ink-600 text-slate-200 ml-2">✕</button>
          </div>
        </div>
        <div className="h-[70vh] w-full"><div ref={holder} style={{ height: "100%", width: "100%" }} /></div>
        <p className="text-xs text-slate-500 mt-1">
          Live TradingView chart (Bybit perpetuals). If a pair doesn't load, it isn't listed on TradingView.
        </p>
      </div>
    </div>
  );
}
