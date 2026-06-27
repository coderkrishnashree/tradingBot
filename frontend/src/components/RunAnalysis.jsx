// Explains how to trigger the agent debate — the subscription-covered step that
// happens in Claude Code, NOT in this web app. (Wired further in Stage 4.)
export default function RunAnalysis({ onRefresh }) {
  return (
    <div className="card border-accent/40">
      <div className="card-title text-accent">Run New Analysis</div>
      <p className="text-sm text-slate-300">
        The agent debate runs on your Claude subscription, inside Claude Code — not here.
      </p>
      <ol className="text-sm text-slate-400 list-decimal list-inside mt-2 space-y-1">
        <li>Open Claude Code in the project folder.</li>
        <li>Type <code className="text-accent">/analyze</code> and let the agents debate.</li>
        <li>It writes a new decision file; this panel auto-loads it.</li>
      </ol>
      <button onClick={onRefresh} className="btn w-full mt-3 bg-ink-700 hover:bg-ink-600 text-slate-200">
        ↻ Check for new decision
      </button>
    </div>
  );
}
