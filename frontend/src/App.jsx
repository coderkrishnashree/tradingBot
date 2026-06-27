import { useState } from "react";
import { api, usePoll } from "./api";
import ModeBanner from "./components/ModeBanner";
import KillSwitch from "./components/KillSwitch";
import PortfolioOverview from "./components/PortfolioOverview";
import PositionsTable from "./components/PositionsTable";
import Charts from "./components/Charts";
import StatsPanel from "./components/StatsPanel";
import OrderHistory from "./components/OrderHistory";
import AgentPanel from "./components/AgentPanel";
import ConfigPanel from "./components/ConfigPanel";
import LiveTradingSection from "./components/LiveTradingSection";
import RunAnalysis from "./components/RunAnalysis";
import ScannerTable from "./components/ScannerTable";
import AutomationPanel from "./components/AutomationPanel";
import AlertsFeed from "./components/AlertsFeed";
import ConnectClaude from "./components/ConnectClaude";
import PnlTab from "./components/PnlTab";
import TradesTab from "./components/TradesTab";
import DecisionsHistory from "./components/DecisionsHistory";

const TABS = ["Overview", "P&L", "Trades", "Scanner", "Automation", "Alerts", "Connect Claude"];

// Compact always-visible kill switch for the header (works on every tab).
function HeaderKill({ mode, onChange }) {
  async function engage() {
    if (!window.confirm("Engage KILL SWITCH? Cancels open orders and halts trading.")) return;
    await api.kill(); onChange?.();
  }
  async function reset() { await api.killReset(); onChange?.(); }
  if (mode?.kill_switch_active) {
    return <button onClick={reset} className="btn bg-ink-700 hover:bg-ink-600 text-down text-sm">⛔ Halted — reset</button>;
  }
  return <button onClick={engage} className="btn bg-down hover:bg-red-600 text-white text-sm">⛔ KILL</button>;
}

export default function App() {
  // Persist the active tab so a browser refresh stays on the same tab.
  const [tab, setTabState] = useState(() => localStorage.getItem("activeTab") || "Overview");
  const setTab = (t) => { localStorage.setItem("activeTab", t); setTabState(t); };

  const mode = usePoll(api.mode, 3000);
  const portfolio = usePoll(api.portfolio, 2500);
  const positions = usePoll(api.positions, 2500);
  const orders = usePoll(api.orders, 4000);
  const equity = usePoll(api.equity, 8000);
  const stats = usePoll(api.stats, 8000);
  const transcript = usePoll(api.latestTranscript, 6000);
  const scan = usePoll(api.scan, 10000);
  const automation = usePoll(api.automation, 5000);
  const alerts = usePoll(api.alerts, 6000);

  const refreshAll = () => {
    mode.refresh(); portfolio.refresh(); positions.refresh();
    orders.refresh(); transcript.refresh(); scan.refresh();
    automation.refresh(); alerts.refresh();
  };

  return (
    <div className="min-h-full">
      <div className="sticky top-0 z-20 shadow-lg">
        <ModeBanner mode={mode.data} />
        <div className="bg-ink-800 border-b border-ink-600 px-4 flex items-center justify-between">
          <nav className="flex gap-1 overflow-x-auto">
            {TABS.map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-4 py-3 text-sm font-semibold whitespace-nowrap border-b-2 transition-colors ${
                  tab === t ? "border-accent text-slate-100" : "border-transparent text-slate-400 hover:text-slate-200"
                }`}
              >
                {t}
              </button>
            ))}
          </nav>
          <HeaderKill mode={mode.data} onChange={mode.refresh} />
        </div>
      </div>

      <div className="max-w-7xl mx-auto p-4 space-y-4">
        {tab === "Overview" && (
          <>
            <PortfolioOverview portfolio={portfolio.data} />
            <StatsPanel stats={stats.data} />
            <div className="grid lg:grid-cols-3 gap-4">
              <div className="lg:col-span-2 space-y-4">
                <Charts equity={equity.data} />
                <PositionsTable positions={positions.data} />
                <AgentPanel transcript={transcript.error ? null : transcript.data} mode={mode.data} autoTrade={automation.data?.auto_trade} onAction={refreshAll} />
                <DecisionsHistory />
                <OrderHistory orders={orders.data} />
              </div>
              <div className="space-y-4">
                <KillSwitch mode={mode.data} onChange={mode.refresh} />
                <RunAnalysis onRefresh={transcript.refresh} />
                <ConfigPanel />
                <LiveTradingSection mode={mode.data} onChange={refreshAll} />
              </div>
            </div>
          </>
        )}

        {tab === "P&L" && <PnlTab />}

        {tab === "Trades" && <TradesTab />}

        {tab === "Scanner" && <ScannerTable scan={scan.data} onRefresh={() => { scan.refresh(); alerts.refresh(); portfolio.refresh(); }} />}

        {tab === "Automation" && (
          <div className="grid lg:grid-cols-2 gap-4">
            <AutomationPanel status={automation.data} mode={mode.data} onRefresh={automation.refresh} />
            <AlertsFeed alerts={alerts.data} />
          </div>
        )}

        {tab === "Alerts" && <AlertsFeed alerts={alerts.data} />}

        {tab === "Connect Claude" && <ConnectClaude />}

        <footer className="text-center text-xs text-slate-600 py-4">
          Layer 2 dashboard · default PAPER/testnet · live trading gated · AI runs in Claude Code on your subscription
        </footer>
      </div>
    </div>
  );
}
