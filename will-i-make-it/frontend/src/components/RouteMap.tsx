import { useEffect, useState, useMemo } from 'react';
import { MapContainer, TileLayer, Polyline, Marker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import { ExternalLink, Layers, Navigation, Compass, Crosshair, Zap } from 'lucide-react';
import type { RoutePlanResponse, DemoRoute, Charger } from '../types/api';
import { getDemoRoute, getAllChargers } from '../utils/api';
import { playCockpitClick } from '../utils/audioService';

// Fix default marker icon issues with bundlers
delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

// Custom SVG Icons (Meitriya Style: Cyan Origin, Orange Destination, High-Contrast Charger Pins)
const createOriginIcon = () => L.divIcon({
  html: `
    <div style="background:#06b6d4;width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#0b0e14;font-weight:900;font-size:12px;border:2.5px solid #ffffff;box-shadow:0 4px 12px rgba(6,182,212,0.6)">
      A
    </div>
  `,
  className: '',
  iconSize: [28, 28],
  iconAnchor: [14, 14],
});

const createDestIcon = () => L.divIcon({
  html: `
    <div style="background:#f97316;width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#ffffff;font-weight:900;font-size:12px;border:2.5px solid #ffffff;box-shadow:0 4px 12px rgba(249,115,22,0.6)">
      B
    </div>
  `,
  className: '',
  iconSize: [28, 28],
  iconAnchor: [14, 14],
});

const createChargerIcon = (isDown: boolean, isStop: boolean, relScore: number) => {
  const bg = isDown ? '#f43f5e' : (isStop ? '#f97316' : (relScore >= 0.75 ? '#10b981' : '#f59e0b'));
  const size = isStop ? 30 : 22;
  const halo = isStop ? `box-shadow:0 0 16px ${bg};animation:pulse 2s infinite;` : `box-shadow:0 2px 8px rgba(0,0,0,0.5);`;
  
  return L.divIcon({
    html: `
      <div style="background:${bg};width:${size}px;height:${size}px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:white;font-size:${isStop ? 13 : 10}px;font-weight:bold;border:2px solid white;${halo}">
        ⚡
      </div>
    `,
    className: '',
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
};

function FitBounds({ positions }: { positions: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    if (positions.length > 1) {
      map.fitBounds(positions, { padding: [40, 40], maxZoom: 14 });
    }
  }, [map, positions]);
  return null;
}

// Map style presets
type MapStyle = 'google-roads' | 'google-satellite' | 'google-terrain' | 'carto-dark' | 'osm';

const MAP_LAYERS: Record<MapStyle, { name: string; url: string; subdomains?: string[]; attribution: string; maxZoom: number }> = {
  'google-roads': {
    name: 'Google Roads',
    url: 'https://mt{s}.google.com/vt/lyrs=m&x={x}&y={y}&z={z}',
    subdomains: ['0', '1', '2', '3'],
    attribution: '&copy; Google Maps',
    maxZoom: 20,
  },
  'google-satellite': {
    name: 'Google Satellite',
    url: 'https://mt{s}.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
    subdomains: ['0', '1', '2', '3'],
    attribution: '&copy; Google Maps Satellite',
    maxZoom: 20,
  },
  'google-terrain': {
    name: 'Google Terrain',
    url: 'https://mt{s}.google.com/vt/lyrs=p&x={x}&y={y}&z={z}',
    subdomains: ['0', '1', '2', '3'],
    attribution: '&copy; Google Maps Terrain',
    maxZoom: 20,
  },
  'carto-dark': {
    name: 'Dark Navigation',
    url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    subdomains: ['a', 'b', 'c', 'd'],
    attribution: '&copy; CARTO &copy; OpenStreetMap',
    maxZoom: 19,
  },
  'osm': {
    name: 'OpenStreetMap',
    url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    subdomains: ['a', 'b', 'c'],
    attribution: '&copy; OpenStreetMap contributors',
    maxZoom: 19,
  },
};

interface Props {
  routeResult: RoutePlanResponse | null;
  selectedRouteId: string;
  disabledChargers: string[];
  onChargerToggle: (id: string, disabled: boolean) => void;
  customOrigin?: { name: string; lat: number; lng: number } | null;
  customDest?: { name: string; lat: number; lng: number } | null;
}

export default function RouteMap({
  routeResult, selectedRouteId, disabledChargers, onChargerToggle,
  customOrigin, customDest
}: Props) {
  const [demoRoute, setDemoRoute] = useState<DemoRoute | null>(null);
  const [allChargers, setAllChargers] = useState<Charger[]>([]);
  const [activeLayer, setActiveLayer] = useState<MapStyle>('google-roads');
  const [showLayerMenu, setShowLayerMenu] = useState(false);

  useEffect(() => {
    if (selectedRouteId && selectedRouteId !== 'CUSTOM_ROUTE') {
      getDemoRoute(selectedRouteId).then(setDemoRoute).catch(() => {});
    } else {
      setDemoRoute(null);
    }
  }, [selectedRouteId]);

  useEffect(() => {
    getAllChargers().then(r => setAllChargers(r.chargers)).catch(() => {});
  }, []);

  // Coarse waypoints as fallback
  const waypoints: [number, number][] = useMemo(() => {
    if (customOrigin && customDest) {
      return [[customOrigin.lat, customOrigin.lng], [customDest.lat, customDest.lng]];
    }
    return demoRoute?.waypoints?.map(w => [w.lat, w.lng] as [number, number]) ?? [];
  }, [demoRoute, customOrigin, customDest]);

  // High-precision road-snapped road geometry (tracing exact curves of expressways/highways)
  const exactRoadGeometry: [number, number][] = useMemo(() => {
    // 1. Prefer road geometry returned with the planned route
    if (routeResult?.fastest_route?.road_geometry && routeResult.fastest_route.road_geometry.length > 5) {
      return routeResult.fastest_route.road_geometry.map(pt => [pt[0], pt[1]] as [number, number]);
    }
    // 2. Or road geometry from the demo route database
    if (demoRoute?.road_geometry && demoRoute.road_geometry.length > 5) {
      return demoRoute.road_geometry.map(pt => [pt[0], pt[1]] as [number, number]);
    }
    // 3. Fallback to waypoints or custom points
    return waypoints;
  }, [routeResult, demoRoute, waypoints]);

  const defaultCenter: [number, number] = exactRoadGeometry[0] ?? [28.6139, 77.2090];

  // Charging stop stations planned on active routes
  const plannedStops = useMemo(() => {
    return [
      ...(routeResult?.fastest_route?.charging_stops ?? []),
      ...(routeResult?.risk_aware_route?.charging_stops ?? []),
    ];
  }, [routeResult]);

  const plannedStopIds = useMemo(() => {
    return new Set(plannedStops.map(s => s.charger.charger_id));
  }, [plannedStops]);

  // Chargers to display on map: route chargers or corridor chargers
  const mapChargers = useMemo(() => {
    const list = [...allChargers];
    // Ensure planned custom chargers are also in the list
    plannedStops.forEach(s => {
      if (!list.some(c => c.charger_id === s.charger.charger_id)) {
        list.push(s.charger);
      }
    });

    return list.filter(c => {
      if (plannedStopIds.has(c.charger_id)) return true;
      if (demoRoute?.charger_ids?.includes(c.charger_id)) return true;
      if (exactRoadGeometry.length > 0) {
        // Within ~60 km of any point on the route polyline
        const minDistance = Math.min(...exactRoadGeometry.map(pt => Math.hypot(c.lat - pt[0], c.lng - pt[1])));
        return minDistance < 0.6;
      }
      return false;
    });
  }, [allChargers, plannedStops, plannedStopIds, demoRoute, exactRoadGeometry]);

  const origin = useMemo(() => {
    if (customOrigin) return customOrigin;
    if (demoRoute?.origin) return demoRoute.origin;
    if (routeResult?.fastest_route?.road_geometry && routeResult.fastest_route.road_geometry.length > 0) {
      const pt = routeResult.fastest_route.road_geometry[0];
      return { lat: pt[0], lng: pt[1], name: 'Start Origin' };
    }
    return null;
  }, [customOrigin, demoRoute, routeResult]);

  const dest = useMemo(() => {
    if (customDest) return customDest;
    if (demoRoute?.destination) return demoRoute.destination;
    if (routeResult?.fastest_route?.road_geometry && routeResult.fastest_route.road_geometry.length > 0) {
      const geom = routeResult.fastest_route.road_geometry;
      const pt = geom[geom.length - 1];
      return { lat: pt[0], lng: pt[1], name: 'Destination' };
    }
    return null;
  }, [customDest, demoRoute, routeResult]);

  // Direct Google Maps Universal Deep-Link (Turn-by-Turn EV Navigation)
  const googleMapsUrl = useMemo(() => {
    if (!origin || !dest) return '#';
    const stopCoords = plannedStops.map(s => `${s.charger.lat},${s.charger.lng}`);
    const waypointsParam = stopCoords.length > 0 ? `&waypoints=${encodeURIComponent(stopCoords.join('|'))}` : '';
    return `https://www.google.com/maps/dir/?api=1&origin=${origin.lat},${origin.lng}&destination=${dest.lat},${dest.lng}${waypointsParam}&travelmode=driving`;
  }, [origin, dest, plannedStops]);

  const currentLayer = MAP_LAYERS[activeLayer];

  return (
    <div className="relative w-full h-full rounded-2xl overflow-hidden border border-[#E2E8F0] shadow-sm flex flex-col bg-white">
      {/* Top Map Action Bar */}
      <div className="absolute top-3 left-3 right-3 z-[1000] flex items-center justify-between pointer-events-none gap-2">
        {/* Navigation / Precision Badge */}
        <div className="bg-white/95 backdrop-blur-md px-3 py-1.5 rounded-xl border border-[#E2E8F0] shadow-sm text-xs font-mono font-medium text-[#172033] flex items-center gap-2 pointer-events-auto">
          <Navigation className="w-3.5 h-3.5 text-orange-500" />
          <span className="font-bold text-[#172033] text-[11px] uppercase tracking-wider">ROAD-SNAPPED ROUTE</span>
          <span className="text-[10px] bg-[#F1F4F8] text-sky-600 font-mono px-1.5 py-0.5 rounded border border-[#E2E8F0]">
            {exactRoadGeometry.length} GPS
          </span>
        </div>

        {/* Right Controls: Turn-by-Turn Nav & Layer Switcher */}
        <div className="flex items-center gap-2 pointer-events-auto">
          {/* Open in Google Maps Button */}
          <a
            href={googleMapsUrl}
            target="_blank"
            rel="noopener noreferrer"
            onClick={() => playCockpitClick()}
            title="Open turn-by-turn route with charging stops directly in Google Maps"
            className="flex items-center gap-1.5 bg-[#F97316] hover:bg-[#EA580C] active:scale-95 text-white text-xs font-mono font-bold px-3 py-1.5 rounded-xl shadow-sm transition-all"
          >
            <span>GOOGLE MAPS NAV</span>
            <ExternalLink className="w-3.5 h-3.5" />
          </a>

          {/* Map Layer Switcher Dropdown */}
          <div className="relative">
            <button
              type="button"
              onClick={() => {
                playCockpitClick();
                setShowLayerMenu(!showLayerMenu);
              }}
              className="flex items-center gap-1.5 bg-white/95 hover:bg-[#F8FAFC] backdrop-blur-md px-2.5 py-1.5 rounded-xl border border-[#E2E8F0] hover:border-slate-400 text-xs font-mono font-medium text-[#172033] shadow-sm transition-colors"
            >
              <Layers className="w-3.5 h-3.5 text-orange-500" />
              <span className="hidden sm:inline">{currentLayer.name}</span>
            </button>

            {showLayerMenu && (
              <div className="absolute right-0 mt-1 w-48 bg-white border border-[#E2E8F0] rounded-xl shadow-xl py-1 z-[1100]">
                <div className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400 border-b border-[#F1F4F8] font-mono">
                  Map Provider
                </div>
                {(Object.keys(MAP_LAYERS) as MapStyle[]).map(key => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => {
                      playCockpitClick();
                      setActiveLayer(key);
                      setShowLayerMenu(false);
                    }}
                    className={`w-full text-left px-3 py-1.5 text-xs transition-colors flex items-center justify-between font-mono ${
                      activeLayer === key
                        ? 'bg-orange-50 text-orange-600 font-bold'
                        : 'text-[#172033] hover:bg-[#F8FAFC]'
                    }`}
                  >
                    <span>{MAP_LAYERS[key].name}</span>
                    {activeLayer === key && <span className="text-orange-600 text-xs">✓</span>}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <MapContainer
        center={defaultCenter}
        zoom={8}
        style={{ height: '100%', width: '100%' }}
        zoomControl={true}
      >
        <TileLayer
          key={activeLayer}
          attribution={currentLayer.attribution}
          url={currentLayer.url}
          subdomains={currentLayer.subdomains}
          maxZoom={currentLayer.maxZoom}
        />

        {/* Route Paths */}
        {exactRoadGeometry.length > 1 && (
          <>
            {/* Primary Route Outer Line */}
            <Polyline
              positions={exactRoadGeometry}
              pathOptions={{
                color: '#0369a1',
                weight: 6,
                opacity: 0.6,
                lineCap: 'round',
                lineJoin: 'round',
              }}
            />

            {/* Primary Route Core Line */}
            <Polyline
              positions={exactRoadGeometry}
              pathOptions={{
                color: '#0284c7',
                weight: 4,
                opacity: 0.95,
                lineCap: 'round',
                lineJoin: 'round',
              }}
            />

            {/* Risk-Aware Route Overlay if Active */}
            {routeResult?.risk_aware_route && (
              <Polyline
                positions={exactRoadGeometry}
                pathOptions={{
                  color: '#10b981',
                  weight: 3,
                  opacity: 0.9,
                  dashArray: '8 6',
                }}
              />
            )}
          </>
        )}

        {/* Origin Pin (A) */}
        {origin && (
          <Marker position={[origin.lat, origin.lng]} icon={createOriginIcon()}>
            <Popup>
              <div className="p-1">
                <span className="text-[10px] uppercase font-bold text-sky-600 block tracking-wider font-mono">Start Origin</span>
                <strong className="text-xs text-[#172033]">{origin.name}</strong>
                <p className="text-[10px] text-[#64748B] font-mono mt-0.5">{origin.lat.toFixed(4)}, {origin.lng.toFixed(4)}</p>
              </div>
            </Popup>
          </Marker>
        )}

        {/* Destination Pin (B) */}
        {dest && (
          <Marker position={[dest.lat, dest.lng]} icon={createDestIcon()}>
            <Popup>
              <div className="p-1">
                <span className="text-[10px] uppercase font-bold text-[#F97316] block tracking-wider font-mono">Destination</span>
                <strong className="text-xs text-[#172033]">{dest.name}</strong>
                <p className="text-[10px] text-[#64748B] font-mono mt-0.5">{dest.lat.toFixed(4)}, {dest.lng.toFixed(4)}</p>
              </div>
            </Popup>
          </Marker>
        )}

        {/* Charging Stations */}
        {mapChargers.map(charger => {
          const isDown = disabledChargers.includes(charger.charger_id);
          const isStop = plannedStopIds.has(charger.charger_id);

          return (
            <Marker
              key={charger.charger_id}
              position={[charger.lat, charger.lng]}
              icon={createChargerIcon(isDown, isStop, charger.reliability_score)}
            >
              <Popup>
                <div className="p-1.5 min-w-[210px]">
                  <div className="flex items-center justify-between gap-1 mb-1">
                    <strong className="text-xs text-[#172033] font-sans">{charger.name}</strong>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono font-bold ${
                      isDown ? 'bg-rose-50 text-rose-700 border border-rose-200' : 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                    }`}>
                      {isDown ? 'OFFLINE' : `${(charger.reliability_score * 100).toFixed(0)}% Rel`}
                    </span>
                  </div>

                  <p className="text-[11px] text-[#475569]">
                    {charger.operator} · <span className="font-mono text-[#F97316] font-semibold">{charger.max_power_kw} kW</span>
                  </p>
                  <p className="text-[10px] text-[#64748B] mb-2 truncate">
                    {charger.address}
                  </p>

                  <div className="flex flex-wrap gap-1 mb-2">
                    {charger.connector_types.map(ct => (
                      <span key={ct} className="text-[9px] bg-[#F1F4F8] text-[#334155] px-1 py-0.5 rounded border border-[#E2E8F0] font-mono">
                        {ct}
                      </span>
                    ))}
                  </div>

                  {/* Interactive 1-click toggle */}
                  <button
                    type="button"
                    onClick={() => onChargerToggle(charger.charger_id, !isDown)}
                    className={`w-full text-[11px] font-semibold py-1.5 px-2 rounded-lg transition-colors font-mono ${
                      isDown 
                        ? 'bg-emerald-600 hover:bg-emerald-700 text-white' 
                        : 'bg-rose-600 hover:bg-rose-700 text-white'
                    }`}
                  >
                    {isDown ? '✓ Restore Station' : '⚡ Simulate Outage'}
                  </button>
                </div>
              </Popup>
            </Marker>
          );
        })}

        {exactRoadGeometry.length > 1 && <FitBounds positions={exactRoadGeometry} />}
      </MapContainer>

      {/* Floating Map Legend Overlay */}
      <div className="absolute bottom-3 right-3 bg-white/95 backdrop-blur-md p-2.5 rounded-xl border border-[#E2E8F0] shadow-sm z-[1000] text-[11px] space-y-1.5 font-medium pointer-events-auto">
        <div className="flex items-center gap-2">
          <div className="w-4 h-1 bg-sky-500 rounded-full" />
          <span className="text-[#334155]">Fastest Route</span>
        </div>
        {routeResult?.risk_aware_route && (
          <div className="flex items-center gap-2">
            <div className="w-4 h-1 bg-emerald-500 border-t border-dashed border-emerald-400" />
            <span className="text-[#334155]">Risk-Aware Path</span>
          </div>
        )}
        <div className="flex items-center gap-2">
          <div className="w-2.5 h-2.5 rounded-full bg-[#F97316] border border-white" />
          <span className="text-[#334155]">Planned Charging Stop</span>
        </div>
        {disabledChargers.length > 0 && (
          <div className="flex items-center gap-2">
            <div className="w-2.5 h-2.5 rounded-full bg-rose-500 border border-white animate-pulse" />
            <span className="text-rose-600 font-semibold">{disabledChargers.length} Simulated Outage</span>
          </div>
        )}
      </div>
    </div>
  );
}
