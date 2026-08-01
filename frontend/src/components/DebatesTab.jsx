import { useEffect, useState } from "react";
import { api, usePoll, fmt } from "../api";
import { Skeleton } from "./Skeleton";
import { PairLink } from "../chart.jsx";
import DebatesGalaxy from "./DebatesGalaxy";

const AGENTS = [
  ["research", "🔍 Research", "border-slate-500/40"],
  ["macro", "🌐 Macro / Positioning", "border-cyan-500/40"],
  ["sentiment", "📰 Sentiment / News", "border-purple-500/40"],
  ["analyst", "⚡ Desk Analyst", "border-accent/40"],
  ["bull", "🐂 Bull", "border-up/40"],
  ["bear", "🐻 Bear", "border-down/40"],
  ["quant", "🧮 Quant", "border-orange-500/40"],
  ["risk", "🛡️ Risk Manager", "border-yellow-500/40"],
  ["portfolio", "⚖️ Portfolio Manager", "border-accent/40"],
];

const STATUS = {
  executed: "bg-up/15 text-up", resting: "bg-yellow-500/15 text-yellow-400",
  failed: "bg-down/15 text-down", rejected: "bg-down/15 text-down",
  reviewed: "bg-white/[0.06] text-slate-400", pending: "bg-white/[0.06] text-slate-300",
  approved: "bg-accent/15 text-accent", triggered: "bg-accent/15 text-accent",
};
const actionColor = (a) => ((a || "").toLowerCase() === "buy" ? "text-up"
  : ["short", "sell"].includes((a || "").toLowerCase()) ? "text-down" : "text-slate-300");

function LiveAI() {
  const log = usePoll(api.analyzeLog, 2500);
  const running = log.data?.running;
  const [busy, setBusy] = useState(false);
  async function runNow() {
    setBusy(true);
    try { await api.runAnalyze(); log.refresh(); } catch (e) { alert(e.message); } finally { setBusy(false); }
  }
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <div className="card-title mb-0 flex items-center gap-2">
          Live AI {running && <span className="inline-flex items-center gap-1 text-accent"><span className="h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />running</span>}
        </div>
        <button onClick={runNow} disabled={busy || running}
          className="btn bg-accent hover:bg-accent2 text-white text-sm">
          {running ? "running…" : busy ? "starting…" : "▶ Run analysis now"}
        </button>
      </div>
      <pre className="bg-ink-950/70 border border-white/[0.06] rounded-xl p-3 text-xs text-slate-300 font-mono max-h-56 overflow-auto whitespace-pre-wrap">
{log.data?.log?.trim() || "No debate running. Click “Run analysis now” or wait for the auto loop."}
      </pre>
    </div>
  );
}

// Full debate detail — shared by both views.
function DecisionDetail({ filename }) {
  const [detail, setDetail] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (!filename) { setDetail(null); return; }
    let alive = true; setDetail(null); setErr(null);
    api.decisionFile(filename).then((d) => alive && setDetail(d)).catch((e) => alive && setErr(e.message));
    return () => { alive = false; };
  }, [filename]);

  if (!filename) return null;
  if (err) return <div className="card text-down text-sm">{err}</div>;
  if (!detail) return <div className="card"><Skeleton className="h-48 w-full" /></div>;

  const fd = detail.final_decision || {};
  const t = detail.transcript || {};
  return (
    <>
      <div className="card">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <div className="card-title mb-0">Final Decision</div>
          <span className="text-xs text-slate-500">{fmt.time(detail.timestamp)}</span>
        </div>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 font-mono text-sm">
          <PairLink symbol={fd.symbol || detail.symbol} className="text-base font-bold" />
          <span className={`px-2.5 py-1 rounded-lg font-bold ${actionColor(fd.action)} bg-white/[0.05]`}>{(fd.action || "").toUpperCase()}</span>
          <span className="text-slate-400">size <b className="text-slate-100">{fmt.num(fd.size, 1)}%</b></span>
          <span className="text-slate-400">entry <b className="text-slate-100">{fmt.num(fd.entry, 2)}</b></span>
          <span className="text-down">stop {fmt.num(fd.stop_loss, 2)}</span>
          <span className="text-up">tp {fmt.num(fd.take_profit, 2)}</span>
          <span className="text-slate-400">conf <b className="text-slate-100">{fmt.num(fd.confidence, 2)}</b></span>
        </div>
        {fd.rationale && <p className="text-sm text-slate-300 mt-3 leading-relaxed">{fd.rationale}</p>}
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        {AGENTS.filter(([k]) => t[k]).map(([k, label, border]) => (
          <div key={k} className={`card border-l-2 ${border}`}>
            <div className="text-sm font-semibold text-slate-200 mb-2">{label}</div>
            <p className="text-sm text-slate-400 whitespace-pre-wrap leading-relaxed">{t[k]}</p>
          </div>
        ))}
      </div>
      {AGENTS.every(([k]) => !t[k]) && (
        <div className="card text-slate-500 text-sm">This decision has no agent transcript.</div>
      )}
    </>
  );
}

