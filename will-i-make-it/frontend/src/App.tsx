import { useState, useEffect } from 'react';
import { 
  Zap, Map as MapIcon, Battery, AlertTriangle, Info, 
  RotateCcw, ShieldCheck, Activity, Database, Sparkles,
  Volume2, VolumeX, Play
} from 'lucide-react';
import TripPlanner, { INDIAN_EV_PRESETS } from './components/TripPlanner';
import RouteResults from './components/RouteResults';
import ChargerPanel from './components/ChargerPanel';
import ExplainPanel from './components/ExplainPanel';
import RouteMap from './components/RouteMap';
import EVCockpitBoot from './components/EVCockpitBoot';
import { healthCheck, planRoute } from './utils/api';
import { isAudioEnabled, setAudioEnabled, playCockpitClick } from './utils/audioService';
import type { RoutePlanResponse, VehicleProfile } from './types/api';

type Tab = 'planner' | 'chargers' | 'explain';

export default function App() {
  // Boot Sequence State (Always plays when site is loaded; can be skipped via ESC or button)
  const [showBootScreen, setShowBootScreen] = useState<boolean>(true);

  const [soundOn, setSoundOn] = useState<boolean>(isAudioEnabled());

  const [backendHealth, setBackendHealth] = useState<{
    ok: boolean | null;
    neo4j: boolean;
    neo4jDiagnostic?: string;
  }>({ ok: null, neo4j: false });

  const [vehicle, setVehicle] = useState<VehicleProfile>(INDIAN_EV_PRESETS[0].profile);
  const [routeResult, setRouteResult] = useState<RoutePlanResponse | null>(null);
  const [selectedRouteId, setSelectedRouteId] = useState<string>('MUMBAI_PUNE');
  const [customOrigin, setCustomOrigin] = useState<{ name: string; lat: number; lng: number } | null>({
    name: 'Connaught Place, New Delhi',
    lat: 28.6315,
    lng: 77.2167
  });
  const [customDest, setCustomDest] = useState<{ name: string; lat: number; lng: number } | null>({
    name: 'Jaipur (Pink City), Rajasthan',
    lat: 26.9124,
    lng: 75.7873
  });
  const [disabledChargers, setDisabledChargers] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<Tab>('planner');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleBootComplete = () => {
    sessionStorage.setItem('ev_cockpit_boot_played', 'true');
    setShowBootScreen(false);
  };

  const handleReplayBoot = () => {
    playCockpitClick();
    setShowBootScreen(true);
  };

  const toggleSound = () => {
    const next = !soundOn;
    setSoundOn(next);
    setAudioEnabled(next);
    if (next) playCockpitClick();
  };

  // Initial load: check health & immediately auto-plan initial route
  useEffect(() => {
    let isMounted = true;

    healthCheck()
      .then(h => {
        if (!isMounted) return;
        setBackendHealth({
          ok: true,
          neo4j: !!h.neo4j_connected,
          neo4jDiagnostic: h.neo4j_diagnostic,
        });

        // Auto-plan initial trip so the dashboard is live immediately!
        setLoading(true);
        planRoute({
          origin_lat: 19.076,
          origin_lng: 72.8777,
          dest_lat: 18.5204,
          dest_lng: 73.8567,
          vehicle: INDIAN_EV_PRESETS[0].profile,
          ambient_temp_c: 28,
          confidence_target: 0.90,
          demo_route_id: 'MUMBAI_PUNE',
          disabled_charger_ids: [],
        })
          .then(res => {
            if (isMounted) setRouteResult(res);
          })
          .catch(e => {
            if (isMounted) setError(e?.message ?? 'Initial route calculation failed');
          })
          .finally(() => {
            if (isMounted) setLoading(false);
          });
      })
      .catch(() => {
        if (!isMounted) return;
        setBackendHealth({ ok: false, neo4j: false });
      });

    return () => {
      isMounted = false;
    };
  }, []);

  const handleRouteResult = (result: RoutePlanResponse) => {
    setRouteResult(result);
    setError(null);
  };

  const handleChargerToggle = (chargerId: string, disabled: boolean) => {
    playCockpitClick();
    const updated = disabled 
      ? [...disabledChargers, chargerId] 
      : disabledChargers.filter(id => id !== chargerId);
    
    setDisabledChargers(updated);

    // If a route is currently active, immediately re-plan with updated outage state
    if (routeResult) {
      setLoading(true);
      const isCustom = selectedRouteId === 'CUSTOM_ROUTE' && customOrigin && customDest;
      planRoute({
        origin_lat: isCustom ? customOrigin.lat : (routeResult.fastest_route.road_geometry?.[0]?.[0] ?? 19.076),
        origin_lng: isCustom ? customOrigin.lng : (routeResult.fastest_route.road_geometry?.[0]?.[1] ?? 72.8777),
        dest_lat: isCustom ? customDest.lat : (routeResult.fastest_route.road_geometry?.slice(-1)[0]?.[0] ?? 18.5204),
        dest_lng: isCustom ? customDest.lng : (routeResult.fastest_route.road_geometry?.slice(-1)[0]?.[1] ?? 73.8567),
        origin_name: isCustom ? customOrigin.name : undefined,
        dest_name: isCustom ? customDest.name : undefined,
        vehicle,
        ambient_temp_c: 28,
        confidence_target: 0.90,
        demo_route_id: isCustom ? undefined : selectedRouteId,
        disabled_charger_ids: updated,
      })
        .then(res => setRouteResult(res))
        .catch(err => setError(err?.message ?? 'Rerouting failed'))
        .finally(() => setLoading(false));
    }
  };

  const resetDisabledChargers = () => {
    playCockpitClick();
    setDisabledChargers([]);
    if (routeResult) {
      setLoading(true);
      const isCustom = selectedRouteId === 'CUSTOM_ROUTE' && customOrigin && customDest;
      planRoute({
        origin_lat: isCustom ? customOrigin.lat : (routeResult.fastest_route.road_geometry?.[0]?.[0] ?? 19.076),
        origin_lng: isCustom ? customOrigin.lng : (routeResult.fastest_route.road_geometry?.[0]?.[1] ?? 72.8777),
        dest_lat: isCustom ? customDest.lat : (routeResult.fastest_route.road_geometry?.slice(-1)[0]?.[0] ?? 18.5204),
        dest_lng: isCustom ? customDest.lng : (routeResult.fastest_route.road_geometry?.slice(-1)[0]?.[1] ?? 73.8567),
        origin_name: isCustom ? customOrigin.name : undefined,
        dest_name: isCustom ? customDest.name : undefined,
        vehicle,
        ambient_temp_c: 28,
        confidence_target: 0.90,
        demo_route_id: isCustom ? undefined : selectedRouteId,
        disabled_charger_ids: [],
      })
        .then(res => setRouteResult(res))
        .catch(() => {})
        .finally(() => setLoading(false));
    }
  };

  const tabs: { id: Tab; label: string; icon: React.ReactNode; count?: number }[] = [
    { id: 'planner', label: 'Trip Planner', icon: <MapIcon size={15} /> },
    { 
      id: 'chargers', 
      label: 'Charging Stations', 
      icon: <Zap size={15} />, 
      count: disabledChargers.length > 0 ? disabledChargers.length : undefined 
    },
    { id: 'explain', label: 'Explainability & AI', icon: <Info size={15} /> },
  ];

  return (
    <div className="min-h-screen bg-[#050811] text-slate-100 flex flex-col antialiased selection:bg-cyan-500 selection:text-black relative">
      {/* 3D EV Cockpit Boot Startup Scene */}
      {showBootScreen && (
        <EVCockpitBoot onComplete={handleBootComplete} />
      )}

      {/* Main Cockpit Application (Hidden from view during boot so map/controls never bleed through) */}
      <div 
        className="flex-1 flex flex-col transition-opacity duration-700" 
        style={{ 
          visibility: showBootScreen ? 'hidden' : 'visible',
          opacity: showBootScreen ? 0 : 1
        }}
      >
        {/* Top Futuristic Cockpit System Bar */}
        <header className="border-b border-cyan-900/40 bg-slate-950/85 backdrop-blur-xl sticky top-0 z-40 shadow-[0_4px_25px_rgba(0,0,0,0.7)]">
        <div className="max-w-screen-2xl mx-auto px-4 py-2.5 flex items-center justify-between">
          {/* Brand & Cockpit Identity */}
          <div className="flex items-center gap-3">
            <div className="relative group cursor-pointer" onClick={handleReplayBoot} title="Click to replay 3D EV Boot Sequence">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-cyan-600 via-teal-500 to-emerald-400 p-0.5 shadow-[0_0_15px_rgba(6,182,212,0.4)] transition-transform group-hover:scale-105">
                <div className="w-full h-full bg-slate-950 rounded-[10px] flex items-center justify-center">
                  <Battery size={20} className="text-cyan-400 stroke-[2.5] pulse-charging" />
                </div>
              </div>
              <div className="absolute -bottom-1 -right-1 w-3.5 h-3.5 rounded-full bg-emerald-500 border-2 border-slate-950 flex items-center justify-center">
                <Zap size={8} className="text-black stroke-[3]" />
              </div>
            </div>

            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-base sm:text-lg font-black tracking-tight text-white font-sans flex items-center gap-1.5">
                  WILL I MAKE IT?
                  <span className="text-[10px] bg-cyan-950 text-cyan-300 font-mono px-2 py-0.5 rounded-full border border-cyan-800/60 shadow-[0_0_8px_rgba(6,182,212,0.2)]">
                    COCKPIT HMI · v1.0
                  </span>
                </h1>
              </div>
              <p className="text-[11px] text-cyan-200/60 font-medium hidden sm:block">
                Explainable, Risk-Aware EV Route Planner for Indian Conditions
              </p>
            </div>
          </div>

          {/* Right Cockpit Telemetry Controls */}
          <div className="flex items-center gap-2.5">
            {/* Replay 3D Boot Screen */}
            <button
              type="button"
              onClick={handleReplayBoot}
              className="badge-pill bg-slate-900 hover:bg-slate-800 text-slate-300 hover:text-cyan-300 border-slate-700 hover:border-cyan-500/40 text-[11px] font-mono transition-all hidden md:inline-flex"
              title="Replay EV 3D Boot Sequence"
            >
              <RotateCcw size={11} className="text-cyan-400" />
              <span>BOOT SEQUENCE</span>
            </button>

            {/* Audio Toggle */}
            <button
              type="button"
              onClick={toggleSound}
              className="badge-pill bg-slate-900 hover:bg-slate-800 text-slate-300 hover:text-cyan-300 border-slate-700 hover:border-cyan-500/40 text-[11px] font-mono transition-all"
              title={soundOn ? 'Mute Cockpit Audio' : 'Enable Cockpit Audio'}
            >
              {soundOn ? <Volume2 size={12} className="text-cyan-400" /> : <VolumeX size={12} className="text-slate-500" />}
              <span className="hidden sm:inline">{soundOn ? 'AUDIO ON' : 'MUTED'}</span>
            </button>

            {/* Simulated Data Badge */}
            <span className="badge-pill bg-amber-500/10 text-amber-300 border-amber-500/30 text-[11px] font-mono hidden lg:inline-flex">
              <AlertTriangle size={11} className="text-amber-400" />
              SIMULATED TELEMETRY
            </span>

            {/* Neo4j Status */}
            <span className={`badge-pill text-[11px] font-mono hidden md:inline-flex ${
              backendHealth.neo4j 
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                : 'bg-slate-900 text-slate-400 border-slate-700'
            }`} title={backendHealth.neo4jDiagnostic || 'Graph database integration status'}>
              <Database size={11} className={backendHealth.neo4j ? 'text-emerald-400' : 'text-slate-500'} />
              {backendHealth.neo4j ? 'Neo4j Graph Active' : 'Deterministic Fallback'}
            </span>

            {/* Backend Connection Status */}
            <div className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border font-mono ${
              backendHealth.ok === null 
                ? 'bg-slate-900 text-slate-400 border-slate-700'
                : backendHealth.ok 
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                  : 'bg-rose-500/10 text-rose-400 border-rose-500/30'
            }`}>
              <div className={`w-2 h-2 rounded-full ${
                backendHealth.ok === null 
                  ? 'bg-slate-500'
                  : backendHealth.ok 
                    ? 'bg-emerald-400 animate-pulse shadow-[0_0_8px_#10b981]'
                    : 'bg-rose-400'
              }`} />
              <span className="font-semibold text-[11px]">
                {backendHealth.ok === null ? 'CONNECTING...' : backendHealth.ok ? 'FASTAPI ONLINE' : 'API OFFLINE'}
              </span>
            </div>
          </div>
        </div>
      </header>

      {/* Backend Offline Alert Banner */}
      {backendHealth.ok === false && (
        <div className="bg-rose-950/80 border-b border-rose-800/80 px-4 py-2 text-center text-xs text-rose-200">
          ⚠️ Backend API unreachable at <code className="bg-rose-900/60 px-1 py-0.5 rounded font-mono">127.0.0.1:8000</code>. 
          Run <code className="bg-rose-900/60 px-1 py-0.5 rounded font-mono">run_backend.bat</code> or double click <code className="bg-rose-900/60 px-1 py-0.5 rounded font-mono">run_all.bat</code> in the project root.
        </div>
      )}

      {/* Main Cockpit Command Stage Layout */}
      <main className="flex-1 max-w-screen-2xl mx-auto w-full px-3 sm:px-4 py-4 grid grid-cols-1 xl:grid-cols-12 gap-4">
        {/* Left Column (5 Cols): Cockpit Journey Configuration */}
        <div className="xl:col-span-5 flex flex-col gap-3.5">
          {/* Tab Navigation Pill Bar */}
          <div className="flex bg-slate-950/90 border border-cyan-900/40 rounded-2xl p-1 gap-1 shadow-xl backdrop-blur-md">
            {tabs.map(tab => (
              <button
                key={tab.id}
                type="button"
                onClick={() => {
                  playCockpitClick();
                  setActiveTab(tab.id);
                }}
                className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-xl text-xs font-bold transition-all ${
                  activeTab === tab.id
                    ? 'bg-gradient-to-r from-cyan-500/20 via-teal-500/20 to-emerald-500/20 text-cyan-300 border border-cyan-500/40 shadow-[0_0_12px_rgba(6,182,212,0.2)]'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
                }`}
              >
                {tab.icon}
                <span>{tab.label}</span>
                {tab.count !== undefined && tab.count > 0 && (
                  <span className="bg-rose-500 text-white text-[10px] font-mono px-1.5 py-0.2 rounded-full font-bold shadow-[0_0_8px_rgba(244,63,94,0.6)]">
                    {tab.count}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Active Tab Component */}
          {activeTab === 'planner' && (
            <TripPlanner
              vehicle={vehicle}
              onVehicleChange={setVehicle}
              selectedRouteId={selectedRouteId}
              onRouteSelect={setSelectedRouteId}
              disabledChargers={disabledChargers}
              onResult={handleRouteResult}
              onError={setError}
              onLoading={setLoading}
              isLoading={loading}
              onCustomLocationsChange={(orig, dest) => {
                setCustomOrigin(orig);
                setCustomDest(dest);
              }}
            />
          )}

          {activeTab === 'chargers' && (
            <ChargerPanel
              routeResult={routeResult}
              disabledChargers={disabledChargers}
              onChargerToggle={handleChargerToggle}
              onResetDisabledChargers={resetDisabledChargers}
            />
          )}

          {activeTab === 'explain' && (
            <ExplainPanel
              routeResult={routeResult}
              vehicle={vehicle}
            />
          )}
        </div>

        {/* Right Column (7 Cols): Cockpit Navigation Map & Dynamic Route Telemetry */}
        <div className="xl:col-span-7 flex flex-col gap-4">
          {/* Map Section with HUD frame */}
          <div className="h-80 sm:h-96 w-full relative">
            <RouteMap
              routeResult={routeResult}
              selectedRouteId={selectedRouteId}
              disabledChargers={disabledChargers}
              onChargerToggle={handleChargerToggle}
              customOrigin={customOrigin}
              customDest={customDest}
            />
          </div>

          {/* Loading Indicator */}
          {loading && (
            <div className="cockpit-panel flex items-center justify-center h-28 border-cyan-500/50 bg-slate-900/90 shadow-[0_0_20px_rgba(6,182,212,0.15)]">
              <div className="flex items-center gap-3 text-cyan-400 text-xs font-mono font-bold tracking-wider">
                <div className="w-5 h-5 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin shadow-[0_0_10px_#00f0ff]" />
                <span>COMPUTING INDIAN EV DYNAMICS & BATTERY FEASIBILITY...</span>
              </div>
            </div>
          )}

          {/* Routing Error Notice */}
          {error && !loading && (
            <div className="cockpit-panel border-rose-500/50 bg-rose-950/40">
              <div className="flex items-center gap-2 text-rose-400 text-xs font-bold uppercase tracking-wider font-mono">
                <AlertTriangle size={15} />
                Routing Constraint Alert
              </div>
              <p className="text-xs text-rose-200 mt-1">{error}</p>
            </div>
          )}

          {/* Route Results & Cockpit Telemetry Cards */}
          {!loading && routeResult && (
            <RouteResults
              result={routeResult}
              vehicle={vehicle}
              disabledChargers={disabledChargers}
              onChargerToggle={handleChargerToggle}
              selectedRouteId={selectedRouteId}
            />
          )}
        </div>
      </main>

      {/* Cockpit Footer */}
      <footer className="border-t border-cyan-950/60 bg-slate-950/80 px-4 py-3 mt-auto text-center text-slate-500 text-[11px] font-mono">
        <div className="max-w-screen-2xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-2">
          <span className="text-cyan-400/80">
            Will I Make It? · EV Cockpit HMI · Hackathon 2026
          </span>
          <span className="italic text-slate-400">
            Physics engine: Aerodynamic Drag, Rolling Resistance, Elevation & Climate · SIMULATED Telemetry
          </span>
        </div>
      </footer>
      </div>
    </div>
  );
}
