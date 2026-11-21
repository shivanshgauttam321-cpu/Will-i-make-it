import { useState, useEffect } from 'react';
import { AlertTriangle, Compass, CheckCircle2, ChevronRight, Zap, Flame } from 'lucide-react';
import NavigationRail, { type ActiveView } from './components/NavigationRail';
import HeaderBar from './components/HeaderBar';
import TripPlanner, { INDIAN_EV_PRESETS } from './components/TripPlanner';
import JourneyResultsPanel from './components/JourneyResultsPanel';
import EnergyIntelligencePanel from './components/EnergyIntelligencePanel';
import ChargerPanel from './components/ChargerPanel';
import ExplainPanel from './components/ExplainPanel';
import RouteMap from './components/RouteMap';
import EVCockpitBoot from './components/EVCockpitBoot';
import { healthCheck, planRoute } from './utils/api';
import { isAudioEnabled, setAudioEnabled, playCockpitClick } from './utils/audioService';
import type { RoutePlanResponse, VehicleProfile } from './types/api';

export default function App() {
  // Boot Sequence State (Plays once per session; can be replayed anytime via header button)
  const [showBootScreen, setShowBootScreen] = useState<boolean>(() => {
    if (typeof window !== 'undefined') {
      return !sessionStorage.getItem('ev_cockpit_boot_played');
    }
    return false;
  });

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
  const [activeView, setActiveView] = useState<ActiveView>('planner');
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
    // Automatically switch view to 'results' so user immediately sees the feasibility decision!
    setActiveView('results');
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

  const activeRouteOption = routeResult?.fastest_route;

  return (
    <div className="min-h-screen bg-[#080b10] text-slate-100 flex flex-col antialiased selection:bg-orange-500 selection:text-white relative font-sans">
      {/* 3D EV Boot Startup Scene (Plays once, skippable) */}
      {showBootScreen && (
        <EVCockpitBoot onComplete={handleBootComplete} />
      )}

      {/* Main Application Interface */}
      <div 
        className="flex-1 flex flex-col lg:flex-row h-screen overflow-hidden transition-opacity duration-500" 
        style={{ 
          visibility: showBootScreen ? 'hidden' : 'visible',
          opacity: showBootScreen ? 0 : 1
        }}
      >
        {/* Left Vertical Navigation Rail (Meitriya Style) */}
        <NavigationRail
          activeView={activeView}
          onViewChange={(view) => {
            playCockpitClick();
            setActiveView(view);
          }}
          hasResult={!!routeResult}
          disabledChargersCount={disabledChargers.length}
          soundOn={soundOn}
          onToggleSound={toggleSound}
          backendOk={backendHealth.ok}
          neo4jOk={backendHealth.neo4j}
        />

        {/* Primary Content Stage */}
        <div className="flex-1 flex flex-col min-w-0 h-full overflow-hidden">
          {/* Header Bar */}
          <HeaderBar
            routeLabel={activeRouteOption?.label}
            distanceKm={activeRouteOption?.distance_km}
            durationMin={activeRouteOption?.duration_min}
            backendOk={backendHealth.ok}
            neo4jOk={backendHealth.neo4j}
            neo4jDiagnostic={backendHealth.neo4jDiagnostic}
            onReplayIntro={handleReplayBoot}
          />

          {/* Backend Offline Warning Banner */}
          {backendHealth.ok === false && (
            <div className="bg-rose-950/80 border-b border-rose-800/80 px-4 py-2 text-center text-xs text-rose-200">
              ⚠️ Backend API unreachable at <code className="bg-rose-900/60 px-1 py-0.5 rounded font-mono">127.0.0.1:8000</code>. 
              Run <code className="bg-rose-900/60 px-1 py-0.5 rounded font-mono">run_backend.bat</code> in the project root.
            </div>
          )}

          {/* Dual-Column Main Workspace */}
          <div className="flex-1 flex flex-col lg:flex-row min-h-0 overflow-y-auto lg:overflow-hidden p-3 sm:p-5 gap-4">
            {/* Left Control / Information Column (Scrollable) */}
            <div className="w-full lg:w-[420px] xl:w-[460px] 2xl:w-[480px] flex flex-col shrink-0 lg:overflow-y-auto pr-0 lg:pr-1 gap-4">
              {activeView === 'planner' && (
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

              {activeView === 'results' && routeResult && (
                <JourneyResultsPanel
                  result={routeResult}
                  vehicle={vehicle}
                  disabledChargers={disabledChargers}
                  onChargerToggle={handleChargerToggle}
                  selectedRouteId={selectedRouteId}
                  onNavigateToEnergy={() => {
                    playCockpitClick();
                    setActiveView('energy');
                  }}
                />
              )}

              {activeView === 'results' && !routeResult && (
                <div className="bg-[#121620] border border-[#222938] rounded-2xl flex flex-col items-center justify-center p-8 text-center text-slate-400">
                  <Compass size={32} className="text-orange-400 mb-2" />
                  <h3 className="text-sm font-bold text-white mb-1 font-mono uppercase">NO ACTIVE ROUTE CALCULATED</h3>
                  <p className="text-xs text-slate-400 mb-4">Plan a journey in the Trip Planner to generate route decisions.</p>
                  <button
                    type="button"
                    onClick={() => setActiveView('planner')}
                    className="btn-primary text-xs"
                  >
                    Open Trip Planner
                  </button>
                </div>
              )}

              {activeView === 'energy' && (
                <EnergyIntelligencePanel
                  result={routeResult}
                  vehicle={vehicle}
                />
              )}

              {activeView === 'chargers' && (
                <ChargerPanel
                  routeResult={routeResult}
                  disabledChargers={disabledChargers}
                  onChargerToggle={handleChargerToggle}
                  onResetDisabledChargers={resetDisabledChargers}
                />
              )}

              {activeView === 'explain' && (
                <ExplainPanel
                  routeResult={routeResult}
                  vehicle={vehicle}
                />
              )}
            </div>

            {/* Right Column: Large Interactive Central Map & Dynamic Action Ribbon */}
            <div className="flex-1 flex flex-col min-w-0 min-h-[440px] lg:min-h-0 gap-3">
              {/* Central Map Canvas (The Visual Centerpiece) */}
              <div className="flex-1 w-full min-h-[380px] lg:min-h-0 relative">
                <RouteMap
                  routeResult={routeResult}
                  selectedRouteId={selectedRouteId}
                  disabledChargers={disabledChargers}
                  onChargerToggle={handleChargerToggle}
                  customOrigin={customOrigin}
                  customDest={customDest}
                />
              </div>

              {/* Dynamic Quick Ribbon under map when route is calculated */}
              {routeResult && (
                <div className="bg-[#121620] border border-[#222938] rounded-2xl px-4 py-3 shadow-xl flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 shrink-0">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className={`w-8 h-8 rounded-xl flex items-center justify-center shrink-0 ${
                      routeResult.fastest_route.feasible 
                        ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' 
                        : 'bg-rose-500/20 text-rose-400 border border-rose-500/30'
                    }`}>
                      <Zap size={16} />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-bold font-mono text-white">
                          {routeResult.fastest_route.feasible ? 'FEASIBLE ROUTE' : 'RANGE CRITICAL'}
                        </span>
                        <span className="text-[10px] bg-[#1a2130] text-orange-400 font-mono font-bold px-1.5 py-0.5 rounded border border-[#262f42]">
                          +{routeResult.fastest_route.feasibility_margin_kwh.toFixed(1)} kWh Reserve
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-400 truncate">
                        P50: <strong className="text-teal-400">{routeResult.fastest_route.energy_result.total_kwh_p50.toFixed(1)} kWh</strong> · P90: <strong className="text-orange-400">{routeResult.fastest_route.energy_result.total_kwh_p90.toFixed(1)} kWh</strong> · Arrival SoC: <strong className="text-white">{routeResult.fastest_route.energy_result.soc_final_p90_pct.toFixed(0)}%</strong>
                      </p>
                    </div>
                  </div>

                  {/* Navigation Shortcuts */}
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      type="button"
                      onClick={() => {
                        playCockpitClick();
                        setActiveView('results');
                      }}
                      className="px-3 py-1.5 rounded-xl bg-orange-500 hover:bg-orange-600 text-white text-xs font-mono font-bold transition-all shadow-md shadow-orange-950/40"
                    >
                      Decision View
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        playCockpitClick();
                        setActiveView('energy');
                      }}
                      className="px-3 py-1.5 rounded-xl bg-[#181e2b] hover:bg-[#202738] text-slate-200 border border-[#262f42] text-xs font-mono font-medium transition-all"
                    >
                      Energy Curves
                    </button>
                  </div>
                </div>
              )}

              {/* Loading Indicator */}
              {loading && (
                <div className="bg-[#121620] border border-[#222938] rounded-2xl flex items-center justify-center h-20 shadow-xl shrink-0">
                  <div className="flex items-center gap-3 text-orange-400 text-xs font-mono font-bold tracking-wider">
                    <div className="w-4 h-4 border-2 border-orange-400 border-t-transparent rounded-full animate-spin" />
                    <span>CALCULATING HIGHWAY FORCES & CHARGER REACHABILITY...</span>
                  </div>
                </div>
              )}

              {/* Routing Error Notice */}
              {error && !loading && (
                <div className="bg-[#1c1214] border border-rose-500/40 rounded-2xl p-3.5 shadow-xl shrink-0">
                  <div className="flex items-center gap-2 text-rose-400 text-xs font-bold uppercase tracking-wider font-mono">
                    <AlertTriangle size={15} />
                    Routing Constraint Alert
                  </div>
                  <p className="text-xs text-rose-200 mt-0.5">{error}</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