const PAGE = 100;
const GALAXY_LOAD = 1500;

export default function DebatesTab() {
  const [view, setViewState] = useState(() => localStorage.getItem("debatesView") || "galaxy");
  const setView = (v) => { localStorage.setItem("debatesView", v); setViewState(v); };
  const [picked, setPicked] = useState(null);

  // TABLE: paginated, polls only the visible page (fast — no more full loads).
  const [page, setPage] = useState(0);
  const decisions = usePoll(() => api.decisions({ limit: PAGE, offset: page * PAGE }), 8000, [page, view]);
  const list = decisions.data?.items || [];
  const total = decisions.data?.total ?? list.length;
  const pages = Math.max(1, Math.ceil(total / PAGE));

  // GALAXY: one big slim load, refreshed on demand (no polling).
  const [gal, setGal] = useState(null);
  const [galLoading, setGalLoading] = useState(false);
  const loadGalaxy = async () => {
    setGalLoading(true);
    try { setGal(await api.decisions({ limit: GALAXY_LOAD })); } catch { /* keep old map */ }
    setGalLoading(false);
  };
  useEffect(() => { if (view === "galaxy" && !gal && !galLoading) loadGalaxy(); }, [view]);

  const current = view === "table" ? (picked || list[0]?.filename) : picked;

  return (
    <div className="space-y-5">
      <LiveAI />

      {/* view switch */}
      <div className="card py-2.5 px-4 flex flex-wrap items-center justify-between gap-2">
        <div className="card-title mb-0">Debate Archive · {total || "—"} decisions</div>
        <div className="flex items-center gap-1">
          <button onClick={() => setView("galaxy")}
            className={`btn text-xs py-1.5 ${view === "galaxy" ? "bg-accent/20 text-accent ring-1 ring-accent/50" : "bg-ink-700 text-slate-400"}`}>
            ✦ UNIVERSE
          </button>
          <button onClick={() => setView("table")}
            className={`btn text-xs py-1.5 ${view === "table" ? "bg-accent/20 text-accent ring-1 ring-accent/50" : "bg-ink-700 text-slate-400"}`}>
            ▦ TABLE
          </button>
        </div>
      </div>

      {view === "galaxy" && (
        <>
          <DebatesGalaxy items={gal?.items} total={gal?.total} loading={galLoading}
                         onRefresh={loadGalaxy} onPick={setPicked} />
          <DecisionDetail filename={picked} />
        </>
      )}

      {view === "table" && (
        <div className="grid lg:grid-cols-[320px_1fr] gap-5">
          {/* LEFT: paginated decision list */}
          <div className="card p-3 flex flex-col max-h-[75vh]">
            <div className="card-title px-2">Decisions ({total})</div>
            <div className="space-y-1 overflow-y-auto flex-1">
              {list.length === 0 && <div className="px-2 text-sm text-slate-500">No debates yet.</div>}
              {list.map((d) => (
                <button key={d.filename} onClick={() => setPicked(d.filename)}
                  className={`w-full text-left rounded-xl px-3 py-2.5 transition ${
                    current === d.filename ? "bg-accent/10 ring-1 ring-accent/30" : "hover:bg-white/[0.04]"}`}>
                  <div className="flex items-center justify-between gap-2">
                    <span className={`font-semibold text-sm ${actionColor(d.action)}`}>{(d.action || "").toUpperCase()} {d.symbol}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${STATUS[d.status] || STATUS.pending}`}>{d.status}</span>
                  </div>
                  <div className="flex items-center justify-between text-[11px] text-slate-500 mt-1 font-mono">
                    <span>{fmt.time(d.ts)}</span><span>conf {fmt.num(d.confidence, 2)}</span>
                  </div>
                </button>
              ))}
            </div>
            {/* pagination */}
            <div className="flex items-center justify-between pt-2 mt-1 border-t border-accent/10 px-2 text-xs font-mono">
              <button className="btn py-1 px-2 bg-ink-700 text-slate-300 disabled:opacity-30"
                      disabled={page === 0} onClick={() => { setPage(page - 1); setPicked(null); }}>
                ← newer
              </button>
              <span className="text-slate-500">{page + 1} / {pages}</span>
              <button className="btn py-1 px-2 bg-ink-700 text-slate-300 disabled:opacity-30"
                      disabled={page >= pages - 1} onClick={() => { setPage(page + 1); setPicked(null); }}>
                older →
              </button>
            </div>
          </div>

          {/* RIGHT: selected debate */}
          <div className="space-y-4 min-w-0">
            {!current && <div className="card text-slate-500 text-sm">No debate selected.</div>}
            <DecisionDetail filename={current} />
          </div>
        </div>
      )}
    </div>
  );
}
