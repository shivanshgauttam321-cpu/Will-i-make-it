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
    ? 'text-emerald-700 bg-emerald-50 border-emerald-200'
    : score >= 0.55 
      ? 'text-amber-700 bg-amber-50 border-amber-200'
      : 'text-rose-700 bg-rose-50 border-rose-200';

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
      <span className="badge-pill bg-rose-50 text-rose-700 border-rose-200 text-[10px] font-mono font-bold">
        ● OUTAGE SIMULATED
      </span>
    );
  }
  if (status === true) {
    return (
      <span className="badge-pill bg-emerald-50 text-emerald-700 border-emerald-200 text-[10px] font-mono font-medium">
        ● OPERATIONAL
      </span>
    );
  }
  if (status === false) {
    return (
      <span className="badge-pill bg-rose-50 text-rose-700 border-rose-200 text-[10px] font-mono font-medium">
        ● OUT OF SERVICE
      </span>
    );
  }
  return (
    <span className="badge-pill bg-slate-100 text-[#475569] border-slate-300 text-[10px] font-mono">
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
      {/* Bayesian Reliability Explainer Banner */}
      <div className="bg-white border border-[#E2E8F0] rounded-2xl p-4 shadow-sm">
        <div className="flex items-start gap-3">
          <div className="p-2 rounded-xl bg-orange-50 border border-orange-200 text-[#F97316] shrink-0 mt-0.5">
            <Zap size={16} />
          </div>
          <div>
            <h4 className="text-xs font-mono font-bold text-orange-600 uppercase tracking-wider mb-1">
              BAYESIAN RELIABILITY ENGINE
            </h4>
            <p className="text-xs text-[#334155] leading-relaxed">
              Stations use Laplace smoothing (&alpha;=1, &beta;=1) with continuous 48-hour freshness decay (e^(-&Delta;t / 48h)). 
              Unverified stations default to an honest 50% prior rather than pretending to be 100% operational.
            </p>
          </div>
        </div>
      </div>

      {/* Search & Filter Bar */}
      <div className="bg-white border border-[#E2E8F0] rounded-2xl p-3.5 shadow-sm">
        <div className="flex items-center gap-2 mb-3">
          <div className="relative flex-1">
            <Search size={14} className="absolute left-3 top-2.5 text-slate-400" />
            <input
              type="text"
              placeholder="Search by operator (Tata Power, Fortum, Zeon) or city..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              className="w-full bg-[#F8FAFC] border border-[#CBD5E1] rounded-xl pl-8 pr-3 py-1.5 text-xs text-[#172033] focus:bg-white focus:outline-none focus:border-orange-500 transition-colors"
            />
          </div>
          {disabledChargers.length > 0 && onResetDisabledChargers && (
            <button
              type="button"
              onClick={() => {
                playCockpitClick();
                onResetDisabledChargers();
              }}
              className="bg-rose-50 hover:bg-rose-100 text-xs flex items-center gap-1.5 py-1.5 px-3 text-rose-700 border border-rose-200 rounded-xl shrink-0 font-mono font-semibold"
              title="Restore all stations online"
            >
              <RotateCcw size={12} />
              <span>RESET OUTAGES</span>
            </button>
          )}
        </div>

        {/* Filter Pills */}
        <div className="flex flex-wrap gap-1.5 font-mono">
          <button
            type="button"
            onClick={() => {
              playCockpitClick();
              setFilterMode('all');
            }}
            className={`px-3 py-1 rounded-xl text-xs font-semibold transition-all ${
              filterMode === 'all' 
                ? 'bg-[#F97316] text-white shadow-sm' 
                : 'bg-[#F8FAFC] text-[#64748B] hover:text-[#172033] border border-[#E2E8F0]'
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
                : 'bg-[#F8FAFC] text-[#64748B] hover:text-[#172033] border border-[#E2E8F0]'
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
                : 'bg-[#F8FAFC] text-[#64748B] hover:text-[#172033] border border-[#E2E8F0]'
            }`}
          >
            OUTAGES ({disabledChargers.length})
          </button>
        </div>
      </div>

      {loading && (
        <div className="bg-white border border-[#E2E8F0] rounded-2xl flex items-center justify-center h-28 shadow-sm">
          <div className="w-5 h-5 border-2 border-orange-500 border-t-transparent rounded-full animate-spin" />
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
              className={`bg-white rounded-2xl p-3.5 border transition-all shadow-sm ${
                isDisabled 
                  ? 'border-rose-200 bg-rose-50/20 opacity-80' 
                  : isOnRoute 
                    ? 'border-orange-400 bg-orange-50/20' 
                    : 'border-[#E2E8F0] hover:border-slate-300'
              }`}
            >
              <div className="flex items-start justify-between gap-3 mb-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h4 className="text-sm font-bold text-[#172033] truncate">
                      {charger.name}
                    </h4>
                    {isOnRoute && (
                      <span className="text-[10px] bg-orange-50 text-orange-700 border border-orange-200 px-1.5 py-0.5 rounded font-mono font-bold">
                        PLANNED STOP
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-[#64748B] mt-0.5">
                    {charger.operator} · <span className="font-mono text-orange-600 font-bold">{charger.max_power_kw} kW</span>
                  </p>
                  <p className="text-[11px] text-slate-400 truncate mt-0.5">
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
                      ? 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100'
                      : 'bg-[#F8FAFC] text-[#334155] border-[#CBD5E1] hover:border-rose-300 hover:text-rose-700 hover:bg-rose-50'
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
                  <span className="text-[10px] bg-emerald-50 text-emerald-700 border border-emerald-200 px-1.5 py-0.5 rounded font-mono font-bold">
                    VERIFIED REAL
                  </span>
                )}
                {charger.status === 'DEMO_SEED' && (
                  <span className="text-[10px] bg-amber-50 text-amber-700 border border-amber-200 px-1.5 py-0.5 rounded font-mono font-bold">
                    DEMO SEED (UNVERIFIED)
                  </span>
                )}
                {(charger.status === 'HYPOTHETICAL' || charger.charger_id.startsWith('CHR_HYPO_')) && (
                  <span className="text-[10px] bg-purple-50 text-purple-700 border border-purple-200 px-1.5 py-0.5 rounded font-mono font-bold">
                    HYPOTHETICAL STOP
                  </span>
                )}
                {(!charger.status || charger.status === 'UNKNOWN') && !charger.charger_id.startsWith('CHR_HYPO_') && (
                  <span className="text-[10px] bg-slate-100 text-[#475569] border border-slate-300 px-1.5 py-0.5 rounded font-mono font-bold">
                    UNVERIFIED STATION
                  </span>
                )}
                <ReliabilityBadge 
                  score={charger.reliability_score} 
                  freshness={charger.reliability_freshness_hours} 
                />
                {charger.connector_types.map(ct => (
                  <span key={ct} className="text-[10px] font-mono bg-[#F1F4F8] text-[#334155] px-2 py-0.5 rounded border border-[#E2E8F0]">
                    {ct}
                  </span>
                ))}
              </div>

              {/* Freshness & Report count */}
              <div className="flex items-center justify-between mt-3 pt-2.5 border-t border-[#F1F4F8] text-[11px] text-[#64748B] font-mono">
                <span className="flex items-center gap-1">
                  <Clock size={11} className="text-slate-400" />
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
                    className="text-orange-600 hover:text-orange-700 text-xs font-mono font-semibold transition-colors"
                  >
                    + SUBMIT LIVE REPORT
                  </button>
                ) : (
                  <div className="flex items-center gap-1.5 font-mono">
                    <button
                      type="button"
                      onClick={() => { handleReport(charger.charger_id, true); setReportingId(null); }}
                      className="bg-emerald-50 text-emerald-700 border border-emerald-200 px-2.5 py-1 rounded-lg text-xs flex items-center gap-1 font-bold"
                    >
                      <ThumbsUp size={11} /> WORKING
                    </button>
                    <button
                      type="button"
                      onClick={() => { handleReport(charger.charger_id, false); setReportingId(null); }}
                      className="bg-rose-50 text-rose-700 border border-rose-200 px-2.5 py-1 rounded-lg text-xs flex items-center gap-1 font-bold"
                    >
                      <ThumbsDown size={11} /> FAILED
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        playCockpitClick();
                        setReportingId(null);
                      }}
                      className="text-[#64748B] hover:text-[#172033] text-xs px-1.5"
                    >
                      CANCEL
                    </button>
                  </div>
                )}
              </div>

              {/* Live report feedback message */}
              {reportSuccessFeedback[charger.charger_id] && (
                <div className="mt-2 text-[11px] text-emerald-800 font-mono bg-emerald-50 px-2.5 py-1 rounded-lg border border-emerald-200">
                  {reportSuccessFeedback[charger.charger_id]}
                </div>
              )}
            </div>
          );
        })}

        {filteredChargers.length === 0 && !loading && (
          <div className="bg-white border border-[#E2E8F0] rounded-2xl text-center py-8 text-[#64748B] text-xs font-mono shadow-sm">
            NO CHARGING STATIONS MATCH CURRENT CRITERIA.
          </div>
        )}
      </div>
    </div>
  );
}
