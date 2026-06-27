import { useEffect, useState } from "react";
import { api } from "../api";

const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];

// Numeric fields with min/max validation (mirrors the backend pydantic ranges).
const NUMS = [
  { key: "leverage", label: "Leverage (x)", min: 1, max: 50, step: 1 },
  { key: "position_size_pct", label: "Position size (% equity)", min: 0.1, max: 100, step: 0.1 },
  { key: "stop_loss_pct", label: "Stop loss (%)", min: 0.1, max: 100, step: 0.1 },
  { key: "take_profit_pct", label: "Take profit (%)", min: 0.1, max: 100, step: 0.1 },
  { key: "max_drawdown_pct", label: "Max drawdown limit (%)", min: 1, max: 100, step: 1 },
];

export default function ConfigPanel() {
  const [cfg, setCfg] = useState(null);
  const [symbolsText, setSymbolsText] = useState("");
  const [msg, setMsg] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.getConfig().then((c) => {
      setCfg(c);
      setSymbolsText((c.symbol_universe || []).join(", "));
    });
  }, []);

  if (!cfg) return <div className="card"><div className="card-title">Config</div><p className="text-slate-500 text-sm">loading…</p></div>;

  function setNum(key, v) {
    setCfg({ ...cfg, [key]: v === "" ? "" : Number(v) });
  }

  function validate(payload) {
    if (payload.symbol_universe.length < 1) return "Add at least one symbol.";
    for (const n of NUMS) {
      const v = payload[n.key];
      if (v === "" || Number.isNaN(v)) return `${n.label} is required.`;
      if (v < n.min || v > n.max) return `${n.label} must be between ${n.min} and ${n.max}.`;
    }
    return null;
  }

  async function save() {
    const payload = {
      ...cfg,
      symbol_universe: symbolsText.split(",").map((s) => s.trim()).filter(Boolean),
    };
    const err = validate(payload);
    if (err) { setMsg({ error: err }); return; }
    setSaving(true);
    setMsg(null);
    try {
      const saved = await api.saveConfig(payload);
      setCfg(saved);
      setMsg({ ok: "Saved." });
    } catch (e) {
      setMsg({ error: e.message });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card">
      <div className="card-title">Trading Config</div>
      <div className="space-y-3">
        <label className="block">
          <span className="text-xs text-slate-400">Symbol universe (comma-separated; agents scan all)</span>
          <textarea
            className="input font-mono"
            rows={2}
            value={symbolsText}
            onChange={(e) => setSymbolsText(e.target.value)}
            placeholder="BTC/USDT:USDT, ETH/USDT:USDT, SOL/USDT:USDT"
          />
        </label>

        <label className="block">
          <span className="text-xs text-slate-400">Timeframe</span>
          <select className="input" value={cfg.timeframe} onChange={(e) => setCfg({ ...cfg, timeframe: e.target.value })}>
            {TIMEFRAMES.map((tf) => <option key={tf} value={tf}>{tf}</option>)}
          </select>
        </label>

        <div className="grid grid-cols-2 gap-3">
          {NUMS.map((n) => (
            <label key={n.key} className="block">
              <span className="text-xs text-slate-400">{n.label}</span>
              <input
                type="number"
                className="input"
                min={n.min}
                max={n.max}
                step={n.step}
                value={cfg[n.key]}
                onChange={(e) => setNum(n.key, e.target.value)}
              />
            </label>
          ))}
        </div>

        <button onClick={save} disabled={saving} className="btn w-full bg-accent hover:bg-blue-600 text-white">
          {saving ? "Saving…" : "Save config"}
        </button>
        {msg && (
          <p className={`text-sm ${msg.error ? "text-down" : "text-up"}`}>{msg.error || msg.ok}</p>
        )}
      </div>
    </div>
  );
}
