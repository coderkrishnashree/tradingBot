import { useState } from "react";

// Data Export: pick a date range, download a full analysis bundle (tar.gz)
// straight through the browser. The backend pulls Bybit closed-PnL/executions
// for the WHOLE range in explicit 7-day windows (the API alone only returns
// ~the last 7 days), plus DB tables, decisions and the AI-debate log.
const day = 86400000;
const iso = (d) => new Date(d).toISOString().slice(0, 10);

export default function ExportPanel() {
  const [start, setStart] = useState(iso(Date.now() - 35 * day));
  const [end, setEnd] = useState(iso(Date.now()));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function download() {
    setBusy(true);
    setErr("");
    try {
      const res = await fetch(`/api/export?start=${start}&end=${end}`);
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const body = await res.json();
          if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
        } catch { /* non-JSON error body */ }
        throw new Error(msg);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `finalbot_export_${start}_${end}.tar.gz`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="card-title">Data Export</div>
      <div className="grid grid-cols-2 gap-3 mb-3">
        <label className="block">
          <span className="text-[10px] uppercase tracking-[0.18em] text-slate-500">From</span>
          <input type="date" className="input mt-1" value={start} max={end}
                 onChange={(e) => setStart(e.target.value)} />
        </label>
        <label className="block">
          <span className="text-[10px] uppercase tracking-[0.18em] text-slate-500">To</span>
          <input type="date" className="input mt-1" value={end} min={start} max={iso(Date.now())}
                 onChange={(e) => setEnd(e.target.value)} />
        </label>
      </div>
      <button onClick={download} disabled={busy}
              className="btn w-full bg-accent/15 text-accent ring-1 ring-accent/40 hover:bg-accent/25">
        {busy ? "◈ compiling archive…" : "⬇ Download bundle"}
      </button>
      {busy && (
        <p className="text-[11px] text-slate-500 mt-2 animate-pulse">
          Walking Bybit history in 7-day windows — this can take a minute…
        </p>
      )}
      {err && <p className="text-[11px] text-down mt-2 font-mono">{err}</p>}
      <p className="text-[10px] text-slate-600 mt-3 leading-relaxed">
        Bundle: trades &amp; fees from Bybit (full range), orders, equity curve,
        decisions, learner stats, AI log. No API keys included.
      </p>
    </div>
  );
}
