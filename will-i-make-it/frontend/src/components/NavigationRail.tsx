import React from 'react';
import { 
  Navigation, CheckCircle2, Zap, BarChart3, Radio, 
  Volume2, VolumeX, ShieldCheck, Database, Layers
} from 'lucide-react';

export type ActiveView = 'planner' | 'results' | 'energy' | 'chargers' | 'explain' | 'graph';

interface Props {
  activeView: ActiveView;
  onViewChange: (view: ActiveView) => void;
  hasResult: boolean;
  disabledChargersCount: number;
  soundOn: boolean;
  onToggleSound: () => void;
  backendOk: boolean | null;
  neo4jOk: boolean;
}

export default function NavigationRail({
  activeView,
  onViewChange,
  hasResult,
  disabledChargersCount,
  soundOn,
  onToggleSound,
  backendOk,
  neo4jOk,
}: Props) {
  const navItems: { id: ActiveView; label: string; icon: React.ReactNode; badge?: number; enabled: boolean }[] = [
    {
      id: 'planner',
      label: 'Planner',
      icon: <Navigation size={18} />,
      enabled: true,
    },
    {
      id: 'results',
      label: 'Results',
      icon: <CheckCircle2 size={18} />,
      enabled: true,
    },
    {
      id: 'energy',
      label: 'Energy',
      icon: <BarChart3 size={18} />,
      enabled: true,
    },
    {
      id: 'chargers',
      label: 'Stations',
      icon: <Zap size={18} />,
      badge: disabledChargersCount > 0 ? disabledChargersCount : undefined,
      enabled: true,
    },
    {
      id: 'explain',
      label: 'Explain',
      icon: <Radio size={18} />,
      enabled: true,
    },
    {
      id: 'graph',
      label: 'Graph',
      icon: <Database size={18} />,
      enabled: true,
    },
  ];

  return (
    <nav className="w-full lg:w-20 bg-[#0e1219] border-b lg:border-b-0 lg:border-r border-[#1e2535] flex lg:flex-col items-center justify-between p-2 lg:py-4 shrink-0 z-30 select-none">
      {/* Brand Icon */}
      <div 
        onClick={() => onViewChange('planner')}
        className="w-10 h-10 rounded-xl bg-[#151a24] border border-[#252e3f] flex items-center justify-center cursor-pointer hover:border-orange-500/50 transition-all shadow-sm group shrink-0"
        title="Will I Make It? EV Route Intelligence"
      >
        <img 
          src="/assets/logo/will-i-make-it.svg" 
          alt="Logo" 
          className="w-7 h-7 transition-transform group-hover:scale-105" 
        />
      </div>

      {/* Primary Navigation Icons */}
      <div className="flex lg:flex-col items-center gap-1 sm:gap-2 my-auto">
        {navItems.map(item => {
          const isActive = activeView === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onViewChange(item.id)}
              className={`relative flex flex-col items-center justify-center w-12 h-12 lg:w-14 lg:h-14 rounded-2xl transition-all ${
                isActive
                  ? 'bg-orange-500 text-white shadow-md shadow-orange-950/40 font-bold'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-[#161c28]'
              }`}
              title={item.label}
            >
              {item.icon}
              <span className="text-[10px] font-sans font-medium tracking-tight mt-1 leading-none">
                {item.label}
              </span>

              {/* Notification Badge */}
              {item.badge !== undefined && item.badge > 0 && (
                <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-rose-500 text-white text-[9px] font-mono font-bold flex items-center justify-center">
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Bottom Quick Controls & Diagnostics */}
      <div className="flex lg:flex-col items-center gap-2 shrink-0">
        {/* Sound Toggle */}
        <button
          type="button"
          onClick={onToggleSound}
          className={`w-9 h-9 rounded-xl border flex items-center justify-center transition-all ${
            soundOn
              ? 'bg-[#181e2b] border-[#252e3f] text-orange-400 hover:text-orange-300'
              : 'bg-[#10141d] border-[#1e2535] text-slate-500 hover:text-slate-400'
          }`}
          title={soundOn ? 'Sound Synthesizer Active (Click to mute)' : 'Sound Synthesizer Muted'}
        >
          {soundOn ? <Volume2 size={15} /> : <VolumeX size={15} />}
        </button>

        {/* Backend Connectivity Status Dot */}
        <div 
          className="w-3 h-3 rounded-full border-2 border-[#0e1219] flex items-center justify-center cursor-help"
          title={`Backend API: ${backendOk ? 'Online' : 'Offline'} · Neo4j: ${neo4jOk ? 'Active' : 'Fallback'}`}
        >
          <div className={`w-2 h-2 rounded-full ${
            backendOk === null 
              ? 'bg-slate-500' 
              : backendOk 
                ? 'bg-emerald-400 animate-pulse' 
                : 'bg-rose-500'
          }`} />
        </div>
      </div>
    </nav>
  );
}
