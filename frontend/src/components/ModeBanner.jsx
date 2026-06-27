// The big, always-visible mode banner. Green = PAPER/TESTNET, Red = LIVE/REAL FUNDS.
// This is the single most important safety affordance — it must never be ambiguous.
export default function ModeBanner({ mode }) {
  if (!mode) {
    return (
      <div className="w-full py-3 text-center font-bold bg-ink-700 text-slate-400">
        connecting to backend…
      </div>
    );
  }
  const live = mode.is_live;
  const paperLabel = mode.paper_backend === "demo" ? "PAPER / DEMO TRADING" : "PAPER / TESTNET";
  return (
    <div
      className={`w-full py-3 px-4 flex items-center justify-center gap-3 font-extrabold tracking-widest text-lg ${
        live ? "bg-down text-white" : "bg-up text-black"
      }`}
    >
      <span className={`h-3 w-3 rounded-full ${live ? "bg-white" : "bg-black"} animate-pulse`} />
      {live ? "● LIVE / REAL FUNDS ●" : paperLabel}
      {mode.kill_switch_active && (
        <span className="ml-4 px-2 py-0.5 rounded bg-black/40 text-white text-sm">
          KILL SWITCH ENGAGED — trading halted
        </span>
      )}
    </div>
  );
}
