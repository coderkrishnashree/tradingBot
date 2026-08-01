// The big, always-visible mode banner. Green = PAPER/TESTNET, Red = LIVE/REAL FUNDS.
// This is the single most important safety affordance — it must never be ambiguous.
export default function ModeBanner({ mode }) {
  if (!mode) {
    return (
      <div className="w-full py-3 text-center font-display font-bold uppercase tracking-[0.3em] bg-ink-700 text-accent/70 animate-pulse">
        ◈ establishing uplink…
      </div>
    );
  }
  const live = mode.is_live;
  const paperLabel = mode.paper_backend === "demo" ? "PAPER · DEMO TRADING" : "PAPER · TESTNET";
  return (
    <div
      className={`w-full py-2 px-4 flex items-center justify-center gap-3 font-display font-bold tracking-[0.28em] text-sm uppercase ${
        live
          ? "bg-gradient-to-r from-down/80 via-down to-down/80 text-white"
          : "bg-gradient-to-r from-up/70 via-up to-up/70 text-black"
      }`}
      style={live ? { textShadow: "0 0 12px rgba(255,255,255,0.6)" } : undefined}
    >
      <span className={`h-2 w-2 rounded-full ${live ? "bg-white" : "bg-black/70"} animate-pulse`} />
      {live ? "⚠ LIVE · REAL FUNDS" : paperLabel}
      {mode.kill_switch_active && (
        <span className="ml-3 px-2 py-0.5 rounded-md bg-black/40 text-white text-xs tracking-normal font-semibold">
          ⛔ KILL SWITCH ENGAGED — trading halted
        </span>
      )}
    </div>
  );
}
