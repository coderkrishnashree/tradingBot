import { useState } from "react";
import { api } from "../api";

// Big, always-visible kill switch. Engaging it cancels open orders on the
// exchange and halts Layer 2. It is intentionally a two-state toggle: engage is
// one click (you want it fast in a panic); resetting requires the explicit
// "Reset" button so you don't un-halt by accident.
export default function KillSwitch({ mode, onChange }) {
  const [busy, setBusy] = useState(false);
  const active = mode?.kill_switch_active;

  async function engage() {
    setBusy(true);
    try {
      const r = await api.kill();
      onChange?.();
      alert(`Kill switch engaged. Open orders canceled: ${r.orders_canceled}`);
    } finally {
      setBusy(false);
    }
  }
  async function reset() {
    setBusy(true);
    try {
      await api.killReset();
      onChange?.();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card border-down/50">
      <div className="card-title text-down">Emergency</div>
      {active ? (
        <div className="space-y-3">
          <div className="text-down font-bold">Trading is HALTED.</div>
          <button onClick={reset} disabled={busy} className="btn w-full bg-ink-700 hover:bg-ink-600 text-slate-200">
            Reset kill switch
          </button>
        </div>
      ) : (
        <button
          onClick={engage}
          disabled={busy}
          className="btn w-full text-lg py-4 bg-down hover:bg-red-600 text-white"
        >
          ⛔ KILL SWITCH
        </button>
      )}
      <p className="text-xs text-slate-500 mt-2">
        Cancels all open orders and halts new trades immediately.
      </p>
    </div>
  );
}
