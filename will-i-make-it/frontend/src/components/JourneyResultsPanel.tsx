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
    ? { label: 'LOW RISK', color: 'bg-emerald-50 text-emerald-700 border-emerald-200' }
    : selectedRoute.risk_score < 0.65 
      ? { label: 'MODERATE RISK', color: 'bg-amber-50 text-amber-700 border-amber-200' }
      : { label: 'HIGH RISK', color: 'bg-rose-50 text-rose-700 border-rose-200' };

  const statusKey = selectedRoute.feasibility_status || (selectedRoute.feasible ? 'WILL_MAKE_IT' : 'WILL_NOT_MAKE_IT');
  const statusDisplayMap: Record<string, { title: string; subtext: string; icon: JSX.Element; bg: string; iconBox: string }> = {
    WILL_MAKE_IT: {
      title: 'YES, YOU WILL MAKE IT',
      subtext: `Arrives with +${selectedRoute.feasibility_margin_kwh.toFixed(1)} kWh margin above your ${vehicle.soc_reserve_pct}% reserve.`,
      icon: <CheckCircle size={24} />,
      bg: 'bg-emerald-50 border-emerald-200 text-emerald-950',
      iconBox: 'bg-emerald-100 text-emerald-600 border-emerald-300',
    },
    SIMULATED_WITH_DEMO_INFRASTRUCTURE: {
      title: 'FEASIBLE VIA DEMO INFRASTRUCTURE',
      subtext: `Journey energy is physically feasible using demonstration charging stations (unverified real-world telemetry).`,
      icon: <CheckCircle size={24} />,
      bg: 'bg-amber-50 border-amber-200 text-amber-950',
      iconBox: 'bg-amber-100 text-amber-600 border-amber-300',
    },
    CONDITIONAL_INFRASTRUCTURE_REQUIRED: {
      title: 'CONDITIONAL — CHARGING REQUIRED',
      subtext: `Direct physical trip violates battery reserve. Reaching destination depends on intermediate charging infrastructure.`,
      icon: <AlertTriangle size={24} />,
      bg: 'bg-sky-50 border-sky-200 text-sky-950',
      iconBox: 'bg-sky-100 text-sky-600 border-sky-300',
    },
    LOW_RESERVE: {
      title: 'WILL MAKE IT WITH LOW RESERVE',
      subtext: `Expected arrival is positive, but conservative P90 reserve is narrow (${energy.soc_final_p90_pct.toFixed(0)}%). Consider topping up.`,
      icon: <AlertTriangle size={24} />,
      bg: 'bg-amber-50 border-amber-200 text-amber-950',
      iconBox: 'bg-amber-100 text-amber-600 border-amber-300',
    },
    UNCERTAIN: {
      title: 'FEASIBILITY UNCERTAIN (UNVERIFIED TERRAIN)',
      subtext: `Elevation data unavailable on route segments. Nominal terrain assumed; actual hill climbs may increase consumption.`,
      icon: <AlertTriangle size={24} />,
      bg: 'bg-slate-50 border-slate-200 text-slate-900',
      iconBox: 'bg-slate-100 text-slate-600 border-slate-300',
    },
    WILL_NOT_MAKE_IT: {
      title: 'RANGE CRITICAL — YOU WILL NOT MAKE IT',
      subtext: `Destination reserve violated or battery exhausted before destination. Corridor charging stop required.`,
      icon: <XCircle size={24} />,
      bg: 'bg-rose-50 border-rose-200 text-rose-950',
      iconBox: 'bg-rose-100 text-rose-600 border-rose-300',
    },
    SIMULATION_ERROR: {
      title: 'SIMULATION ERROR',
      subtext: `Authoritative simulation failed to converge on physical state.`,
      icon: <XCircle size={24} />,
      bg: 'bg-rose-50 border-rose-200 text-rose-950',
      iconBox: 'bg-rose-100 text-rose-600 border-rose-300',
    },
  };
  const statusDisplay = statusDisplayMap[statusKey] || {
    title: selectedRoute.feasible ? 'YES, YOU WILL MAKE IT' : 'RANGE CRITICAL — YOU MAY NOT MAKE IT',
    subtext: selectedRoute.feasible ? `Arrives with reserve margin.` : `Insufficient battery energy on corridor.`,
    icon: selectedRoute.feasible ? <CheckCircle size={24} /> : <XCircle size={24} />,
    bg: selectedRoute.feasible ? 'bg-emerald-50 border-emerald-200 text-emerald-950' : 'bg-rose-50 border-rose-200 text-rose-950',
    iconBox: selectedRoute.feasible ? 'bg-emerald-100 text-emerald-600 border-emerald-300' : 'bg-rose-100 text-rose-600 border-rose-300',
  };

  return (
    <div className="flex flex-col gap-4">
      {/* 1. Primary "Will I Make It?" Decision Banner (Highest Visual Priority) */}
      <div className={`p-4 rounded-2xl border transition-all shadow-sm ${statusDisplay.bg}`}>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className={`w-11 h-11 rounded-2xl flex items-center justify-center shrink-0 border ${statusDisplay.iconBox}`}>
              {statusDisplay.icon}
            </div>
            <div>
              <span className="text-[10px] font-mono font-bold tracking-widest uppercase text-[#64748B] block">
                JOURNEY FEASIBILITY DECISION
              </span>
              <h2 className="text-base sm:text-lg font-black tracking-tight font-sans text-[#172033]">
                {statusDisplay.title}
              </h2>
              <p className="text-xs text-[#334155] mt-0.5">
                {statusDisplay.subtext}
              </p>
            </div>
          </div>

          {/* Risk Level Badge */}
          <div className="flex sm:flex-col items-center sm:items-end justify-between gap-1.5 shrink-0 pt-2 sm:pt-0 border-t sm:border-t-0 border-slate-200">
            <span className={`badge-pill text-[10px] font-mono font-bold border ${riskBadge.color}`}>
              {riskBadge.label} ({(selectedRoute.risk_score * 100).toFixed(0)}%)
            </span>
            <span className="text-[10px] font-mono text-[#64748B]">
              Arrival SoC (P90): <strong className="text-[#172033]">{energy.soc_final_p90_pct.toFixed(0)}%</strong>
            </span>
          </div>
        </div>
      </div>

      {/* 2. Route Mode Selector Tabs (Fastest vs Risk-Aware) */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-2 bg-white border border-[#E2E8F0] rounded-2xl p-1.5 shadow-sm">
        <div className="flex gap-1.5 flex-1">
          <button
            type="button"
            onClick={() => {
              playCockpitClick();
              setActiveTab('fastest');
            }}
            className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl text-xs font-mono font-medium transition-all ${
              activeTab === 'fastest'
                ? 'bg-[#F97316] text-white shadow-sm font-bold'
                : 'text-[#64748B] hover:text-[#172033] hover:bg-[#F8FAFC]'
            }`}
          >
            <Compass size={14} className={activeTab === 'fastest' ? 'text-white' : 'text-slate-400'} />
            <span>FASTEST ROUTE</span>
            {result.recommended === result.fastest_route.route_id && (
              <span className={`text-[9px] px-1.5 py-0.5 rounded font-mono ${
                activeTab === 'fastest' ? 'bg-black/20 text-white font-bold' : 'bg-emerald-50 text-emerald-700 border border-emerald-200 font-bold'
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
                  ? 'bg-emerald-600 text-white shadow-sm font-bold'
                  : 'text-[#64748B] hover:text-[#172033] hover:bg-[#F8FAFC]'
              }`}
            >
              <ShieldCheck size={14} className={activeTab === 'risk_aware' ? 'text-white' : 'text-slate-400'} />
              <span>RISK-AWARE ROUTE</span>
              {result.recommended === result.risk_aware_route.route_id && (
                <span className={`text-[9px] px-1.5 py-0.5 rounded font-mono ${
                  activeTab === 'risk_aware' ? 'bg-black/20 text-white font-bold' : 'bg-emerald-50 text-emerald-700 border border-emerald-200 font-bold'
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
          className="bg-[#F8FAFC] hover:bg-white text-[#334155] hover:text-[#172033] border border-[#CBD5E1] text-xs font-mono flex items-center justify-center gap-1.5 py-2 px-3.5 rounded-xl font-semibold transition-all shrink-0 active:scale-95 shadow-sm"
        >
          {isSimulating ? (
            <div className="w-3.5 h-3.5 border-2 border-orange-500 border-t-transparent rounded-full animate-spin" />
          ) : (
            <Play size={13} className="text-[#F97316] fill-[#F97316]" />
          )}
          <span>SIMULATE DRIVE</span>
        </button>
      </div>

      {/* 3. Four Core Journey Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
        <div className="bg-white border border-[#E2E8F0] rounded-2xl p-3 text-center shadow-sm">
          <span className="text-[10px] font-mono uppercase tracking-wider text-[#64748B] block mb-1">TOTAL DISTANCE</span>
          <span className="text-xl font-black font-mono text-[#172033]">{selectedRoute.distance_km}</span>
          <span className="text-xs text-[#64748B] ml-1 font-mono">km</span>
        </div>

        <div className="bg-white border border-[#E2E8F0] rounded-2xl p-3 text-center shadow-sm">
          <span className="text-[10px] font-mono uppercase tracking-wider text-[#64748B] block mb-1">TRAVEL TIME</span>
          <span className="text-xl font-black font-mono text-[#172033]">{Math.round(selectedRoute.duration_min)}</span>
          <span className="text-xs text-[#64748B] ml-1 font-mono">min</span>
        </div>

        <div className="bg-white border border-[#E2E8F0] rounded-2xl p-3 text-center shadow-sm">
          <span className="text-[10px] font-mono uppercase tracking-wider text-[#64748B] block mb-1">P50 EXPECTED</span>
          <span className="text-xl font-black font-mono text-teal-600">{energy.total_kwh_p50.toFixed(1)}</span>
          <span className="text-xs text-teal-600 ml-1 font-mono">kWh</span>
        </div>

        <div className="bg-white border border-[#E2E8F0] rounded-2xl p-3 text-center shadow-sm">
          <span className="text-[10px] font-mono uppercase tracking-wider text-[#64748B] block mb-1">P90 CONSERVATIVE</span>
          <span className="text-xl font-black font-mono text-orange-600">{energy.total_kwh_p90.toFixed(1)}</span>
          <span className="text-xs text-orange-600 ml-1 font-mono">kWh</span>
          <span className="block text-[8px] text-[#64748B] font-mono mt-0.5">MODEL_BASED_P90_ESTIMATE</span>
        </div>
      </div>

      {/* 4. Arrival Battery Estimate Gauges */}
      <div className="bg-white border border-[#E2E8F0] rounded-2xl p-4 shadow-sm">
        <div className="flex justify-between items-center mb-2.5 border-b border-[#F1F4F8] pb-2">
          <div className="flex items-center gap-2">
            <BatteryCharging size={15} className="text-orange-500" />
            <h3 className="text-xs font-bold font-mono tracking-wider text-[#172033] uppercase">
              ARRIVAL BATTERY ESTIMATE
            </h3>
          </div>
          <span className="text-xs font-mono text-[#64748B]">
            Min Safety Reserve: <strong className="text-rose-600">{vehicle.soc_reserve_pct}%</strong>
          </span>
        </div>

        <div className="space-y-3">
          {/* Expected (P50) Arrival State */}
          <div>
            <div className="flex justify-between text-xs mb-1 font-mono">
              <span className="text-[#64748B] text-[11px]">EXPECTED ARRIVAL (P50)</span>
              <span className="font-bold text-teal-700">{energy.soc_final_p50_pct.toFixed(1)}%</span>
            </div>
            <div className="h-2 bg-[#F1F4F8] rounded-full overflow-hidden p-0.5 border border-[#E2E8F0]">
              <div 
                className="h-full rounded-full bg-gradient-to-r from-teal-500 to-cyan-500 transition-all duration-700" 
                style={{ width: `${Math.min(100, Math.max(0, energy.soc_final_p50_pct))}%` }} 
              />
            </div>
          </div>

          {/* Conservative (P90) Arrival State */}
          <div>
            <div className="flex justify-between text-xs mb-1 font-mono">
              <span className="text-[#64748B] text-[11px]">CONSERVATIVE ARRIVAL (P90 WITH BUFFERS)</span>
              <span className="font-bold text-orange-600">{energy.soc_final_p90_pct.toFixed(1)}%</span>
            </div>
            <div className="h-2 bg-[#F1F4F8] rounded-full overflow-hidden p-0.5 border border-[#E2E8F0]">
              <div 
                className="h-full rounded-full bg-gradient-to-r from-orange-500 to-amber-500 transition-all duration-700" 
                style={{ width: `${Math.min(100, Math.max(0, energy.soc_final_p90_pct))}%` }} 
              />
            </div>
          </div>
        </div>
      </div>

      {/* 4.5. Battery Thermal & Derating Intelligence */}
      {selectedRoute.max_battery_temp_c !== undefined && selectedRoute.max_battery_temp_c !== null && (
        <div className="bg-white border border-[#E2E8F0] rounded-2xl p-4 shadow-sm">
          <div className="flex items-center justify-between mb-2.5 border-b border-[#F1F4F8] pb-2">
            <div className="flex items-center gap-2">
              <Thermometer size={15} className="text-orange-500" />
              <h3 className="text-xs font-bold font-mono tracking-wider text-[#172033] uppercase">
                THERMAL DYNAMICS & BTMS
              </h3>
            </div>
            <span className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded ${
              selectedRoute.was_thermally_derated
                ? 'bg-rose-50 text-rose-700 border border-rose-200'
                : 'bg-emerald-50 text-emerald-700 border border-emerald-200'
            }`}>
              {selectedRoute.was_thermally_derated ? '⚠️ DERATING ACTIVE' : '✓ NORMAL TEMPERATURE'}
            </span>
          </div>

          <div className="grid grid-cols-3 gap-2 text-center text-xs">
            <div className="bg-[#F8FAFC] p-2.5 rounded-xl border border-[#E2E8F0]">
              <span className="text-[10px] text-[#64748B] block font-mono">PEAK PACK TEMP</span>
              <span className="font-mono font-bold text-[#172033] text-sm">{selectedRoute.max_battery_temp_c.toFixed(1)}°C</span>
            </div>
            <div className="bg-[#F8FAFC] p-2.5 rounded-xl border border-[#E2E8F0]">
              <span className="text-[10px] text-[#64748B] block font-mono">MIN PACK TEMP</span>
              <span className="font-mono font-bold text-[#475569] text-sm">{selectedRoute.min_battery_temp_c?.toFixed(1) ?? '—'}°C</span>
            </div>
            <div className="bg-[#F8FAFC] p-2.5 rounded-xl border border-[#E2E8F0]">
              <span className="text-[10px] text-[#64748B] block font-mono">BTMS ENERGY</span>
              <span className="font-mono font-bold text-teal-700 text-sm">{selectedRoute.total_btms_energy_kwh?.toFixed(2) ?? '0.00'} kWh</span>
            </div>
          </div>
        </div>
      )}

      {/* 5. Recommended Charging Stops Card */}
      <div className="bg-white border border-[#E2E8F0] rounded-2xl p-4 shadow-sm">
        <div className="flex items-center justify-between mb-3 border-b border-[#F1F4F8] pb-2">
          <div className="flex items-center gap-2">
            <Zap size={15} className="text-orange-500" />
            <h3 className="text-xs font-bold font-mono tracking-wider text-[#172033] uppercase">
              RECOMMENDED CHARGING STOPS ({selectedRoute.charging_stops.length})
            </h3>
          </div>
          <span className="text-[10px] text-[#64748B] font-mono">
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
                      ? 'bg-rose-50 border-rose-200 opacity-75' 
                      : 'bg-[#F8FAFC] border-[#E2E8F0] hover:border-slate-300'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <div className="p-2 rounded-xl bg-orange-50 text-[#F97316] border border-orange-200 shrink-0">
                      <Zap size={16} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2 flex-wrap">
                        <h4 className="text-sm font-bold text-[#172033] font-sans">{stop.charger.name}</h4>
                        <span className="text-[10px] bg-white text-orange-700 border border-[#CBD5E1] px-1.5 py-0.5 rounded font-mono font-bold">
                          {stop.charger.max_power_kw} kW
                        </span>
                        {stop.charger.status === 'VERIFIED_REAL' && (
                          <span className="text-[10px] bg-emerald-50 text-emerald-700 border border-emerald-200 px-1.5 py-0.5 rounded font-mono font-bold">
                            VERIFIED REAL
                          </span>
                        )}
                        {stop.charger.status === 'DEMO_SEED' && (
                          <span className="text-[10px] bg-amber-50 text-amber-700 border border-amber-200 px-1.5 py-0.5 rounded font-mono font-bold">
                            DEMO SEED (UNVERIFIED)
                          </span>
                        )}
                        {(stop.charger.status === 'HYPOTHETICAL' || stop.charger.charger_id.startsWith('CHR_HYPO_')) && (
                          <span className="text-[10px] bg-purple-50 text-purple-700 border border-purple-200 px-1.5 py-0.5 rounded font-mono font-bold">
                            HYPOTHETICAL STOP
                          </span>
                        )}
                        {(!stop.charger.status || stop.charger.status === 'UNKNOWN') && !stop.charger.charger_id.startsWith('CHR_HYPO_') && (
                          <span className="text-[10px] bg-slate-100 text-[#475569] border border-slate-300 px-1.5 py-0.5 rounded font-mono font-bold">
                            UNVERIFIED STATION
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-[#64748B] mt-0.5">
                        {stop.charger.operator} · Arrive {stop.arrive_soc_pct.toFixed(0)}% → Charge to {stop.depart_soc_pct.toFixed(0)}%
                        · Duration: <span className="font-mono text-orange-600 font-bold">{stop.charge_duration_min.toFixed(0)} min</span>
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 shrink-0">
                    <span className="text-xs font-mono font-bold text-emerald-700">
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
                          ? 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100'
                          : 'bg-rose-50 text-rose-700 border-rose-200 hover:bg-rose-100'
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
          <div className="p-4 rounded-xl bg-[#F8FAFC] border border-[#E2E8F0] text-center text-xs text-[#64748B] font-mono">
            No intermediate charging stops required. Direct transit within battery envelope!
          </div>
        )}
      </div>

      {/* 6. Live Simulation Telemetry Box (When Run) */}
      {tripSimulation && (
        <div className="bg-emerald-50 border border-emerald-200 rounded-2xl p-4 shadow-sm">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <CheckCircle size={15} className="text-emerald-600" />
              <span className="text-xs font-mono font-bold text-[#172033] uppercase tracking-wider">
                LIVE DRIVE TELEMETRY (SIMULATED)
              </span>
              <span className="text-[10px] bg-white text-emerald-700 border border-emerald-200 px-2 py-0.5 rounded-full font-mono">
                Trip #{tripSimulation.trip_id}
              </span>
            </div>
            <span className={`text-xs font-mono font-bold px-2 py-0.5 rounded ${
              tripSimulation.within_p90 ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800'
            }`}>
              {tripSimulation.within_p90 ? '✓ INSIDE P90 SAFE ENVELOPE' : '⚠️ EXCEEDED P90'}
            </span>
          </div>

          <div className="grid grid-cols-3 gap-2 text-center text-xs mt-2">
            <div className="bg-white p-2 rounded-xl border border-[#E2E8F0]">
              <span className="text-[10px] text-[#64748B] block font-mono">ACTUAL DRAWN</span>
              <span className="font-mono font-bold text-[#172033] text-sm">{tripSimulation.actual_kwh} kWh</span>
            </div>
            <div className="bg-white p-2 rounded-xl border border-[#E2E8F0]">
              <span className="text-[10px] text-[#64748B] block font-mono">PREDICTED P50</span>
              <span className="font-mono font-bold text-[#475569] text-sm">{tripSimulation.predicted_kwh_p50} kWh</span>
            </div>
            <div className="bg-white p-2 rounded-xl border border-[#E2E8F0]">
              <span className="text-[10px] text-[#64748B] block font-mono">FINAL BATTERY</span>
              <span className="font-mono font-bold text-emerald-700 text-sm">{tripSimulation.soc_final_pct}%</span>
            </div>
          </div>
        </div>
      )}

      {/* 7. Route Strategy Explanation & Link to Deep Energy Intelligence */}
      <div className="bg-white border border-[#E2E8F0] rounded-2xl p-4 shadow-sm flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
        <div className="min-w-0">
          <span className="text-[10px] font-mono font-bold text-orange-600 uppercase tracking-wider block mb-1">
            STRATEGY ASSESSMENT
          </span>
          <p className="text-xs text-[#334155] leading-relaxed font-sans line-clamp-2">
            {selectedRoute.explanation}
          </p>
        </div>

        {onNavigateToEnergy && (
          <button
            type="button"
            onClick={onNavigateToEnergy}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-[#F8FAFC] hover:bg-white border border-[#CBD5E1] text-xs font-mono font-semibold text-[#172033] shrink-0 transition-colors shadow-sm"
          >
            <span>Inspect Energy Curves</span>
            <ChevronRight size={14} className="text-[#F97316]" />
          </button>
        )}
      </div>
    </div>
  );
}
