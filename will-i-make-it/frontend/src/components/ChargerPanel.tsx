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
    ? 'text-emerald-300 bg-emerald-500/15 border-emerald-500/40'
    : score >= 0.55 
      ? 'text-amber-300 bg-amber-500/15 border-amber-500/40'
      : 'text-rose-300 bg-rose-500/15 border-rose-500/40';

  return (
    <div className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full border text-[11px] font-mono font-medium ${color}`}>
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
      <span className="badge-pill bg-rose-500/20 text-rose-300 border-rose-500/50 text-[10px] font-mono font-bold">
        ● OUTAGE SIMULATED
      </span>
    );
  }
  if (status === true) {
    return (
      <span className="badge-pill bg-emerald-500/10 text-emerald-400 border-emerald-500/30 text-[10px] font-mono font-medium">
        ● OPERATIONAL
      </span>
    );
  }
  if (status === false) {
    return (
      <span className="badge-pill bg-rose-500/10 text-rose-400 border-rose-500/30 text-[10px] font-mono font-medium">
        ● OUT OF SERVICE
      </span>
    );
  }
  return (
    <span className="badge-pill bg-[#0e1219] text-slate-400 border-[#222938] text-[10px] font-mono">
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
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const matchName = c.name.toLowerCase().includes(q);
      const matchOp = c.operator.toLowerCase().includes(q);
      const matchAddr = c.address ? c.address.toLowerCase().includes(q) : false;
      if (!matchName && !matchOp && !matchAddr) return false;
    }
    if (filterMode === 'on_route' && !routeChargerIds.has(c.charger_id)) return false;
    if (filterMode === 'outages' && !disabledChargers.includes(c.charger_id)) return false;
    return true;
  });

  return (
    <div className="flex flex-col gap-4">
      {/* Bayesian Reliability Explainer Banner (Meitriya Style) */}
      <div className="bg-[#121620] border border-[#222938] rounded-2xl p-4 shadow-xl">
        <div className="flex items-start gap-3">
          <div className="p-2 rounded-xl bg-orange-500/10 border border-orange-500/20 text-orange-400 shrink-0 mt-0.5">
            <Zap size={16} />
          </div>
          <div>
            <h4 className="text-xs font-mono font-bold text-orange-400 uppercase tracking-wider mb-1">
              BAYESIAN RELIABILITY ENGINE
            </h4>
            <p className="text-xs text-slate-300 leading-relaxed">
              Stations use Laplace smoothing (&alpha;=1, &beta;=1) with continuous 48-hour freshness decay (e^(-&Delta;t / 48h)). 
              Unverified stations default to an honest 50% prior rather than pretending to be 100% operational.
            </p>
          </div>
        </div>
      </div>

      {/* Search & Filter Bar */}
      <div className="bg-[#121620] border border-[#222938] rounded-2xl p-3.5 shadow-xl">
        <div className="flex items-center gap-2 mb-3">
          <div className="relative flex-1">
            <Search size={14} className="absolute left-3 top-2.5 text-slate-500" />
            <input
              type="text"
              placeholder="Search by operator (Tata Power, Fortum, Zeon) or city..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="w-full bg-[#0a0e14] border border-[#242c3d] rounded-xl pl-8 pr-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-orange-500 transition-colors"
            />
          </div>
          {disabledChargers.length > 0 && onResetDisabledChargers && (
            <button
              type="button"
              onClick={() => {
                playCockpitClick();
                onResetDisabledChargers();
              }}
              className="bg-[#181e2b] hover:bg-[#202738] text-xs flex items-center gap-1.5 py-1.5 px-3 text-rose-300 border border-rose-500/40 rounded-xl shrink-0 font-mono font-semibold"
              title="Restore all stations online"
            >
              <RotateCcw size={12} />
              <span>RESET OUTAGES</span>
            </button>
          )}
        </div>

        {/* Filter Pills (Meitriya Style) */}
        <div className="flex gap-1.5 font-mono">
          <button
            type="button"
            onClick={() => {
              playCockpitClick();
              setFilterMode('all');
            }}
            className={`px-3 py-1 rounded-xl text-xs font-semibold transition-all ${
              filterMode === 'all' 
                ? 'bg-orange-500 text-white shadow-sm' 
                : 'bg-[#181e2b] text-slate-400 hover:text-slate-200 border border-[#222938]'
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
            className={`px-3 py-1 rounded-xl text-xs font-semibold transition-all ${
              filterMode === 'on_route' 
                ? 'bg-emerald-600 text-white shadow-sm' 
                : 'bg-[#181e2b] text-slate-400 hover:text-slate-200 border border-[#222938]'
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
            className={`px-3 py-1 rounded-xl text-xs font-semibold transition-all ${
              filterMode === 'outages' 
                ? 'bg-rose-600 text-white shadow-sm' 
                : 'bg-[#181e2b] text-slate-400 hover:text-slate-200 border border-[#222938]'
            }`}
          >
            OUTAGES ({disabledChargers.length})
          </button>
        </div>
      </div>

      {loading && (
        <div className="bg-[#121620] border border-[#222938] rounded-2xl flex items-center justify-center h-28">
          <div className="w-5 h-5 border-2 border-orange-400 border-t-transparent rounded-full animate-spin" />
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
              className={`bg-[#121620] rounded-2xl p-3.5 border transition-all ${
                isDisabled 
                  ? 'border-rose-500/40 bg-rose-950/20 opacity-80' 
                  : isOnRoute 
                    ? 'border-orange-500/50 shadow-md' 
                    : 'border-[#222938] hover:border-slate-600'
              }`}
            >
              <div className="flex items-start justify-between gap-3 mb-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h4 className="text-sm font-bold text-white truncate">
                      {charger.name}
                    </h4>
                    {isOnRoute && (
                      <span className="text-[10px] bg-orange-500/15 text-orange-300 border border-orange-500/30 px-1.5 py-0.5 rounded font-mono font-bold">
                        PLANNED STOP
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {charger.operator} · <span className="font-mono text-orange-400 font-bold">{charger.max_power_kw} kW</span>
                  </p>
                  <p className="text-[11px] text-slate-500 truncate mt-0.5">
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
                  className={`text-xs px-3 py-1.5 rounded-xl font-mono font-semibold border transition-all shrink-0 ${
                    isDisabled
                      ? 'bg-emerald-600/20 text-emerald-300 border-emerald-500/40 hover:bg-emerald-600/30'
                      : 'bg-[#181e2b] text-slate-300 border-[#262f42] hover:border-rose-500/40 hover:text-rose-300'
                  }`}
                  title={isDisabled ? 'Bring station back online' : 'Simulate station failure and test reroute'}
                >
                  {isDisabled ? '✓ Restore' : '⚡ Simulate Outage'}
                </button>
              </div>

              {/* Status Badges */}
              <div className="flex items-center gap-2 flex-wrap pt-1">
                <OperationalBadge status={charger.is_operational} isDisabled={isDisabled} />
                {charger.status === 'VERIFIED_REAL' && (
                  <span className="text-[10px] bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 px-1.5 py-0.5 rounded font-mono font-bold">
                    VERIFIED REAL
                  </span>
                )}
                {charger.status === 'DEMO_SEED' && (
                  <span className="text-[10px] bg-amber-500/20 text-amber-300 border border-amber-500/40 px-1.5 py-0.5 rounded font-mono font-bold">
                    DEMO SEED (UNVERIFIED)
                  </span>
                )}
                {(charger.status === 'HYPOTHETICAL' || charger.charger_id.startsWith('CHR_HYPO_')) && (
                  <span className="text-[10px] bg-purple-500/20 text-purple-300 border border-purple-500/40 px-1.5 py-0.5 rounded font-mono font-bold">
                    HYPOTHETICAL STOP
                  </span>
                )}
                {(!charger.status || charger.status === 'UNKNOWN') && !charger.charger_id.startsWith('CHR_HYPO_') && (
                  <span className="text-[10px] bg-slate-700/40 text-slate-300 border border-slate-600/40 px-1.5 py-0.5 rounded font-mono font-bold">
                    UNVERIFIED STATION
                  </span>
                )}
                <ReliabilityBadge 
                  score={charger.reliability_score} 
                  freshness={charger.reliability_freshness_hours} 
                />
                {charger.connector_types.map(ct => (
                  <span key={ct} className="text-[10px] font-mono bg-[#0e1219] text-slate-400 px-2 py-0.5 rounded border border-[#1e2535]">
                    {ct}
                  </span>
                ))}
              </div>

              {/* Freshness & Report count */}
              <div className="flex items-center justify-between mt-3 pt-2.5 border-t border-[#1e2535] text-[11px] text-slate-400 font-mono">
                <span className="flex items-center gap-1">
                  <Clock size={11} className="text-slate-500" />
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
                    className="text-orange-400 hover:text-orange-300 text-xs font-mono font-semibold transition-colors"
                  >
                    + SUBMIT LIVE REPORT
                  </button>
                ) : (
                  <div className="flex items-center gap-1.5 font-mono">
                    <button
                      type="button"
                      onClick={() => { handleReport(charger.charger_id, true); setReportingId(null); }}
                      className="bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 px-2.5 py-1 rounded-lg text-xs flex items-center gap-1 font-bold"
                    >
                      <ThumbsUp size={11} /> WORKING
                    </button>
                    <button
                      type="button"
                      onClick={() => { handleReport(charger.charger_id, false); setReportingId(null); }}
                      className="bg-rose-500/20 text-rose-300 border border-rose-500/40 px-2.5 py-1 rounded-lg text-xs flex items-center gap-1 font-bold"
                    >
                      <ThumbsDown size={11} /> FAILED
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        playCockpitClick();
                        setReportingId(null);
                      }}
                      className="text-slate-400 hover:text-slate-200 text-xs px-1.5"
                    >
                      CANCEL
                    </button>
                  </div>
                )}
              </div>

              {/* Live report feedback message */}
              {reportSuccessFeedback[charger.charger_id] && (
                <div className="mt-2 text-[11px] text-emerald-400 font-mono bg-emerald-500/10 px-2.5 py-1 rounded-lg border border-emerald-500/20">
                  {reportSuccessFeedback[charger.charger_id]}
                </div>
              )}
            </div>
          );
        })}

        {filteredChargers.length === 0 && !loading && (
          <div className="bg-[#121620] border border-[#222938] rounded-2xl text-center py-8 text-slate-500 text-xs font-mono">
            NO CHARGING STATIONS MATCH CURRENT CRITERIA.
          </div>
        )}
      </div>
    </div>
  );
}
