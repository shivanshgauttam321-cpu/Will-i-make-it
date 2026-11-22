import { useState, useEffect, useRef } from 'react';
import { 
  Zap, Thermometer, Weight, Wind, Car, 
  RotateCcw, Sliders, ShieldCheck, Sun, CloudRain, Snowflake, Check,
  MapPin, Search, ArrowUpDown, Navigation, Sparkles, BatteryCharging,
  ChevronDown, ChevronUp, Layers, CheckCircle2
} from 'lucide-react';
import { getDemoRoutes, planRoute, geocodePlaces } from '../utils/api';
import { playCockpitClick } from '../utils/audioService';
import type { VehicleProfile, DemoRoute, RoutePlanResponse, PlaceLocation } from '../types/api';

interface Props {
  vehicle: VehicleProfile;
  onVehicleChange: (v: VehicleProfile) => void;
  selectedRouteId: string;
  onRouteSelect: (id: string) => void;
  disabledChargers: string[];
  onResult: (r: RoutePlanResponse) => void;
  onError: (e: string | null) => void;
  onLoading: (l: boolean) => void;
  isLoading: boolean;
  onCustomLocationsChange?: (
    origin: { name: string; lat: number; lng: number } | null,
    dest: { name: string; lat: number; lng: number } | null
  ) => void;
}

// Indian EV Profiles
export const INDIAN_EV_PRESETS: { name: string; shortName: string; tag: string; profile: VehicleProfile }[] = [
  {
    name: 'Tata Nexon.ev Max (LR)',
    shortName: 'Nexon.ev LR',
    tag: '40.5 kWh · India Bestseller',
    profile: {
      battery_capacity_kwh: 40.5,
      soc_start_pct: 85.0,
      soc_reserve_pct: 10.0,
      vehicle_mass_kg: 1400.0,
      drag_coefficient: 0.29,
      frontal_area_m2: 2.25,
      rolling_resistance: 0.011,
      drivetrain_efficiency: 0.89,
      regen_efficiency: 0.68,
      connector_types: ['CCS2', 'Type2_AC'],
      ac_load_kw: 1.5,
      payload_kg: 75.0,
    }
  },
  {
    name: 'Tata Punch.ev (LR)',
    shortName: 'Punch.ev LR',
    tag: '35.0 kWh · City & Highway',
    profile: {
      battery_capacity_kwh: 35.0,
      soc_start_pct: 90.0,
      soc_reserve_pct: 10.0,
      vehicle_mass_kg: 1340.0,
      drag_coefficient: 0.32,
      frontal_area_m2: 2.20,
      rolling_resistance: 0.012,
      drivetrain_efficiency: 0.88,
      regen_efficiency: 0.65,
      connector_types: ['CCS2', 'Type2_AC'],
      ac_load_kw: 1.2,
      payload_kg: 75.0,
    }
  },
  {
    name: 'MG ZS EV',
    shortName: 'MG ZS EV',
    tag: '50.3 kWh · Premium Crossover',
    profile: {
      battery_capacity_kwh: 50.3,
      soc_start_pct: 80.0,
      soc_reserve_pct: 10.0,
      vehicle_mass_kg: 1540.0,
      drag_coefficient: 0.29,
      frontal_area_m2: 2.35,
      rolling_resistance: 0.011,
      drivetrain_efficiency: 0.90,
      regen_efficiency: 0.70,
      connector_types: ['CCS2', 'Type2_AC'],
      ac_load_kw: 1.8,
      payload_kg: 100.0,
    }
  },
  {
    name: 'Mahindra XUV400 EL Pro',
    shortName: 'XUV400 EL',
    tag: '39.4 kWh · Performance EV',
    profile: {
      battery_capacity_kwh: 39.4,
      soc_start_pct: 85.0,
      soc_reserve_pct: 12.0,
      vehicle_mass_kg: 1578.0,
      drag_coefficient: 0.31,
      frontal_area_m2: 2.30,
      rolling_resistance: 0.012,
      drivetrain_efficiency: 0.88,
      regen_efficiency: 0.65,
      connector_types: ['CCS2', 'Type2_AC'],
      ac_load_kw: 1.6,
      payload_kg: 80.0,
    }
  },
  {
    name: 'Hyundai Ioniq 5',
    shortName: 'Ioniq 5',
    tag: '72.6 kWh · Ultra Long-Range',
    profile: {
      battery_capacity_kwh: 72.6,
      soc_start_pct: 75.0,
      soc_reserve_pct: 10.0,
      vehicle_mass_kg: 1910.0,
      drag_coefficient: 0.288,
      frontal_area_m2: 2.45,
      rolling_resistance: 0.010,
      drivetrain_efficiency: 0.92,
      regen_efficiency: 0.75,
      connector_types: ['CCS2', 'Type2_AC'],
      ac_load_kw: 1.5,
      payload_kg: 80.0,
    }
  }
];

