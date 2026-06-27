import { useEffect, useState } from "react";
import { api } from "../api";

function Check({ ok, label }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className={ok ? "text-up" : "text-down"}>{ok ? "✓" : "✗"}</span>
      <span className={ok ? "text-slate-200" : "text-slate-400"}>{label}</span>
    </div>
  );
}

function Cmd({ children }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center gap-2 bg-ink-900 border border-ink-600 rounded-lg px-3 py-2 font-mono text-sm">
      <code className="flex-1 text-slate-200 break-all">{children}</code>
      <button
        onClick={() => { navigator.clipboard?.writeText(children); setCopied(true); setTimeout(() => setCopied(false), 1200); }}
        className="text-xs text-accent hover:underline shrink-0"
      >
        {copied ? "copied" : "copy"}
      </button>
    </div>
  );
}

// Explains + reflects how the AI step is connected. The actual Claude login is
// done INSIDE Claude Code (its own account login) — a web app cannot drive your
// Max subscription, so there is intentionally no "Claude password" box here.
export default function ConnectClaude() {
  const [s, setS] = useState(null);
  useEffect(() => { api.claudeStatus().then(setS).catch(() => setS({ error: true })); }, []);

  return (
    <div className="space-y-4">
      <div className="card border-accent/40">
        <div className="card-title text-accent">Connect Claude Code (the AI brain)</div>
        <p className="text-sm text-slate-300">
          The multi-agent debate runs on your <b>Claude Max subscription</b>, inside the Claude Code
          app — not in this web dashboard. You log in <b>once, inside Claude Code</b>, with your
          Anthropic account; that ties it to your Max plan. This dashboard then reads the decision
          files it produces and (optionally) auto-executes them.
        </p>
        <div className="mt-3 p-3 rounded-lg bg-down/10 border border-down/30 text-sm text-slate-300">
          <b className="text-down">Why no “login with Claude” button here?</b> A web app can’t use your
          Max subscription directly — that would require an Anthropic API key, which switches to paid
          per-token billing (the exact thing this design avoids). So login stays inside Claude Code,
          where your subscription already works.
        </div>
      </div>

      <div className="card">
        <div className="card-title">Connection status</div>
        {!s && <p className="text-slate-500 text-sm">checking…</p>}
        {s && !s.error && (
          <div className="space-y-2">
            <Check ok={s.cli_installed} label="Claude Code CLI installed on this machine" />
            <Check ok={s.agents_installed} label="Trading subagents installed in .claude/agents" />
            <Check ok={s.analyze_command_installed} label="/analyze command installed" />
            <Check ok={!!s.last_decision} label={s.last_decision ? `Last decision: ${s.last_decision.symbol} (${s.last_decision.status})` : "No decision generated yet"} />
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-title">Setup steps (one-time)</div>
        <ol className="space-y-3 text-sm text-slate-300">
          <li>1. Install Claude Code:<div className="mt-1"><Cmd>npm i -g @anthropic-ai/claude-code</Cmd></div></li>
          <li>2. Open it in this project folder:<div className="mt-1"><Cmd>claude</Cmd></div></li>
          <li>3. Log into your Claude Max account (one-time browser sign-in):<div className="mt-1"><Cmd>/login</Cmd></div></li>
          <li>4. Install the trading agents:<div className="mt-1"><Cmd>bash agents/claude_code/install_agents.sh</Cmd></div></li>
          <li>5. Run the debate any time — it writes a decision this dashboard auto-loads:<div className="mt-1"><Cmd>/analyze</Cmd></div></li>
        </ol>
      </div>
    </div>
  );
}
