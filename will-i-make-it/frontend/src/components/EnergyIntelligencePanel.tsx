import { useState } from 'react';
import { 
  Flame, Layers, Activity, ChevronDown, ChevronRight, Zap, Thermometer, Wind, AlertTriangle
} from 'lucide-react';
import { 
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, 
  ReferenceLine, BarChart, Bar
} from 'recharts';
import type { RoutePlanResponse, RouteOption, VehicleProfile } from '../types/api';

interface Props {
  result: RoutePlanResponse | null;
  vehicle: VehicleProfile;
}

export default function EnergyIntelligencePanel({ result, vehicle }: Props) {
  const [selectedMode, setSelectedMode] = useState<'fastest' | 'risk_aware'>('fastest');
  const [showSegmentDetails, setShowSegmentDetails] = useState(true);

  if (!result) {
    return (
      <div className="bg-[#121620] border border-[#222938] rounded-2xl flex flex-col items-center justify-center h-56 text-center text-slate-500 p-6">
        <Flame size={28} className="mb-2 text-slate-400" />
        <h4 className="text-sm font-mono font-bold text-slate-300 uppercase">NO ACTIVE ROUTE SIMULATION</h4>
        <p className="text-xs text-slate-500 mt-1">Compute a route in the Trip Planner to view full physical energy curves & terrain breakdown.</p>
      </div>
    );
  }

  const selectedRoute: RouteOption = (selectedMode === 'risk_aware' && result.risk_aware_route)
    ? result.risk_aware_route
    : result.fastest_route;

  const energy = selectedRoute.energy_result;
  const p50 = energy.total_kwh_p50;
  const p90 = energy.total_kwh_p90;
  const uncertaintyDelta = p90 - p50;
  const uncertaintyPct = ((uncertaintyDelta / (p50 || 1)) * 100).toFixed(1);

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

  // Energy contributors share percentages
  const n = energy.segments.length || 1;
  const avgRoll = energy.segments.reduce((s, x) => s + x.rolling_kj, 0) / n / 3600;
  const avgAero = energy.segments.reduce((s, x) => s + x.aero_kj, 0) / n / 3600;
  const avgGrad = energy.segments.reduce((s, x) => s + Math.max(0, x.gradient_kj), 0) / n / 3600;
  const avgAux = energy.segments.reduce((s, x) => s + x.aux_kj, 0) / n / 3600;
  const avgRegen = energy.segments.reduce((s, x) => s + Math.abs(x.regen_kj), 0) / n / 3600;
  const totalForces = avgRoll + avgAero + avgGrad + avgAux;

  return (
    <div className="flex flex-col gap-4">
      {/* 1. Header with Mode Selector */}
      <div className="bg-[#121620] border border-[#222938] rounded-2xl p-4 shadow-xl flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Activity size={16} className="text-orange-400" />
          <div>
            <h3 className="text-xs font-bold font-mono tracking-wider text-slate-200 uppercase">
              DETAILED ENERGY INTELLIGENCE
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Trajectory modeling, log-normal uncertainty bounds & road segment forces.
            </p>
          </div>
        </div>

        {/* Mode Switcher */}
        {result.risk_aware_route && (
          <div className="flex bg-[#0e1219] p-0.5 rounded-xl border border-[#222938] text-xs font-mono">
            <button
              type="button"
              onClick={() => setSelectedMode('fastest')}
              className={`px-3 py-1 rounded-lg font-medium transition-all ${
                selectedMode === 'fastest'
                  ? 'bg-orange-500 text-white font-bold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Fastest Path
            </button>
            <button
              type="button"
              onClick={() => setSelectedMode('risk_aware')}
              className={`px-3 py-1 rounded-lg font-medium transition-all ${
                selectedMode === 'risk_aware'
                  ? 'bg-emerald-600 text-white font-bold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Risk-Aware Path
            </button>
          </div>
        )}
      </div>

      {/* 2. Battery SoC Trajectory Profile AreaChart */}
      <div className="bg-[#121620] border border-[#222938] rounded-2xl p-4 shadow-xl">
        <div className="flex items-center justify-between mb-3 border-b border-[#1e2535] pb-2">
          <div className="flex items-center gap-2">
            <Flame size={14} className="text-orange-400" />
            <h4 className="text-xs font-bold font-mono tracking-wider text-slate-200 uppercase">
              BATTERY SOC TRAJECTORY PROFILE (%)
            </h4>
          </div>
          <div className="flex items-center gap-3 text-[10px] text-slate-400 font-mono">
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-full bg-teal-400 inline-block" /> P50 Expected
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 rounded-full bg-orange-400 inline-block" /> P90 Conservative
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-0.5 bg-rose-500 inline-block" /> Reserve ({vehicle.soc_reserve_pct}%)
            </span>
          </div>
        </div>

        <div className="h-52 w-full bg-[#0a0e14] rounded-xl p-2.5 border border-[#1e2535]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={dischargeData} margin={{ top: 10, right: 15, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="energyP50Grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#14b8a6" stopOpacity={0.35}/>
                  <stop offset="95%" stopColor="#14b8a6" stopOpacity={0.0}/>
                </linearGradient>
                <linearGradient id="energyP90Grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#f97316" stopOpacity={0.3}/>
                  <stop offset="95%" stopColor="#f97316" stopOpacity={0.0}/>
                </linearGradient>
              </defs>
              <XAxis dataKey="km" tick={{ fontSize: 10, fill: '#64748b' }} unit="km" />
              <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#64748b' }} unit="%" />
              <Tooltip 
                contentStyle={{ backgroundColor: '#121620', borderColor: '#262f42', borderRadius: '12px', fontSize: '11px', boxShadow: '0 10px 25px rgba(0,0,0,0.8)' }}
                labelStyle={{ color: '#cbd5e1', fontFamily: 'monospace' }}
              />
              <ReferenceLine 
                y={vehicle.soc_reserve_pct} 
                stroke="#f43f5e" 
                strokeDasharray="4 4" 
                label={{ value: 'Min Reserve', fill: '#f43f5e', fontSize: 10, position: 'right' }} 
              />
              <Area 
                type="monotone" 
                dataKey="soc_p50" 
                name="P50 SoC (%)" 
                stroke="#14b8a6" 
                strokeWidth={2.2} 
                fillOpacity={1} 
                fill="url(#energyP50Grad)" 
              />
              <Area 
                type="monotone" 
                dataKey="soc_p90" 
                name="P90 SoC (%)" 
                stroke="#f97316" 
                strokeWidth={1.8} 
                strokeDasharray="3 3" 
                fillOpacity={1} 
                fill="url(#energyP90Grad)" 
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* 3. Uncertainty & Risk Spread Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
        <div className="bg-[#121620] border border-[#222938] rounded-2xl p-3.5 text-center shadow-lg">
          <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 block mb-1">
            EXPECTED VS P90 SPREAD
          </span>
          <span className="text-xl font-black font-mono text-orange-400">
            +{uncertaintyDelta.toFixed(1)} kWh
          </span>
          <span className="text-[10px] text-slate-500 font-mono block mt-0.5">
            (+{uncertaintyPct}% Reserve Buffer)
          </span>
        </div>

        <div className="bg-[#121620] border border-[#222938] rounded-2xl p-3.5 text-center shadow-lg">
          <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 block mb-1">
            CONFIDENCE LEVEL
          </span>
          <span className="text-xl font-black font-mono text-teal-400">
            90% Target
          </span>
          <span className="text-[10px] text-slate-500 font-mono block mt-0.5">
            Log-Normal Analytical Prior
          </span>
        </div>

        <div className="bg-[#121620] border border-[#222938] rounded-2xl p-3.5 text-center shadow-lg">
          <span className="text-[10px] font-mono uppercase tracking-wider text-slate-400 block mb-1">
            REGEN ENERGY RECAPTURED
          </span>
          <span className="text-xl font-black font-mono text-emerald-400">
            ~{avgRegen.toFixed(2)} kWh
          </span>
          <span className="text-[10px] text-slate-500 font-mono block mt-0.5">
            {((avgRegen / Math.max(0.01, totalForces)) * 100).toFixed(0)}% Kinetic Recapture
          </span>
        </div>
      </div>

      {/* 4. Segment Physical Forces Breakdown BarChart */}
      <div className="bg-[#121620] border border-[#222938] rounded-2xl p-4 shadow-xl">
        <div className="flex items-center justify-between mb-3 border-b border-[#1e2535] pb-2">
          <div className="flex items-center gap-2">
            <Layers size={14} className="text-orange-400" />
            <h4 className="text-xs font-bold font-mono tracking-wider text-slate-200 uppercase">
              ROAD SEGMENT FORCES (kWh)
            </h4>
          </div>
          <div className="flex items-center gap-3 text-[10px] font-mono text-slate-400">
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 bg-sky-500 rounded-sm" /> Rolling
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 bg-blue-500 rounded-sm" /> Aero Drag
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 bg-orange-500 rounded-sm" /> Ghats / Gradient
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2.5 h-2.5 bg-emerald-500 rounded-sm" /> AC Auxiliary
            </span>
          </div>
        </div>

        <div className="h-48 w-full bg-[#0a0e14] rounded-xl p-2 border border-[#1e2535]">
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
    </div>
  );
}
