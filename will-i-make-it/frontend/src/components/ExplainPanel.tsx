import { useState, useRef } from 'react';
import { 
  Info, AlertTriangle, Volume2, VolumeX, ShieldCheck, 
  BookOpen, ChevronRight, Sparkles, Activity, Layers, Radio, Mic, MicOff, Send, MessageSquare
} from 'lucide-react';
import { getSarvamStatus, explainRoute, converseWithSarvam } from '../utils/api';
import { playCockpitClick, playChargeZap } from '../utils/audioService';
import type { RoutePlanResponse, VehicleProfile } from '../types/api';

interface Props {
  routeResult: RoutePlanResponse | null;
  vehicle: VehicleProfile;
}

export default function ExplainPanel({ routeResult, vehicle }: Props) {
  // TTS & Route Explanation states
  const [ttsAudio, setTtsAudio] = useState<string | null>(null);
  const [ttsLoading, setTtsLoading] = useState(false);
  const [ttsError, setTtsError] = useState<string | null>(null);
  const [explainText, setExplainText] = useState<string | null>(null);
  const [selectedLang, setSelectedLang] = useState<'hi-IN' | 'en-IN'>('hi-IN');
  const [selectedSpeaker, setSelectedSpeaker] = useState('meera');

  // Conversational Assistant states
  const [conversePrompt, setConversePrompt] = useState('');
  const [isRecording, setIsRecording] = useState(false);
  const [converseLoading, setConverseLoading] = useState(false);
  const [converseResponse, setConverseResponse] = useState<any>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  const handleExplain = async () => {
    if (!routeResult) return;
    playCockpitClick();
    setTtsLoading(true);
    setTtsError(null);
    setTtsAudio(null);
    try {
      const r = await explainRoute(routeResult, selectedLang);
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

  const playBase64Audio = (b64Audio: string) => {
    try {
      const binary = atob(b64Audio);
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

  const handleConverseSubmit = async (customText?: string) => {
    const textToSend = customText ?? conversePrompt;
    if (!textToSend.trim()) return;
    playCockpitClick();
    setConverseLoading(true);
    try {
      const resp = await converseWithSarvam({
        text: textToSend,
        language_code: selectedLang,
        speak_response: true,
        speaker: selectedSpeaker,
      });
      setConverseResponse(resp);
      playChargeZap();
      if (resp.audio_b64) {
        playBase64Audio(resp.audio_b64);
      }
    } catch (e: any) {
      setConverseResponse({
        explanation: e.response?.data?.detail || 'Conversational service unavailable. Check Sarvam API key in .env.',
        intent: 'ERROR',
        feasible: false,
      });
    } finally {
      setConverseLoading(false);
    }
  };

  const startVoiceRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioChunksRef.current = [];
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data);
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/wav' });
        const reader = new FileReader();
        reader.readAsDataURL(audioBlob);
        reader.onloadend = async () => {
          const base64Data = (reader.result as string).split(',')[1];
          setConverseLoading(true);
          try {
            const resp = await converseWithSarvam({
              audio_b64: base64Data,
              language_code: selectedLang,
              speak_response: true,
              speaker: selectedSpeaker,
            });
            setConverseResponse(resp);
            if (resp.transcript) setConversePrompt(resp.transcript);
            if (resp.audio_b64) playBase64Audio(resp.audio_b64);
          } catch (e: any) {
            setConverseResponse({
              explanation: e.response?.data?.detail || 'Voice processing error.',
              intent: 'ERROR',
            });
          } finally {
            setConverseLoading(false);
          }
        };
      };

      mediaRecorder.start();
      setIsRecording(true);
      playCockpitClick();
    } catch {
      alert('Microphone access was denied or is not supported in this browser.');
    }
  };

  const stopVoiceRecording = () => {
    if (mediaRecorderRef.current && isRecording) {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
      playCockpitClick();
    }
  };

  if (!routeResult) {
    return (
      <div className="bg-[#121620] border border-[#222938] rounded-2xl flex flex-col items-center justify-center h-48 text-center text-slate-500 p-4">
        <Info size={26} className="mb-2 text-slate-400" />
        <p className="text-sm font-mono font-bold text-slate-300 uppercase">NO ACTIVE ROUTE PLAN</p>
        <p className="text-xs text-slate-500 mt-1">Compute a route in Trip Planner to view physical energy contributors & uncertainty.</p>
      </div>
    );
  }

  const route = routeResult.fastest_route;
  const energy = route.energy_result;
  const p50 = energy.total_kwh_p50;
  const p90 = energy.total_kwh_p90;
  const uncertaintyDelta = p90 - p50;
  const uncertaintyPct = ((uncertaintyDelta / (p50 || 1)) * 100).toFixed(1);

  const n = energy.segments.length || 1;
  const avgRoll = energy.segments.reduce((s, x) => s + x.rolling_kj, 0) / n / 3600;
  const avgAero = energy.segments.reduce((s, x) => s + x.aero_kj, 0) / n / 3600;
  const avgGrad = energy.segments.reduce((s, x) => s + Math.max(0, x.gradient_kj), 0) / n / 3600;
  const avgAux = energy.segments.reduce((s, x) => s + x.aux_kj, 0) / n / 3600;
  const avgRegen = energy.segments.reduce((s, x) => s + Math.abs(x.regen_kj), 0) / n / 3600;
  const totalForces = avgRoll + avgAero + avgGrad + avgAux;

  const forceItems = [
    { name: 'Aerodynamic Drag', val: avgAero, color: 'bg-blue-500', desc: '0.5 · ρ · Cd · A · v²' },
    { name: 'Rolling Resistance', val: avgRoll, color: 'bg-cyan-500', desc: 'Crr · m · g' },
    { name: 'Gradient / Elevation', val: avgGrad, color: 'bg-orange-500', desc: 'm · g · sin(θ)' },
    { name: 'Auxiliary & AC Power', val: avgAux, color: 'bg-emerald-500', desc: 'kW · time' },
  ];

  return (
    <div className="flex flex-col gap-4">
      {/* Analytical Disclaimer Banner */}
      <div className="bg-[#1c1610] border border-orange-500/30 rounded-2xl p-4 shadow-xl">
        <div className="flex items-start gap-3">
          <AlertTriangle size={16} className="text-orange-400 shrink-0 mt-0.5" />
          <div>
            <h4 className="text-xs font-mono font-bold text-orange-400 uppercase tracking-wider mb-0.5">
              ANALYTICAL PHYSICS DISCLAIMER
            </h4>
            <p className="text-xs text-orange-200/90 leading-relaxed">
              All energy estimates are derived deterministically from first-principles vehicle dynamics. 
              P90 bounds are log-normal analytical estimates labeled as <strong className="font-mono text-orange-400">MODEL_BASED_P90_ESTIMATE</strong>.
            </p>
          </div>
        </div>
      </div>

      {/* 1. Energy Forces Breakdown */}
      <div className="bg-[#121620] border border-[#222938] rounded-2xl p-4 shadow-xl">
        <div className="flex items-center gap-2 mb-3 border-b border-[#1e2535] pb-2">
          <Layers size={14} className="text-orange-400" />
          <h3 className="text-xs font-bold font-mono tracking-wider text-slate-200 uppercase">
            PHYSICAL ENERGY CONTRIBUTORS (PER SEGMENT)
          </h3>
        </div>

        <div className="space-y-3">
          {forceItems.map(item => {
            const pct = Math.min(100, (item.val / Math.max(totalForces, 0.001)) * 100);
            return (
              <div key={item.name}>
                <div className="flex justify-between items-center text-xs mb-1">
                  <div>
                    <span className="font-semibold text-slate-200">{item.name}</span>
                    <span className="text-[10px] text-slate-500 ml-2 font-mono">({item.desc})</span>
                  </div>
                  <span className="font-mono text-slate-300 font-bold">{pct.toFixed(0)}%</span>
                </div>
                <div className="h-2 bg-[#0e1219] rounded-full overflow-hidden p-0.5 border border-[#1e2535]">
                  <div className={`h-full rounded-full ${item.color}`} style={{ width: `${pct}%` }} />
                </div>
              </div>
            );
          })}
        </div>

        {avgRegen > 0 && (
          <div className="mt-3.5 pt-2.5 border-t border-[#1e2535] flex items-center justify-between text-xs font-mono">
            <span className="text-emerald-400 font-bold flex items-center gap-1">
              ⚡ Regenerative Braking Recaptured:
            </span>
            <span className="text-emerald-300 font-bold">~{avgRegen.toFixed(2)} kWh/seg</span>
          </div>
        )}
      </div>

      {/* 2. P50 vs P90 Risk & Uncertainty Assessment */}
      <div className="bg-[#121620] border border-[#222938] rounded-2xl p-4 shadow-xl">
        <div className="flex items-center gap-2 mb-2.5 border-b border-[#1e2535] pb-2">
          <Activity size={14} className="text-orange-400" />
          <h3 className="text-xs font-bold font-mono tracking-wider text-slate-200 uppercase">
            UNCERTAINTY & RISK RESERVE SPREAD
          </h3>
        </div>

        <div className="grid grid-cols-2 gap-2.5 mb-3 text-center">
          <div className="bg-[#0e1219] border border-[#1e2535] rounded-xl p-3">
            <span className="text-[10px] text-slate-400 block font-mono uppercase">NOMINAL SPREAD</span>
            <span className="font-mono font-black text-orange-400 text-lg">+{uncertaintyDelta.toFixed(1)} kWh</span>
            <span className="text-[10px] text-slate-500 font-mono block mt-0.5">(+{uncertaintyPct}% Reserve)</span>
          </div>
          <div className="bg-[#0e1219] border border-[#1e2535] rounded-xl p-3">
            <span className="text-[10px] text-slate-400 block font-mono uppercase">CONFIDENCE BAND</span>
            <span className="font-mono font-black text-teal-400 text-lg">90% Target</span>
            <span className="text-[10px] text-slate-500 font-mono block mt-0.5">(Log-normal prior)</span>
          </div>
        </div>

        <p className="text-xs text-slate-300 leading-relaxed">
          The conservative P90 estimate budgets an additional <strong className="text-orange-400 font-mono">{uncertaintyDelta.toFixed(1)} kWh</strong> buffer 
          against highway headwinds, high ambient AC cooling demand, Indian traffic congestion, and battery degradation.
        </p>
      </div>

      {/* 3. Interactive Multilingual Voice & AI Assistant (Phase 2 Master Feature) */}
      <div className="bg-[#121620] border border-[#222938] rounded-2xl p-4 shadow-xl">
        <div className="flex items-center justify-between mb-2 border-b border-[#1e2535] pb-2">
          <div className="flex items-center gap-2">
            <Radio size={14} className="text-orange-400" />
            <h3 className="text-xs font-bold font-mono tracking-wider text-slate-200 uppercase">
              SARVAM MULTILINGUAL CONVERSATIONAL ASSISTANT
            </h3>
          </div>
          <div className="flex items-center gap-2">
            {/* Language Toggle */}
            <select
              value={selectedLang}
              onChange={(e) => setSelectedLang(e.target.value as any)}
              className="bg-[#0e1219] text-xs text-slate-300 font-mono border border-[#1e2535] rounded-lg px-2 py-1 outline-none"
            >
              <option value="hi-IN">Hindi (hi-IN)</option>
              <option value="en-IN">Indian English (en-IN)</option>
            </select>
            {/* Speaker Selector */}
            <select
              value={selectedSpeaker}
              onChange={(e) => setSelectedSpeaker(e.target.value)}
              className="bg-[#0e1219] text-xs text-slate-300 font-mono border border-[#1e2535] rounded-lg px-2 py-1 outline-none hidden sm:block"
            >
              <option value="meera">Speaker: Meera</option>
              <option value="pavithra">Speaker: Pavithra</option>
              <option value="maitreyi">Speaker: Maitreyi</option>
              <option value="arvind">Speaker: Arvind</option>
              <option value="amol">Speaker: Amol</option>
            </select>
          </div>
        </div>

        <p className="text-xs text-slate-300 mb-3">
          Ask questions naturally in Hindi, English, or Hinglish. Grounded in authoritative physics results.
        </p>

        {/* Quick prompt suggestions */}
        <div className="flex flex-wrap gap-1.5 mb-3">
          {[
            'Can my EV reach Jaipur with 80% battery?',
            'Mujhe Jaipur pahunchne ke liye kitni battery chahiye?',
            'Find charging stops from Mumbai to Pune',
            'Explain why I cannot complete this journey',
          ].map((prompt) => (
            <button
              key={prompt}
              type="button"
              onClick={() => {
                setConversePrompt(prompt);
                handleConverseSubmit(prompt);
              }}
              className="text-[10px] bg-[#181e2b] hover:bg-[#202738] text-slate-300 hover:text-white px-2.5 py-1 rounded-lg border border-[#273244] font-mono transition-all text-left"
            >
              "{prompt}"
            </button>
          ))}
        </div>

        {/* Input box with Mic recording */}
        <div className="flex items-center gap-2 bg-[#0a0e14] border border-[#1e2535] rounded-xl p-1.5 focus-within:border-orange-500/50">
          <input
            type="text"
            value={conversePrompt}
            onChange={(e) => setConversePrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleConverseSubmit();
            }}
            placeholder="Type your question or click mic to speak..."
            className="bg-transparent text-xs text-white placeholder-slate-500 flex-1 px-2.5 outline-none font-sans"
          />

          {/* Voice Record Button */}
          <button
            type="button"
            onClick={isRecording ? stopVoiceRecording : startVoiceRecording}
            className={`p-2 rounded-lg font-mono text-xs transition-all flex items-center gap-1 ${
              isRecording
                ? 'bg-rose-500 text-white animate-pulse'
                : 'bg-[#181e2b] hover:bg-[#222a3a] text-orange-400 border border-[#262f42]'
            }`}
            title={isRecording ? 'Click to stop recording' : 'Click to speak via Sarvam STT'}
          >
            {isRecording ? <MicOff size={14} /> : <Mic size={14} />}
            <span className="hidden sm:inline text-[10px]">{isRecording ? 'RECORDING' : 'VOICE'}</span>
          </button>

          {/* Submit button */}
          <button
            type="button"
            onClick={() => handleConverseSubmit()}
            disabled={converseLoading || !conversePrompt.trim()}
            className="p-2 bg-orange-500 hover:bg-orange-600 disabled:opacity-50 text-white rounded-lg transition-all"
          >
            <Send size={14} />
          </button>
        </div>

        {/* Loading Spinner */}
        {converseLoading && (
          <div className="flex items-center gap-2 text-xs text-orange-400 mt-2 font-mono">
            <div className="w-3.5 h-3.5 border-2 border-orange-400 border-t-transparent rounded-full animate-spin" />
            <span>PROCESSING GROUNDED SIMULATION...</span>
          </div>
        )}

        {/* Conversational Result Display */}
        {converseResponse && (
          <div className="mt-3 bg-[#0a0e14] p-3 rounded-xl border border-[#1e2535] text-xs">
            <div className="flex items-center justify-between mb-1.5 flex-wrap gap-2">
              <div className="flex items-center gap-1.5">
                <MessageSquare size={13} className="text-orange-400" />
                <span className="font-bold text-orange-400 font-mono text-[11px]">
                  INTENT: {converseResponse.intent}
                </span>
              </div>
              {converseResponse.feasibility_status && (
                <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full border font-bold ${
                  converseResponse.feasible 
                    ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
                    : 'bg-rose-500/15 text-rose-400 border-rose-500/30'
                }`}>
                  {converseResponse.feasibility_status}
                </span>
              )}
            </div>

            <p className="text-slate-200 leading-relaxed font-sans mb-2">
              {converseResponse.explanation}
            </p>

            {converseResponse.audio_b64 && (
              <button
                type="button"
                onClick={() => playBase64Audio(converseResponse.audio_b64)}
                className="bg-[#181e2b] hover:bg-[#202738] text-slate-200 border border-[#262f42] text-[11px] flex items-center gap-1.5 py-1 px-2.5 rounded-lg font-mono font-bold transition-all"
              >
                <Volume2 size={13} className="text-orange-400" />
                <span>LISTEN TO SPEECH RESPONSE</span>
              </button>
            )}
          </div>
        )}

        {/* Direct Route Explanation fallback button */}
        <div className="mt-4 pt-3 border-t border-[#1e2535] flex items-center justify-between flex-wrap gap-2">
          <button
            type="button"
            onClick={handleExplain}
            disabled={ttsLoading}
            className="bg-[#181e2b] hover:bg-[#222a3a] text-slate-300 hover:text-white border border-[#262f42] font-semibold text-xs flex items-center gap-1.5 py-2 px-3 rounded-xl transition-all disabled:opacity-50 font-mono"
          >
            {ttsLoading ? (
              <>
                <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                <span>EXPLAINING ROUTE...</span>
              </>
            ) : (
              <>
                <Sparkles size={13} className="text-orange-400" />
                <span>EXPLAIN ACTIVE ROUTE</span>
              </>
            )}
          </button>

          {ttsAudio && (
            <button
              type="button"
              onClick={() => playBase64Audio(ttsAudio)}
              className="bg-[#181e2b] hover:bg-[#202738] text-slate-200 hover:text-white border border-[#262f42] text-xs flex items-center gap-1.5 py-1.5 px-3 rounded-xl font-mono font-bold transition-all"
            >
              <Volume2 size={13} className="text-orange-400" />
              <span>PLAY ROUTE AUDIO</span>
            </button>
          )}
        </div>

        {ttsError && (
          <p className="text-xs text-amber-300 mt-2 font-mono bg-[#1c1610] p-2 rounded-xl border border-orange-500/30">
            Notice: {ttsError}
          </p>
        )}

        {explainText && !converseResponse && (
          <div className="mt-2.5 bg-[#0a0e14] p-2.5 rounded-xl border border-[#1e2535] text-xs text-slate-300 leading-relaxed font-sans">
            <span className="font-bold text-orange-400 block mb-0.5 font-mono">[AUDIO SCRIPT]:</span>
            {explainText}
          </div>
        )}
      </div>
    </div>
  );
}
