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
import Neo4jGraphMonitor from './components/Neo4jGraphMonitor';
import SarvamVoiceAssistant from './components/SarvamVoiceAssistant';
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
    <div className="min-h-screen bg-[#F6F8FB] text-[#172033] flex flex-col antialiased selection:bg-orange-500 selection:text-white relative font-sans">
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
        {/* Left Vertical Navigation Rail */}
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
            <div className="bg-rose-100 border-b border-rose-300 px-4 py-2 text-center text-xs text-rose-800">
              ⚠️ Backend API unreachable at <code className="bg-rose-200 px-1 py-0.5 rounded font-mono">127.0.0.1:8000</code>. 
              Run <code className="bg-rose-200 px-1 py-0.5 rounded font-mono">run_backend.bat</code> in the project root.
            </div>
          )}

          {/* Main Stage: Graph Monitor OR Dual-Column Map Workspace */}
          {activeView === 'graph' ? (
            <div className="flex-1 w-full h-full min-h-0 p-3 sm:p-5 overflow-hidden">
              <div className="w-full h-full rounded-2xl overflow-hidden border border-[#E2E8F0] shadow-sm bg-white">
                <Neo4jGraphMonitor />
              </div>
            </div>
          ) : (
            <div className="flex-1 flex flex-col lg:flex-row min-h-0 overflow-y-auto lg:overflow-hidden p-3 sm:p-5 gap-4">
            {/* Left Control / Information Column (Scrollable, ~40% width on desktop) */}
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
                <div className="bg-white border border-[#E2E8F0] rounded-2xl flex flex-col items-center justify-center p-8 text-center text-[#64748B] shadow-sm">
                  <Compass size={32} className="text-[#F97316] mb-2" />
                  <h3 className="text-sm font-bold text-[#172033] mb-1 font-mono uppercase">NO ACTIVE ROUTE CALCULATED</h3>
                  <p className="text-xs text-[#64748B] mb-4">Plan a journey in the Trip Planner to generate route decisions.</p>
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

              {activeView === 'voice' && (
                <SarvamVoiceAssistant
                  vehicle={vehicle}
                  currentRoute={routeResult}
                  onApplyRoute={(newRoute) => {
                    setRouteResult(newRoute);
                    setActiveView('results');
                  }}
                />
              )}

              {activeView === 'explain' && (
                <ExplainPanel
                  routeResult={routeResult}
                  vehicle={vehicle}
                />
              )}
            </div>

            {/* Right Column: Visualization & Map Dashboard (~60% width on desktop) */}
            <div className="flex-1 flex flex-col min-w-0 overflow-y-auto pr-0 lg:pr-1 gap-4">
              {/* Controlled-Height Interactive Map Canvas */}
              <div className="w-full h-[380px] sm:h-[400px] lg:h-[440px] shrink-0 relative">
                <RouteMap
                  routeResult={routeResult}
                  selectedRouteId={selectedRouteId}
                  disabledChargers={disabledChargers}
                  onChargerToggle={handleChargerToggle}
                  customOrigin={customOrigin}
                  customDest={customDest}
                />
              </div>

              {/* Dynamic Route Summary Card under the Map */}
              {routeResult && (
                <div className="bg-white border border-[#E2E8F0] rounded-2xl p-4 shadow-sm flex flex-col gap-3 shrink-0">
                  <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 ${
                        routeResult.fastest_route.feasible 
                          ? 'bg-emerald-50 text-emerald-600 border border-emerald-200' 
                          : 'bg-rose-50 text-rose-600 border border-rose-200'
                      }`}>
                        <Zap size={20} />
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-bold font-mono text-[#172033]">
                            {routeResult.fastest_route.feasible ? 'FEASIBLE ROUTE' : 'RANGE CRITICAL'}
                          </span>
                          <span className="text-xs bg-orange-50 text-orange-700 font-mono font-bold px-2 py-0.5 rounded border border-orange-200">
                            +{routeResult.fastest_route.feasibility_margin_kwh.toFixed(1)} kWh Reserve
                          </span>
                        </div>
                        <p className="text-xs text-[#64748B] truncate mt-0.5">
                          P50: <strong className="text-teal-700">{routeResult.fastest_route.energy_result.total_kwh_p50.toFixed(1)} kWh</strong> · P90: <strong className="text-orange-700">{routeResult.fastest_route.energy_result.total_kwh_p90.toFixed(1)} kWh</strong> · Arrival SoC: <strong className="text-[#172033]">{routeResult.fastest_route.energy_result.soc_final_p90_pct.toFixed(0)}%</strong>
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
                        className="px-3.5 py-2 rounded-xl bg-[#F97316] hover:bg-[#EA580C] text-white text-xs font-mono font-bold transition-all shadow-sm"
                      >
                        Decision View
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          playCockpitClick();
                          setActiveView('energy');
                        }}
                        className="px-3.5 py-2 rounded-xl bg-white hover:bg-[#F8FAFC] text-[#334155] border border-[#CBD5E1] text-xs font-mono font-medium transition-all shadow-sm"
                      >
                        Energy Curves
                      </button>
                    </div>
                  </div>

                  {/* Planned Charging Stops summary strip */}
                  {routeResult.fastest_route.charging_stops.length > 0 && (
                    <div className="pt-2 border-t border-[#F1F4F8] flex items-center gap-2 overflow-x-auto text-xs font-mono">
                      <span className="text-[10px] text-[#64748B] font-bold uppercase tracking-wider shrink-0">STOPS:</span>
                      {routeResult.fastest_route.charging_stops.map((stop, sidx) => (
                        <div key={stop.charger.charger_id || sidx} className="flex items-center gap-1.5 bg-[#F8FAFC] px-2.5 py-1 rounded-lg border border-[#E2E8F0] shrink-0 text-[#334155]">
                          <span className="w-1.5 h-1.5 rounded-full bg-[#F97316]" />
                          <span className="font-semibold text-[#172033]">{stop.charger.name.slice(0, 18)}</span>
                          <span className="text-[10px] text-orange-600">({stop.arrive_soc_pct.toFixed(0)}% → {stop.depart_soc_pct.toFixed(0)}%)</span>
                          <span className="text-[10px] text-[#64748B]">{stop.charge_duration_min.toFixed(0)}m</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Loading Indicator */}
              {loading && (
                <div className="bg-white border border-[#E2E8F0] rounded-2xl flex items-center justify-center h-20 shadow-sm shrink-0">
                  <div className="flex items-center gap-3 text-orange-600 text-xs font-mono font-bold tracking-wider">
                    <div className="w-4 h-4 border-2 border-orange-500 border-t-transparent rounded-full animate-spin" />
                    <span>CALCULATING HIGHWAY FORCES & CHARGER REACHABILITY...</span>
                  </div>
                </div>
              )}

              {/* Routing Error Notice */}
              {error && !loading && (
                <div className="bg-rose-50 border border-rose-200 rounded-2xl p-3.5 shadow-sm shrink-0">
                  <div className="flex items-center gap-2 text-rose-700 text-xs font-bold uppercase tracking-wider font-mono">
                    <AlertTriangle size={15} />
                    Routing Constraint Alert
                  </div>
                  <p className="text-xs text-rose-800 mt-0.5">{error}</p>
                </div>
              )}
            </div>
          </div>
          )}
        </div>
      </div>
    </div>
  );
}
