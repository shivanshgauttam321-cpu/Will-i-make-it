import React, { useState, useEffect } from 'react';
import { 
  Search, X, Navigation, Share2, RefreshCw, Smartphone, 
  Clock, CreditCard, Zap, ShieldCheck, Info, Snowflake, Sun,
  CheckCircle2, AlertTriangle, Play, Pause, ChevronRight,
  Sliders, BatteryCharging, Compass, ExternalLink, Sparkles
} from 'lucide-react';
import RouteMap from './RouteMap';
import type { RoutePlanResponse, VehicleProfile, ChargingStop } from '../types/api';
import { INDIAN_EV_PRESETS } from './TripPlanner';
import { playCockpitClick } from '../utils/audioService';

interface Props {
  routeResult: RoutePlanResponse | null;
  vehicle: VehicleProfile;
  onVehicleChange: (v: VehicleProfile) => void;
  selectedRouteId: string;
  onRouteSelect: (id: string) => void;
  disabledChargers: string[];
  onChargerToggle: (id: string, disabled: boolean) => void;
  onOpenStations: () => void;
  onOpenEnergy: () => void;
  onOpenExplain: () => void;
  onOpenPlanner: () => void;
  onReplan: () => void;
  isLoading: boolean;
  ambientTempC?: number;
  onAmbientTempChange?: (temp: number) => void;
  customOrigin?: { name: string; lat: number; lng: number } | null;
  customDest?: { name: string; lat: number; lng: number } | null;
}

