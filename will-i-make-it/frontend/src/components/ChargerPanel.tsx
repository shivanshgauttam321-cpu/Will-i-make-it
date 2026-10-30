import { useState, useEffect } from 'react';
import { 
  Zap, AlertTriangle, CheckCircle, HelpCircle, XCircle, 
  Search, Filter, Clock, RotateCcw, ThumbsUp, ThumbsDown
} from 'lucide-react';
import { getAllChargers, reportCharger } from '../utils/api';
import { playCockpitClick, playChargeZap } from '../utils/audioService';
import type { Charger, RoutePlanResponse } from '../types/api';

interface Props {
  routeResult: RoutePlanResponse | null;
  disabledChargers: string[];
  onChargerToggle: (id: string, disabled: boolean) => void;
  onResetDisabledChargers?: () => void;
}

function ReliabilityBadge({ score, freshness }: { score: number; freshness?: number | null }) {
  const pct = Math.round(score * 100);
  const isStale = freshness && freshness > 48;
  const isUnknown = freshness === null || freshness === undefined;

  const color = score >= 0.75 
    ? 'text-emerald-300 bg-emerald-500/15 border-emerald-500/40 shadow-[0_0_8px_rgba(16,185,129,0.2)]'
    : score >= 0.55 
      ? 'text-amber-300 bg-amber-500/15 border-amber-500/40'
      : 'text-rose-300 bg-rose-500/15 border-rose-500/40';

  return (
    <div className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full border text-[11px] font-mono font-bold ${color}`}>
      {score >= 0.75 ? <CheckCircle size={11} /> : score >= 0.55 ? <AlertTriangle size={11} /> : <XCircle size={11} />}
      <span>{pct}% REL</span>
      {isStale && <span className="text-[9px] text-slate-400 font-mono ml-0.5">(STALE)</span>}
      {isUnknown && <span className="text-[9px] text-slate-400 font-mono ml-0.5">(PRIOR)</span>}
    </div>
  );
}

function OperationalBadge({ status, isDisabled }: { status?: boolean | null; isDisabled: boolean }) {
  if (isDisabled) {
    return (
      <span className="badge-pill bg-rose-500/20 text-rose-300 border-rose-500/50 text-[10px] font-mono font-bold shadow-[0_0_8px_rgba(244,63,94,0.3)]">
        ● OUTAGE SIMULATED
      </span>
    );
  }
  if (status === true) {
    return (
      <span className="badge-pill bg-emerald-500/10 text-emerald-400 border-emerald-500/30 text-[10px] font-mono font-bold">
        ● OPERATIONAL
      </span>
    );
  }
  if (status === false) {
    return (
      <span className="badge-pill bg-rose-500/10 text-rose-400 border-rose-500/30 text-[10px] font-mono font-bold">
        ● OUT OF SERVICE
      </span>
    );
  }
  return (
    <span className="badge-pill bg-slate-900 text-slate-400 border-slate-700 text-[10px] font-mono">
      <HelpCircle size={10} /> UNVERIFIED (0.5 PRIOR)
    </span>
  );
}

export default function ChargerPanel({
  routeResult, disabledChargers, onChargerToggle, onResetDisabledChargers
}: Props) {
  const [allChargers, setAllChargers] = useState<Charger[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterMode, setFilterMode] = useState<'all' | 'on_route' | 'outages'>('all');
  const [reportingId, setReportingId] = useState<string | null>(null);
  const [reportSuccessFeedback, setReportSuccessFeedback] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    getAllChargers()
      .then(r => setAllChargers(r.chargers))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleReport = async (chargerId: string, success: boolean) => {
    playCockpitClick();
    const charger = allChargers.find(c => c.charger_id === chargerId);
    if (!charger) return;
    const connector = charger.connector_types[0] ?? 'CCS2';

    try {
      const r = await reportCharger({
        charger_id: chargerId,
        success,
        connector_type: connector,
        notes: success ? 'User live test: operational' : 'User live test: failed/unavailable',
      });
      setReportSuccessFeedback(prev => ({
        ...prev,
        [chargerId]: `Recorded! Updated Beta-posterior: ${(r.new_reliability_score * 100).toFixed(0)}% (${r.total_reports} reports)`
      }));
      playChargeZap();
      // Refresh charger list to reflect new Bayesian score
      getAllChargers().then(res => setAllChargers(res.chargers)).catch(() => {});
    } catch {
      setReportSuccessFeedback(prev => ({ ...prev, [chargerId]: 'Report failed' }));
    }
  };

  const routeChargerIds = new Set([
    ...(routeResult?.fastest_route?.charging_stops ?? []).map(s => s.charger.charger_id),
    ...(routeResult?.risk_aware_route?.charging_stops ?? []).map(s => s.charger.charger_id),
  ]);

  const filteredChargers = allChargers.filter(c => {
    // Search
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const matchName = c.name.toLowerCase().includes(q);
      const matchOp = c.operator.toLowerCase().includes(q);
      const matchAddr = c.address ? c.address.toLowerCase().includes(q) : false;
      if (!matchName && !matchOp && !matchAddr) return false;
    }
    // Filter mode
    if (filterMode === 'on_route' && !routeChargerIds.has(c.charger_id)) return false;
    if (filterMode === 'outages' && !disabledChargers.includes(c.charger_id)) return false;

    return true;
  });

  return (
    <div className="flex flex-col gap-3.5">
      {/* Informative Bayesian Banner */}
      <div className="bg-slate-950/80 border border-cyan-900/40 rounded-2xl p-3.5 shadow-xl backdrop-blur-md">
        <div className="flex items-start gap-2.5">
          <Zap size={16} className="text-cyan-400 shrink-0 mt-0.5" />
          <p className="text-xs text-slate-300 leading-relaxed font-sans">
            <span className="font-bold text-cyan-300 font-mono">[BAYESIAN RELIABILITY ENGINE]:</span> Stations use 
            Laplace smoothing ($\alpha=1, \beta=1$) with a 24h freshness half-life. Unverified stations 
            default to 50% prior rather than pretending to be 100% operational.
          </p>
        </div>
      </div>

      {/* Search & Filter Bar */}
      <div className="cockpit-panel hud-bracket">
        <div className="flex items-center gap-2 mb-3">
          <div className="relative flex-1">
            <Search size={14} className="absolute left-3 top-2.5 text-cyan-400" />
            <input
              type="text"
              placeholder="Search by operator (Tata Power, Fortum, Zeon) or city..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700/80 rounded-xl pl-8 pr-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-cyan-500 font-sans transition-colors"
            />
          </div>
          {disabledChargers.length > 0 && onResetDisabledChargers && (
            <button
              type="button"
              onClick={() => {
                playCockpitClick();
                onResetDisabledChargers();
              }}
              className="btn-secondary text-xs flex items-center gap-1 py-1.5 px-2.5 text-rose-300 border-rose-500/40 hover:bg-rose-500/10 shrink-0 font-mono font-bold"
              title="Restore all stations online"
            >
              <RotateCcw size={12} />
              <span>RESET ALL</span>
            </button>
          )}
        </div>

        {/* Filter Pills */}
        <div className="flex gap-1.5 font-mono">
          <button
            type="button"
            onClick={() => {
              playCockpitClick();
              setFilterMode('all');
            }}
            className={`px-3 py-1 rounded-lg text-xs font-bold border transition-colors ${
              filterMode === 'all' 
                ? 'bg-cyan-600 text-slate-950 border-cyan-400 shadow-[0_0_8px_rgba(6,182,212,0.4)]' 
                : 'bg-slate-950 text-slate-400 border-slate-800 hover:text-slate-200'
            }`}
          >
            ALL ({allChargers.length})
          </button>
          <button
            type="button"
            onClick={() => {
              playCockpitClick();
              setFilterMode('on_route');
            }}
            className={`px-3 py-1 rounded-lg text-xs font-bold border transition-colors ${
              filterMode === 'on_route' 
                ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/50 shadow-[0_0_8px_rgba(16,185,129,0.3)]' 
                : 'bg-slate-950 text-slate-400 border-slate-800 hover:text-slate-200'
            }`}
          >
            ON ROUTE ({routeChargerIds.size})
          </button>
          <button
            type="button"
            onClick={() => {
              playCockpitClick();
              setFilterMode('outages');
            }}
            className={`px-3 py-1 rounded-lg text-xs font-bold border transition-colors ${
              filterMode === 'outages' 
                ? 'bg-rose-500/20 text-rose-300 border-rose-500/50 shadow-[0_0_8px_rgba(244,63,94,0.3)]' 
                : 'bg-slate-950 text-slate-400 border-slate-800 hover:text-slate-200'
            }`}
          >
            OUTAGES ({disabledChargers.length})
          </button>
        </div>
      </div>

      {loading && (
        <div className="cockpit-panel flex items-center justify-center h-28">
          <div className="w-5 h-5 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin shadow-[0_0_8px_#00f0ff]" />
        </div>
      )}

      {/* Charger List */}
      <div className="space-y-2.5">
        {filteredChargers.map(charger => {
          const isDisabled = disabledChargers.includes(charger.charger_id);
          const isOnRoute = routeChargerIds.has(charger.charger_id);
          const isReporting = reportingId === charger.charger_id;

          return (
            <div
              key={charger.charger_id}
              className={`cockpit-panel transition-all border ${
                isDisabled 
                  ? 'border-rose-500/50 bg-rose-950/20 opacity-80' 
                  : isOnRoute 
                    ? 'border-cyan-500/50 bg-slate-950/90 shadow-[0_0_15px_rgba(6,182,212,0.15)]' 
                    : 'border-slate-800/80 hover:border-cyan-900/60'
              }`}
            >
              <div className="flex items-start justify-between gap-3 mb-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h4 className="text-sm font-bold text-white tracking-tight truncate font-sans">
                      {charger.name}
                    </h4>
                    {isOnRoute && (
                      <span className="badge-pill bg-cyan-500/20 text-cyan-300 border-cyan-500/40 text-[10px] font-mono font-bold shadow-[0_0_6px_rgba(6,182,212,0.3)]">
                        PLANNED STOP
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5 font-sans">
                    {charger.operator} · <span className="font-mono text-cyan-300 font-bold">{charger.max_power_kw} kW</span>
                  </p>
                  <p className="text-[11px] text-slate-500 truncate mt-0.5 font-sans">
                    {charger.address}
                  </p>
                </div>

                {/* 1-Click Toggle for Outage Simulation */}
                <button
                  type="button"
                  onClick={() => {
                    playChargeZap();
                    onChargerToggle(charger.charger_id, !isDisabled);
                  }}
                  className={`text-xs px-2.5 py-1.5 rounded-xl font-mono font-bold border transition-all shrink-0 ${
                    isDisabled
                      ? 'bg-emerald-600/30 text-emerald-300 border-emerald-500/50 hover:bg-emerald-600/40 shadow-[0_0_10px_rgba(16,185,129,0.3)]'
                      : 'bg-slate-950 text-slate-300 border-slate-700 hover:border-rose-500/50 hover:text-rose-300 hover:bg-rose-500/10'
                  }`}
                  title={isDisabled ? 'Bring station back online' : 'Simulate station failure and test reroute'}
                >
                  {isDisabled ? 'Restore Station' : '⚡ Simulate Outage'}
                </button>
              </div>

              {/* Status Badges */}
              <div className="flex items-center gap-2 flex-wrap pt-1">
                <OperationalBadge status={charger.is_operational} isDisabled={isDisabled} />
                <ReliabilityBadge 
                  score={charger.reliability_score} 
                  freshness={charger.reliability_freshness_hours} 
                />
                {charger.connector_types.map(ct => (
                  <span key={ct} className="text-[10px] font-mono bg-slate-950 text-cyan-400/80 px-2 py-0.5 rounded border border-slate-800">
                    {ct}
                  </span>
                ))}
              </div>

              {/* Freshness & Report count */}
              <div className="flex items-center justify-between mt-3 pt-2.5 border-t border-slate-800/80 text-[11px] text-slate-400 font-mono">
                <span className="flex items-center gap-1">
                  <Clock size={11} className="text-cyan-400" />
                  {charger.reliability_freshness_hours != null 
                    ? `Observed ~${charger.reliability_freshness_hours.toFixed(0)}h ago`
                    : 'No telemetry reports'}
                  {charger.total_reports != null && ` · ${charger.total_reports} reports`}
                </span>

                {/* Submit report button or action bar */}
                {!isReporting ? (
                  <button
                    type="button"
                    onClick={() => {
                      playCockpitClick();
                      setReportingId(charger.charger_id);
                    }}
                    className="text-cyan-400 hover:text-cyan-300 text-xs font-mono font-bold transition-colors"
                  >
                    + SUBMIT LIVE REPORT
                  </button>
                ) : (
                  <div className="flex items-center gap-1.5 font-mono">
                    <button
                      type="button"
                      onClick={() => { handleReport(charger.charger_id, true); setReportingId(null); }}
                      className="bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 px-2 py-1 rounded text-xs flex items-center gap-1 font-bold"
                    >
                      <ThumbsUp size={11} /> WORKING
                    </button>
                    <button
                      type="button"
                      onClick={() => { handleReport(charger.charger_id, false); setReportingId(null); }}
                      className="bg-rose-500/20 text-rose-300 border border-rose-500/40 px-2 py-1 rounded text-xs flex items-center gap-1 font-bold"
                    >
                      <ThumbsDown size={11} /> FAILED
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        playCockpitClick();
                        setReportingId(null);
                      }}
                      className="text-slate-400 hover:text-slate-200 text-xs px-1"
                    >
                      CANCEL
                    </button>
                  </div>
                )}
              </div>

              {/* Live report feedback message */}
              {reportSuccessFeedback[charger.charger_id] && (
                <div className="mt-2 text-[11px] text-emerald-400 font-mono bg-emerald-500/10 px-2.5 py-1 rounded border border-emerald-500/20">
                  {reportSuccessFeedback[charger.charger_id]}
                </div>
              )}
            </div>
          );
        })}

        {filteredChargers.length === 0 && !loading && (
          <div className="cockpit-panel text-center py-8 text-slate-500 text-xs font-mono">
            NO CHARGING STATIONS MATCH CURRENT CRITERIA.
          </div>
        )}
      </div>
    </div>
  );
}