// Popular Indian EV Corridors for One-Click Planning
const POPULAR_CORRIDORS = [
  {
    label: 'Delhi → Jaipur',
    dist: '285 km',
    origin: { name: 'Connaught Place, New Delhi', lat: 28.6315, lng: 77.2167 },
    dest: { name: 'Jaipur (Pink City), Rajasthan', lat: 26.9124, lng: 75.7873 },
  },
  {
    label: 'Mumbai → Pune',
    dist: '148 km',
    origin: { name: 'Mumbai / BKC, Maharashtra', lat: 19.0657, lng: 72.8687 },
    dest: { name: 'Pune / Kharadi, Maharashtra', lat: 18.5512, lng: 73.9478 },
  },
  {
    label: 'Bengaluru → Chennai',
    dist: '346 km',
    origin: { name: 'Indiranagar, Bengaluru', lat: 12.9784, lng: 77.6408 },
    dest: { name: 'Chennai / OMR, Tamil Nadu', lat: 12.9940, lng: 80.2490 },
  },
  {
    label: 'Mumbai → Goa',
    dist: '550 km',
    origin: { name: 'Mumbai / Nariman Point', lat: 18.9256, lng: 72.8242 },
    dest: { name: 'Panaji, Goa', lat: 15.4909, lng: 73.8278 },
  },
  {
    label: 'Delhi → Agra',
    dist: '210 km',
    origin: { name: 'Noida Sector 62, NCR', lat: 28.6280, lng: 77.3649 },
    dest: { name: 'Agra / Taj Mahal, UP', lat: 27.1767, lng: 78.0081 },
  },
  {
    label: 'Chandigarh → Delhi',
    dist: '245 km',
    origin: { name: 'Chandigarh Sector 17', lat: 30.7333, lng: 76.7794 },
    dest: { name: 'Connaught Place, New Delhi', lat: 28.6315, lng: 77.2167 },
  },
];

