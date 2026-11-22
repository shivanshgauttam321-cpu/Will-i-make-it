import React, { useState, useEffect, useRef, useMemo } from 'react';
import { 
  Database, RefreshCw, Activity, ShieldCheck, AlertCircle, CheckCircle2, 
  Clock, Server, Layers, Search, Filter, Play, Trash2, ArrowRight,
  ExternalLink, Info, Cpu, Zap, MapPin, Radio, GitBranch
} from 'lucide-react';
import { 
  getNeo4jStats, getNeo4jGraph, getNeo4jSyncStatus, getNeo4jSyncEvents,
  retryNeo4jEvent, triggerNeo4jSync, createDemoInfrastructure,
  updateDemoStation, cleanupDemoData, getNeo4jNode
} from '../utils/api';

interface GraphNode {
  id: string;
  element_id: string;
  label: string;
  labels: string[];
  name: string;
  properties: Record<string, any>;
  provenance: string;
  environment: string;
  x?: number;
  y?: number;
}

interface GraphRel {
  id: string;
  source: string;
  target: string;
  type: string;
  properties: Record<string, any>;
}

interface SyncEvent {
  event_id: string;
  entity_id: string;
  entity_type: string;
  operation: string;
  payload: Record<string, any>;
  status: 'PENDING' | 'PROCESSING' | 'SUCCESS' | 'FAILED' | 'DEAD_LETTER';
  retry_count: number;
  max_retries: number;
  last_attempt_at: string | null;
  last_error: string | null;
  created_at: string;
  processed_at: string | null;
}

