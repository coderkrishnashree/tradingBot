import AgentPanel from "./AgentPanel";
import DecisionsHistory from "./DecisionsHistory";

// Dedicated tab for the AI agent debates. Shows the latest debate in full, plus
// the complete history of every decision (click any to read all agents).
export default function DebatesTab({ transcript, mode, autoTrade, onAction }) {
  return (
    <div className="space-y-4">
      <div className="card border-accent/30">
        <div className="card-title text-accent">About these debates</div>
        <p className="text-sm text-slate-300">
          These are the <b>AI multi-agent debates</b> (Research → Macro → Sentiment → Bull → Bear →
          Quant → Risk → Portfolio), produced when <code className="text-accent">/analyze</code> runs in
          Claude Code. Their confidence is the Portfolio Manager's call.
        </p>
        <p className="text-xs text-slate-500 mt-2">
          Note: the always-on <b>mechanical screener</b> that auto-trades uses a separate, math-based
          confidence (indicators + market structure) — those trades don't generate a debate. If this
          tab is empty, no AI debate has run yet.
        </p>
      </div>

      <AgentPanel transcript={transcript} mode={mode} autoTrade={autoTrade} onAction={onAction} />
      <DecisionsHistory />
    </div>
  );
}
