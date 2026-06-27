import { useState } from "react";
import { api, fmt } from "../api";

const AGENTS = [
  { key: "research", label: "🔍 Research Agent", color: "text-slate-300" },
  { key: "macro", label: "🌐 Macro / Positioning", color: "text-cyan-400" },
  { key: "sentiment", label: "📰 Sentiment / News", color: "text-purple-400" },
  { key: "bull", label: "🐂 Bull Agent", color: "text-up" },
  { key: "bear", label: "🐻 Bear Agent", color: "text-down" },
  { key: "quant", label: "🧮 Quant (devil's advocate)", color: "text-orange-400" },
  { key: "risk", label: "🛡️ Risk Manager", color: "text-yellow-400" },
  { key: "portfolio", label: "⚖️ Portfolio Manager", color: "text-accent" },
];

function DecisionBadge({ d }) {
  if (!d) return null;
  const action = (d.action || "").toUpperCase();
  const isEnter = ["BUY", "SHORT"].includes(action);
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-1 font-mono text-sm">
      <span className={`px-2 py-1 rounded font-bold ${isEnter ? "bg-accent/20 text-accent" : "bg-ink-700 text-slate-300"}`}>
        {action} {d.symbol}
      </span>
      <span>size <b>{fmt.num(d.size, 1)}%</b></span>
      <span>entry <b>{fmt.num(d.entry, 2)}</b></span>
      <span className="text-down">stop <b>{fmt.num(d.stop_loss, 2)}</b></span>
      <span className="text-up">target <b>{fmt.num(d.take_profit, 2)}</b></span>
      <span>conf <b>{fmt.num(d.confidence, 2)}</b></span>
    </div>
  );
}

// Latest debate transcript per agent + the final decision, with approve/reject.
// (Stage 3: buttons record the choice. Stage 4 wires "approve" into execution.)
export default function AgentPanel({ transcript, mode, autoTrade, onAction }) {
  const [open, setOpen] = useState("portfolio");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  if (!transcript) {
    return (
      <div className="card">
        <div className="card-title">Agent Debate</div>
        <p className="text-slate-500 text-sm">
          No decision yet. Run <code className="text-accent">/analyze</code> in Claude Code to
          generate one.
        </p>
      </div>
    );
  }

  const d = transcript.final_decision;
  const t = transcript.transcript || {};

  async function act(approve) {
    // Extra guard: executing while LIVE places a REAL order — confirm first.
    if (approve && mode?.is_live) {
      const ok = window.confirm(
        `LIVE MODE: this will place a REAL order on Bybit mainnet for ${d?.symbol}.\n\nProceed?`
      );
      if (!ok) return;
    }
    setBusy(true);
    try {
      const r = await api.decisionAction(transcript.filename, approve);
      setResult(r);
      onAction?.();
    } catch (e) {
      setResult({ error: e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <div className="card-title mb-0">Agent Debate — Latest Decision</div>
        <span className="text-xs text-slate-500">{fmt.time(transcript.timestamp)}</span>
      </div>

      <div className="mb-3 p-3 rounded-lg bg-ink-900 border border-ink-600">
        <DecisionBadge d={d} />
        <p className="text-sm text-slate-300 mt-2">{d?.rationale}</p>
      </div>

      <div className="space-y-2">
        {AGENTS.map((a) => {
          const text = t[a.key];
          if (!text) return null;
          const isOpen = open === a.key;
          return (
            <div key={a.key} className="border border-ink-700 rounded-lg overflow-hidden">
              <button
                onClick={() => setOpen(isOpen ? null : a.key)}
                className={`w-full text-left px-3 py-2 font-semibold flex justify-between ${a.color} bg-ink-700/40 hover:bg-ink-700`}
              >
                <span>{a.label}</span>
                <span>{isOpen ? "−" : "+"}</span>
              </button>
              {isOpen && (
                <pre className="px-3 py-2 text-sm text-slate-300 whitespace-pre-wrap font-sans">{text}</pre>
              )}
            </div>
          );
        })}
      </div>

      {autoTrade ? (
        <div className="mt-4 p-3 rounded-lg bg-up/10 border border-up/30 text-sm text-up">
          Auto-trade is ON — decisions above your confidence threshold execute automatically.
          Manual approve/reject is disabled. (Turn off Auto-trade in the Automation tab to approve by hand.)
        </div>
      ) : (
        <div className="flex gap-3 mt-4">
          <button onClick={() => act(true)} disabled={busy} className="btn flex-1 bg-up hover:bg-green-600 text-black">
            ✓ Approve &amp; execute
          </button>
          <button onClick={() => act(false)} disabled={busy} className="btn flex-1 bg-ink-700 hover:bg-ink-600 text-slate-200">
            ✕ Reject
          </button>
        </div>
      )}
      {result && (
        <p className={`text-sm mt-2 ${
          result.error || result.executed === false ? "text-down" : "text-up"
        }`}>
          {result.error
            ? `Error: ${result.error}`
            : `[${result.status}] ${result.message}${result.order_id ? ` (order ${result.order_id})` : ""}`}
        </p>
      )}
    </div>
  );
}
