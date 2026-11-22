import React, { useState, useEffect, useRef } from 'react';
import {
  Mic, MicOff, Send, Volume2, VolumeX, Play, Pause, RotateCcw,
  Sparkles, AlertTriangle, ShieldCheck, Activity, Zap, CheckCircle2,
  XCircle, Radio, Clock, ArrowRight, Settings, Info, RefreshCw, MessageSquare
} from 'lucide-react';
import {
  speechToText, converseWithSarvam, textToSpeech, getSarvamHealth
} from '../utils/api';
import { playCockpitClick, playChargeZap } from '../utils/audioService';
import type { RoutePlanResponse, VehicleProfile } from '../types/api';

interface Props {
  vehicle: VehicleProfile;
  currentRoute: RoutePlanResponse | null;
  onApplyRoute: (route: RoutePlanResponse) => void;
}

export default function SarvamVoiceAssistant({ vehicle, currentRoute, onApplyRoute }: Props) {
  // Voice & Interaction Language
  const [selectedLang, setSelectedLang] = useState<'hi-IN' | 'en-IN'>('en-IN');
  const [selectedSpeaker, setSelectedSpeaker] = useState('simran');

  // Recording & Transcription states
  const [isRecording, setIsRecording] = useState(false);
  const [recordSeconds, setRecordSeconds] = useState(0);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [transcribedText, setTranscribedText] = useState('');
  const [hasEditedTranscript, setHasEditedTranscript] = useState(false);

  // Conversational Feasibility simulation states
  const [isSimulating, setIsSimulating] = useState(false);
  const [simulationResponse, setSimulationResponse] = useState<any>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Audio Playback states
  const [audioBase64, setAudioBase64] = useState<string | null>(null);
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);
  const [audioDuration, setAudioDuration] = useState(0);
  const [audioCurrentTime, setAudioCurrentTime] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Health Panel states
  const [healthData, setHealthData] = useState<any>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [showHealthPanel, setShowHealthPanel] = useState(false);

  // MediaRecorder & timer refs
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const timerIntervalRef = useRef<any>(null);

  // Fetch Sarvam health on mount
  useEffect(() => {
    loadHealth();
  }, []);

  const loadHealth = async () => {
    setHealthLoading(true);
    try {
      const data = await getSarvamHealth();
      setHealthData(data);
    } catch {
      // Graceful fallback
    } finally {
      setHealthLoading(false);
    }
  };

  // Clean up timer on unmount
  useEffect(() => {
    return () => {
      if (timerIntervalRef.current) clearInterval(timerIntervalRef.current);
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
    };
  }, []);

  // Format seconds to mm:ss
  const formatTimer = (sec: number) => {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  // 1. START AUDIO RECORDING
  const startRecording = async () => {
    playCockpitClick();
    setErrorMessage(null);
    audioChunksRef.current = [];

    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error('Microphone access is not supported by your browser.');
      }

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
        }
      });

      // Prefer standard mime types
      let mimeType = 'audio/webm';
      if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) {
        mimeType = 'audio/webm;codecs=opus';
      } else if (MediaRecorder.isTypeSupported('audio/ogg;codecs=opus')) {
        mimeType = 'audio/ogg;codecs=opus';
      } else if (MediaRecorder.isTypeSupported('audio/wav')) {
        mimeType = 'audio/wav';
      }

      const mediaRecorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = mediaRecorder;

      mediaRecorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        // Stop all stream tracks to release microphone hardware light
        stream.getTracks().forEach(track => track.stop());

        if (audioChunksRef.current.length === 0) {
          setIsTranscribing(false);
          return;
        }

        const audioBlob = new Blob(audioChunksRef.current, { type: mimeType });
        await handleAudioUploadForTranscription(audioBlob);
      };

      mediaRecorder.start(250); // Slice chunks every 250ms
      setIsRecording(true);
      setRecordSeconds(0);

      // Start elapsed timer
      timerIntervalRef.current = setInterval(() => {
        setRecordSeconds((prev) => {
          if (prev >= 29) {
            // Sarvam max REST audio is 30 seconds
            stopRecording();
            return 30;
          }
          return prev + 1;
        });
      }, 1000);

    } catch (err: any) {
      setIsRecording(false);
      setErrorMessage(
        err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError'
          ? 'Microphone permission was denied. Please allow microphone access in your browser address bar.'
          : `Audio recording error: ${err.message || 'Unable to access microphone'}`
      );
    }
  };

  // 2. STOP RECORDING & TRIGGER STT
  const stopRecording = () => {
    if (timerIntervalRef.current) {
      clearInterval(timerIntervalRef.current);
      timerIntervalRef.current = null;
    }

    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
      setIsTranscribing(true);
      playCockpitClick();
    }
  };

  // Convert Blob to Base64 and invoke /api/sarvam/stt
  const handleAudioUploadForTranscription = async (blob: Blob) => {
    setIsTranscribing(true);
    setErrorMessage(null);

    try {
      const reader = new FileReader();
      reader.readAsDataURL(blob);
      reader.onloadend = async () => {
        const base64Data = (reader.result as string).split(',')[1];
        try {
          const sttRes = await speechToText(base64Data, selectedLang);
          const transcript = sttRes.transcript || '';
          setTranscribedText(transcript);
          setHasEditedTranscript(false);
          playChargeZap();
          loadHealth(); // Refresh health stats
        } catch (err: any) {
          const detail = err.response?.data?.detail || err.message || 'Speech-to-text service error.';
          setErrorMessage(detail);
        } finally {
          setIsTranscribing(false);
        }
      };
    } catch (e: any) {
      setErrorMessage(`Failed to process recorded audio: ${e.message}`);
      setIsTranscribing(false);
    }
  };

  // 3. SUBMIT EDITABLE TRANSCRIPTION TO CONVERSATIONAL SIMULATION
  const handleFeasibilitySubmit = async (overrideText?: string) => {
    const query = (overrideText ?? transcribedText).trim();
    if (!query) {
      setErrorMessage('Please record speech or enter a destination query.');
      return;
    }

    playCockpitClick();
    setIsSimulating(true);
    setErrorMessage(null);
    setSimulationResponse(null);

    try {
      const res = await converseWithSarvam({
        text: query,
        language_code: selectedLang,
        speak_response: true,
        speaker: selectedSpeaker,
      });

      setSimulationResponse(res);
      playChargeZap();

      if (res.audio_b64) {
        setAudioBase64(res.audio_b64);
        playSpokenAudio(res.audio_b64);
      }

      loadHealth(); // Refresh last request timestamp
    } catch (err: any) {
      const detail = err.response?.data?.detail || err.message || 'Simulation processing failed.';
      setErrorMessage(detail);
    } finally {
      setIsSimulating(false);
    }
  };

  // 4. AUDIO PLAYBACK CONTROLS
  const playSpokenAudio = (b64Audio: string) => {
    try {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }

      const binary = atob(b64Audio);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      const blob = new Blob([bytes], { type: 'audio/wav' });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;

      audio.onloadedmetadata = () => {
        setAudioDuration(audio.duration || 0);
      };

      audio.ontimeupdate = () => {
        setAudioCurrentTime(audio.currentTime || 0);
      };

      audio.onplay = () => setIsPlayingAudio(true);
      audio.onpause = () => setIsPlayingAudio(false);
      audio.onended = () => {
        setIsPlayingAudio(false);
        setAudioCurrentTime(0);
      };

      audio.play().catch(() => {
        // Browser autoplay restriction handling
        setIsPlayingAudio(false);
      });
    } catch {
      setIsPlayingAudio(false);
    }
  };

  const toggleAudioPlay = () => {
    if (!audioRef.current && audioBase64) {
      playSpokenAudio(audioBase64);
      return;
    }
    if (audioRef.current) {
      if (isPlayingAudio) {
        audioRef.current.pause();
      } else {
        audioRef.current.play().catch(() => {});
      }
    }
  };

  const restartAudio = () => {
    if (audioRef.current) {
      audioRef.current.currentTime = 0;
      audioRef.current.play().catch(() => {});
    } else if (audioBase64) {
      playSpokenAudio(audioBase64);
    }
  };

  // 5. TEST CONNECTIVITY PROBE
  const handleTestProbe = async () => {
    playCockpitClick();
    setErrorMessage(null);
    try {
      const testTxt = selectedLang === 'hi-IN' ? 'परीक्षण' : 'Connection verified';
      const r = await textToSpeech(testTxt, selectedLang, selectedSpeaker);
      if (r.audio_b64) {
        playSpokenAudio(r.audio_b64);
      }
      loadHealth();
    } catch (e: any) {
      setErrorMessage(e.response?.data?.detail || 'Connection test probe failed.');
    }
  };

  return (
    <div className="flex flex-col gap-4 max-w-full">
      {/* ── TOP HEADER & CONTROLS ── */}
      <div className="bg-white border border-[#E2E8F0] rounded-2xl p-4 shadow-sm">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-orange-50 border border-orange-200 flex items-center justify-center text-[#F97316]">
              <Mic size={20} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-bold text-[#172033] tracking-wide">
                  SARVAM AI VOICE ASSISTANT
                </h3>
                <span className="text-[10px] bg-orange-50 text-orange-700 border border-orange-200 font-mono font-bold px-2 py-0.5 rounded-full">
                  BILINGUAL STT / TTS
                </span>
              </div>
              <p className="text-xs text-[#64748B]">
                Speak naturally in English or Hindi to test journey feasibility and receive spoken physics calculations.
              </p>
            </div>
          </div>

          {/* Language and Diagnostic Toggle */}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                playCockpitClick();
                setSelectedLang(selectedLang === 'en-IN' ? 'hi-IN' : 'en-IN');
              }}
              className="px-3 py-1.5 rounded-xl bg-[#F8FAFC] hover:bg-white text-xs font-mono font-bold text-[#172033] border border-[#CBD5E1] transition-all flex items-center gap-1.5 shadow-sm"
              title="Toggle English / Hindi speech recognition"
            >
              <span>{selectedLang === 'en-IN' ? '🇺🇸 English (en-IN)' : '🇮🇳 हिंदी (hi-IN)'}</span>
            </button>

            <button
              type="button"
              onClick={() => {
                playCockpitClick();
                setShowHealthPanel(!showHealthPanel);
              }}
              className={`p-2 rounded-xl text-xs font-mono transition-all border ${
                showHealthPanel 
                  ? 'bg-[#F97316] text-white border-orange-500 shadow-sm' 
                  : 'bg-[#F8FAFC] text-[#64748B] hover:text-[#172033] border-[#CBD5E1]'
              }`}
              title="Toggle Sarvam Operational Diagnostics Panel"
            >
              <Activity size={15} />
            </button>
          </div>
        </div>

        {/* ── EXPANDABLE HEALTH & DIAGNOSTICS PANEL ── */}
        {showHealthPanel && (
          <div className="mt-4 pt-3 border-t border-[#F1F4F8] animate-in fade-in duration-200">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <ShieldCheck size={14} className="text-emerald-600" />
                <span className="text-xs font-mono font-bold text-[#172033] uppercase tracking-wider">
                  SARVAM AI SERVICE HEALTH & MODEL SPECIFICATION
                </span>
              </div>
              <button
                type="button"
                onClick={loadHealth}
                disabled={healthLoading}
                className="text-[11px] font-mono text-[#64748B] hover:text-orange-600 flex items-center gap-1"
              >
                <RefreshCw size={12} className={healthLoading ? 'animate-spin' : ''} />
                <span>Refresh</span>
              </button>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
              <div className="bg-[#F8FAFC] p-2.5 rounded-xl border border-[#E2E8F0]">
                <span className="text-[10px] text-[#64748B] uppercase font-mono block">STT Model</span>
                <span className="font-mono font-bold text-orange-600">
                  {healthData?.stt_model || 'saaras:v4'}
                </span>
                <span className="text-[10px] text-emerald-700 block mt-0.5">
                  ● {healthData?.stt_status || 'READY'}
                </span>
              </div>

              <div className="bg-[#F8FAFC] p-2.5 rounded-xl border border-[#E2E8F0]">
                <span className="text-[10px] text-[#64748B] uppercase font-mono block">TTS Model</span>
                <span className="font-mono font-bold text-orange-600">
                  {healthData?.tts_model || 'bulbul:v3'}
                </span>
                <span className="text-[10px] text-emerald-700 block mt-0.5">
                  ● {healthData?.tts_status || 'READY'}
                </span>
              </div>

              <div className="bg-[#F8FAFC] p-2.5 rounded-xl border border-[#E2E8F0]">
                <span className="text-[10px] text-[#64748B] uppercase font-mono block">Speaker Persona</span>
                <select
                  value={selectedSpeaker}
                  onChange={(e) => setSelectedSpeaker(e.target.value)}
                  className="bg-transparent text-xs font-mono font-bold text-[#172033] focus:outline-none w-full"
                >
                  <option value="simran">Simran (Voice Assistant)</option>
                  <option value="ritu">Ritu (Warm & Articulate)</option>
                  <option value="aditya">Aditya (Clear Male)</option>
                  <option value="shubh">Shubh (Conversational)</option>
                  <option value="anushka">Anushka (Expressive)</option>
                </select>
                <span className="text-[10px] text-[#64748B] block mt-0.5">Automotive Persona</span>
              </div>

              <div className="bg-[#F8FAFC] p-2.5 rounded-xl border border-[#E2E8F0]">
                <span className="text-[10px] text-[#64748B] uppercase font-mono block">Activity Total</span>
                <span className="font-mono font-bold text-[#172033]">
                  STT: {healthData?.stt_call_count ?? 0} | TTS: {healthData?.tts_call_count ?? 0}
                </span>
                <button
                  type="button"
                  onClick={handleTestProbe}
                  className="text-[10px] text-orange-600 hover:underline block mt-0.5 font-mono"
                >
                  Probe Live Audio &rarr;
                </button>
              </div>
            </div>

            {healthData?.last_error && (
              <div className="mt-2 p-2 bg-rose-50 border border-rose-200 rounded-xl text-[11px] text-rose-700 font-mono">
                Last Error: {healthData.last_error}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── MAIN INTERACTIVE VOICE COCKPIT ── */}
      <div className="bg-white border border-[#E2E8F0] rounded-2xl p-5 shadow-sm flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Radio size={15} className={isRecording ? 'text-rose-500 animate-pulse' : 'text-[#64748B]'} />
            <span className="text-xs font-mono font-bold text-[#172033] uppercase tracking-wider">
              {isRecording 
                ? 'RECORDING AUDIO (SPEAK NOW)...' 
                : isTranscribing 
                ? 'TRANSCRIBING SPEECH VIA SARVAM STT...'
                : isSimulating
                ? 'EVALUATING ROUTE PHYSICS...'
                : 'VOICE INPUT COCKPIT'}
            </span>
          </div>

          {isRecording && (
            <div className="flex items-center gap-2 bg-rose-50 border border-rose-200 px-2.5 py-1 rounded-full text-xs font-mono font-bold text-rose-700 animate-pulse">
              <span className="w-2 h-2 rounded-full bg-rose-500" />
              <span>{formatTimer(recordSeconds)} / 00:30</span>
            </div>
          )}
        </div>

        {/* Microphone Action Area */}
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4 py-3 bg-[#F8FAFC] border border-[#E2E8F0] rounded-2xl p-4">
          {!isRecording ? (
            <button
              type="button"
              onClick={startRecording}
              disabled={isTranscribing || isSimulating}
              className="relative group flex items-center justify-center w-16 h-16 rounded-full bg-[#F97316] hover:bg-[#EA580C] text-white shadow-md hover:scale-105 active:scale-95 transition-all disabled:opacity-50"
              title="Click to start voice recording"
            >
              <Mic size={26} className="transition-transform group-hover:scale-110" />
            </button>
          ) : (
            <button
              type="button"
              onClick={stopRecording}
              className="relative group flex items-center justify-center w-16 h-16 rounded-full bg-rose-600 text-white shadow-md animate-pulse hover:scale-105 active:scale-95 transition-all"
              title="Click to stop recording and transcribe"
            >
              <MicOff size={26} />
            </button>
          )}

          <div className="text-center sm:text-left">
            <p className="text-sm font-bold text-[#172033]">
              {isRecording ? 'Listening to speech...' : 'Click microphone to record your journey question'}
            </p>
            <p className="text-xs text-[#64748B] mt-0.5">
              {selectedLang === 'en-IN'
                ? 'Example: "Can my EV travel from Jaipur to Delhi with 80 percent battery?"'
                : 'उदाहरण: "क्या मेरी गाड़ी 80 प्रतिशत बैटरी के साथ जयपुर से दिल्ली जा सकती है?"'}
            </p>
          </div>
        </div>

        {/* ── EDITABLE TRANSCRIPTION DISPLAY ── */}
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between text-xs">
            <label className="font-mono text-[#64748B] flex items-center gap-1.5 font-semibold">
              <MessageSquare size={13} className="text-[#F97316]" />
              <span>TRANSCRIBED TEXT QUERY (EDITABLE BEFORE SUBMISSION):</span>
            </label>
            {transcribedText && (
              <button
                type="button"
                onClick={() => {
                  setTranscribedText('');
                  setSimulationResponse(null);
                }}
                className="text-[#64748B] hover:text-[#172033] text-[11px] font-mono"
              >
                Clear
              </button>
            )}
          </div>

          <div className="relative">
            <textarea
              value={transcribedText}
              onChange={(e) => {
                setTranscribedText(e.target.value);
                setHasEditedTranscript(true);
              }}
              placeholder={
                selectedLang === 'en-IN'
                  ? 'Transcribed speech will appear here. You can also type or edit your question directly...'
                  : 'बोला गया वाक्य यहाँ दिखाई देगा। आप इसे सीधे टाइप या संपादित भी कर सकते हैं...'
              }
              rows={3}
              className="w-full bg-[#F8FAFC] border border-[#CBD5E1] focus:bg-white focus:border-orange-500 rounded-xl p-3 text-sm text-[#172033] placeholder:text-slate-400 focus:outline-none resize-none font-sans leading-relaxed transition-all shadow-inner"
            />
            {isTranscribing && (
              <div className="absolute inset-0 bg-white/80 backdrop-blur-sm rounded-xl flex items-center justify-center gap-2 text-xs font-mono text-orange-600">
                <div className="w-4 h-4 border-2 border-orange-500 border-t-transparent rounded-full animate-spin" />
                <span>SARVAM SAARAS RECOGNIZING SPEECH...</span>
              </div>
            )}
          </div>

          {/* Quick Prompt Pills */}
          <div className="flex items-center gap-1.5 flex-wrap pt-1">
            <span className="text-[10px] font-mono text-[#64748B]">Quick Prompts:</span>
            <button
              type="button"
              onClick={() => {
                setTranscribedText('Can my EV travel from Jaipur to Delhi with 80 percent battery?');
                handleFeasibilitySubmit('Can my EV travel from Jaipur to Delhi with 80 percent battery?');
              }}
              className="text-[11px] bg-[#F8FAFC] hover:bg-white text-[#334155] hover:text-[#172033] border border-[#E2E8F0] hover:border-orange-400 px-2.5 py-1 rounded-lg transition-all font-mono shadow-sm"
            >
              Jaipur to Delhi (80%)
            </button>
            <button
              type="button"
              onClick={() => {
                setSelectedLang('hi-IN');
                setTranscribedText('क्या मेरी गाड़ी 80 प्रतिशत बैटरी के साथ जयपुर से दिल्ली जा सकती है?');
                handleFeasibilitySubmit('क्या मेरी गाड़ी 80 प्रतिशत बैटरी के साथ जयपुर से दिल्ली जा सकती है?');
              }}
              className="text-[11px] bg-[#F8FAFC] hover:bg-white text-[#334155] hover:text-[#172033] border border-[#E2E8F0] hover:border-orange-400 px-2.5 py-1 rounded-lg transition-all font-mono shadow-sm"
            >
              जयपुर से दिल्ली (80%)
            </button>
            <button
              type="button"
              onClick={() => {
                setTranscribedText('Can I reach Pune from Mumbai with 30 percent battery?');
                handleFeasibilitySubmit('Can I reach Pune from Mumbai with 30 percent battery?');
              }}
              className="text-[11px] bg-[#F8FAFC] hover:bg-white text-[#334155] hover:text-[#172033] border border-[#E2E8F0] hover:border-orange-400 px-2.5 py-1 rounded-lg transition-all font-mono shadow-sm"
            >
              Mumbai to Pune (30%)
            </button>
          </div>

          {/* Submit Action */}
          <div className="flex items-center justify-end gap-2 mt-2">
            <button
              type="button"
              onClick={() => handleFeasibilitySubmit()}
              disabled={isSimulating || !transcribedText.trim()}
              className="px-5 py-2.5 rounded-xl bg-[#F97316] hover:bg-[#EA580C] disabled:opacity-50 text-white text-xs font-mono font-bold tracking-wide transition-all shadow-md flex items-center gap-2"
            >
              {isSimulating ? (
                <>
                  <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  <span>SIMULATING POWERTRAIN...</span>
                </>
              ) : (
                <>
                  <Send size={14} />
                  <span>CALCULATE FEASIBILITY</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Error Notice */}
        {errorMessage && (
          <div className="bg-rose-50 border border-rose-200 rounded-xl p-3 flex items-start gap-2.5 text-xs text-rose-800">
            <AlertTriangle size={15} className="text-rose-600 shrink-0 mt-0.5" />
            <div className="min-w-0">
              <strong className="block font-mono uppercase text-rose-700 text-[10px]">
                Interaction Alert
              </strong>
              <p className="mt-0.5">{errorMessage}</p>
            </div>
          </div>
        )}
      </div>

      {/* ── GROUNDED SIMULATION RESULT & AUDIO PLAYBACK ── */}
      {simulationResponse && (
        <div className="bg-white border border-[#E2E8F0] rounded-2xl p-5 shadow-sm flex flex-col gap-4 animate-in fade-in duration-300">
          <div className="flex items-center justify-between flex-wrap gap-2 pb-3 border-b border-[#F1F4F8]">
            <div className="flex items-center gap-2">
              {simulationResponse.feasible ? (
                <CheckCircle2 size={18} className="text-emerald-600" />
              ) : (
                <XCircle size={18} className="text-rose-600" />
              )}
              <span className="text-xs font-mono font-bold text-[#172033] uppercase tracking-wider">
                PHYSICAL FEASIBILITY RESULT
              </span>
            </div>

            <span className={`text-xs font-mono font-bold px-3 py-1 rounded-full border ${
              simulationResponse.feasible 
                ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                : 'bg-rose-50 text-rose-700 border-rose-200'
            }`}>
              {simulationResponse.feasibility_status || (simulationResponse.feasible ? 'WILL MAKE IT' : 'WILL NOT MAKE IT')}
            </span>
          </div>

          {/* Physical Metrics Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
            <div className="bg-[#F8FAFC] p-3 rounded-xl border border-[#E2E8F0]">
              <span className="text-[10px] text-[#64748B] uppercase font-mono block">Route Corridor</span>
              <span className="font-bold text-[#172033] truncate block">
                {simulationResponse.entities?.origin} &rarr; {simulationResponse.entities?.destination}
              </span>
              <span className="text-[10px] text-[#64748B] block mt-0.5 font-mono">
                {simulationResponse.entities?.distance_km?.toFixed(1)} km
              </span>
            </div>

            <div className="bg-[#F8FAFC] p-3 rounded-xl border border-[#E2E8F0]">
              <span className="text-[10px] text-[#64748B] uppercase font-mono block">Arrival Battery</span>
              <span className={`font-mono font-bold text-sm ${simulationResponse.feasible ? 'text-emerald-700' : 'text-rose-700'}`}>
                {simulationResponse.arrival_soc_p90_pct?.toFixed(0)}% P90
              </span>
              <span className="text-[10px] text-[#64748B] block mt-0.5">
                Start: {simulationResponse.entities?.soc_start_pct?.toFixed(0)}%
              </span>
            </div>

            <div className="bg-[#F8FAFC] p-3 rounded-xl border border-[#E2E8F0]">
              <span className="text-[10px] text-[#64748B] uppercase font-mono block">Estimated Energy</span>
              <span className="font-mono font-bold text-sm text-orange-600">
                {simulationResponse.energy_p50_kwh?.toFixed(1)} kWh
              </span>
              <span className="text-[10px] text-[#64748B] block mt-0.5 font-mono">
                P90: {simulationResponse.energy_p90_kwh?.toFixed(1)} kWh
              </span>
            </div>

            <div className="bg-[#F8FAFC] p-3 rounded-xl border border-[#E2E8F0]">
              <span className="text-[10px] text-[#64748B] uppercase font-mono block">Charging Stops</span>
              <span className="font-mono font-bold text-sm text-sky-700">
                {simulationResponse.charging_stops_count ?? 0} Stops
              </span>
              <span className="text-[10px] text-[#64748B] block mt-0.5">
                {simulationResponse.charging_stops_count > 0 ? 'Required' : 'Non-stop feasible'}
              </span>
            </div>
          </div>

          {/* Natural Language Spoken Explanation */}
          <div className="bg-[#F8FAFC] p-4 rounded-xl border border-[#E2E8F0]">
            <span className="text-[10px] font-mono font-bold text-orange-700 uppercase tracking-wider block mb-1">
              GROUNDED NATURAL LANGUAGE EXPLANATION
            </span>
            <p className="text-sm text-[#172033] leading-relaxed font-sans">
              {simulationResponse.explanation}
            </p>
          </div>

          {/* Spoken Audio Controls Bar */}
          {audioBase64 && (
            <div className="bg-[#F1F4F8] border border-[#CBD5E1] rounded-xl p-3 flex items-center justify-between flex-wrap gap-3">
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={toggleAudioPlay}
                  className="w-9 h-9 rounded-full bg-[#F97316] hover:bg-[#EA580C] text-white flex items-center justify-center transition-all shadow-md"
                  title={isPlayingAudio ? 'Pause Voice' : 'Play Voice'}
                >
                  {isPlayingAudio ? <Pause size={16} /> : <Play size={16} className="ml-0.5" />}
                </button>

                <button
                  type="button"
                  onClick={restartAudio}
                  className="w-8 h-8 rounded-full bg-white text-[#334155] hover:text-[#172033] border border-[#CBD5E1] flex items-center justify-center transition-all shadow-sm"
                  title="Replay from start"
                >
                  <RotateCcw size={14} />
                </button>

                <div className="flex flex-col">
                  <span className="text-xs font-bold text-[#172033] flex items-center gap-1.5 font-mono">
                    <Volume2 size={13} className="text-[#F97316]" />
                    <span>SARVAM BULBUL:V3 AUDIO</span>
                  </span>
                  <span className="text-[10px] text-[#64748B] font-mono">
                    Speaker: {selectedSpeaker} · Language: {selectedLang}
                  </span>
                </div>
              </div>

              {simulationResponse.route_plan && (
                <button
                  type="button"
                  onClick={() => {
                    playCockpitClick();
                    onApplyRoute(simulationResponse.route_plan);
                  }}
                  className="px-3.5 py-1.5 rounded-lg bg-white hover:bg-[#F8FAFC] text-xs font-mono font-bold text-orange-700 border border-orange-300 transition-all flex items-center gap-1.5 shadow-sm"
                >
                  <span>View Route on Map</span>
                  <ArrowRight size={13} />
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
