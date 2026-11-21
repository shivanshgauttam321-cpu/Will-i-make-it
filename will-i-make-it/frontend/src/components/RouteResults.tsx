import { useState } from 'react';
import { 
  CheckCircle, XCircle, AlertTriangle, Zap, Clock, Battery, 
  ChevronDown, ChevronRight, Play, RefreshCw, ShieldAlert, ShieldCheck, 
  CornerDownRight, Compass, Flame, Gauge, ArrowRight
} from 'lucide-react';
import { 
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, 
  ReferenceLine, BarChart, Bar
} from 'recharts';
import { simulateTrip } from '../utils/api';
import { playCockpitClick, playChargeZap } from '../utils/audioService';
import type { RoutePlanResponse, RouteOption, VehicleProfile, TripRecord } from '../types/api';

interface Props {
  result: RoutePlanResponse;
  vehicle: VehicleProfile;
  disabledChargers: string[];
  onChargerToggle: (id: string, disabled: boolean) => void;
  selectedRouteId: string;
}

export default function RouteResults({
  result, vehicle, disabledChargers, onChargerToggle, selectedRouteId
}: Props) {
  // Tab to choose between fastest route and risk-aware route
  const [activeTab, setActiveTab] = useState<'fastest' | 'risk_aware'>('fastest');
  const [showSegmentDetails, setShowSegmentDetails] = useState(false);
  const [isSimulating, setIsSimulating] = useState(false);
  const [tripSimulation, setTripSimulation] = useState<TripRecord | null>(null);

  const selectedRoute: RouteOption = (activeTab === 'risk_aware' && result.risk_aware_route)
    ? result.risk_aware_route
    : result.fastest_route;

  const energy = selectedRoute.energy_result;
  const isRecommended = result.recommended === selectedRoute.route_id;

  // Build discharge curve data for the SoC profile
  let cumulativeDist = 0;
  let runningSoCP50 = vehicle.soc_start_pct;
  let runningSoCP90 = vehicle.soc_start_pct;

  const dischargeData = [
    {
      km: 0,
      name: 'Start',
      soc_p50: vehicle.soc_start_pct,
      soc_p90: vehicle.soc_start_pct,
      reserve: vehicle.soc_reserve_pct,
    }
  ];

  selectedRoute.segments.forEach((seg, idx) => {
    const segRes = energy.segments[idx];
    cumulativeDist += seg.distance_km;
    
    // P50 delta
    const deltaP50 = (segRes.net_kwh / vehicle.battery_capacity_kwh) * 100;
    runningSoCP50 = Math.max(0, Math.min(100, runningSoCP50 - deltaP50));

    // P90 delta
    const deltaP90 = (segRes.net_kwh_p90 / vehicle.battery_capacity_kwh) * 100;
    runningSoCP90 = Math.max(0, Math.min(100, runningSoCP90 - deltaP90));

    // Check if there is a charging stop after this segment
    const matchingStop = selectedRoute.charging_stops.find(s => 
      Math.abs(s.arrive_soc_pct - runningSoCP50) < 5 || (idx === Math.floor(selectedRoute.segments.length / 2))
    );

    dischargeData.push({
      km: Math.round(cumulativeDist),
      name: seg.name ? seg.name.slice(0, 12) : `Seg ${idx + 1}`,
      soc_p50: Math.round(runningSoCP50 * 10) / 10,
      soc_p90: Math.round(runningSoCP90 * 10) / 10,
      reserve: vehicle.soc_reserve_pct,
    });

    if (matchingStop && idx < selectedRoute.segments.length - 1) {
      // Step jump from charge
      runningSoCP50 = matchingStop.depart_soc_pct;
      runningSoCP90 = matchingStop.depart_soc_pct;
      dischargeData.push({
        km: Math.round(cumulativeDist),
        name: `Charge (${matchingStop.charger.name.slice(0, 8)})`,
        soc_p50: matchingStop.depart_soc_pct,
        soc_p90: matchingStop.depart_soc_pct,
        reserve: vehicle.soc_reserve_pct,
      });
    }
  });

  // Segment energy bar chart data
  const segmentEnergyData = energy.segments.map(s => ({
    name: s.name ? s.name.replace(/–|-/g, ' ').slice(0, 10) : s.segment_id,
    rolling: +(s.rolling_kj / 3600).toFixed(2),
    aero: +(s.aero_kj / 3600).toFixed(2),
    gradient: +(Math.max(0, s.gradient_kj) / 3600).toFixed(2),
    aux: +(s.aux_kj / 3600).toFixed(2),
    regen: +(Math.abs(s.regen_kj) / 3600).toFixed(2),
  }));

  // Trigger live trip simulation endpoint
  const handleSimulateDrive = async () => {
    playCockpitClick();
    setIsSimulating(true);
    try {
      const rec = await simulateTrip({
        route_id: selectedRouteId,
        vehicle,
        ambient_temp_c: 28,
        noise_seed: Math.floor(Math.random() * 1000),
      });
      setTripSimulation(rec);
      playChargeZap();
    } catch {
      // ignore
    } finally {
      setIsSimulating(false);
    }
  };

  const riskBadge = selectedRoute.risk_score < 0.35 
    ? { label: 'LOW RISK', color: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' }
    : selectedRoute.risk_score < 0.65 
      ? { label: 'MODERATE RISK', color: 'bg-amber-500/10 text-amber-400 border-amber-500/30' }
      : { label: 'HIGH RISK', color: 'bg-rose-500/10 text-rose-400 border-rose-500/30' };

  return (
    <div className="flex flex-col gap-4">
      {/* Route Mode Switcher & Live Simulation Action Bar (Meitriya Style) */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-2.5 bg-[#121620] border border-[#222938] rounded-2xl p-2 shadow-xl">
        <div className="flex gap-1.5 flex-1">
          {/* Fastest Mode */}
          <button
            type="button"
            onClick={() => {
              playCockpitClick();
              setActiveTab('fastest');
            }}
            className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl text-xs font-mono font-medium transition-all ${
              activeTab === 'fastest'
                ? 'bg-orange-500 text-white shadow-sm font-bold'
                : 'text-slate-400 hover:text-slate-200 hover:bg-[#181e2b]'
            }`}
          >
            <Compass size={14} className={activeTab === 'fastest' ? 'text-white' : 'text-slate-500'} />
            <span>FASTEST ROUTE</span>
            {result.recommended === result.fastest_route.route_id && (
              <span className={`text-[10px] px-1.5 py-0.2 rounded font-mono ${
                activeTab === 'fastest' ? 'bg-black/30 text-white' : 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
              }`}>
                RECOMMENDED
              </span>
            )}
          </button>

          {/* Risk-Aware Mode */}
          {result.risk_aware_route && (
            <button
              type="button"
              onClick={() => {
                playCockpitClick();
                setActiveTab('risk_aware');
              }}
              className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl text-xs font-mono font-medium transition-all ${
                activeTab === 'risk_aware'
                  ? 'bg-emerald-600 text-white shadow-sm font-bold'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-[#181e2b]'
              }`}
            >
              <ShieldCheck size={14} className={activeTab === 'risk_aware' ? 'text-white' : 'text-slate-500'} />
              <span>RISK-AWARE ROUTE</span>
              {result.recommended === result.risk_aware_route.route_id && (
                <span className={`text-[10px] px-1.5 py-0.2 rounded font-mono ${
                  activeTab === 'risk_aware' ? 'bg-black/30 text-white' : 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                }`}>
                  RECOMMENDED
                </span>
              )}
            </button>
          )}
        </div>

        {/* Live Simulation Button */}
        <button
          type="button"
          onClick={handleSimulateDrive}
          disabled={isSimulating}
          className="bg-[#181e2b] hover:bg-[#202738] text-slate-200 hover:text-white border border-[#262f42] hover:border-slate-600 text-xs font-mono flex items-center justify-center gap-2 py-2 px-3.5 rounded-xl font-semibold transition-all shrink-0 active:scale-95"
        >
          {isSimulating ? (
            <div className="w-3.5 h-3.5 border-2 border-orange-400 border-t-transparent rounded-full animate-spin" />
          ) : (
            <Play size={13} className="text-orange-400 fill-orange-400" />
          )}
          <span>SIMULATE DRIVE</span>
        </button>
      </div>

      {/* Dynamic Outage Reroute Banner */}
      {result.charger_failure_scenario && (
        <div className="bg-[#1c1610] border border-orange-500/40 rounded-2xl p-4 flex items-start gap-3 shadow-lg">
          <AlertTriangle size={18} className="text-orange-400 shrink-0 mt-0.5" />
          <div className="text-xs text-orange-200 leading-relaxed font-sans">
            <span className="font-bold text-orange-100 uppercase tracking-wider font-mono mr-1">
              [DYNAMIC REROUTE TRIGGERED]:
            </span>
            {result.charger_failure_scenario}
          </div>
        </div>
      )}

      {/* Main Telemetry & Energy Intelligence Card (Meitriya Style) */}
      <div className="bg-[#121620] border border-[#222938] rounded-2xl p-4 shadow-xl">
        {/* Header Bar */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3.5 border-b border-[#1e2535]">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-extrabold text-white text-base tracking-tight font-sans">
                {selectedRoute.label}
              </h3>
              <span className={`badge-pill text-[10px] font-mono ${riskBadge.color}`}>
                {riskBadge.label} ({(selectedRoute.risk_score * 100).toFixed(0)}%)
              </span>
              {isRecommended && (
                <span className="badge-pill bg-orange-500/10 text-orange-300 border-orange-500/30 text-[10px] font-mono font-bold">
                  ✓ RECOMMENDED STRATEGY
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400 mt-0.5">{selectedRoute.description}</p>
          </div>

          {/* Feasibility Indicator */}
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-xl border text-xs font-mono font-bold shadow-sm ${
            selectedRoute.feasible 
              ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300'
              : 'bg-rose-500/10 border-rose-500/40 text-rose-300'
          }`}>
            {selectedRoute.feasible ? <CheckCircle size={15} /> : <XCircle size={15} />}
            <span>
              {selectedRoute.feasible 
                ? `FEASIBLE (+${selectedRoute.feasibility_margin_kwh.toFixed(1)} kWh RESERVE)`
                : 'RANGE CRITICAL (INFEASIBLE)'
              }
            </span>
          </div>
        </div>

        {/* 4 Key Metric Dials (Clean Charcoal Tiles) */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5 py-3.5">
          <div className="bg-[#0e1219] border border-[#1e2535] rounded-xl p-3 text-center">
            <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 block mb-1">TOTAL DISTANCE</span>
            <span className="text-xl font-black font-mono text-white">{selectedRoute.distance_km}</span>
            <span className="text-xs text-slate-400 ml-1 font-mono">km</span>
          </div>
          <div className="bg-[#0e1219] border border-[#1e2535] rounded-xl p-3 text-center">
            <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 block mb-1">TRAVEL TIME</span>
            <span className="text-xl font-black font-mono text-white">{Math.round(selectedRoute.duration_min)}</span>
            <span className="text-xs text-slate-400 ml-1 font-mono">min</span>
          </div>
          <div className="bg-[#0e1219] border border-[#1e2535] rounded-xl p-3 text-center">
            <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 block mb-1">P50 EXPECTED</span>
            <span className="text-xl font-black font-mono text-teal-400">{energy.total_kwh_p50.toFixed(1)}</span>
            <span className="text-xs text-teal-400 ml-1 font-mono">kWh</span>
          </div>
          <div className="bg-[#0e1219] border border-[#1e2535] rounded-xl p-3 text-center">
            <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 block mb-1">P90 CONSERVATIVE</span>
            <span className="text-xl font-black font-mono text-orange-400">{energy.total_kwh_p90.toFixed(1)}</span>
            <span className="text-xs text-orange-400 ml-1 font-mono">kWh</span>
            <span className="block text-[8px] text-slate-500 font-mono mt-0.5">MODEL_BASED_P90_ESTIMATE</span>
          </div>
        </div>

        {/* Battery Arrival Gauge */}
        <div className="bg-[#0e1219] rounded-xl p-3.5 border border-[#1e2535] mb-3.5">
          <div className="flex justify-between items-center mb-2.5">
            <div className="flex items-center gap-1.5 text-xs font-mono font-bold text-slate-200">
              <Battery size={14} className="text-orange-400" />
              ARRIVAL BATTERY SOC PREDICTION
            </div>
            <div className="text-xs font-mono text-slate-400">
              MIN RESERVE: <span className="text-rose-400 font-bold">{vehicle.soc_reserve_pct}%</span>
            </div>
          </div>

          <div className="space-y-2.5">
            {/* P50 Bar */}
            <div>
              <div className="flex justify-between text-xs mb-1 font-mono">
                <span className="text-slate-400 text-[11px]">EXPECTED (P50) ARRIVAL</span>
                <span className="font-bold text-teal-400">{energy.soc_final_p50_pct.toFixed(1)}%</span>
              </div>
              <div className="h-2 bg-[#171c28] rounded-full overflow-hidden p-0.5 border border-[#222938]">
                <div 
                  className="h-full rounded-full bg-gradient-to-r from-teal-500 to-cyan-400 transition-all duration-700" 
                  style={{ width: `${Math.min(100, Math.max(0, energy.soc_final_p50_pct))}%` }} 
                />
              </div>
            </div>

            {/* P90 Bar */}
            <div>
              <div className="flex justify-between text-xs mb-1 font-mono">
                <span className="text-slate-400 text-[11px]">CONSERVATIVE (P90) ARRIVAL</span>
                <span className="font-bold text-orange-400">{energy.soc_final_p90_pct.toFixed(1)}%</span>
              </div>
              <div className="h-2 bg-[#171c28] rounded-full overflow-hidden p-0.5 border border-[#222938]">
                <div 
                  className="h-full rounded-full bg-gradient-to-r from-orange-500 to-amber-400 transition-all duration-700" 
                  style={{ width: `${Math.min(100, Math.max(0, energy.soc_final_p90_pct))}%` }} 
                />
              </div>
            </div>
          </div>
        </div>

        {/* Battery Discharge Curve Chart (Meitriya Style with Orange & Cyan) */}
        <div className="mt-1">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
              <Flame size={13} className="text-orange-400" />
              BATTERY SOC TRAJECTORY PROFILE (%)
            </span>
            <div className="flex items-center gap-3 text-[10px] text-slate-400 font-mono">
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-full bg-teal-400 inline-block" /> P50
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-full bg-orange-400 inline-block" /> P90
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-0.5 bg-rose-500 inline-block" /> Reserve ({vehicle.soc_reserve_pct}%)
              </span>
            </div>
          </div>

          <div className="h-44 w-full bg-[#0a0e14] rounded-xl p-2 border border-[#1e2535]">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={dischargeData} margin={{ top: 10, right: 15, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="p50Grad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#14b8a6" stopOpacity={0.35}/>
                    <stop offset="95%" stopColor="#14b8a6" stopOpacity={0.0}/>
                  </linearGradient>
                  <linearGradient id="p90Grad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#f97316" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#f97316" stopOpacity={0.0}/>
                  </linearGradient>
                </defs>
                <XAxis 
                  dataKey="km" 
                  tick={{ fontSize: 10, fill: '#64748b' }} 
                  unit="km" 
                />
                <YAxis 
                  domain={[0, 100]} 
                  tick={{ fontSize: 10, fill: '#64748b' }} 
                  unit="%" 
                />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#121620', borderColor: '#262f42', borderRadius: '12px', fontSize: '11px', boxShadow: '0 10px 25px rgba(0,0,0,0.8)' }}
                  labelStyle={{ color: '#cbd5e1', fontFamily: 'monospace' }}
                />
                <ReferenceLine 
                  y={vehicle.soc_reserve_pct} 
                  stroke="#f43f5e" 
                  strokeDasharray="4 4" 
                  label={{ value: 'Reserve', fill: '#f43f5e', fontSize: 10, position: 'right' }} 
                />
                <Area 
                  type="monotone" 
                  dataKey="soc_p50" 
                  name="P50 SoC (%)" 
                  stroke="#14b8a6" 
                  strokeWidth={2.2} 
                  fillOpacity={1} 
                  fill="url(#p50Grad)" 
                />
                <Area 
                  type="monotone" 
                  dataKey="soc_p90" 
                  name="P90 SoC (%)" 
                  stroke="#f97316" 
                  strokeWidth={1.8} 
                  strokeDasharray="3 3" 
                  fillOpacity={1} 
                  fill="url(#p90Grad)" 
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Planned Charging Stops with 1-Click Failure Simulation */}
        {selectedRoute.charging_stops.length > 0 && (
          <div className="mt-4 pt-3.5 border-t border-[#1e2535]">
            <div className="flex items-center justify-between mb-2.5">
              <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-slate-300 flex items-center gap-1.5">
                <Zap size={13} className="text-orange-400" />
                REQUIRED CHARGING STOPS ({selectedRoute.charging_stops.length})
              </span>
              <span className="text-[10px] text-slate-400 font-mono">
                Click button to simulate outage & reroute
              </span>
            </div>

            <div className="space-y-2">
              {selectedRoute.charging_stops.map((stop, i) => {
                const isDown = disabledChargers.includes(stop.charger.charger_id);
                return (
                  <div 
                    key={i} 
                    className={`p-3 rounded-xl border transition-all flex flex-col sm:flex-row sm:items-center justify-between gap-3 ${
                      isDown 
                        ? 'bg-rose-950/20 border-rose-800/40 opacity-75' 
                        : 'bg-[#0e1219] border-[#1e2535] hover:border-[#2b3547]'
                    }`}
                  >
                    <div className="flex items-start gap-2.5">
                      <div className="p-2 rounded-lg mt-0.5 shrink-0 bg-orange-500/10 text-orange-400 border border-orange-500/20">
                        <Zap size={16} />
                      </div>
                      <div>
                        <div className="flex items-center gap-2 flex-wrap">
                          <h4 className="text-sm font-bold text-white font-sans">{stop.charger.name}</h4>
                          <span className="text-[10px] bg-[#1a2130] text-orange-400 border border-[#273244] px-1.5 py-0.5 rounded font-mono font-bold">
                            {stop.charger.max_power_kw} kW
                          </span>
                          {stop.charger.status === 'VERIFIED_REAL' && (
                            <span className="text-[10px] bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 px-1.5 py-0.5 rounded font-mono font-bold">
                              VERIFIED REAL
                            </span>
                          )}
                          {stop.charger.status === 'DEMO_SEED' && (
                            <span className="text-[10px] bg-amber-500/20 text-amber-300 border border-amber-500/40 px-1.5 py-0.5 rounded font-mono font-bold">
                              DEMO SEED (UNVERIFIED)
                            </span>
                          )}
                          {(stop.charger.status === 'HYPOTHETICAL' || stop.charger.charger_id.startsWith('CHR_HYPO_')) && (
                            <span className="text-[10px] bg-purple-500/20 text-purple-300 border border-purple-500/40 px-1.5 py-0.5 rounded font-mono font-bold">
                              HYPOTHETICAL STOP
                            </span>
                          )}
                          {(!stop.charger.status || stop.charger.status === 'UNKNOWN') && !stop.charger.charger_id.startsWith('CHR_HYPO_') && (
                            <span className="text-[10px] bg-slate-700/40 text-slate-300 border border-slate-600/40 px-1.5 py-0.5 rounded font-mono font-bold">
                              UNVERIFIED STATION
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-slate-400 mt-0.5">
                          {stop.charger.operator} · Arrive {stop.arrive_soc_pct.toFixed(0)}% → Charge to {stop.depart_soc_pct.toFixed(0)}%
                          · Duration: <span className="font-mono text-orange-400 font-bold">{stop.charge_duration_min.toFixed(0)} min</span>
                        </p>
                      </div>
                    </div>

                    {/* Interactive 1-Click Outage Trigger */}
                    <div className="flex items-center gap-3 shrink-0">
                      <span className="text-xs font-mono font-bold text-emerald-400">
                        +{stop.charge_energy_kwh.toFixed(1)} kWh
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          playChargeZap();
                          onChargerToggle(stop.charger.charger_id, !isDown);
                        }}
                        className={`text-xs px-3 py-1.5 rounded-xl font-mono font-semibold transition-all border ${
                          isDown
                            ? 'bg-emerald-600/20 text-emerald-300 border-emerald-500/40 hover:bg-emerald-600/30'
                            : 'bg-rose-600/15 text-rose-300 border-rose-500/30 hover:bg-rose-600/25'
                        }`}
                      >
                        {isDown ? '✓ Restore Station' : '⚡ Simulate Outage'}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Live Simulation Output Box (when triggered) */}
        {tripSimulation && (
          <div className="mt-4 bg-[#0d1614] border border-emerald-500/30 rounded-xl p-3.5">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <CheckCircle size={15} className="text-emerald-400" />
                <span className="text-xs font-mono font-bold text-white uppercase tracking-wider">
                  LIVE DRIVE TELEMETRY (SIMULATED)
                </span>
                <span className="text-[10px] bg-emerald-500/15 text-emerald-300 px-2 py-0.5 rounded-full font-mono">
                  Trip #{tripSimulation.trip_id}
                </span>
              </div>
              <span className={`text-xs font-mono font-bold px-2 py-0.5 rounded ${
                tripSimulation.within_p90 ? 'bg-emerald-500/20 text-emerald-400' : 'bg-rose-500/20 text-rose-400'
              }`}>
                {tripSimulation.within_p90 ? '✓ INSIDE P90 SAFE ENVELOPE' : '⚠️ EXCEEDED P90'}
              </span>
            </div>

            <div className="grid grid-cols-3 gap-2 text-center text-xs mt-2">
              <div className="bg-[#121620] p-2 rounded-lg border border-[#1e2535]">
                <span className="text-[10px] text-slate-400 block font-mono">ACTUAL DRAWN</span>
                <span className="font-mono font-bold text-white text-sm">{tripSimulation.actual_kwh} kWh</span>
              </div>
              <div className="bg-[#121620] p-2 rounded-lg border border-[#1e2535]">
                <span className="text-[10px] text-slate-400 block font-mono">PREDICTED P50</span>
                <span className="font-mono font-bold text-slate-300 text-sm">{tripSimulation.predicted_kwh_p50} kWh</span>
              </div>
              <div className="bg-[#121620] p-2 rounded-lg border border-[#1e2535]">
                <span className="text-[10px] text-slate-400 block font-mono">FINAL BATTERY</span>
                <span className="font-mono font-bold text-emerald-400 text-sm">{tripSimulation.soc_final_pct}%</span>
              </div>
            </div>
            <p className="text-[10px] text-slate-400 mt-2 italic text-center font-mono">
              Gaussian variance injected. Validates mathematical uncertainty bounds.
            </p>
          </div>
        )}

        {/* Collapsible Segment Energy Breakdown */}
        <div className="mt-4 pt-3.5 border-t border-[#1e2535]">
          <button
            type="button"
            onClick={() => {
              playCockpitClick();
              setShowSegmentDetails(v => !v);
            }}
            className="flex items-center gap-1.5 text-xs font-mono font-medium text-slate-300 hover:text-white transition-colors w-full"
          >
            {showSegmentDetails ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            INSPECT SEGMENT FORCES & TERRAIN BREAKDOWN ({energy.segments.length} SEGMENTS)
          </button>

          {showSegmentDetails && (
            <div className="mt-3">
              <p className="text-[11px] text-slate-400 mb-2">
                Forces breakdown per road segment in kWh (aerodynamics, rolling resistance, uphill gradients, and AC aux load):
              </p>
              <div className="h-44 w-full bg-[#0a0e14] rounded-xl p-2 border border-[#1e2535]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={segmentEnergyData} margin={{ top: 5, right: 10, bottom: 5, left: -20 }}>
                    <XAxis dataKey="name" tick={{ fontSize: 9, fill: '#64748b' }} />
                    <YAxis tick={{ fontSize: 9, fill: '#64748b' }} unit="kWh" />
                    <Tooltip 
                      contentStyle={{ backgroundColor: '#121620', borderColor: '#262f42', borderRadius: '8px', fontSize: '11px' }} 
                      labelStyle={{ color: '#cbd5e1' }}
                    />
                    <Bar dataKey="rolling" name="Rolling Force" stackId="a" fill="#0284c7" />
                    <Bar dataKey="aero" name="Aero Drag" stackId="a" fill="#3b82f6" />
                    <Bar dataKey="gradient" name="Ghats / Elevation" stackId="a" fill="#f97316" />
                    <Bar dataKey="aux" name="AC Auxiliary" stackId="a" fill="#10b981" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </div>

        {/* Model Narrative Explanation */}
        <div className="mt-4 bg-[#0e1219] rounded-xl p-3 border border-[#1e2535]">
          <div className="flex items-center gap-1.5 mb-1 text-orange-400 text-xs font-mono font-bold">
            <CornerDownRight size={13} className="text-orange-400" />
            EXPLAINABILITY & ROUTE STRATEGY ASSESSMENT:
          </div>
          <p className="text-xs text-slate-300 leading-relaxed">
            {selectedRoute.explanation}
          </p>
        </div>
      </div>
    </div>
  );
}
