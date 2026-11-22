import React from 'react';
import { 
  Navigation, CheckCircle2, Zap, BarChart3, Radio, 
  Volume2, VolumeX, ShieldCheck, Database, Layers, Mic
} from 'lucide-react';

export type ActiveView = 'planner' | 'results' | 'energy' | 'chargers' | 'voice' | 'explain' | 'graph';

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
      id: 'voice',
      label: 'Voice AI',
      icon: <Mic size={18} />,
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
    <nav className="w-full lg:w-20 bg-[#FFFFFF] border-b lg:border-b-0 lg:border-r border-[#E2E8F0] flex lg:flex-col items-center justify-between p-2 lg:py-4 shrink-0 z-30 select-none shadow-sm">
      {/* Brand Icon */}
      <div 
        onClick={() => onViewChange('planner')}
        className="w-10 h-10 rounded-xl bg-[#F8FAFC] border border-[#E2E8F0] flex items-center justify-center cursor-pointer hover:border-orange-500/50 transition-all shadow-sm group shrink-0"
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
                  ? 'bg-[#F97316] text-white shadow-md shadow-orange-500/25 font-semibold'
                  : 'text-[#64748B] hover:text-[#172033] hover:bg-[#F1F4F8]'
              }`}
              title={item.label}
            >
              {item.icon}
              <span className="text-[10px] font-sans font-medium tracking-tight mt-1 leading-none">
                {item.label}
              </span>

              {/* Notification Badge */}
              {item.badge !== undefined && item.badge > 0 && (
                <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-rose-500 text-white text-[9px] font-mono font-bold flex items-center justify-center shadow-sm">
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
              ? 'bg-[#FFF7ED] border-orange-200 text-orange-600 hover:text-orange-700'
              : 'bg-[#F8FAFC] border-[#E2E8F0] text-[#94A3B8] hover:text-[#64748B]'
          }`}
          title={soundOn ? 'Sound Synthesizer Active (Click to mute)' : 'Sound Synthesizer Muted'}
        >
          {soundOn ? <Volume2 size={15} /> : <VolumeX size={15} />}
        </button>

        {/* Backend Connectivity Status Dot */}
        <div 
          className="w-3 h-3 rounded-full border-2 border-white flex items-center justify-center cursor-help shadow-sm"
          title={`Backend API: ${backendOk ? 'Online' : 'Offline'} · Neo4j: ${neo4jOk ? 'Active' : 'Fallback'}`}
        >
          <div className={`w-2 h-2 rounded-full ${
            backendOk === null 
              ? 'bg-slate-400' 
              : backendOk 
                ? 'bg-emerald-500' 
                : 'bg-rose-500'
          }`} />
        </div>
      </div>
    </nav>
  );
}
