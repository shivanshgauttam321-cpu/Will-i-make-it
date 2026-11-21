import { useState } from 'react';
import { 
  CheckCircle, XCircle, AlertTriangle, Zap, Clock, Battery, 
  Play, ShieldCheck, Compass, ArrowRight, BatteryCharging, ChevronRight, Thermometer
} from 'lucide-react';
import { simulateTrip } from '../utils/api';
import { playCockpitClick, playChargeZap } from '../utils/audioService';
import type { RoutePlanResponse, RouteOption, VehicleProfile, TripRecord } from '../types/api';

interface Props {
  result: RoutePlanResponse;
  vehicle: VehicleProfile;
  disabledChargers: string[];
  onChargerToggle: (id: string, disabled: boolean) => void;
  selectedRouteId: string;
  onNavigateToEnergy?: () => void;
}

export default function JourneyResultsPanel({
  result,
  vehicle,
  disabledChargers,
  onChargerToggle,
  selectedRouteId,
  onNavigateToEnergy,
}: Props) {
  const [activeTab, setActiveTab] = useState<'fastest' | 'risk_aware'>('fastest');
  const [isSimulating, setIsSimulating] = useState(false);
  const [tripSimulation, setTripSimulation] = useState<TripRecord | null>(null);

  const selectedRoute: RouteOption = (activeTab === 'risk_aware' && result.risk_aware_route)
    ? result.risk_aware_route
    : result.fastest_route;

  const energy = selectedRoute.energy_result;
  const isRecommended = result.recommended === selectedRoute.route_id;

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

  const statusKey = selectedRoute.feasibility_status || (selectedRoute.feasible ? 'WILL_MAKE_IT' : 'WILL_NOT_MAKE_IT');
  const statusDisplayMap: Record<string, { title: string; subtext: string; icon: JSX.Element; bg: string; iconBox: string }> = {
    WILL_MAKE_IT: {
      title: 'YES, YOU WILL MAKE IT',
      subtext: `Arrives with +${selectedRoute.feasibility_margin_kwh.toFixed(1)} kWh margin above your ${vehicle.soc_reserve_pct}% reserve.`,
      icon: <CheckCircle size={24} />,
      bg: 'bg-[#0f1d1a] border-emerald-500/40 text-emerald-100',
      iconBox: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40',
    },
    SIMULATED_WITH_DEMO_INFRASTRUCTURE: {
      title: 'FEASIBLE VIA DEMO INFRASTRUCTURE',
      subtext: `Journey energy is physically feasible using demonstration charging stations (unverified real-world telemetry).`,
      icon: <CheckCircle size={24} />,
      bg: 'bg-[#1a170f] border-amber-500/40 text-amber-100',
      iconBox: 'bg-amber-500/20 text-amber-400 border-amber-500/40',
    },
    CONDITIONAL_INFRASTRUCTURE_REQUIRED: {
      title: 'CONDITIONAL — CHARGING REQUIRED',
      subtext: `Direct physical trip violates battery reserve. Reaching destination depends on intermediate charging infrastructure.`,
      icon: <AlertTriangle size={24} />,
      bg: 'bg-[#181324] border-purple-500/40 text-purple-100',
      iconBox: 'bg-purple-500/20 text-purple-400 border-purple-500/40',
    },
    LOW_RESERVE: {
      title: 'WILL MAKE IT WITH LOW RESERVE',
      subtext: `Expected arrival is positive, but conservative P90 reserve is narrow (${energy.soc_final_p90_pct.toFixed(0)}%). Consider topping up.`,
      icon: <AlertTriangle size={24} />,
      bg: 'bg-[#1e1a0f] border-amber-500/40 text-amber-100',
      iconBox: 'bg-amber-500/20 text-amber-400 border-amber-500/40',
    },
    UNCERTAIN: {
      title: 'FEASIBILITY UNCERTAIN (UNVERIFIED TERRAIN)',
      subtext: `Elevation data unavailable on route segments. Nominal terrain assumed; actual hill climbs may increase consumption.`,
      icon: <AlertTriangle size={24} />,
      bg: 'bg-[#181324] border-purple-500/40 text-purple-100',
      iconBox: 'bg-purple-500/20 text-purple-400 border-purple-500/40',
    },
    WILL_NOT_MAKE_IT: {
      title: 'RANGE CRITICAL — YOU WILL NOT MAKE IT',
      subtext: `Destination reserve violated or battery exhausted before destination. Corridor charging stop required.`,
      icon: <XCircle size={24} />,
      bg: 'bg-[#201014] border-rose-500/40 text-rose-100',
      iconBox: 'bg-rose-500/20 text-rose-400 border-rose-500/40',
    },
    SIMULATION_ERROR: {
      title: 'SIMULATION ERROR',
      subtext: `Authoritative simulation failed to converge on physical state.`,
      icon: <XCircle size={24} />,
      bg: 'bg-[#201014] border-rose-500/40 text-rose-100',
      iconBox: 'bg-rose-500/20 text-rose-400 border-rose-500/40',
    },
  };
  const statusDisplay = statusDisplayMap[statusKey] || {
    title: selectedRoute.feasible ? 'YES, YOU WILL MAKE IT' : 'RANGE CRITICAL — YOU MAY NOT MAKE IT',
    subtext: selectedRoute.feasible ? `Arrives with reserve margin.` : `Insufficient battery energy on corridor.`,
    icon: selectedRoute.feasible ? <CheckCircle size={24} /> : <XCircle size={24} />,
    bg: selectedRoute.feasible ? 'bg-[#0f1d1a] border-emerald-500/40 text-emerald-100' : 'bg-[#201014] border-rose-500/40 text-rose-100',
    iconBox: selectedRoute.feasible ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40' : 'bg-rose-500/20 text-rose-400 border-rose-500/40',
  };

  return (
    <div className="flex flex-col gap-4">
      {/* 1. Primary "Will I Make It?" Decision Banner (Highest Visual Priority) */}
      <div className={`p-4 rounded-2xl border transition-all shadow-xl ${statusDisplay.bg}`}>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className={`w-11 h-11 rounded-2xl flex items-center justify-center shrink-0 ${statusDisplay.iconBox}`}>
              {statusDisplay.icon}
            </div>
            <div>
              <span className="text-[10px] font-mono font-bold tracking-widest uppercase text-slate-400 block">
                JOURNEY FEASIBILITY DECISION
              </span>
              <h2 className="text-base sm:text-lg font-black tracking-tight font-sans">
                {statusDisplay.title}
              </h2>
              <p className="text-xs text-slate-300 mt-0.5">
                {statusDisplay.subtext}
              </p>
            </div>
          </div>

          {/* Risk Level Badge */}
          <div className="flex sm:flex-col items-center sm:items-end justify-between gap-1.5 shrink-0 pt-2 sm:pt-0 border-t sm:border-t-0 border-white/10">
            <span className={`badge-pill text-[10px] font-mono font-bold ${riskBadge.color}`}>
              {riskBadge.label} ({(selectedRoute.risk_score * 100).toFixed(0)}%)
            </span>
            <span className="text-[10px] font-mono text-slate-400">
              Arrival SoC (P90): <strong className="text-white">{energy.soc_final_p90_pct.toFixed(0)}%</strong>
            </span>
          </div>
        </div>
      </div>

      {/* 2. Route Mode Selector Tabs (Fastest vs Risk-Aware) */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-2 bg-[#121620] border border-[#222938] rounded-2xl p-1.5 shadow-xl">
        <div className="flex gap-1.5 flex-1">
          <button
            type="button"
            onClick={() => {
              playCockpitClick();
              setActiveTab('fastest');
            }}
            className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl text-xs font-mono font-medium transition-all ${
              activeTab === 'fastest'
                ? 'bg-orange-500 text-white shadow-md font-bold'
                : 'text-slate-400 hover:text-slate-200 hover:bg-[#181e2b]'
            }`}
          >
            <Compass size={14} className={activeTab === 'fastest' ? 'text-white' : 'text-slate-500'} />
            <span>FASTEST ROUTE</span>
            {result.recommended === result.fastest_route.route_id && (
              <span className={`text-[9px] px-1.5 py-0.2 rounded font-mono ${
                activeTab === 'fastest' ? 'bg-black/30 text-white font-bold' : 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 font-bold'
              }`}>
                RECOMMENDED
              </span>
            )}
          </button>

          {result.risk_aware_route && (
            <button
              type="button"
              onClick={() => {
                playCockpitClick();
                setActiveTab('risk_aware');
              }}
              className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl text-xs font-mono font-medium transition-all ${
                activeTab === 'risk_aware'
                  ? 'bg-emerald-600 text-white shadow-md font-bold'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-[#181e2b]'
              }`}
            >
              <ShieldCheck size={14} className={activeTab === 'risk_aware' ? 'text-white' : 'text-slate-500'} />
              <span>RISK-AWARE ROUTE</span>
              {result.recommended === result.risk_aware_route.route_id && (
                <span className={`text-[9px] px-1.5 py-0.2 rounded font-mono ${
                  activeTab === 'risk_aware' ? 'bg-black/30 text-white font-bold' : 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 font-bold'
                }`}>
                  RECOMMENDED
                </span>
              )}
            </button>
          )}
        </div>

        {/* Live Drive Simulation Button */}
        <button
          type="button"
          onClick={handleSimulateDrive}
          disabled={isSimulating}
          className="bg-[#181e2b] hover:bg-[#202738] text-slate-200 hover:text-white border border-[#262f42] hover:border-slate-500 text-xs font-mono flex items-center justify-center gap-1.5 py-2 px-3.5 rounded-xl font-semibold transition-all shrink-0 active:scale-95"
        >
          {isSimulating ? (
            <div className="w-3.5 h-3.5 border-2 border-orange-400 border-t-transparent rounded-full animate-spin" />
          ) : (
            <Play size={13} className="text-orange-400 fill-orange-400" />
          )}
          <span>SIMULATE DRIVE</span>
        </button>
      </div>

      {/* 3. Four Core Journey Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
        <div className="bg-[#121620] border border-[#222938] rounded-2xl p-3 text-center shadow-lg">
          <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 block mb-1">TOTAL DISTANCE</span>
          <span className="text-xl font-black font-mono text-white">{selectedRoute.distance_km}</span>
          <span className="text-xs text-slate-400 ml-1 font-mono">km</span>
        </div>

        <div className="bg-[#121620] border border-[#222938] rounded-2xl p-3 text-center shadow-lg">
          <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 block mb-1">TRAVEL TIME</span>
          <span className="text-xl font-black font-mono text-white">{Math.round(selectedRoute.duration_min)}</span>
          <span className="text-xs text-slate-400 ml-1 font-mono">min</span>
        </div>

        <div className="bg-[#121620] border border-[#222938] rounded-2xl p-3 text-center shadow-lg">
          <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 block mb-1">P50 EXPECTED</span>
          <span className="text-xl font-black font-mono text-teal-400">{energy.total_kwh_p50.toFixed(1)}</span>
          <span className="text-xs text-teal-400 ml-1 font-mono">kWh</span>
        </div>

        <div className="bg-[#121620] border border-[#222938] rounded-2xl p-3 text-center shadow-lg">
          <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 block mb-1">P90 CONSERVATIVE</span>
          <span className="text-xl font-black font-mono text-orange-400">{energy.total_kwh_p90.toFixed(1)}</span>
          <span className="text-xs text-orange-400 ml-1 font-mono">kWh</span>
          <span className="block text-[8px] text-slate-500 font-mono mt-0.5">MODEL_BASED_P90_ESTIMATE</span>
        </div>
      </div>

      {/* 4. Arrival Battery Estimate Gauges */}
      <div className="bg-[#121620] border border-[#222938] rounded-2xl p-4 shadow-xl">
        <div className="flex justify-between items-center mb-2.5 border-b border-[#1e2535] pb-2">
          <div className="flex items-center gap-2">
            <BatteryCharging size={15} className="text-orange-400" />
            <h3 className="text-xs font-bold font-mono tracking-wider text-slate-200 uppercase">
              ARRIVAL BATTERY ESTIMATE
            </h3>
          </div>
          <span className="text-xs font-mono text-slate-400">
            Min Safety Reserve: <strong className="text-rose-400">{vehicle.soc_reserve_pct}%</strong>
          </span>
        </div>

        <div className="space-y-3">
          {/* Expected (P50) Arrival State */}
          <div>
            <div className="flex justify-between text-xs mb-1 font-mono">
              <span className="text-slate-400 text-[11px]">EXPECTED ARRIVAL (P50)</span>
              <span className="font-bold text-teal-400">{energy.soc_final_p50_pct.toFixed(1)}%</span>
            </div>
            <div className="h-2 bg-[#0e1219] rounded-full overflow-hidden p-0.5 border border-[#1e2535]">
              <div 
                className="h-full rounded-full bg-gradient-to-r from-teal-500 to-cyan-400 transition-all duration-700" 
                style={{ width: `${Math.min(100, Math.max(0, energy.soc_final_p50_pct))}%` }} 
              />
            </div>
          </div>

          {/* Conservative (P90) Arrival State */}
          <div>
            <div className="flex justify-between text-xs mb-1 font-mono">
              <span className="text-slate-400 text-[11px]">CONSERVATIVE ARRIVAL (P90 WITH BUFFERS)</span>
              <span className="font-bold text-orange-400">{energy.soc_final_p90_pct.toFixed(1)}%</span>
            </div>
            <div className="h-2 bg-[#0e1219] rounded-full overflow-hidden p-0.5 border border-[#1e2535]">
              <div 
                className="h-full rounded-full bg-gradient-to-r from-orange-500 to-amber-400 transition-all duration-700" 
                style={{ width: `${Math.min(100, Math.max(0, energy.soc_final_p90_pct))}%` }} 
              />
            </div>
          </div>
        </div>
      </div>

      {/* 4.5. Battery Thermal & Derating Intelligence */}
      {selectedRoute.max_battery_temp_c !== undefined && selectedRoute.max_battery_temp_c !== null && (
        <div className="bg-[#121620] border border-[#222938] rounded-2xl p-4 shadow-xl">
          <div className="flex items-center justify-between mb-2.5 border-b border-[#1e2535] pb-2">
            <div className="flex items-center gap-2">
              <Thermometer size={15} className="text-orange-400" />
              <h3 className="text-xs font-bold font-mono tracking-wider text-slate-200 uppercase">
                THERMAL DYNAMICS & BTMS
              </h3>
            </div>
            <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded ${
              selectedRoute.was_thermally_derated
                ? 'bg-rose-500/20 text-rose-300 border border-rose-500/30'
                : 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
            }`}>
              {selectedRoute.was_thermally_derated ? '⚠️ DERATING ACTIVE' : '✓ NORMAL TEMPERATURE'}
            </span>
          </div>

          <div className="grid grid-cols-3 gap-2 text-center text-xs">
            <div className="bg-[#0e1219] p-2.5 rounded-xl border border-[#1e2535]">
              <span className="text-[10px] text-slate-400 block font-mono">PEAK PACK TEMP</span>
              <span className="font-mono font-bold text-white text-sm">{selectedRoute.max_battery_temp_c.toFixed(1)}°C</span>
            </div>
            <div className="bg-[#0e1219] p-2.5 rounded-xl border border-[#1e2535]">
              <span className="text-[10px] text-slate-400 block font-mono">MIN PACK TEMP</span>
              <span className="font-mono font-bold text-slate-300 text-sm">{selectedRoute.min_battery_temp_c?.toFixed(1) ?? '—'}°C</span>
            </div>
            <div className="bg-[#0e1219] p-2.5 rounded-xl border border-[#1e2535]">
              <span className="text-[10px] text-slate-400 block font-mono">BTMS ENERGY</span>
              <span className="font-mono font-bold text-teal-400 text-sm">{selectedRoute.total_btms_energy_kwh?.toFixed(2) ?? '0.00'} kWh</span>
            </div>
          </div>
        </div>
      )}

      {/* 5. Recommended Charging Stops Card */}
      <div className="bg-[#121620] border border-[#222938] rounded-2xl p-4 shadow-xl">
        <div className="flex items-center justify-between mb-3 border-b border-[#1e2535] pb-2">
          <div className="flex items-center gap-2">
            <Zap size={15} className="text-orange-400" />
            <h3 className="text-xs font-bold font-mono tracking-wider text-slate-200 uppercase">
              RECOMMENDED CHARGING STOPS ({selectedRoute.charging_stops.length})
            </h3>
          </div>
          <span className="text-[10px] text-slate-400 font-mono">
            Click ⚡ to simulate failure & reroute
          </span>
        </div>

        {selectedRoute.charging_stops.length > 0 ? (
          <div className="space-y-2.5">
            {selectedRoute.charging_stops.map((stop, i) => {
              const isDown = disabledChargers.includes(stop.charger.charger_id);
              return (
                <div 
                  key={i}
                  className={`p-3 rounded-xl border transition-all flex flex-col sm:flex-row sm:items-center justify-between gap-3 ${
                    isDown 
                      ? 'bg-rose-950/20 border-rose-800/40 opacity-75' 
                      : 'bg-[#0e1219] border-[#1e2535] hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <div className="p-2 rounded-xl bg-orange-500/10 text-orange-400 border border-orange-500/20 shrink-0">
                      <Zap size={16} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <h4 className="text-sm font-bold text-white font-sans">{stop.charger.name}</h4>
                        <span className="text-[10px] bg-[#181e2b] text-orange-400 border border-[#273244] px-1.5 py-0.5 rounded font-mono font-bold">
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
        ) : (
          <div className="p-4 rounded-xl bg-[#0e1219] border border-[#1e2535] text-center text-xs text-slate-400 font-mono">
            No intermediate charging stops required. Direct transit within battery envelope!
          </div>
        )}
      </div>

      {/* 6. Live Simulation Telemetry Box (When Run) */}
      {tripSimulation && (
        <div className="bg-[#0d1614] border border-emerald-500/30 rounded-2xl p-4 shadow-xl">
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
            <div className="bg-[#121620] p-2 rounded-xl border border-[#1e2535]">
              <span className="text-[10px] text-slate-400 block font-mono">ACTUAL DRAWN</span>
              <span className="font-mono font-bold text-white text-sm">{tripSimulation.actual_kwh} kWh</span>
            </div>
            <div className="bg-[#121620] p-2 rounded-xl border border-[#1e2535]">
              <span className="text-[10px] text-slate-400 block font-mono">PREDICTED P50</span>
              <span className="font-mono font-bold text-slate-300 text-sm">{tripSimulation.predicted_kwh_p50} kWh</span>
            </div>
            <div className="bg-[#121620] p-2 rounded-xl border border-[#1e2535]">
              <span className="text-[10px] text-slate-400 block font-mono">FINAL BATTERY</span>
              <span className="font-mono font-bold text-emerald-400 text-sm">{tripSimulation.soc_final_pct}%</span>
            </div>
          </div>
        </div>
      )}

      {/* 7. Route Strategy Explanation & Link to Deep Energy Intelligence */}
      <div className="bg-[#121620] border border-[#222938] rounded-2xl p-4 shadow-xl flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
        <div className="min-w-0">
          <span className="text-[10px] font-mono font-bold text-orange-400 uppercase tracking-wider block mb-1">
            STRATEGY ASSESSMENT
          </span>
          <p className="text-xs text-slate-300 leading-relaxed font-sans line-clamp-2">
            {selectedRoute.explanation}
          </p>
        </div>

        {onNavigateToEnergy && (
          <button
            type="button"
            onClick={onNavigateToEnergy}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-[#181e2b] hover:bg-[#202738] border border-[#252e3f] text-xs font-mono font-semibold text-slate-200 hover:text-white shrink-0 transition-colors"
          >
            <span>Inspect Energy Curves</span>
            <ChevronRight size={14} className="text-orange-400" />
          </button>
        )}
      </div>
    </div>
  );
}