export default function TripPlanner({
  vehicle, onVehicleChange, selectedRouteId, onRouteSelect,
  disabledChargers, onResult, onError, onLoading, isLoading,
  onCustomLocationsChange
}: Props) {
  const [demoRoutes, setDemoRoutes] = useState<DemoRoute[]>([]);
  const [routeMode, setRouteMode] = useState<'custom' | 'preset'>('custom');
  
  // Custom Origin & Destination State
  const [originText, setOriginText] = useState('Connaught Place, New Delhi');
  const [destText, setDestText] = useState('Jaipur (Pink City), Rajasthan');
  const [originLocation, setOriginLocation] = useState<PlaceLocation>({
    name: 'Connaught Place, New Delhi',
    lat: 28.6315,
    lng: 77.2167,
    type: 'City Center'
  });
  const [destLocation, setDestLocation] = useState<PlaceLocation>({
    name: 'Jaipur (Pink City), Rajasthan',
    lat: 26.9124,
    lng: 75.7873,
    type: 'Heritage City'
  });

  const [originSuggestions, setOriginSuggestions] = useState<PlaceLocation[]>([]);
  const [destSuggestions, setDestSuggestions] = useState<PlaceLocation[]>([]);
  const [showOriginMenu, setShowOriginMenu] = useState(false);
  const [showDestMenu, setShowDestMenu] = useState(false);

  const [ambientTemp, setAmbientTemp] = useState(28);
  const [confidence, setConfidence] = useState(0.90);
  const [selectedPresetName, setSelectedPresetName] = useState('Tata Nexon.ev Max (LR)');
  const [showAdvanced, setShowAdvanced] = useState(false);

  const originDebounceRef = useRef<number | null>(null);
  const destDebounceRef = useRef<number | null>(null);

  useEffect(() => {
    getDemoRoutes()
      .then(r => setDemoRoutes(r.routes))
      .catch(() => {});
  }, []);

  // Inform map when custom locations change
  useEffect(() => {
    if (routeMode === 'custom' && onCustomLocationsChange) {
      onCustomLocationsChange(originLocation, destLocation);
    }
  }, [routeMode, originLocation, destLocation, onCustomLocationsChange]);

  // Autocomplete search for Origin
  const handleOriginChange = (text: string) => {
    setOriginText(text);
    setShowOriginMenu(true);

    if (originDebounceRef.current) clearTimeout(originDebounceRef.current);
    originDebounceRef.current = window.setTimeout(() => {
      geocodePlaces(text)
        .then(res => setOriginSuggestions(res.results))
        .catch(() => {});
    }, 250);
  };

  // Autocomplete search for Destination
  const handleDestChange = (text: string) => {
    setDestText(text);
    setShowDestMenu(true);

    if (destDebounceRef.current) clearTimeout(destDebounceRef.current);
    destDebounceRef.current = window.setTimeout(() => {
      geocodePlaces(text)
        .then(res => setDestSuggestions(res.results))
        .catch(() => {});
    }, 250);
  };

  // Swap locations button
  const handleSwapLocations = () => {
    playCockpitClick();
    const tempText = originText;
    const tempLoc = originLocation;
    setOriginText(destText);
    setOriginLocation(destLocation);
    setDestText(tempText);
    setDestLocation(tempLoc);
  };

  // Quick select an Indian Corridor
  const selectQuickCorridor = (c: typeof POPULAR_CORRIDORS[0]) => {
    playCockpitClick();
    setOriginText(c.origin.name);
    setOriginLocation({ ...c.origin, type: 'Metro Hub' });
    setDestText(c.dest.name);
    setDestLocation({ ...c.dest, type: 'Destination Hub' });
    setRouteMode('custom');
  };

  const selectPreset = (name: string) => {
    playCockpitClick();
    const preset = INDIAN_EV_PRESETS.find(p => p.name === name);
    if (!preset) return;
    setSelectedPresetName(name);
    onVehicleChange({
      ...preset.profile,
      soc_start_pct: vehicle.soc_start_pct,
      soc_reserve_pct: vehicle.soc_reserve_pct,
      ac_load_kw: vehicle.ac_load_kw,
    });
  };

  const updateVehicle = (field: keyof VehicleProfile, val: unknown) => {
    onVehicleChange({ ...vehicle, [field]: val });
  };

  const applyWeatherPreset = (temp: number, acKw: number) => {
    playCockpitClick();
    setAmbientTemp(temp);
    updateVehicle('ac_load_kw', acKw);
  };

  const handlePlan = async () => {
    playCockpitClick();
    onLoading(true);
    onError(null);

    try {
      if (routeMode === 'custom') {
        const res = await planRoute({
          origin_lat: originLocation.lat,
          origin_lng: originLocation.lng,
          dest_lat: destLocation.lat,
          dest_lng: destLocation.lng,
          origin_name: originLocation.name,
          dest_name: destLocation.name,
          vehicle,
          ambient_temp_c: ambientTemp,
          confidence_target: confidence,
          demo_route_id: undefined,
          disabled_charger_ids: disabledChargers,
        });
        onRouteSelect('CUSTOM_ROUTE');
        onResult(res);
      } else {
        const activePreset = demoRoutes.find(r => r.route_id === selectedRouteId) ?? demoRoutes[0];
        const res = await planRoute({
          origin_lat: activePreset ? activePreset.origin.lat : 19.076,
          origin_lng: activePreset ? activePreset.origin.lng : 72.8777,
          dest_lat: activePreset ? activePreset.destination.lat : 18.5204,
          dest_lng: activePreset ? activePreset.destination.lng : 73.8567,
          vehicle,
          ambient_temp_c: ambientTemp,
          confidence_target: confidence,
          demo_route_id: selectedRouteId,
          disabled_charger_ids: disabledChargers,
        });
        onResult(res);
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } }; message?: string })
        ?.response?.data?.detail ?? (err as Error)?.message ?? 'Route calculation failed';
      onError(msg);
    } finally {
      onLoading(false);
    }
  };

  const activeRoute = demoRoutes.find(r => r.route_id === selectedRouteId);
  const currentVehiclePreset = INDIAN_EV_PRESETS.find(p => p.name === selectedPresetName) ?? INDIAN_EV_PRESETS[0];

  return (
    <div className="flex flex-col gap-4">
      {/* 1. Journey Corridor Card */}
      <div className="bg-white border border-[#E2E8F0] rounded-2xl p-4 shadow-sm">
        <div className="flex items-center justify-between mb-3 border-b border-[#F1F4F8] pb-2.5">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#F97316]" />
            <h3 className="text-xs font-bold font-mono tracking-wider text-[#172033] uppercase">
              JOURNEY CONFIGURATION
            </h3>
          </div>
          
          {/* Mode Switcher */}
          <div className="flex bg-[#F1F4F8] p-0.5 rounded-xl border border-[#E2E8F0] text-xs">
            <button
              type="button"
              onClick={() => {
                playCockpitClick();
                setRouteMode('custom');
              }}
              className={`px-3 py-1 rounded-lg font-medium transition-all ${
                routeMode === 'custom'
                  ? 'bg-white text-[#172033] shadow-sm font-semibold'
                  : 'text-[#64748B] hover:text-[#172033]'
              }`}
            >
              Custom Route
            </button>
            <button
              type="button"
              onClick={() => {
                playCockpitClick();
                setRouteMode('preset');
                if (onCustomLocationsChange) onCustomLocationsChange(null, null);
              }}
              className={`px-3 py-1 rounded-lg font-medium transition-all ${
                routeMode === 'preset'
                  ? 'bg-white text-[#172033] shadow-sm font-semibold'
                  : 'text-[#64748B] hover:text-[#172033]'
              }`}
            >
              Preset Corridors
            </button>
          </div>
        </div>

        {routeMode === 'custom' ? (
          <div className="space-y-3">
            {/* Start Origin Input */}
            <div className="relative">
              <label className="text-[11px] font-mono font-medium text-[#64748B] flex items-center gap-1.5 mb-1.5">
                <span className="w-4 h-4 rounded-full bg-sky-500 text-white text-[10px] font-black flex items-center justify-center">A</span>
                START ORIGIN
              </label>
              <div className="relative">
                <input
                  type="text"
                  value={originText}
                  onChange={e => handleOriginChange(e.target.value)}
                  onFocus={() => {
                    if (originSuggestions.length === 0) {
                      geocodePlaces(originText).then(r => setOriginSuggestions(r.results)).catch(() => {});
                    }
                    setShowOriginMenu(true);
                  }}
                  placeholder="e.g. Connaught Place, New Delhi or Mumbai BKC"
                  className="w-full bg-[#F8FAFC] border border-[#CBD5E1] rounded-xl pl-9 pr-3 py-2.5 text-xs text-[#172033] placeholder-slate-400 focus:bg-white focus:outline-none focus:border-orange-500 font-medium transition-colors"
                />
                <Search size={14} className="absolute left-3 top-3 text-slate-400 pointer-events-none" />
              </div>

              {/* Origin Autocomplete Suggestions */}
              {showOriginMenu && originSuggestions.length > 0 && (
                <div className="absolute left-0 right-0 top-full mt-1 bg-white border border-[#E2E8F0] rounded-xl shadow-xl py-1 z-50 max-h-48 overflow-y-auto">
                  {originSuggestions.map((item, idx) => (
                    <button
                      key={idx}
                      type="button"
                      onClick={() => {
                        playCockpitClick();
                        setOriginLocation(item);
                        setOriginText(item.name);
                        setShowOriginMenu(false);
                      }}
                      className="w-full text-left px-3 py-2 text-xs text-[#172033] hover:bg-[#F8FAFC] flex items-center justify-between border-b border-[#F1F4F8] last:border-0"
                    >
                      <div className="truncate pr-2">
                        <span className="font-medium block truncate text-[#172033]">{item.name}</span>
                        {item.type && <span className="text-[10px] text-sky-600 font-mono">{item.type}</span>}
                      </div>
                      <span className="text-[10px] text-slate-400 font-mono shrink-0">
                        {item.lat.toFixed(2)}, {item.lng.toFixed(2)}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Swap Button */}
            <div className="flex justify-center -my-1">
              <button
                type="button"
                onClick={handleSwapLocations}
                title="Swap Origin and Destination"
                className="p-1.5 rounded-full bg-[#F1F4F8] hover:bg-[#E2E8F0] border border-[#CBD5E1] text-[#475569] hover:text-orange-600 transition-all shadow-sm active:scale-95"
              >
                <ArrowUpDown size={13} />
              </button>
            </div>

            {/* Destination Input */}
            <div className="relative">
              <label className="text-[11px] font-mono font-medium text-[#64748B] flex items-center gap-1.5 mb-1.5">
                <span className="w-4 h-4 rounded-full bg-[#F97316] text-white text-[10px] font-black flex items-center justify-center">B</span>
                DESTINATION
              </label>
              <div className="relative">
                <input
                  type="text"
                  value={destText}
                  onChange={e => handleDestChange(e.target.value)}
                  onFocus={() => {
                    if (destSuggestions.length === 0) {
                      geocodePlaces(destText).then(r => setDestSuggestions(r.results)).catch(() => {});
                    }
                    setShowDestMenu(true);
                  }}
                  placeholder="e.g. Jaipur, Agra, Goa, Pune, Chennai..."
                  className="w-full bg-[#F8FAFC] border border-[#CBD5E1] rounded-xl pl-9 pr-3 py-2.5 text-xs text-[#172033] placeholder-slate-400 focus:bg-white focus:outline-none focus:border-orange-500 font-medium transition-colors"
                />
                <MapPin size={14} className="absolute left-3 top-3 text-[#F97316] pointer-events-none" />
              </div>

              {/* Destination Autocomplete Suggestions */}
              {showDestMenu && destSuggestions.length > 0 && (
                <div className="absolute left-0 right-0 top-full mt-1 bg-white border border-[#E2E8F0] rounded-xl shadow-xl py-1 z-50 max-h-48 overflow-y-auto">
                  {destSuggestions.map((item, idx) => (
                    <button
                      key={idx}
                      type="button"
                      onClick={() => {
                        playCockpitClick();
                        setDestLocation(item);
                        setDestText(item.name);
                        setShowDestMenu(false);
                      }}
                      className="w-full text-left px-3 py-2 text-xs text-[#172033] hover:bg-[#F8FAFC] flex items-center justify-between border-b border-[#F1F4F8] last:border-0"
                    >
                      <div className="truncate pr-2">
                        <span className="font-medium block truncate text-[#172033]">{item.name}</span>
                        {item.type && <span className="text-[10px] text-orange-600 font-mono">{item.type}</span>}
                      </div>
                      <span className="text-[10px] text-slate-400 font-mono shrink-0">
                        {item.lat.toFixed(2)}, {item.lng.toFixed(2)}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Quick One-Click Indian Corridors Pills */}
            <div className="pt-1.5">
              <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-[#64748B] block mb-1.5">
                POPULAR QUICK CORRIDORS:
              </span>
              <div className="flex flex-wrap gap-1.5">
                {POPULAR_CORRIDORS.map(c => (
                  <button
                    key={c.label}
                    type="button"
                    onClick={() => selectQuickCorridor(c)}
                    className="text-[11px] font-sans px-2.5 py-1 rounded-lg bg-[#F8FAFC] hover:bg-white text-[#334155] hover:text-[#172033] border border-[#E2E8F0] hover:border-orange-400 shadow-sm transition-all flex items-center gap-1.5"
                  >
                    <span>{c.label}</span>
                    <span className="text-[10px] text-[#F97316] font-mono font-semibold">{c.dist}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div>
            <select
              value={selectedRouteId}
              onChange={e => {
                playCockpitClick();
                onRouteSelect(e.target.value);
              }}
              className="w-full bg-[#F8FAFC] border border-[#CBD5E1] rounded-xl px-3.5 py-2.5 text-xs text-[#172033] font-medium focus:bg-white focus:outline-none focus:border-orange-500 transition-colors cursor-pointer"
            >
              {demoRoutes.length === 0 && <option value="MUMBAI_PUNE">Loading routes...</option>}
              {demoRoutes.map(r => (
                <option key={r.route_id} value={r.route_id}>{r.label}</option>
              ))}
            </select>
            {activeRoute && (
              <p className="text-xs text-[#64748B] mt-2 leading-relaxed">
                {activeRoute.description}
              </p>
            )}
          </div>
        )}
      </div>

      {/* 2. Vehicle Hardware Profile Card */}
      <div className="bg-white border border-[#E2E8F0] rounded-2xl p-4 shadow-sm">
        <div className="flex items-center justify-between mb-3 border-b border-[#F1F4F8] pb-2.5">
          <div className="flex items-center gap-2">
            <Car size={15} className="text-orange-500" />
            <h3 className="text-xs font-bold font-mono tracking-wider text-[#172033] uppercase">
              VEHICLE HARDWARE PROFILE
            </h3>
          </div>
          <span className="text-xs text-orange-600 font-mono font-bold">
            {vehicle.battery_capacity_kwh} kWh Pack
          </span>
        </div>

        {/* Selected Vehicle Visual Card */}
        <div className="bg-[#F8FAFC] border border-[#E2E8F0] rounded-xl p-3 mb-3 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <span className="text-[10px] text-[#64748B] font-mono uppercase tracking-wider block">CURRENT MODEL</span>
            <h4 className="text-sm font-bold text-[#172033] truncate">{currentVehiclePreset.name}</h4>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-[10px] bg-orange-50 text-orange-700 border border-orange-200 px-1.5 py-0.5 rounded font-mono font-medium">
                {vehicle.connector_types.join(', ')}
              </span>
              <span className="text-[10px] text-[#64748B] font-mono">
                0-80% ~35 min DC
              </span>
            </div>
          </div>
          <img 
            src="/assets/vehicles/ev-vehicle.svg" 
            alt="EV Vehicle Silhouette" 
            className="w-20 h-10 object-contain shrink-0" 
          />
        </div>

        {/* Vehicle Preset Selector (Compact Dropdown / Pills) */}
        <div className="mb-3">
          <label className="text-[10px] text-[#64748B] block mb-1.5 font-mono uppercase">SWITCH EV MODEL</label>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
            {INDIAN_EV_PRESETS.map(p => {
              const isSelected = selectedPresetName === p.name;
              return (
                <button
                  key={p.name}
                  type="button"
                  onClick={() => selectPreset(p.name)}
                  className={`text-left px-2 py-1.5 rounded-xl text-xs transition-all border ${
                    isSelected 
                      ? 'bg-orange-50 border-orange-400 text-[#172033] font-bold shadow-sm' 
                      : 'bg-[#F8FAFC] border-[#E2E8F0] text-[#475569] hover:bg-white hover:border-slate-300'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="truncate">{p.shortName}</span>
                    {isSelected && <Check size={12} className="text-[#F97316] shrink-0" />}
                  </div>
                  <span className="text-[10px] text-[#64748B] truncate block mt-0.5 font-mono">
                    {p.profile.battery_capacity_kwh} kWh
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Battery Capacity & Reserve Inputs */}
        <div className="grid grid-cols-2 gap-2 pt-2 border-t border-[#F1F4F8]">
          <div className="bg-[#F8FAFC] rounded-xl p-2.5 border border-[#E2E8F0]">
            <label className="text-[10px] text-[#64748B] block mb-1 font-mono uppercase">BATTERY (kWh)</label>
            <input
              type="number" min={15} max={120} step={0.5}
              value={vehicle.battery_capacity_kwh}
              onChange={e => updateVehicle('battery_capacity_kwh', parseFloat(e.target.value) || 40)}
              className="w-full bg-white border border-[#CBD5E1] rounded-lg px-2.5 py-1 text-xs font-mono text-[#172033] focus:outline-none focus:border-orange-500"
            />
          </div>
          <div className="bg-[#F8FAFC] rounded-xl p-2.5 border border-[#E2E8F0]">
            <label className="text-[10px] text-[#64748B] block mb-1 font-mono uppercase">MIN RESERVE (%)</label>
            <input
              type="number" min={5} max={25} step={1}
              value={vehicle.soc_reserve_pct}
              onChange={e => updateVehicle('soc_reserve_pct', parseFloat(e.target.value) || 10)}
              className="w-full bg-white border border-[#CBD5E1] rounded-lg px-2.5 py-1 text-xs font-mono text-[#172033] focus:outline-none focus:border-orange-500"
            />
          </div>
        </div>
      </div>

      {/* 3. Starting State of Charge (SoC) Slider */}
      <div className="bg-white border border-[#E2E8F0] rounded-2xl p-4 shadow-sm">
        <div className="flex items-center justify-between mb-2">
          <label className="text-xs font-mono font-bold tracking-wider text-[#172033] flex items-center gap-1.5 uppercase">
            <BatteryCharging size={15} className="text-orange-500" />
            STARTING STATE OF CHARGE (SOC)
          </label>
          <span className="text-2xl font-black font-mono tracking-tight text-[#F97316]">
            {vehicle.soc_start_pct}%
          </span>
        </div>

        <div className="space-y-2">
          <input
            type="range" min={15} max={100} step={1}
            value={vehicle.soc_start_pct}
            onChange={e => updateVehicle('soc_start_pct', parseFloat(e.target.value))}
            className="w-full cursor-pointer h-2 bg-[#F1F4F8] rounded-lg accent-[#F97316]"
          />
          <div className="flex justify-between text-[10px] text-[#64748B] font-mono">
            <span>15% (Critical)</span>
            <span>50% (Nominal)</span>
            <span>80% (Daily)</span>
            <span>100% (Full)</span>
          </div>
        </div>
      </div>

      {/* 4. Ambient Climate & Cabin Thermal Management */}
      <div className="bg-white border border-[#E2E8F0] rounded-2xl p-4 shadow-sm">
        <div className="flex items-center justify-between mb-2.5 border-b border-[#F1F4F8] pb-2">
          <div className="flex items-center gap-1.5">
            <Thermometer size={15} className="text-orange-500" />
            <h3 className="text-xs font-bold font-mono tracking-wider text-[#172033] uppercase">
              CABIN CLIMATE & THERMAL
            </h3>
          </div>
          <span className="text-xs font-mono text-orange-600 font-bold">{ambientTemp}°C</span>
        </div>

        {/* Quick Weather Presets */}
        <div className="grid grid-cols-3 gap-1.5 mb-3">
          <button
            type="button"
            onClick={() => applyWeatherPreset(42, 2.5)}
            className={`p-2 rounded-xl border text-left transition-all ${
              ambientTemp === 42
                ? 'bg-orange-50 border-orange-400 text-orange-950 font-semibold shadow-sm'
                : 'bg-[#F8FAFC] border-[#E2E8F0] text-[#475569] hover:bg-white hover:border-slate-300'
            }`}
          >
            <div className="flex items-center gap-1 text-[11px] font-bold text-orange-600 font-mono">
              <Sun size={12} />
              SUMMER
            </div>
            <span className="text-[10px] text-[#64748B] font-mono block mt-0.5">42°C · 2.5 kW</span>
          </button>
          
          <button
            type="button"
            onClick={() => applyWeatherPreset(28, 1.2)}
            className={`p-2 rounded-xl border text-left transition-all ${
              ambientTemp === 28
                ? 'bg-emerald-50 border-emerald-400 text-emerald-950 font-semibold shadow-sm'
                : 'bg-[#F8FAFC] border-[#E2E8F0] text-[#475569] hover:bg-white hover:border-slate-300'
            }`}
          >
            <div className="flex items-center gap-1 text-[11px] font-bold text-emerald-600 font-mono">
              <CloudRain size={12} />
              MODERATE
            </div>
            <span className="text-[10px] text-[#64748B] font-mono block mt-0.5">28°C · 1.2 kW</span>
          </button>
          
          <button
            type="button"
            onClick={() => applyWeatherPreset(8, 2.0)}
            className={`p-2 rounded-xl border text-left transition-all ${
              ambientTemp === 8
                ? 'bg-sky-50 border-sky-400 text-sky-950 font-semibold shadow-sm'
                : 'bg-[#F8FAFC] border-[#E2E8F0] text-[#475569] hover:bg-white hover:border-slate-300'
            }`}
          >
            <div className="flex items-center gap-1 text-[11px] font-bold text-sky-600 font-mono">
              <Snowflake size={12} />
              WINTER
            </div>
            <span className="text-[10px] text-[#64748B] font-mono block mt-0.5">8°C · 2.0 kW</span>
          </button>
        </div>

        {/* Sliders for Temp and AC Load */}
        <div className="space-y-3">
          <div>
            <div className="flex justify-between text-[11px] text-[#334155] mb-1 font-mono">
              <span className="text-[#64748B]">Ambient Temperature</span>
              <span className="font-bold text-[#172033]">{ambientTemp}°C</span>
            </div>
            <input
              type="range" min={0} max={48} step={1}
              value={ambientTemp}
              onChange={e => setAmbientTemp(parseInt(e.target.value))}
              className="w-full cursor-pointer h-1.5 bg-[#F1F4F8] rounded-lg accent-[#F97316]"
            />
          </div>

          <div>
            <div className="flex justify-between text-[11px] text-[#334155] mb-1 font-mono">
              <span className="text-[#64748B]">Cabin HVAC Power (AC / Heating)</span>
              <span className="font-bold text-[#172033]">{vehicle.ac_load_kw.toFixed(1)} kW</span>
            </div>
            <input
              type="range" min={0} max={3.5} step={0.1}
              value={vehicle.ac_load_kw}
              onChange={e => updateVehicle('ac_load_kw', parseFloat(e.target.value))}
              className="w-full cursor-pointer h-1.5 bg-[#F1F4F8] rounded-lg accent-[#F97316]"
            />
          </div>
        </div>
      </div>

      {/* 5. Collapsible Advanced Physics & Confidence Target */}
      <div className="bg-white border border-[#E2E8F0] rounded-2xl p-3.5 shadow-sm">
        <button
          type="button"
          onClick={() => {
            playCockpitClick();
            setShowAdvanced(!showAdvanced);
          }}
          className="flex items-center justify-between w-full text-xs font-mono font-medium text-[#334155] hover:text-[#172033]"
        >
          <span className="flex items-center gap-1.5 font-semibold">
            <Sliders size={13} className="text-orange-500" />
            PAYLOAD, CONFIDENCE & PHYSICAL CONSTANTS
          </span>
          <span className="text-[10px] text-[#64748B] font-mono">{showAdvanced ? '▲ COLLAPSE' : '▼ EXPAND'}</span>
        </button>

        {showAdvanced && (
          <div className="grid grid-cols-2 gap-2.5 pt-3 mt-2.5 border-t border-[#F1F4F8] text-xs">
            <div>
              <label className="text-[10px] text-[#64748B] block mb-1 font-mono uppercase">PAYLOAD (KG)</label>
              <input
                type="number" min={0} max={500} step={10}
                value={vehicle.payload_kg}
                onChange={e => updateVehicle('payload_kg', parseFloat(e.target.value) || 0)}
                className="w-full bg-[#F8FAFC] border border-[#CBD5E1] rounded-lg px-2.5 py-1 text-xs font-mono text-[#172033]"
              />
            </div>
            <div>
              <label className="text-[10px] text-[#64748B] block mb-1 font-mono uppercase">CONFIDENCE TARGET</label>
              <select
                value={confidence}
                onChange={e => setConfidence(parseFloat(e.target.value))}
                className="w-full bg-[#F8FAFC] border border-[#CBD5E1] rounded-lg px-2.5 py-1 text-xs text-[#172033] font-mono cursor-pointer"
              >
                <option value={0.90}>P90 (90% Conservative)</option>
                <option value={0.95}>P95 (95% Ultra Conservative)</option>
                <option value={0.99}>P99 (99% Extreme Reserve)</option>
                <option value={0.50}>P50 (Nominal Expected)</option>
              </select>
            </div>
            <div>
              <label className="text-[10px] text-[#64748B] block mb-1 font-mono uppercase">DRIVETRAIN EFFICIENCY</label>
              <input
                type="number" min={0.7} max={0.98} step={0.01}
                value={vehicle.drivetrain_efficiency}
                onChange={e => updateVehicle('drivetrain_efficiency', parseFloat(e.target.value))}
                className="w-full bg-[#F8FAFC] border border-[#CBD5E1] rounded-lg px-2.5 py-1 text-xs font-mono text-[#172033]"
              />
            </div>
            <div>
              <label className="text-[10px] text-[#64748B] block mb-1 font-mono uppercase">REGEN EFFICIENCY</label>
              <input
                type="number" min={0.4} max={0.9} step={0.05}
                value={vehicle.regen_efficiency}
                onChange={e => updateVehicle('regen_efficiency', parseFloat(e.target.value))}
                className="w-full bg-[#F8FAFC] border border-[#CBD5E1] rounded-lg px-2.5 py-1 text-xs font-mono text-[#172033]"
              />
            </div>
            <div className="col-span-2 pt-1">
              <label className="text-[10px] text-[#64748B] block mb-1.5 font-mono uppercase">COMPATIBLE CONNECTORS</label>
              <div className="flex flex-wrap gap-1.5">
                {['CCS2', 'Type2_AC', 'CHAdeMO', 'Bharat_DC', 'Bharat_AC'].map(ct => {
                  const has = vehicle.connector_types.includes(ct);
                  return (
                    <button
                      key={ct}
                      type="button"
                      onClick={() => {
                        playCockpitClick();
                        const updated = has 
                          ? vehicle.connector_types.filter(c => c !== ct)
                          : [...vehicle.connector_types, ct];
                        updateVehicle('connector_types', updated);
                      }}
                      className={`px-2.5 py-1 rounded-lg text-xs font-mono transition-all border ${
                        has 
                          ? 'bg-orange-50 text-orange-700 border-orange-300 font-semibold' 
                          : 'bg-[#F8FAFC] text-[#64748B] border-[#E2E8F0] hover:border-slate-300'
                      }`}
                    >
                      {ct}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 6. Main Action Trigger Button */}
      <button 
        type="button"
        onClick={handlePlan} 
        disabled={isLoading}
        className="w-full bg-[#F97316] hover:bg-[#EA580C] text-white font-bold py-3.5 px-4 rounded-xl shadow-md active:scale-[0.99] transition-all flex items-center justify-center gap-2 text-xs font-mono tracking-wider uppercase disabled:opacity-50"
      >
        {isLoading ? (
          <>
            <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
            <span>CALCULATING EV FEASIBILITY...</span>
          </>
        ) : (
          <>
            <Navigation size={15} />
            <span>COMPUTE EV FEASIBILITY & PLAN ROUTE</span>
          </>
        )}
      </button>

      {/* Outage Warning Banner if any chargers disabled */}
      {disabledChargers.length > 0 && (
        <div className="bg-orange-50 border border-orange-200 rounded-xl p-3 flex items-start gap-2.5">
          <div className="w-2 h-2 rounded-full bg-orange-500 mt-1 shrink-0 animate-ping" />
          <div className="text-xs text-orange-900 font-mono">
            <span className="font-bold">{disabledChargers.length} charging station(s)</span> marked offline.
            Routes automatically avoid these stations.
          </div>
        </div>
      )}
    </div>
  );
}
