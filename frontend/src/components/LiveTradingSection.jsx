import { useState } from "react";
import { api } from "../api";

// The ONLY place paper->live can happen. Deliberately gated:
//   (a) it's a separate, visually-distinct red section,
//   (b) you must type exactly "GO LIVE",
//   (c) the backend additionally checks the mainnet keys are present.
// No single click can move you to real funds.
export default function LiveTradingSection({ mode, onChange }) {
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  if (!mode) return null;

  const live = mode.is_live;
  const keysReady = mode.mainnet_keys_present;

  async function goLive() {
    setBusy(true); setMsg(null);
    try {
      await api.goLive(confirm);
      setConfirm("");
      onChange?.();
    } catch (e) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function goPaper() {
    setBusy(true); setMsg(null);
    try { await api.goPaper(); onChange?.(); } finally { setBusy(false); }
  }

  return (
    <div className="card border-2 border-down/60 bg-down/5">
      <div className="card-title text-down">⚠️ Live Trading — Real Funds</div>

      {live ? (
        <div className="space-y-3">
          <p className="text-down font-bold">You are LIVE on Bybit mainnet. Real money is at risk.</p>
          <button onClick={goPaper} disabled={busy} className="btn w-full bg-up hover:bg-green-600 text-black">
            ← Return to PAPER (testnet)
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-slate-300">
            Currently in safe paper/testnet mode. To trade real funds you must type{" "}
            <code className="text-down font-bold">GO LIVE</code> below.
          </p>
          <div className={`text-xs ${keysReady ? "text-up" : "text-down"}`}>
            Mainnet API keys: {keysReady ? "detected ✓" : "NOT set — add them to .env first"}
          </div>
          <input
            className="input border-down/50"
            placeholder='type GO LIVE'
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
          <button
            onClick={goLive}
            disabled={busy || confirm !== "GO LIVE" || !keysReady}
            className="btn w-full bg-down hover:bg-red-600 text-white"
          >
            Switch to LIVE / real funds
          </button>
          {msg && <p className="text-sm text-down">{msg}</p>}
          <p className="text-xs text-slate-500">
            The app always restarts in paper mode — going live is never remembered across reboots.
          </p>
        </div>
      )}
    </div>
  );
}