export default function Neo4jGraphMonitor() {
  // Navigation tabs within Graph Monitor
  const [activeTab, setActiveTab] = useState<'explorer' | 'events' | 'demo'>('explorer');

  // Connection & stats state
  const [syncStatus, setSyncStatus] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [autoRefresh, setAutoRefresh] = useState<boolean>(true);

  // Graph explorer state
  const [graphData, setGraphData] = useState<{ nodes: GraphNode[]; relationships: GraphRel[] }>({ nodes: [], relationships: [] });
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [nodeDetail, setNodeDetail] = useState<any | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedLabelFilter, setSelectedLabelFilter] = useState<string>('ALL');
  const [selectedEnvFilter, setSelectedEnvFilter] = useState<string>('ALL');
  const [zoomLevel, setZoomLevel] = useState<number>(1);
  const [panOffset, setPanOffset] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const [dragStart, setDragStart] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

  // Sync events state
  const [syncEvents, setSyncEvents] = useState<SyncEvent[]>([]);
  const [eventStatusFilter, setEventStatusFilter] = useState<string>('ALL');
  const [retryingId, setRetryingId] = useState<string | null>(null);

  // Demo panel state
  const [demoActionLoading, setDemoActionLoading] = useState<string | null>(null);
  const [demoFeedback, setDemoFeedback] = useState<{ type: 'success' | 'error' | 'info'; message: string } | null>(null);

  // Initial load
  useEffect(() => {
    loadAllData();
  }, []);

  // Auto-refresh interval
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(() => {
      loadStatusAndEventsOnly();
    }, 6000);
    return () => clearInterval(interval);
  }, [autoRefresh]);

  const loadAllData = async () => {
    setLoading(true);
    try {
      const [statusRes, statsRes, graphRes, eventsRes] = await Promise.all([
        getNeo4jSyncStatus().catch(() => null),
        getNeo4jStats().catch(() => null),
        getNeo4jGraph({ limit: 150 }).catch(() => ({ nodes: [], relationships: [] })),
        getNeo4jSyncEvents({ limit: 40 }).catch(() => ({ events: [] })),
      ]);

      setSyncStatus(statusRes);
      setStats(statsRes);
      if (graphRes && graphRes.nodes) {
        positionNodes(graphRes.nodes, graphRes.relationships || []);
      }
      if (eventsRes && eventsRes.events) {
        setSyncEvents(eventsRes.events);
      }
    } finally {
      setLoading(false);
    }
  };

  const loadStatusAndEventsOnly = async () => {
    setRefreshing(true);
    try {
      const [statusRes, statsRes, eventsRes] = await Promise.all([
        getNeo4jSyncStatus().catch(() => null),
        getNeo4jStats().catch(() => null),
        getNeo4jSyncEvents({ limit: 40 }).catch(() => ({ events: [] })),
      ]);
      setSyncStatus(statusRes);
      setStats(statsRes);
      if (eventsRes && eventsRes.events) {
        setSyncEvents(eventsRes.events);
      }
    } finally {
      setRefreshing(false);
    }
  };

  const reloadGraphOnly = async () => {
    setRefreshing(true);
    try {
      const graphRes = await getNeo4jGraph({
        limit: 150,
        entity_types: selectedLabelFilter === 'ALL' ? undefined : selectedLabelFilter,
        environment: selectedEnvFilter === 'ALL' ? undefined : selectedEnvFilter,
      });
      if (graphRes && graphRes.nodes) {
        positionNodes(graphRes.nodes, graphRes.relationships || []);
      }
    } finally {
      setRefreshing(false);
    }
  };

  // Topological / Radial auto-layout for graph nodes
  const positionNodes = (rawNodes: GraphNode[], rels: GraphRel[]) => {
    const width = 800;
    const height = 500;
    const count = rawNodes.length;

    // Group nodes by label
    const positioned: GraphNode[] = rawNodes.map((n, i) => {
      // Deterministic layout based on label & index
      let radius = 180;
      if (n.label === 'City' || n.label === 'Region') radius = 80;
      else if (n.label === 'ChargingStation' || n.label === 'Charger') radius = 170;
      else if (n.label === 'ChargingConnector' || n.label === 'ChargingReport') radius = 240;
      else if (n.label === 'RoadSegment' || n.label === 'RoadNode') radius = 130;

      const angle = (i / Math.max(1, count)) * 2 * Math.PI + (i % 3);
      const x = width / 2 + radius * Math.cos(angle) + (Math.sin(i * 11) * 30);
      const y = height / 2 + radius * Math.sin(angle) + (Math.cos(i * 7) * 30);
      return { ...n, x, y };
    });

    setGraphData({ nodes: positioned, relationships: rels });
  };

  // Node selection & detail lookup
  const handleSelectNode = async (node: GraphNode) => {
    setSelectedNode(node);
    try {
      const detail = await getNeo4jNode(node.id);
      setNodeDetail(detail);
    } catch {
      setNodeDetail(null);
    }
  };

  // Retry event
  const handleRetryEvent = async (eventId: string) => {
    setRetryingId(eventId);
    try {
      await retryNeo4jEvent(eventId);
      await loadStatusAndEventsOnly();
    } finally {
      setRetryingId(null);
    }
  };

  // Trigger immediate sync
  const handleManualSync = async () => {
    setRefreshing(true);
    try {
      await triggerNeo4jSync();
      await loadAllData();
      setDemoFeedback({ type: 'success', message: 'Synchronization triggered. Outbox dispatched to Neo4j.' });
    } catch (e: any) {
      setDemoFeedback({ type: 'error', message: `Sync failed: ${e.message}` });
    } finally {
      setRefreshing(false);
    }
  };

  // Demo: Create Sample
  const handleCreateDemo = async () => {
    setDemoActionLoading('create');
    setDemoFeedback(null);
    try {
      const res = await createDemoInfrastructure();
      setDemoFeedback({ 
        type: 'success', 
        message: `Created demo infrastructure: Station '${res.station_id}' with ${res.events_created.length} outbox sync events.` 
      });
      await loadAllData();
      setActiveTab('explorer');
    } catch (e: any) {
      setDemoFeedback({ type: 'error', message: `Demo creation failed: ${e.message}` });
    } finally {
      setDemoActionLoading(null);
    }
  };

  // Demo: Update Sample
  const handleUpdateDemo = async () => {
    setDemoActionLoading('update');
    setDemoFeedback(null);
    try {
      const res = await updateDemoStation({
        station_id: 'CHR_DEMO_EXPRESS_01',
        power_kw: 150.0,
        reliability_score: 0.98,
        is_operational: true,
      });
      setDemoFeedback({ 
        type: 'success', 
        message: `Updated demo station to 150 kW capacity (Outbox Event: ${res.event_id}).` 
      });
      await loadAllData();
    } catch (e: any) {
      setDemoFeedback({ type: 'error', message: `Update failed: ${e.message}` });
    } finally {
      setDemoActionLoading(null);
    }
  };

  // Demo: Purge
  const handlePurgeDemo = async () => {
    setDemoActionLoading('purge');
    setDemoFeedback(null);
    try {
      const res = await cleanupDemoData();
      setDemoFeedback({ 
        type: 'info', 
        message: `Demo records purged. Primary DB: ${res.primary_db_cleanup.entities_deleted} entities. Neo4j: ${res.neo4j_nodes_deleted} nodes.` 
      });
      setSelectedNode(null);
      await loadAllData();
    } catch (e: any) {
      setDemoFeedback({ type: 'error', message: `Purge failed: ${e.message}` });
    } finally {
      setDemoActionLoading(null);
    }
  };

  // Node Color Helper
  const getNodeColor = (label: string) => {
    switch (label) {
      case 'ChargingStation':
      case 'Charger':
        return '#f97316'; // Orange
      case 'City':
        return '#06b6d4'; // Cyan
      case 'ChargingOperator':
        return '#a855f7'; // Purple
      case 'ChargingConnector':
        return '#10b981'; // Emerald
      case 'RoadSegment':
      case 'Road':
      case 'Highway':
        return '#3b82f6'; // Blue
      case 'RoadNode':
        return '#64748b'; // Slate
      case 'ChargingReport':
        return '#eab308'; // Amber
      default:
        return '#8b5cf6';
    }
  };

  // Filtering
  const filteredNodes = useMemo(() => {
    return graphData.nodes.filter(n => {
      const matchesSearch = !searchQuery || 
        n.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
        n.id.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesLabel = selectedLabelFilter === 'ALL' || n.label === selectedLabelFilter;
      const matchesEnv = selectedEnvFilter === 'ALL' || n.environment === selectedEnvFilter;
      return matchesSearch && matchesLabel && matchesEnv;
    });
  }, [graphData.nodes, searchQuery, selectedLabelFilter, selectedEnvFilter]);

  const filteredEvents = useMemo(() => {
    return syncEvents.filter(ev => {
      if (eventStatusFilter === 'ALL') return true;
      return ev.status === eventStatusFilter;
    });
  }, [syncEvents, eventStatusFilter]);

  // Canvas Drag / Pan
  const handleMouseDown = (e: React.MouseEvent) => {
    setIsDragging(true);
    setDragStart({ x: e.clientX - panOffset.x, y: e.clientY - panOffset.y });
  };
  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging) return;
    setPanOffset({ x: e.clientX - dragStart.x, y: e.clientY - dragStart.y });
  };
  const handleMouseUp = () => setIsDragging(false);

  return (
    <div className="flex flex-col h-full bg-[#0a0d14] text-slate-200 font-sans overflow-hidden">
      {/* ── TOP MONITOR HEADER ── */}
      <div className="border-b border-[#E2E8F0] bg-white px-5 py-3 flex flex-wrap items-center justify-between gap-3 shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-orange-50 border border-orange-200 flex items-center justify-center text-[#F97316]">
            <Database size={18} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-black tracking-wide text-[#172033] uppercase font-sans">
                Neo4j Graph Monitor & Sync Engine
              </h2>
              <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full border ${
                syncStatus?.status === 'CONNECTED'
                  ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                  : syncStatus?.status === 'DISABLED'
                    ? 'bg-slate-100 text-[#64748B] border-slate-200'
                    : 'bg-rose-50 text-rose-700 border-rose-200'
              }`}>
                {syncStatus?.status || 'CHECKING...'}
              </span>
            </div>
            <p className="text-[11px] text-[#64748B]">
              Live highway corridor topology, charging graph & transactional outbox synchronization
            </p>
          </div>
        </div>

        {/* Global Monitor Controls */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleManualSync}
            disabled={refreshing}
            className="px-2.5 py-1.5 rounded-lg bg-[#F8FAFC] hover:bg-white text-[#334155] hover:text-[#172033] border border-[#CBD5E1] text-xs font-mono transition-all flex items-center gap-1.5 shadow-sm"
            title="Dispatch pending outbox events to Neo4j"
          >
            <GitBranch size={13} className="text-[#F97316]" />
            <span>Sync Outbox</span>
          </button>

          <button
            type="button"
            onClick={loadAllData}
            disabled={refreshing}
            className="px-2.5 py-1.5 rounded-lg bg-[#F8FAFC] hover:bg-white text-[#334155] hover:text-[#172033] border border-[#CBD5E1] text-xs font-mono transition-all flex items-center gap-1.5 shadow-sm"
          >
            <RefreshCw size={12} className={refreshing ? 'animate-spin text-sky-600' : 'text-[#64748B]'} />
            <span>Refresh</span>
          </button>

          <label className="flex items-center gap-1.5 text-[11px] font-mono text-[#64748B] bg-[#F8FAFC] px-2.5 py-1.5 rounded-lg border border-[#CBD5E1] cursor-pointer shadow-sm">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={e => setAutoRefresh(e.target.checked)}
              className="rounded bg-white border-slate-300 text-orange-500 focus:ring-0 w-3.5 h-3.5"
            />
            <span>Auto (6s)</span>
          </label>
        </div>
      </div>

      {/* ── CONNECTION & STATISTICS BAR ── */}
      <div className="border-b border-[#E2E8F0] bg-[#F8FAFC] px-5 py-2.5 grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3 shrink-0 text-xs font-mono">
        <div className="bg-white p-2 rounded-xl border border-[#E2E8F0] shadow-sm">
          <div className="text-[10px] text-[#64748B] uppercase">Database</div>
          <div className="text-[#172033] font-bold truncate mt-0.5">{syncStatus?.database || 'neo4j'}</div>
        </div>

        <div className="bg-white p-2 rounded-xl border border-[#E2E8F0] shadow-sm">
          <div className="text-[10px] text-[#64748B] uppercase">Total Nodes</div>
          <div className="text-sky-600 font-bold mt-0.5">{stats?.total_nodes ?? 0}</div>
        </div>

        <div className="bg-white p-2 rounded-xl border border-[#E2E8F0] shadow-sm">
          <div className="text-[10px] text-[#64748B] uppercase">Relationships</div>
          <div className="text-indigo-600 font-bold mt-0.5">{stats?.total_relationships ?? 0}</div>
        </div>

        <div className="bg-white p-2 rounded-xl border border-[#E2E8F0] shadow-sm">
          <div className="text-[10px] text-[#64748B] uppercase">Outbox Synced</div>
          <div className="text-emerald-600 font-bold mt-0.5">{stats?.outbox_statistics?.success ?? 0}</div>
        </div>

        <div className="bg-white p-2 rounded-xl border border-[#E2E8F0] shadow-sm">
          <div className="text-[10px] text-[#64748B] uppercase">Pending Sync</div>
          <div className="text-amber-600 font-bold mt-0.5">{stats?.outbox_statistics?.pending ?? 0}</div>
        </div>

        <div className="bg-white p-2 rounded-xl border border-[#E2E8F0] shadow-sm">
          <div className="text-[10px] text-[#64748B] uppercase">Sync Worker</div>
          <div className="text-emerald-600 font-bold mt-0.5 flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            {syncStatus?.worker_health || 'RUNNING'}
          </div>
        </div>
      </div>

      {/* ── NAVIGATION TABS ── */}
      <div className="border-b border-[#E2E8F0] bg-white px-5 flex items-center justify-between shrink-0">
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setActiveTab('explorer')}
            className={`px-3 py-2 text-xs font-mono font-medium transition-colors border-b-2 flex items-center gap-1.5 ${
              activeTab === 'explorer'
                ? 'border-orange-500 text-orange-600 font-bold'
                : 'border-transparent text-[#64748B] hover:text-[#172033]'
            }`}
          >
            <Layers size={14} />
            <span>Interactive Graph</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('events')}
            className={`px-3 py-2 text-xs font-mono font-medium transition-colors border-b-2 flex items-center gap-1.5 ${
              activeTab === 'events'
                ? 'border-orange-500 text-orange-600 font-bold'
                : 'border-transparent text-[#64748B] hover:text-[#172033]'
            }`}
          >
            <Clock size={14} />
            <span>Outbox Events ({syncEvents.length})</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('demo')}
            className={`px-3 py-2 text-xs font-mono font-medium transition-colors border-b-2 flex items-center gap-1.5 ${
              activeTab === 'demo'
                ? 'border-orange-500 text-orange-600 font-bold'
                : 'border-transparent text-[#64748B] hover:text-[#172033]'
            }`}
          >
            <Play size={14} className="text-orange-500" />
            <span>2-Min Demo Panel</span>
          </button>
        </div>

        {demoFeedback && (
          <div className={`text-[11px] font-mono px-3 py-1 rounded border flex items-center gap-1.5 ${
            demoFeedback.type === 'success' 
              ? 'bg-emerald-950/60 text-emerald-300 border-emerald-800'
              : demoFeedback.type === 'error'
                ? 'bg-rose-950/60 text-rose-300 border-rose-800'
                : 'bg-cyan-950/60 text-cyan-300 border-cyan-800'
          }`}>
            <span>{demoFeedback.message}</span>
          </div>
        )}
      </div>

      {/* ── TAB 1: INTERACTIVE GRAPH EXPLORER ── */}
      {activeTab === 'explorer' && (
        <div className="flex-1 flex flex-col lg:flex-row min-h-0 overflow-hidden">
          {/* Main Visual Stage */}
          <div className="flex-1 flex flex-col min-w-0 bg-[#080b12] relative overflow-hidden">
            {/* Explorer Filter Bar */}
            <div className="p-3 bg-[#0d121c]/90 backdrop-blur border-b border-[#1a2233] flex flex-wrap items-center justify-between gap-2 z-10">
              <div className="flex items-center gap-2 flex-1 min-w-[200px] max-w-sm">
                <div className="relative w-full">
                  <Search size={13} className="absolute left-2.5 top-2.5 text-slate-500" />
                  <input
                    type="text"
                    placeholder="Search node by name or ID..."
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                    className="w-full bg-[#121724] border border-[#202a3d] rounded-lg pl-8 pr-3 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-orange-500/60"
                  />
                </div>
              </div>

              <div className="flex items-center gap-2 text-xs font-mono">
                {/* Entity Type Filter */}
                <select
                  value={selectedLabelFilter}
                  onChange={e => {
                    setSelectedLabelFilter(e.target.value);
                  }}
                  className="bg-[#121724] border border-[#202a3d] rounded-lg px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none"
                >
                  <option value="ALL">All Entity Labels</option>
                  <option value="ChargingStation">Charging Stations</option>
                  <option value="City">Cities</option>
                  <option value="ChargingOperator">Operators</option>
                  <option value="ChargingConnector">Connectors</option>
                  <option value="RoadSegment">Road Segments</option>
                  <option value="RoadNode">Road Nodes</option>
                  <option value="ChargingReport">Reports</option>
                </select>

                {/* Environment Filter */}
                <select
                  value={selectedEnvFilter}
                  onChange={e => setSelectedEnvFilter(e.target.value)}
                  className="bg-[#121724] border border-[#202a3d] rounded-lg px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none"
                >
                  <option value="ALL">All Environments</option>
                  <option value="DEMO">Demo Seed</option>
                  <option value="PROD">Production Real</option>
                </select>

                <button
                  type="button"
                  onClick={reloadGraphOnly}
                  className="p-1.5 rounded-lg bg-[#121724] hover:bg-[#182030] text-slate-300 border border-[#202a3d]"
                  title="Reload graph elements"
                >
                  <RefreshCw size={13} />
                </button>
              </div>
            </div>

            {/* SVG Visual Graph Stage */}
            <div 
              className="flex-1 cursor-grab active:cursor-grabbing select-none relative overflow-hidden"
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
            >
              {loading ? (
                <div className="absolute inset-0 flex items-center justify-center text-slate-400 font-mono text-xs">
                  <RefreshCw size={16} className="animate-spin text-orange-400 mr-2" />
                  Loading graph entities from Neo4j Aura...
                </div>
              ) : filteredNodes.length === 0 ? (
                <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-500 font-mono text-xs p-6 text-center">
                  <Database size={32} className="text-slate-600 mb-2" />
                  <p className="text-slate-300 font-bold mb-1">No Graph Entities Loaded</p>
                  <p className="text-slate-500 max-w-sm mb-4">
                    {syncStatus?.status === 'DISABLED'
                      ? 'Neo4j is disabled in configuration. Enable NEO4J_ENABLED=true in backend/.env to query live graph nodes.'
                      : 'No graph nodes match current filters, or database is currently unseeded.'}
                  </p>
                  <button
                    type="button"
                    onClick={() => setActiveTab('demo')}
                    className="px-3 py-1.5 rounded-lg bg-orange-500/20 text-orange-400 border border-orange-500/40 text-xs font-mono hover:bg-orange-500/30 transition-all flex items-center gap-1.5"
                  >
                    <Play size={12} />
                    <span>Open 2-Min Demo Panel</span>
                  </button>
                </div>
              ) : (
                <svg className="w-full h-full">
                  <g transform={`translate(${panOffset.x}, ${panOffset.y}) scale(${zoomLevel})`}>
                    {/* Render Relationships / Edges */}
                    {graphData.relationships.map((rel, idx) => {
                      const srcNode = graphData.nodes.find(n => n.id === rel.source);
                      const dstNode = graphData.nodes.find(n => n.id === rel.target);
                      if (!srcNode || !dstNode || !srcNode.x || !srcNode.y || !dstNode.x || !dstNode.y) return null;

                      const midX = (srcNode.x + dstNode.x) / 2;
                      const midY = (srcNode.y + dstNode.y) / 2;

                      return (
                        <g key={rel.id || `rel_${idx}`} className="transition-opacity">
                          <line
                            x1={srcNode.x}
                            y1={srcNode.y}
                            x2={dstNode.x}
                            y2={dstNode.y}
                            stroke="#2a364f"
                            strokeWidth="1.5"
                            strokeDasharray={rel.type === 'REPORTS_STATUS' ? '3,3' : 'none'}
                          />
                          <text
                            x={midX}
                            y={midY}
                            fill="#64748b"
                            fontSize="9"
                            fontFamily="monospace"
                            textAnchor="middle"
                            dy="-3"
                            className="pointer-events-none select-none"
                          >
                            {rel.type}
                          </text>
                        </g>
                      );
                    })}

                    {/* Render Graph Nodes */}
                    {filteredNodes.map(node => {
                      const isSelected = selectedNode?.id === node.id;
                      const color = getNodeColor(node.label);

                      return (
                        <g
                          key={node.id}
                          transform={`translate(${node.x}, ${node.y})`}
                          onClick={e => {
                            e.stopPropagation();
                            handleSelectNode(node);
                          }}
                          className="cursor-pointer transition-transform hover:scale-110"
                        >
                          <circle
                            r={isSelected ? 18 : 13}
                            fill={color}
                            fillOpacity="0.25"
                            stroke={color}
                            strokeWidth={isSelected ? 2.5 : 1.5}
                          />
                          <circle r={isSelected ? 6 : 4} fill={color} />
                          <text
                            x="0"
                            y="24"
                            fill="#cbd5e1"
                            fontSize="10"
                            fontFamily="sans-serif"
                            textAnchor="middle"
                            className="pointer-events-none font-medium select-none"
                          >
                            {node.name.length > 18 ? node.name.slice(0, 16) + '...' : node.name}
                          </text>
                        </g>
                      );
                    })}
                  </g>
                </svg>
              )}

              {/* Zoom Controls Overlay */}
              <div className="absolute bottom-3 right-3 flex items-center gap-1.5 bg-[#101622]/90 backdrop-blur border border-[#1e273b] p-1 rounded-lg text-xs font-mono">
                <button
                  type="button"
                  onClick={() => setZoomLevel(z => Math.max(0.4, z - 0.2))}
                  className="px-2 py-0.5 hover:bg-slate-800 rounded text-slate-300"
                >
                  -
                </button>
                <span className="text-[10px] text-slate-400 px-1">{Math.round(zoomLevel * 100)}%</span>
                <button
                  type="button"
                  onClick={() => setZoomLevel(z => Math.min(2.5, z + 0.2))}
                  className="px-2 py-0.5 hover:bg-slate-800 rounded text-slate-300"
                >
                  +
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setZoomLevel(1);
                    setPanOffset({ x: 0, y: 0 });
                  }}
                  className="px-1.5 py-0.5 hover:bg-slate-800 rounded text-slate-400 text-[10px]"
                >
                  Reset
                </button>
              </div>
            </div>
          </div>

          {/* Right Inspector Sidebar */}
          <div className="w-full lg:w-80 xl:w-96 border-t lg:border-t-0 lg:border-l border-[#1c2436] bg-[#0c101a] p-4 flex flex-col overflow-y-auto shrink-0 text-xs">
            <h3 className="text-xs font-bold text-white uppercase font-mono tracking-wider mb-3 flex items-center gap-1.5">
              <Info size={14} className="text-cyan-400" />
              <span>Node Inspector</span>
            </h3>

            {selectedNode ? (
              <div className="space-y-3 font-sans">
                {/* Node Title & Identity */}
                <div className="p-3 bg-[#111726] rounded-lg border border-[#1e283d]">
                  <div className="flex items-center justify-between mb-1.5">
                    <span 
                      className="text-[10px] font-mono px-2 py-0.5 rounded-full border font-bold"
                      style={{ 
                        color: getNodeColor(selectedNode.label),
                        borderColor: `${getNodeColor(selectedNode.label)}40`,
                        backgroundColor: `${getNodeColor(selectedNode.label)}15`
                      }}
                    >
                      {selectedNode.label}
                    </span>
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800/60 text-slate-400 border border-slate-700/50">
                      {selectedNode.environment}
                    </span>
                  </div>
                  <h4 className="font-bold text-white text-sm">{selectedNode.name}</h4>
                  <div className="text-[10px] font-mono text-slate-500 mt-1 break-all">
                    ID: {selectedNode.id}
                  </div>
                </div>

                {/* Provenance Badge */}
                <div className="p-2.5 bg-[#0f1422] rounded-lg border border-[#1a2233] text-[11px]">
                  <span className="text-[10px] font-mono text-slate-500 block">DATA PROVENANCE</span>
                  <div className="flex items-center gap-1.5 mt-0.5 font-mono font-bold text-amber-400">
                    <ShieldCheck size={13} />
                    <span>{selectedNode.provenance}</span>
                  </div>
                </div>

                {/* Property Map */}
                <div>
                  <span className="text-[10px] font-mono text-slate-500 uppercase tracking-wider block mb-1.5">
                    Node Properties
                  </span>
                  <div className="bg-[#101624] rounded-lg border border-[#1d273a] p-2.5 space-y-1.5 font-mono text-[11px] max-h-56 overflow-y-auto">
                    {Object.entries(selectedNode.properties || {}).map(([k, v]) => (
                      <div key={k} className="flex justify-between items-start gap-2 border-b border-slate-800/40 pb-1">
                        <span className="text-slate-400 truncate">{k}:</span>
                        <span className="text-slate-200 text-right break-all">
                          {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Relationships Degree */}
                {nodeDetail && (
                  <div>
                    <span className="text-[10px] font-mono text-slate-500 uppercase tracking-wider block mb-1.5">
                      Graph Relationships
                    </span>
                    <div className="bg-[#101624] rounded-lg border border-[#1d273a] p-2.5 space-y-1.5 text-[11px] font-mono max-h-40 overflow-y-auto">
                      {nodeDetail.outgoing_relationships?.map((r: any, idx: number) => (
                        <div key={`out_${idx}`} className="text-slate-300 flex items-center gap-1.5">
                          <span className="text-indigo-400 font-bold">-[{r.type}]-&gt;</span>
                          <span className="text-slate-400 truncate">{r.target}</span>
                        </div>
                      ))}
                      {nodeDetail.incoming_relationships?.map((r: any, idx: number) => (
                        <div key={`in_${idx}`} className="text-slate-300 flex items-center gap-1.5">
                          <span className="text-slate-400 truncate">{r.source}</span>
                          <span className="text-cyan-400 font-bold">-[{r.type}]-&gt;</span>
                        </div>
                      ))}
                      {(!nodeDetail.outgoing_relationships?.length && !nodeDetail.incoming_relationships?.length) && (
                        <div className="text-slate-500 text-[10px]">No direct relationships linked yet.</div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex-1 flex flex-col items-center justify-center text-slate-500 font-mono text-center p-4">
                <Info size={24} className="mb-2 text-slate-600" />
                <p>Click on any node in the graph explorer to inspect properties, labels, and connected graph edges.</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── TAB 2: OUTBOX SYNCHRONIZATION EVENT MONITOR ── */}
      {activeTab === 'events' && (
        <div className="flex-1 p-5 flex flex-col min-h-0 overflow-y-auto font-mono text-xs">
          {/* Outbox Event Filters */}
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <div className="flex items-center gap-2">
              <span className="text-slate-400 text-xs">Filter Status:</span>
              {['ALL', 'PENDING', 'SUCCESS', 'FAILED', 'DEAD_LETTER'].map(st => (
                <button
                  key={st}
                  type="button"
                  onClick={() => setEventStatusFilter(st)}
                  className={`px-2.5 py-1 rounded text-[11px] transition-colors border ${
                    eventStatusFilter === st
                      ? 'bg-orange-500/20 text-orange-400 border-orange-500/40 font-bold'
                      : 'bg-[#121622] text-slate-400 border-[#20293d] hover:text-white'
                  }`}
                >
                  {st}
                </button>
              ))}
            </div>

            <button
              type="button"
              onClick={handleManualSync}
              className="px-3 py-1.5 rounded-lg bg-orange-600 hover:bg-orange-500 text-white font-mono text-xs font-bold transition-all shadow flex items-center gap-1.5"
            >
              <GitBranch size={13} />
              <span>Process Pending Events</span>
            </button>
          </div>

          {/* Events Table */}
          <div className="flex-1 overflow-x-auto bg-[#0d121c] rounded-xl border border-[#1e273b]">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-[#1c2538] bg-[#111726] text-[11px] text-slate-400">
                  <th className="py-2.5 px-3">Event ID</th>
                  <th className="py-2.5 px-3">Entity Type</th>
                  <th className="py-2.5 px-3">Entity ID</th>
                  <th className="py-2.5 px-3">Operation</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3">Retries</th>
                  <th className="py-2.5 px-3">Created At</th>
                  <th className="py-2.5 px-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/40 font-mono">
                {filteredEvents.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="py-8 text-center text-slate-500">
                      No transactional outbox events found matching criteria.
                    </td>
                  </tr>
                ) : (
                  filteredEvents.map(ev => (
                    <tr key={ev.event_id} className="hover:bg-[#121826] transition-colors">
                      <td className="py-2.5 px-3 text-cyan-400 font-bold">{ev.event_id}</td>
                      <td className="py-2.5 px-3 text-white">{ev.entity_type}</td>
                      <td className="py-2.5 px-3 text-slate-300 truncate max-w-[140px]" title={ev.entity_id}>
                        {ev.entity_id}
                      </td>
                      <td className="py-2.5 px-3">
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          ev.operation === 'CREATE'
                            ? 'bg-emerald-500/20 text-emerald-400'
                            : ev.operation === 'UPDATE'
                              ? 'bg-blue-500/20 text-blue-400'
                              : 'bg-rose-500/20 text-rose-400'
                        }`}>
                          {ev.operation}
                        </span>
                      </td>
                      <td className="py-2.5 px-3">
                        <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${
                          ev.status === 'SUCCESS'
                            ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                            : ev.status === 'PENDING'
                              ? 'bg-amber-500/15 text-amber-400 border-amber-500/30'
                              : 'bg-rose-500/15 text-rose-400 border-rose-500/30'
                        }`}>
                          {ev.status}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 text-slate-400">
                        {ev.retry_count} / {ev.max_retries}
                      </td>
                      <td className="py-2.5 px-3 text-slate-500 text-[11px]">
                        {ev.created_at.slice(11, 19)}
                      </td>
                      <td className="py-2.5 px-3 text-right">
                        {(ev.status === 'FAILED' || ev.status === 'DEAD_LETTER') && (
                          <button
                            type="button"
                            onClick={() => handleRetryEvent(ev.event_id)}
                            disabled={retryingId === ev.event_id}
                            className="px-2 py-1 rounded bg-[#1e293b] hover:bg-[#28354d] text-orange-400 text-[11px] font-mono transition-colors"
                          >
                            {retryingId === ev.event_id ? 'Retrying...' : 'Retry'}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── TAB 3: 2-MINUTE DEMONSTRATION PANEL ── */}
      {activeTab === 'demo' && (
        <div className="flex-1 p-5 overflow-y-auto space-y-5 max-w-4xl">
          <div className="bg-[#0f1420] border border-orange-500/30 rounded-xl p-5 shadow-lg">
            <div className="flex items-center gap-2 mb-2">
              <Play size={18} className="text-orange-400" />
              <h3 className="text-sm font-bold text-white uppercase font-sans tracking-wide">
                Automated 2-Minute Neo4j Aura Demonstration Workflow
              </h3>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed font-sans mb-4">
              Demonstrates automatic website-to-Neo4j synchronization. Every button below commits
              a transaction to the primary SQLite database, records a transactional outbox event, and syncs
              interconnected graph nodes into Neo4j without requiring manual Cypher writes.
            </p>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {/* Step 1: Create */}
              <div className="bg-[#131929] border border-[#222c42] rounded-lg p-3.5 flex flex-col justify-between">
                <div>
                  <div className="text-[10px] font-mono text-orange-400 font-bold mb-1">STEP 1: CREATE</div>
                  <h4 className="text-xs font-bold text-white mb-1">Add Demo Infrastructure</h4>
                  <p className="text-[11px] text-slate-400 mb-3">
                    Creates Demo City (Navi Mumbai), Operator (Jio-bp), Charging Station (60 kW), Connector, and Corridor Link.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={handleCreateDemo}
                  disabled={demoActionLoading === 'create'}
                  className="w-full py-2 rounded-lg bg-orange-600 hover:bg-orange-500 text-white font-mono text-xs font-bold transition-all shadow flex items-center justify-center gap-1.5"
                >
                  <Play size={12} />
                  <span>{demoActionLoading === 'create' ? 'Creating...' : '1. Create Infrastructure'}</span>
                </button>
              </div>

              {/* Step 2: Update */}
              <div className="bg-[#131929] border border-[#222c42] rounded-lg p-3.5 flex flex-col justify-between">
                <div>
                  <div className="text-[10px] font-mono text-cyan-400 font-bold mb-1">STEP 2: UPDATE</div>
                  <h4 className="text-xs font-bold text-white mb-1">Upgrade Station Power</h4>
                  <p className="text-[11px] text-slate-400 mb-3">
                    Upgrades the existing station in SQLite from 60 kW to 150 kW and updates Neo4j via idempotent MERGE.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={handleUpdateDemo}
                  disabled={demoActionLoading === 'update'}
                  className="w-full py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-mono text-xs font-bold transition-all shadow flex items-center justify-center gap-1.5"
                >
                  <Zap size={12} />
                  <span>{demoActionLoading === 'update' ? 'Updating...' : '2. Upgrade to 150 kW'}</span>
                </button>
              </div>

              {/* Step 3: Cleanup */}
              <div className="bg-[#131929] border border-[#222c42] rounded-lg p-3.5 flex flex-col justify-between">
                <div>
                  <div className="text-[10px] font-mono text-rose-400 font-bold mb-1">STEP 3: CLEANUP</div>
                  <h4 className="text-xs font-bold text-white mb-1">Purge Demo Records</h4>
                  <p className="text-[11px] text-slate-400 mb-3">
                    Safely purges only records tagged with environment = 'DEMO'. Production infrastructure remains untouched.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={handlePurgeDemo}
                  disabled={demoActionLoading === 'purge'}
                  className="w-full py-2 rounded-lg bg-rose-600/80 hover:bg-rose-500 text-white font-mono text-xs font-bold transition-all shadow flex items-center justify-center gap-1.5"
                >
                  <Trash2 size={12} />
                  <span>{demoActionLoading === 'purge' ? 'Purging...' : '3. Purge Demo Records'}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