export default function MeitriyaCockpit({
  routeResult,
  vehicle,
  onVehicleChange,
  selectedRouteId,
  onRouteSelect,
  disabledChargers,
  onChargerToggle,
  onOpenStations,
  onOpenEnergy,
  onOpenExplain,
  onOpenPlanner,
  onReplan,
  isLoading,
  ambientTempC = 28,
  onAmbientTempChange,
  customOrigin,
  customDest,
}: Props) {
  const [searchQuery, setSearchQuery] = useState('');
  const [isSimulating, setIsSimulating] = useState(false);
  const [simProgress, setSimProgress] = useState(0);
  const [simSpeed, setSimSpeed] = useState(1);
  const [copiedLink, setCopiedLink] = useState(false);

  // Active route selection (fastest or risk_aware)
  const [routeMode, setRouteMode] = useState<'fastest' | 'risk_aware'>('fastest');
  const activeRoute = routeMode === 'fastest' 
    ? routeResult?.fastest_route 
    : (routeResult?.risk_aware_route ?? routeResult?.fastest_route);

  // Simulation timer
  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    if (isSimulating) {
      interval = setInterval(() => {
        setSimProgress(prev => {
          if (prev >= 100) {
            setIsSimulating(false);
            return 0;
          }
          return prev + 1 * simSpeed;
        });
      }, 200);
    }
    return () => clearInterval(interval);
  }, [isSimulating, simSpeed]);

  const toggleSimulation = () => {
    playCockpitClick();
    if (!isSimulating && simProgress >= 100) {
      setSimProgress(0);
    }
    setIsSimulating(!isSimulating);
  };

  // Google Maps Deep Link generator
  const getGoogleMapsUrl = () => {
    if (!activeRoute) return 'https://maps.google.com';
    const coords = activeRoute.road_geometry;
    if (!coords || coords.length === 0) return 'https://maps.google.com';
    const orig = coords[0];
    const dest = coords[coords.length - 1];
    return `https://www.google.com/maps/dir/?api=1&origin=${orig[0]},${orig[1]}&destination=${dest[0]},${dest[1]}&travelmode=driving`;
  };

  const handleSendToPhone = () => {
    playCockpitClick();
    const url = getGoogleMapsUrl();
    if (navigator.clipboard) {
      navigator.clipboard.writeText(url);
      setCopiedLink(true);
      setTimeout(() => setCopiedLink(false), 2500);
    }
    window.open(url, '_blank', 'noopener,noreferrer');
  };

  // Current vehicle display name
  const currentVehiclePreset = INDIAN_EV_PRESETS.find(
    p => p.profile.battery_capacity_kwh === vehicle.battery_capacity_kwh &&
         p.profile.vehicle_mass_kg === vehicle.vehicle_mass_kg
  ) || INDIAN_EV_PRESETS[0];

  // Route title display
  const routeTitle = customOrigin && customDest && selectedRouteId === 'CUSTOM_ROUTE'
    ? `${customOrigin.name.split(',')[0]} to ${customDest.name.split(',')[0]}`
    : (activeRoute?.label || 'Mumbai to Pune Expressway');

  // Format travel time
  const durationMin = activeRoute?.duration_min ?? 130;
  const hours = Math.floor(durationMin / 60);
  const minutes = Math.round(durationMin % 60);
  const timeFormatted = `${hours > 0 ? `${hours} hr ` : ''}${minutes} min`;

  // Charging stops count
  const chargingStops = activeRoute?.charging_stops ?? [];
  const chargingStopsCount = chargingStops.length;
  const totalChargingTime = chargingStops.reduce((sum, s) => sum + (s.charge_duration_min ?? 0), 0);

  // Energy & Feasibility KPIs
  const isFeasible = activeRoute?.feasible ?? true;
  const p50Kwh = activeRoute?.energy_result?.total_kwh_p50?.toFixed(1) ?? '24.2';
  const p90Kwh = activeRoute?.energy_result?.total_kwh_p90?.toFixed(1) ?? '27.8';
  const arrivalSoc = activeRoute?.energy_result?.soc_final_p90_pct?.toFixed(0) ?? '38';
  const estCostRupees = Math.round((Number(p50Kwh) * 9.5)); // Average Indian commercial EV tariff ₹9.5/kWh

  // Simulated live drive values
  const currentSimSoc = Math.max(
    10, 
    Math.round(vehicle.soc_start_pct - ((vehicle.soc_start_pct - Number(arrivalSoc)) * (simProgress / 100)))
  );
  const currentSimDist = ((activeRoute?.distance_km ?? 148) * (simProgress / 100)).toFixed(1);

  // Corridors list
  const corridors = [
    { id: 'MUMBAI_PUNE', label: 'Mumbai–Pune', dist: '148 km' },
    { id: 'DELHI_JAIPUR', label: 'Delhi–Jaipur', dist: '280 km' },
    { id: 'BLR_MYSURU', label: 'Bengaluru–Mysuru', dist: '145 km' },
    { id: 'CHENNAI_PONDY', label: 'Chennai–Pondy', dist: '152 km' },
  ];

  return (
    <div className="w-full h-full flex flex-col xl:flex-row gap-4 p-3 sm:p-5 overflow-y-auto xl:overflow-hidden select-none bg-[#0a0d14]">
      
      {/* =========================================================================
          COLUMN 1: BRAND, SEARCH, FILTER PILLS & CHARGING HERO CARD
          ========================================================================= */}
      <div className="w-full xl:w-[350px] 2xl:w-[380px] flex flex-col shrink-0 gap-4">
        <div className="bg-[#121620] border border-[#1e2638] rounded-[24px] p-5 flex flex-col gap-4 shadow-xl">
          
          {/* Top Brand Logo: 4 orange tilted squares + Meitriya */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {/* Meitriya Orange Diamond Logo Mark */}
              <div className="grid grid-cols-2 gap-1 w-6 h-6 rotate-45 shrink-0">
                <div className="bg-[#ff5520] rounded-sm"></div>
                <div className="bg-[#ea4310] rounded-sm"></div>
                <div className="bg-[#ea4310] rounded-sm"></div>
                <div className="bg-[#ff5520] rounded-sm"></div>
              </div>
              <div className="flex flex-col">
                <span className="text-white font-bold text-lg tracking-tight font-sans">
                  Meitriya
                </span>
                <span className="text-[10px] text-slate-400 font-mono -mt-1 tracking-wider uppercase">
                  WILL I MAKE IT? · PANDAV
                </span>
              </div>
            </div>

            {/* Quick Trip Planner Modal Opener */}
            <button
              type="button"
              onClick={() => {
                playCockpitClick();
                onOpenPlanner();
              }}
              className="p-2 rounded-xl bg-[#181e2b] hover:bg-[#202738] text-slate-300 hover:text-white border border-[#252f44] transition-all text-xs flex items-center gap-1.5"
              title="Open Full Journey Planner"
            >
              <Sliders size={14} className="text-orange-400" />
              <span className="text-[11px] font-medium hidden sm:inline">Route Params</span>
            </button>
          </div>

          {/* Search Input for model, brand, or corridor */}
          <div className="relative">
            <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder="Search for a model or brand..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-[#181e2b] text-slate-200 placeholder-slate-500 text-xs rounded-xl pl-9 pr-3 py-2.5 border border-[#263146] focus:outline-none focus:border-orange-500/80 transition-all font-sans"
            />
            {searchQuery && (
              <button 
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
              >
                <X size={14} />
              </button>
            )}
          </div>

          {/* Filter Pill Tags (Exact Meitriya Visual Tags) */}
          <div className="flex flex-col gap-2">
            {/* Row 1: Active vehicle tags */}
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="bg-[#ff5520] text-white text-[11px] font-semibold px-2.5 py-1 rounded-lg flex items-center gap-1 shadow-sm shadow-orange-950/40">
                EV <span className="text-[10px] opacity-75">✕</span>
              </span>
              <button
                type="button"
                onClick={() => {
                  playCockpitClick();
                  onOpenPlanner();
                }}
                className="bg-[#ff5520] text-white text-[11px] font-semibold px-2.5 py-1 rounded-lg flex items-center gap-1 shadow-sm shadow-orange-950/40"
              >
                {currentVehiclePreset.shortName} <span className="text-[10px] opacity-75">✕</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  playCockpitClick();
                  onVehicleChange(INDIAN_EV_PRESETS[2].profile);
                }}
                className="bg-[#181e2b] hover:bg-[#222a3d] text-slate-300 text-[11px] font-medium px-2.5 py-1 rounded-lg transition-colors border border-[#242e42]"
              >
                MG ZS EV
              </button>
              <button
                type="button"
                onClick={() => {
                  playCockpitClick();
                  onVehicleChange(INDIAN_EV_PRESETS[3].profile);
                }}
                className="bg-[#181e2b] hover:bg-[#222a3d] text-slate-300 text-[11px] font-medium px-2.5 py-1 rounded-lg transition-colors border border-[#242e42]"
              >
                XUV400
              </button>
            </div>

            {/* Row 2: Route Modes and Corridors */}
            <div className="flex flex-wrap items-center gap-1.5">
              <button
                type="button"
                onClick={() => {
                  playCockpitClick();
                  setRouteMode('fastest');
                }}
                className={`text-[11px] font-medium px-2.5 py-1 rounded-lg transition-all border ${
                  routeMode === 'fastest'
                    ? 'bg-[#1e293b] text-orange-400 border-orange-500/50'
                    : 'bg-[#181e2b] text-slate-400 border-[#242e42] hover:text-slate-200'
                }`}
              >
                Fastest Route
              </button>
              <button
                type="button"
                onClick={() => {
                  playCockpitClick();
                  setRouteMode('risk_aware');
                }}
                className={`text-[11px] font-medium px-2.5 py-1 rounded-lg transition-all border ${
                  routeMode === 'risk_aware'
                    ? 'bg-[#1e293b] text-teal-400 border-teal-500/50'
                    : 'bg-[#181e2b] text-slate-400 border-[#242e42] hover:text-slate-200'
                }`}
              >
                Risk-Aware (P90)
              </button>
              <button
                type="button"
                onClick={() => {
                  playCockpitClick();
                  onRouteSelect('MUMBAI_PUNE');
                }}
                className={`text-[11px] font-medium px-2.5 py-1 rounded-lg transition-all border ${
                  selectedRouteId === 'MUMBAI_PUNE'
                    ? 'bg-[#ff5520]/20 text-orange-300 border-[#ff5520]/50'
                    : 'bg-[#181e2b] text-slate-400 border-[#242e42] hover:text-slate-200'
                }`}
              >
                Mumbai–Pune
              </button>
            </div>

            {/* Row 3: Other Indian corridors */}
            <div className="flex flex-wrap items-center gap-1.5">
              <button
                type="button"
                onClick={() => {
                  playCockpitClick();
                  onRouteSelect('DELHI_JAIPUR');
                }}
                className={`text-[11px] font-medium px-2.5 py-1 rounded-lg transition-all border ${
                  selectedRouteId === 'DELHI_JAIPUR'
                    ? 'bg-[#ff5520]/20 text-orange-300 border-[#ff5520]/50'
                    : 'bg-[#181e2b] text-slate-400 border-[#242e42] hover:text-slate-200'
                }`}
              >
                Delhi–Jaipur
              </button>
              <button
                type="button"
                onClick={() => {
                  playCockpitClick();
                  onRouteSelect('BLR_MYSURU');
                }}
                className={`text-[11px] font-medium px-2.5 py-1 rounded-lg transition-all border ${
                  selectedRouteId === 'BLR_MYSURU'
                    ? 'bg-[#ff5520]/20 text-orange-300 border-[#ff5520]/50'
                    : 'bg-[#181e2b] text-slate-400 border-[#242e42] hover:text-slate-200'
                }`}
              >
                BLR–Mysuru
              </button>
              <button
                type="button"
                onClick={() => {
                  playCockpitClick();
                  onOpenPlanner();
                }}
                className="bg-[#181e2b] hover:bg-[#202738] text-slate-300 text-[11px] font-medium px-2.5 py-1 rounded-lg transition-colors border border-[#242e42] flex items-center gap-1"
              >
                <Compass size={11} className="text-orange-400" />
                Custom...
              </button>
            </div>
          </div>

          {/* Hero Fast Charging Card with Orange Stripes and Plug */}
          <div className="relative mt-2 rounded-2xl overflow-hidden border border-[#242e42] group shadow-inner">
            <img 
              src="/assets/chargers/charging-plug-hero.svg" 
              alt="Fast Charging DC Plug with Bayesian Reliability"
              className="w-full h-auto object-cover transform transition-transform duration-500 group-hover:scale-[1.02]"
            />

            {/* Interactive battery slider overlay at bottom of the card */}
            <div className="absolute bottom-3 left-3 right-3 bg-[#0d111a]/85 backdrop-blur-md border border-[#252e42] rounded-xl p-2.5 flex items-center justify-between gap-2 shadow-lg">
              <div className="flex items-center gap-2 min-w-0">
                <BatteryCharging size={16} className="text-orange-400 shrink-0" />
                <div className="flex flex-col">
                  <span className="text-[10px] text-slate-400 uppercase font-mono">Starting Battery</span>
                  <span className="text-xs font-bold text-white font-mono">{vehicle.soc_start_pct.toFixed(0)}% SoC</span>
                </div>
              </div>
              <input 
                type="range"
                min={20}
                max={100}
                step={5}
                value={vehicle.soc_start_pct}
                onChange={(e) => {
                  const val = parseFloat(e.target.value);
                  onVehicleChange({ ...vehicle, soc_start_pct: val });
                }}
                className="w-24 accent-orange-500 cursor-pointer"
                title="Adjust starting SoC"
              />
            </div>
          </div>
        </div>
      </div>

      {/* =========================================================================
          COLUMN 2: LARGE INTERACTIVE ROUTE MAP & VEHICLE PROFILE CARD
          ========================================================================= */}
      <div className="flex-1 flex flex-col min-w-0 min-h-[550px] xl:min-h-0 gap-4">
        
        {/* Top Card: Interactive Highway Route Map */}
        <div className="flex-1 min-h-[360px] xl:min-h-0 bg-[#121620] border border-[#1e2638] rounded-[24px] overflow-hidden relative shadow-xl">
          <RouteMap
            routeResult={routeResult}
            selectedRouteId={selectedRouteId}
            disabledChargers={disabledChargers}
            onChargerToggle={onChargerToggle}
            customOrigin={customOrigin}
            customDest={customDest}
          />

          {/* Floating Top Info Overlay on Map */}
          <div className="absolute top-3 left-3 z-[1000] pointer-events-none">
            <div className="bg-[#0e1219]/90 backdrop-blur-md border border-[#242e42] rounded-xl px-3 py-1.5 shadow-lg flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-[11px] font-mono text-slate-200">
                OSRM Highway Geometry · {activeRoute?.distance_km?.toFixed(0) ?? 148} km
              </span>
            </div>
          </div>

          {/* Map Loading Overlay */}
          {isLoading && (
            <div className="absolute inset-0 z-[1001] bg-[#0c1017]/70 backdrop-blur-sm flex items-center justify-center">
              <div className="bg-[#121620] border border-orange-500/40 rounded-2xl px-5 py-3 shadow-2xl flex items-center gap-3 text-orange-400 font-mono text-xs">
                <div className="w-4 h-4 border-2 border-orange-400 border-t-transparent rounded-full animate-spin" />
                <span>Computing Aerodynamic Drag & Elevation Forces...</span>
              </div>
            </div>
          )}
        </div>

        {/* Bottom Card: EV Vehicle Profile & Technical Specifications */}
        <div className="h-[230px] sm:h-[240px] xl:h-[250px] bg-[#121620] border border-[#1e2638] rounded-[24px] p-5 flex flex-col justify-between shrink-0 shadow-xl relative overflow-hidden">
          
          {/* Vehicle Title & Selector Header */}
          <div className="flex items-center justify-between z-10">
            <div>
              <h2 className="text-lg font-bold text-white tracking-tight font-sans">
                {currentVehiclePreset.name.split(' ')[0]}
              </h2>
              <p className="text-xs text-slate-400 font-medium">
                {currentVehiclePreset.name.split(' ').slice(1).join(' ')}
              </p>
            </div>

            {/* Quick Vehicle Switcher Dropdown */}
            <select
              value={currentVehiclePreset.name}
              onChange={(e) => {
                playCockpitClick();
                const found = INDIAN_EV_PRESETS.find(p => p.name === e.target.value);
                if (found) onVehicleChange(found.profile);
              }}
              className="bg-[#181e2b] text-slate-200 border border-[#252f44] rounded-xl px-3 py-1.5 text-xs focus:outline-none focus:border-orange-500 font-sans cursor-pointer"
            >
              {INDIAN_EV_PRESETS.map(p => (
                <option key={p.name} value={p.name}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          {/* 3/4 Perspective White Electric SUV Vector */}
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none opacity-95">
            <img 
              src="/assets/vehicles/ev-vehicle.svg" 
              alt="Electric SUV Vehicle Profile" 
              className="max-h-[160px] sm:max-h-[175px] object-contain transform translate-y-1 transition-transform duration-300"
            />
          </div>

          {/* Bottom Spec Pills (Exact Meitriya 3-Box Spec Bar) */}
          <div className="grid grid-cols-3 gap-2.5 z-10 mt-auto pt-2">
            {/* Box 1: Plug Type */}
            <div className="bg-[#181e2b]/90 backdrop-blur-sm border border-[#252f44] rounded-2xl p-2.5 flex flex-col justify-center">
              <span className="text-[10px] text-slate-400 font-medium font-sans">Plug type</span>
              <span className="text-xs sm:text-sm font-bold text-white tracking-tight truncate">
                {vehicle.connector_types?.join(', ') || 'Type, CCS 2'}
              </span>
            </div>

            {/* Box 2: 0 to 80% Fast Charge */}
            <div className="bg-[#181e2b]/90 backdrop-blur-sm border border-[#252f44] rounded-2xl p-2.5 flex flex-col justify-center">
              <span className="text-[10px] text-slate-400 font-medium font-sans">0 to 80%</span>
              <span className="text-xs sm:text-sm font-bold text-white tracking-tight">
                ~35 min
              </span>
            </div>

            {/* Box 3: Battery Capacity */}
            <div className="bg-[#181e2b]/90 backdrop-blur-sm border border-[#252f44] rounded-2xl p-2.5 flex flex-col justify-center">
              <span className="text-[10px] text-slate-400 font-medium font-sans">Battery</span>
              <span className="text-xs sm:text-sm font-bold text-white tracking-tight">
                {vehicle.battery_capacity_kwh.toFixed(1)} kWh
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* =========================================================================
          COLUMN 3: JOURNEY SUMMARY, ACTION BUTTONS, STATS & GOOD TO KNOW
          ========================================================================= */}
      <div className="w-full xl:w-[360px] 2xl:w-[400px] flex flex-col shrink-0 gap-4">
        <div className="bg-[#121620] border border-[#1e2638] rounded-[24px] p-6 flex flex-col gap-5 shadow-xl flex-1 justify-between">
          
          {/* Header & Vehicle Subtitle */}
          <div>
            <h1 className="text-xl font-bold text-white tracking-tight font-sans leading-snug">
              {routeTitle}
            </h1>
            <p className="text-xs text-slate-400 mt-0.5">
              Driving <strong className="text-slate-300 font-medium">{currentVehiclePreset.shortName}</strong> · {vehicle.soc_start_pct}% Battery
            </p>
          </div>

          {/* Top Action Buttons (Side by Side) */}
          <div className="grid grid-cols-2 gap-3">
            {/* Primary Orange Action: Send to phone / Google Maps */}
            <button
              type="button"
              onClick={handleSendToPhone}
              className="bg-[#ff5520] hover:bg-[#ea4310] active:scale-[0.98] text-white rounded-2xl py-3 px-3 flex items-center justify-center gap-2 font-semibold text-xs transition-all shadow-lg shadow-orange-950/50"
              title="Open Google Maps Turn-by-Turn Route Navigation"
            >
              <Smartphone size={16} />
              <span>{copiedLink ? 'Link Copied!' : 'Send to phone'}</span>
            </button>

            {/* Secondary Action: Simulate Drive / Refresh Route */}
            <button
              type="button"
              onClick={toggleSimulation}
              className={`rounded-2xl py-3 px-3 flex items-center justify-center gap-2 font-semibold text-xs transition-all border ${
                isSimulating 
                  ? 'bg-amber-500/20 text-amber-300 border-amber-500/50' 
                  : 'bg-[#181e2b] hover:bg-[#222a3d] text-slate-200 border-[#263146]'
              }`}
            >
              {isSimulating ? <Pause size={15} /> : <Play size={15} />}
              <span>{isSimulating ? 'Pause Drive' : 'Simulate Drive'}</span>
            </button>
          </div>

          {/* Live Simulation Progress Bar (When simulating) */}
          {isSimulating && (
            <div className="bg-[#181e2b] border border-amber-500/30 rounded-2xl p-3 flex flex-col gap-2">
              <div className="flex items-center justify-between text-xs font-mono">
                <span className="text-amber-400 font-bold flex items-center gap-1.5">
                  <Play size={12} className="animate-pulse" /> LIVE TELEMETRY
                </span>
                <span className="text-slate-300">{currentSimDist} / {activeRoute?.distance_km?.toFixed(0)} km</span>
              </div>
              <div className="w-full bg-[#0d111a] rounded-full h-2 overflow-hidden">
                <div 
                  className="bg-amber-400 h-full transition-all duration-200"
                  style={{ width: `${simProgress}%` }}
                />
              </div>
              <div className="flex items-center justify-between text-[11px] text-slate-400 font-mono">
                <span>SoC: <strong className="text-white">{currentSimSoc}%</strong></span>
                <span>Speed: <strong className="text-white">88 km/h</strong></span>
                <button
                  type="button"
                  onClick={() => setSimSpeed(s => s === 1 ? 2 : s === 2 ? 4 : 1)}
                  className="text-amber-400 underline"
                >
                  {simSpeed}x Speed
                </button>
              </div>
            </div>
          )}

          {/* Large Travel Time Display */}
          <div>
            <div className="text-3xl sm:text-4xl font-extrabold text-white tracking-tight font-sans">
              {timeFormatted}
            </div>
            <div className="text-xs text-slate-400 mt-1 flex items-center gap-2 font-medium">
              <span>{activeRoute?.distance_km?.toFixed(0) ?? 148} km</span>
              <span>·</span>
              <span>{chargingStopsCount} charging {chargingStopsCount === 1 ? 'stop' : 'stops'}</span>
              <span>·</span>
              <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                isFeasible ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-rose-500/20 text-rose-400 border border-rose-500/30'
              }`}>
                {isFeasible ? 'Feasible' : 'Critical'}
              </span>
            </div>
          </div>

          {/* Metric KPI List (Clean vertical list with icons) */}
          <div className="flex flex-col gap-3 py-1 border-t border-b border-[#1e2638]">
            {/* KPI 1: Charging time */}
            <div className="flex items-center justify-between text-xs">
              <div className="flex items-center gap-2.5 text-slate-400">
                <Clock size={16} className="text-slate-400" />
                <span>Charging time</span>
              </div>
              <span className="font-semibold text-white">
                {totalChargingTime > 0 ? `${totalChargingTime} min` : '0 min (Direct reach)'}
              </span>
            </div>

            {/* KPI 2: Est. charge costs */}
            <div className="flex items-center justify-between text-xs">
              <div className="flex items-center gap-2.5 text-slate-400">
                <CreditCard size={16} className="text-slate-400" />
                <span>Est. charge costs</span>
              </div>
              <span className="font-semibold text-white">
                ₹ {estCostRupees}
              </span>
            </div>

            {/* KPI 3: Est. consumption */}
            <div className="flex items-center justify-between text-xs">
              <div className="flex items-center gap-2.5 text-slate-400">
                <Zap size={16} className="text-orange-400" />
                <span>Est. consumption</span>
              </div>
              <span className="font-semibold text-white">
                {p50Kwh} kWh <span className="text-slate-500 text-[10px]">(P50)</span>
              </span>
            </div>

            {/* KPI 4: P90 Conservative Reserve */}
            <div className="flex items-center justify-between text-xs">
              <div className="flex items-center gap-2.5 text-slate-400">
                <ShieldCheck size={16} className="text-teal-400" />
                <span>P90 Conservative</span>
              </div>
              <span className="font-semibold text-white">
                {p90Kwh} kWh <span className="text-teal-400 text-[11px]">({arrivalSoc}% SoC)</span>
              </span>
            </div>
          </div>

          {/* "Show stations on range" Pill Button */}
          <button
            type="button"
            onClick={() => {
              playCockpitClick();
              onOpenStations();
            }}
            className="w-full bg-[#231b1c] hover:bg-[#2c2022] active:scale-[0.99] text-orange-200 border border-[#48281e] rounded-2xl py-3 px-4 flex items-center justify-center gap-2.5 transition-all text-xs font-semibold shadow-md group"
          >
            <Compass size={16} className="text-[#ff5520] group-hover:rotate-45 transition-transform" />
            <span>Show stations on range</span>
            <ChevronRight size={14} className="text-orange-400 ml-auto" />
          </button>

          {/* "Good to know" Card (Bottom Right) */}
          <div className="bg-[#161c28] border border-[#242e42] rounded-2xl p-4 flex flex-col gap-2.5">
            <div className="flex items-center gap-1.5 text-slate-400 text-[11px] font-semibold">
              <Info size={13} className="text-slate-400" />
              <span>Good to know</span>
            </div>

            {/* Temperature badge pill */}
            <div className="bg-[#121620] border border-[#252f44] rounded-xl p-2.5 flex items-start gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-sky-500/20 text-sky-400 flex items-center justify-center shrink-0 border border-sky-500/30">
                {ambientTempC < 15 ? <Snowflake size={16} /> : <Sun size={16} />}
              </div>
              <div className="flex flex-col min-w-0">
                <span className="text-xs font-bold text-white">
                  {ambientTempC}°C Moderate
                </span>
                <p className="text-[10px] text-slate-400 leading-tight mt-0.5">
                  Ideal battery chemistry temperature (22°C - 30°C). Minimal thermal management parasitic loss.
                </p>
              </div>
            </div>

            <p className="text-[10px] text-slate-500 leading-tight">
              Range predicted using first-principles physics (aerodynamic drag, rolling resistance, elevation grade) with Bayesian charger uptime.
            </p>
          </div>

        </div>
      </div>

    </div>
  );
}
