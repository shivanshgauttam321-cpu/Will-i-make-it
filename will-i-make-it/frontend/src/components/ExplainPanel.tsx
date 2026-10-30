import { useState } from 'react';
import { 
  Info, AlertTriangle, Volume2, VolumeX, ShieldCheck, 
  BookOpen, ChevronRight, Sparkles, Activity, Layers, Radio
} from 'lucide-react';
import { getSarvamStatus, explainRoute } from '../utils/api';
import { playCockpitClick } from '../utils/audioService';
import type { RoutePlanResponse, VehicleProfile } from '../types/api';

interface Props {
  routeResult: RoutePlanResponse | null;
  vehicle: VehicleProfile;
}

export default function ExplainPanel({ routeResult, vehicle }: Props) {
  const [sarvamStatus, setSarvamStatus] = useState<{ configured: boolean; message: string } | null>(null);
  const [ttsAudio, setTtsAudio] = useState<string | null>(null);
  const [ttsLoading, setTtsLoading] = useState(false);
  const [ttsError, setTtsError] = useState<string | null>(null);
  const [explainText, setExplainText] = useState<string | null>(null);

  const fetchSarvamStatus = async () => {
    try {
      const status = await getSarvamStatus();
      setSarvamStatus(status);
    } catch {
      setSarvamStatus({ configured: false, message: 'Sarvam voice service offline or unconfigured.' });
    }
  };

  const handleExplain = async () => {
    if (!routeResult) return;
    playCockpitClick();
    setTtsLoading(true);
    setTtsError(null);
    setTtsAudio(null);
    try {
      const r = await explainRoute(routeResult);
      setExplainText(r.explanation_text);
      if (r.tts_available && r.audio_b64) {
        setTtsAudio(r.audio_b64);
      } else {
        setTtsError(r.tts_error ?? 'TTS server response in text-only mode');
      }
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } }; message?: string })
        ?.response?.data?.detail ?? 'Explain service unavailable';
      setTtsError(msg);
    } finally {
      setTtsLoading(false);
    }
  };

  const playAudio = () => {
    if (!ttsAudio) return;
    try {
      const binary = atob(ttsAudio);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      const blob = new Blob([bytes], { type: 'audio/wav' });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.play();
    } catch {
      // Audio playback fallback
    }
  };

  if (!routeResult) {
    return (
      <div className="cockpit-panel hud-bracket flex flex-col items-center justify-center h-48 text-center text-slate-500">
        <Info size={28} className="mb-2 text-cyan-500/60" />
        <p className="text-sm font-mono font-bold text-slate-300 uppercase">NO ACTIVE ROUTE PLAN</p>
        <p className="text-xs text-slate-500 mt-1 font-sans">Compute a route in Trip Planner to view physical energy contributors & uncertainty.</p>
      </div>
    );
  }

  const route = routeResult.fastest_route;
  const energy = route.energy_result;
  const p50 = energy.total_kwh_p50;
  const p90 = energy.total_kwh_p90;
  const uncertaintyDelta = p90 - p50;
  const uncertaintyPct = ((uncertaintyDelta / (p50 || 1)) * 100).toFixed(1);

  // Compute energy share percentages
  const n = energy.segments.length || 1;
  const avgRoll = energy.segments.reduce((s, x) => s + x.rolling_kj, 0) / n / 3600;
  const avgAero = energy.segments.reduce((s, x) => s + x.aero_kj, 0) / n / 3600;
  const avgGrad = energy.segments.reduce((s, x) => s + Math.max(0, x.gradient_kj), 0) / n / 3600;
  const avgAux = energy.segments.reduce((s, x) => s + x.aux_kj, 0) / n / 3600;
  const avgRegen = energy.segments.reduce((s, x) => s + Math.abs(x.regen_kj), 0) / n / 3600;
  const totalForces = avgRoll + avgAero + avgGrad + avgAux;

  const forceItems = [
    { name: 'Aerodynamic Drag', val: avgAero, color: 'bg-indigo-400', desc: '0.5 · ρ · Cd · A · v²' },
    { name: 'Rolling Resistance', val: avgRoll, color: 'bg-cyan-400', desc: 'Crr · m · g' },
    { name: 'Gradient / Elevation', val: avgGrad, color: 'bg-amber-400', desc: 'm · g · sin(θ)' },
    { name: 'Auxiliary & AC Power', val: avgAux, color: 'bg-emerald-400', desc: 'kW · time' },
  ];

  return (
    <div className="flex flex-col gap-3.5">
      {/* Analytical Disclaimer Banner */}
      <div className="bg-amber-950/20 border border-amber-500/30 rounded-2xl p-3.5">
        <div className="flex items-start gap-2.5">
          <AlertTriangle size={16} className="text-amber-400 shrink-0 mt-0.5" />
          <p className="text-xs text-amber-200/90 leading-relaxed font-sans">
            <span className="font-bold text-amber-100 font-mono">[ANALYTICAL DISCLAIMER]:</span> All energy estimates are 
            derived deterministically from first-principles vehicle dynamics. P90 bounds are log-normal analytical 
            estimates — not validated against independent telemetry datasets.
          </p>
        </div>
      </div>

      {/* 1. Energy Forces Breakdown */}
      <div className="cockpit-panel hud-bracket">
        <p className="label-cap mb-3 flex items-center gap-1.5 text-cyan-300">
          <Layers size={13} className="text-cyan-400" />
          PHYSICAL ENERGY CONTRIBUTORS (PER SEGMENT)
        </p>

        <div className="space-y-3">
          {forceItems.map(item => {
            const pct = Math.min(100, (item.val / Math.max(totalForces, 0.001)) * 100);
            return (
              <div key={item.name}>
                <div className="flex justify-between items-center text-xs mb-1">
                  <div>
                    <span className="font-semibold text-slate-200">{item.name}</span>
                    <span className="text-[10px] text-cyan-400/80 ml-2 font-mono">({item.desc})</span>
                  </div>
                  <span className="font-mono text-slate-300 font-bold">{pct.toFixed(0)}%</span>
                </div>
                <div className="h-2 bg-slate-950 rounded-full overflow-hidden p-0.5 border border-slate-800">
                  <div className={`h-full rounded-full ${item.color}`} style={{ width: `${pct}%` }} />
                </div>
              </div>
            );
          })}
        </div>

        {avgRegen > 0 && (
          <div className="mt-3.5 pt-2.5 border-t border-cyan-900/40 flex items-center justify-between text-xs font-mono">
            <span className="text-emerald-400 font-bold flex items-center gap-1">
              ⚡ Regenerative Braking Recaptured:
            </span>
            <span className="text-emerald-300 font-bold">~{avgRegen.toFixed(2)} kWh/seg</span>
          </div>
        )}
      </div>

      {/* 2. P50 vs P90 Risk & Uncertainty Assessment */}
      <div className="cockpit-panel hud-bracket">
        <p className="label-cap mb-2.5 flex items-center gap-1.5 text-cyan-300">
          <Activity size={13} className="text-cyan-400" />
          UNCERTAINTY & RISK RESERVE SPREAD
        </p>

        <div className="grid grid-cols-2 gap-2.5 mb-3 text-center">
          <div className="card-subtle">
            <span className="text-[10px] text-slate-400 block font-mono">NOMINAL SPREAD</span>
            <span className="font-mono font-black text-amber-400 text-lg">+{uncertaintyDelta.toFixed(1)} kWh</span>
            <span className="text-[10px] text-slate-500 font-mono block mt-0.5">(+{uncertaintyPct}% Reserve)</span>
          </div>
          <div className="card-subtle">
            <span className="text-[10px] text-slate-400 block font-mono">CONFIDENCE BAND</span>
            <span className="font-mono font-black text-cyan-400 text-lg">90% Target</span>
            <span className="text-[10px] text-slate-500 font-mono block mt-0.5">(Log-normal prior)</span>
          </div>
        </div>

        <p className="text-xs text-slate-300 leading-relaxed font-sans">
          The conservative P90 estimate budgets an additional <strong className="text-amber-300 font-mono">{uncertaintyDelta.toFixed(1)} kWh</strong> buffer 
          against highway headwinds, high ambient AC cooling demand, Indian traffic congestion, and battery degradation.
        </p>
      </div>

      {/* 3. Sarvam Voice AI Explanation */}
      <div className="cockpit-panel hud-bracket">
        <div className="flex items-center justify-between mb-2">
          <p className="label-cap flex items-center gap-1.5 text-cyan-300">
            <Radio size={13} className="text-cyan-400" />
            SARVAM MULTILINGUAL VOICE EXPLANATION
          </p>
          <span className="text-[10px] font-mono text-slate-400">Hindi / Indian English</span>
        </div>

        <p className="text-xs text-slate-300 mb-3 font-sans">
          Generates a natural-language voice explanation of why this route was selected, charging station reliability, and safety margins.
        </p>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={handleExplain}
            disabled={ttsLoading}
            className="btn-secondary text-xs flex items-center gap-2 py-2 px-3.5 font-mono font-bold text-cyan-300 border-cyan-500/40"
          >
            {ttsLoading ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-cyan-400 border-t-transparent rounded-full animate-spin" />
                <span>GENERATING VOICE EXPLANATION...</span>
              </>
            ) : (
              <>
                <Sparkles size={14} className="text-cyan-400" />
                <span>EXPLAIN ROUTE (SARVAM AI)</span>
              </>
            )}
          </button>

          {ttsAudio && (
            <button
              type="button"
              onClick={playAudio}
              className="btn-primary text-xs flex items-center gap-1.5 py-2 px-3 font-mono font-bold"
            >
              <Volume2 size={14} />
              <span>PLAY AUDIO</span>
            </button>
          )}
        </div>

        {ttsError && (
          <p className="text-xs text-amber-300 mt-2 font-mono bg-amber-950/40 p-2 rounded-lg border border-amber-800/60">
            Notice: {ttsError}
          </p>
        )}

        {explainText && (
          <div className="mt-3 bg-slate-950 p-3 rounded-xl border border-cyan-950 text-xs text-slate-300 leading-relaxed font-sans">
            <span className="font-bold text-cyan-300 block mb-1 font-mono">[AUDIO SCRIPT]:</span>
            {explainText}
          </div>
        )}
      </div>
    </div>
  );
}
