import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { Battery, Zap, Volume2, VolumeX, ShieldCheck, ChevronRight, Sparkles } from 'lucide-react';
import { playStartupHum, isAudioEnabled, setAudioEnabled } from '../utils/audioService';

interface Props {
  onComplete: () => void;
}

export default function EVCockpitBoot({ onComplete }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<'A' | 'B' | 'C' | 'D'>('A');
  const [bootLog, setBootLog] = useState<string>('CONNECTING HIGH-VOLTAGE VEHICLE BUS');
  const [soundOn, setSoundOn] = useState<boolean>(isAudioEnabled());
  const [batteryFill, setBatteryFill] = useState<number>(15);
  const [webGLFailed, setWebGLFailed] = useState<boolean>(false);

  // Check prefers-reduced-motion
  useEffect(() => {
    if (typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      onComplete();
    }
  }, [onComplete]);

  // Extended, Cinematic Phase Sequencer (~6 seconds total)
  useEffect(() => {
    // Phase A -> B at 1.0s
    const tA = setTimeout(() => {
      setPhase('B');
      setBootLog('INITIALIZING HIGH-VOLTAGE INVERTER & POWERTRAIN');
      setBatteryFill(35);
    }, 1000);

    // Phase B calibration step 1 at 1.8s
    const tB1 = setTimeout(() => {
      setBootLog('CALIBRATING AERODYNAMIC DRAG & ROLLING FRICTION MODEL');
      setBatteryFill(65);
    }, 1800);

    // Phase B calibration step 2 at 2.5s
    const tB2 = setTimeout(() => {
      setBootLog('INITIALIZING ROAD GRAPH & CHARGER RELIABILITY ENGINE');
      setBatteryFill(85);
    }, 2500);

    // Phase C: Brand & Route reveal at 3.2s
    const tC = setTimeout(() => {
      setPhase('C');
      setBootLog('SYSTEM READY · MOBILITY & ROUTE INTELLIGENCE ONLINE');
      setBatteryFill(100);
    }, 3200);

    // Phase D: Dissolve transition into cockpit at 5.0s
    const tD = setTimeout(() => {
      setPhase('D');
    }, 5000);

    // Complete at 5.9s
    const tEnd = setTimeout(() => {
      onComplete();
    }, 5900);

    return () => {
      clearTimeout(tA);
      clearTimeout(tB1);
      clearTimeout(tB2);
      clearTimeout(tC);
      clearTimeout(tD);
      clearTimeout(tEnd);
    };
  }, [onComplete]);

  // Keyboard shortcut: Escape to skip
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onComplete();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onComplete]);

  // Sound toggle handler
  const toggleSound = () => {
    const next = !soundOn;
    setSoundOn(next);
    setAudioEnabled(next);
    if (next) {
      playStartupHum();
    }
  };

  // Three.js Procedural Electric Vehicle Studio Scene
  useEffect(() => {
    if (!mountRef.current || phase === 'D') return;

    let scene: THREE.Scene;
    let camera: THREE.PerspectiveCamera;
    let renderer: THREE.WebGLRenderer;
    let animationFrameId: number;
    let carGroup: THREE.Group;
    let lightSweep: THREE.PointLight;
    let particles: THREE.Points;

    try {
      scene = new THREE.Scene();
      scene.fog = new THREE.FogExp2(0x050811, 0.07);

      const width = mountRef.current.clientWidth || window.innerWidth;
      const height = mountRef.current.clientHeight || window.innerHeight;

      camera = new THREE.PerspectiveCamera(40, width / height, 0.1, 100);
      camera.position.set(0, 1.6, 6.2);
      camera.lookAt(0, 0.4, 0);

      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.shadowMap.enabled = false;
      mountRef.current.appendChild(renderer.domElement);

      // 1. Studio Lighting
      const ambientLight = new THREE.AmbientLight(0x0c1e33, 1.4);
      scene.add(ambientLight);

      const topLight = new THREE.DirectionalLight(0x38bdf8, 2.2);
      topLight.position.set(2, 6, 4);
      scene.add(topLight);

      const rimLight = new THREE.DirectionalLight(0x10b981, 2.0);
      rimLight.position.set(-4, 3, -4);
      scene.add(rimLight);

      lightSweep = new THREE.PointLight(0x00f0ff, 4.0, 14);
      lightSweep.position.set(-4, 0.8, 2);
      scene.add(lightSweep);

      // 2. Procedural Electric Sports Sedan Silhouette
      carGroup = new THREE.Group();

      // Sleek Lower Body / Chassis
      const bodyGeo = new THREE.BoxGeometry(3.6, 0.55, 1.65);
      const carMat = new THREE.MeshStandardMaterial({
        color: 0x07111e,
        metalness: 0.92,
        roughness: 0.12,
        wireframe: false,
      });
      const carBody = new THREE.Mesh(bodyGeo, carMat);
      carBody.position.y = 0.5;
      carGroup.add(carBody);

      // High-Tech Cyber Wireframe Overlay on vehicle body
      const wireframeMat = new THREE.MeshBasicMaterial({
        color: 0x00f0ff,
        wireframe: true,
        transparent: true,
        opacity: 0.22,
      });
      const carWireframe = new THREE.Mesh(bodyGeo, wireframeMat);
      carWireframe.position.y = 0.5;
      carWireframe.scale.set(1.002, 1.002, 1.002);
      carGroup.add(carWireframe);

      // Aerodynamic Fastback Cabin Greenhouse
      const cabinGeo = new THREE.CylinderGeometry(0.65, 0.95, 1.8, 4, 1, false, Math.PI / 4);
      const glassMat = new THREE.MeshPhysicalMaterial({
        color: 0x061426,
        metalness: 0.2,
        roughness: 0.05,
        transmission: 0.85,
        transparent: true,
        opacity: 0.9,
      });
      const cabin = new THREE.Mesh(cabinGeo, glassMat);
      cabin.rotation.z = Math.PI / 2;
      cabin.position.set(-0.15, 0.92, 0);
      carGroup.add(cabin);

      // Glowing Cyan LED Lightbar (Headlights & Taillights)
      const headlightGeo = new THREE.BoxGeometry(0.08, 0.06, 1.45);
      const lightbarMat = new THREE.MeshBasicMaterial({ color: 0x00f0ff });
      const headlight = new THREE.Mesh(headlightGeo, lightbarMat);
      headlight.position.set(1.8, 0.55, 0);
      carGroup.add(headlight);

      const taillightGeo = new THREE.BoxGeometry(0.08, 0.06, 1.45);
      const taillightMat = new THREE.MeshBasicMaterial({ color: 0x10b981 });
      const taillight = new THREE.Mesh(taillightGeo, taillightMat);
      taillight.position.set(-1.8, 0.65, 0);
      carGroup.add(taillight);

      // Glowing Wheels with Turbine Rims
      const wheelGeo = new THREE.CylinderGeometry(0.35, 0.35, 0.22, 24);
      const wheelMat = new THREE.MeshStandardMaterial({ color: 0x040810, roughness: 0.7 });
      const rimMat = new THREE.MeshBasicMaterial({ color: 0x00f0ff, wireframe: true });

      const wheelPositions = [
        [1.15, 0.35, 0.85],
        [1.15, 0.35, -0.85],
        [-1.15, 0.35, 0.85],
        [-1.15, 0.35, -0.85],
      ];

      wheelPositions.forEach(([x, y, z]) => {
        const tire = new THREE.Mesh(wheelGeo, wheelMat);
        tire.rotation.x = Math.PI / 2;
        tire.position.set(x, y, z);
        
        const rim = new THREE.Mesh(wheelGeo, rimMat);
        rim.rotation.x = Math.PI / 2;
        rim.position.set(x, y, z * 1.05);
        rim.scale.set(0.75, 1.02, 0.75);

        carGroup.add(tire);
        carGroup.add(rim);
      });

      // Subtle underglow halo
      const underglowGeo = new THREE.PlaneGeometry(3.8, 1.9);
      const underglowMat = new THREE.MeshBasicMaterial({
        color: 0x00f0ff,
        transparent: true,
        opacity: 0.3,
      });
      const underglow = new THREE.Mesh(underglowGeo, underglowMat);
      underglow.rotation.x = -Math.PI / 2;
      underglow.position.y = 0.02;
      carGroup.add(underglow);

      scene.add(carGroup);

      // 3. Studio Ground Grid Lines
      const grid = new THREE.GridHelper(24, 32, 0x00f0ff, 0x0c1e33);
      grid.position.y = 0;
      scene.add(grid);

      // 4. Floating Energy Particle Stream
      const particleCount = 220;
      const particleGeo = new THREE.BufferGeometry();
      const posArray = new Float32Array(particleCount * 3);

      for (let i = 0; i < particleCount * 3; i += 3) {
        posArray[i] = (Math.random() - 0.5) * 12;
        posArray[i + 1] = Math.random() * 3.5;
        posArray[i + 2] = (Math.random() - 0.5) * 8;
      }
      particleGeo.setAttribute('position', new THREE.BufferAttribute(posArray, 3));
      const particleMat = new THREE.PointsMaterial({
        size: 0.035,
        color: 0x38bdf8,
        transparent: true,
        opacity: 0.65,
      });
      particles = new THREE.Points(particleGeo, particleMat);
      scene.add(particles);

      // Animation Loop
      let clock = new THREE.Clock();

      const animate = () => {
        animationFrameId = requestAnimationFrame(animate);
        const elapsed = clock.getElapsedTime();

        // Rotate vehicle gently for cinematic presentation
        carGroup.rotation.y = 0.35 + Math.sin(elapsed * 0.45) * 0.18;
        carGroup.position.y = Math.sin(elapsed * 1.2) * 0.03;

        // Animate light sweep from left to right along body
        lightSweep.position.x = Math.sin(elapsed * 1.8) * 4.2;
        lightSweep.position.z = 2.2 + Math.cos(elapsed * 1.8) * 1.5;

        // Drift particles towards vehicle
        const positions = particleGeo.attributes.position.array as Float32Array;
        for (let i = 0; i < particleCount * 3; i += 3) {
          positions[i] -= 0.018;
          if (positions[i] < -6) positions[i] = 6;
        }
        particleGeo.attributes.position.needsUpdate = true;

        renderer.render(scene, camera);
      };

      animate();

      const handleResize = () => {
        if (!mountRef.current) return;
        const w = mountRef.current.clientWidth;
        const h = mountRef.current.clientHeight;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
      };

      window.addEventListener('resize', handleResize);

      return () => {
        window.removeEventListener('resize', handleResize);
        cancelAnimationFrame(animationFrameId);
        if (renderer && renderer.domElement && mountRef.current) {
          try {
            mountRef.current.removeChild(renderer.domElement);
          } catch {}
          renderer.dispose();
        }
        carMat.dispose();
        wireframeMat.dispose();
        bodyGeo.dispose();
        cabinGeo.dispose();
        glassMat.dispose();
        headlightGeo.dispose();
        lightbarMat.dispose();
        wheelGeo.dispose();
        wheelMat.dispose();
        rimMat.dispose();
        particleGeo.dispose();
        particleMat.dispose();
      };
    } catch {
      setWebGLFailed(true);
    }
  }, [phase]);

  return (
    <div 
      className={`fixed inset-0 z-[99999] flex flex-col justify-between overflow-hidden bg-[#050811] text-white transition-opacity duration-1000 ${
        phase === 'D' ? 'opacity-0 pointer-events-none' : 'opacity-100 pointer-events-auto'
      }`}
      style={{ isolation: 'isolate' }}
    >
      {/* Background Cyber Grid Overlay */}
      <div className="absolute inset-0 bg-[radial-gradient(#0e2238_1px,transparent_1px)] [background-size:24px_24px] opacity-25 pointer-events-none" />

      {/* Top Cockpit HUD Bar */}
      <header className="relative z-10 flex items-center justify-between px-6 py-4">
        {/* Brand System Status */}
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-cyan-500/10 border border-cyan-400/40 text-cyan-400 shadow-[0_0_12px_rgba(6,182,212,0.4)]">
            <Zap size={18} className="animate-pulse" />
          </div>
          <div>
            <span className="text-xs font-mono font-bold tracking-widest text-cyan-400 uppercase">
              EV Cockpit HMI · v1.0
            </span>
            <div className="flex items-center gap-2 text-[10px] text-slate-400 font-mono">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
              <span>POWER BUS ACTIVE</span>
            </div>
          </div>
        </div>

        {/* Audio Toggle & Skip Button */}
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={toggleSound}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-mono rounded-lg border border-slate-700 bg-slate-900/80 text-slate-300 hover:text-white hover:border-cyan-500/50 transition-colors"
            title={soundOn ? 'Mute Cockpit Audio' : 'Enable Cockpit Audio'}
          >
            {soundOn ? <Volume2 size={14} className="text-cyan-400" /> : <VolumeX size={14} className="text-slate-500" />}
            <span className="hidden sm:inline">{soundOn ? 'Audio: On' : 'Audio: Muted'}</span>
          </button>

          <button
            type="button"
            onClick={onComplete}
            className="flex items-center gap-1.5 px-4 py-1.5 text-xs font-mono font-semibold rounded-lg bg-cyan-500/15 border border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/30 hover:border-cyan-400 transition-all shadow-[0_0_12px_rgba(6,182,212,0.2)]"
          >
            <span>Skip Intro</span>
            <span className="text-[10px] bg-cyan-950 px-1 rounded text-cyan-400 font-mono hidden sm:inline">ESC</span>
            <ChevronRight size={14} />
          </button>
        </div>
      </header>

      {/* Main Center Stage: 3D Canvas OR CSS Fallback */}
      <div className="relative flex-1 w-full h-full flex items-center justify-center overflow-hidden">
        {/* Three.js 3D Viewport */}
        {!webGLFailed && (
          <div ref={mountRef} className="absolute inset-0 w-full h-full cursor-grab active:cursor-grabbing" />
        )}

        {/* CSS/SVG Fallback if WebGL fails */}
        {webGLFailed && (
          <div className="relative flex flex-col items-center justify-center text-center p-6">
            <div className="relative w-72 h-36 border border-cyan-500/40 rounded-3xl bg-slate-900/60 backdrop-blur-md flex items-center justify-center shadow-[0_0_35px_rgba(6,182,212,0.25)]">
              <div className="absolute inset-x-4 top-2 h-0.5 bg-gradient-to-r from-transparent via-cyan-400 to-transparent animate-pulse" />
              <Zap size={48} className="text-cyan-400 animate-bounce" />
              <div className="absolute bottom-2 text-[10px] font-mono text-cyan-300 tracking-wider">
                PROCEDURAL EV SILHOUETTE
              </div>
            </div>
          </div>
        )}

        {/* Phase A: Outward Electric Circuit Tracing Pulse */}
        {phase === 'A' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
            <div className="relative flex items-center justify-center mb-6">
              <div className="w-20 h-20 rounded-full bg-cyan-400/20 animate-ping absolute" />
              <div className="w-12 h-12 rounded-full bg-cyan-500/30 border border-cyan-400 flex items-center justify-center shadow-[0_0_30px_#00f0ff]">
                <Zap size={22} className="text-cyan-300 stroke-[3] animate-pulse" />
              </div>
            </div>
            <p className="text-xs font-mono font-bold tracking-widest text-cyan-400 uppercase animate-pulse">
              INITIALIZING HIGH-VOLTAGE POWER CONTACTORS...
            </p>
          </div>
        )}

        {/* Phase C: Identity & Core Brand Reveal */}
        {phase === 'C' && (
          <div className="relative z-20 flex flex-col items-center text-center px-4 max-w-xl animate-fade-in">
            {/* Super Header Tag */}
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 text-xs font-mono font-medium tracking-widest uppercase mb-3 shadow-[0_0_15px_rgba(6,182,212,0.3)]">
              <Sparkles size={13} className="text-cyan-400" />
              Autonomous Energy Intelligence
            </div>

            {/* Title */}
            <h1 className="text-4xl sm:text-5xl font-extrabold tracking-tight text-white mb-2 font-sans drop-shadow-[0_0_20px_rgba(255,255,255,0.4)]">
              WILL I MAKE IT?
            </h1>
            <p className="text-sm sm:text-base text-cyan-200/90 font-medium tracking-wide mb-6">
              Explainable, Risk-Aware EV Route Planner for Indian Conditions
            </p>

            {/* Stylized Mini Corridor Route Map Graphic */}
            <div className="w-full max-w-md bg-slate-900/90 border border-cyan-500/40 rounded-2xl p-4 backdrop-blur-xl mb-4 shadow-[0_0_30px_rgba(6,182,212,0.2)]">
              <div className="flex items-center justify-between text-xs font-mono text-slate-300 mb-2">
                <span className="flex items-center gap-1.5 text-cyan-400 font-bold">
                  <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 inline-block shadow-[0_0_8px_#00f0ff]" /> Origin [A]
                </span>
                <span className="flex items-center gap-1.5 text-amber-400 font-bold">
                  <Zap size={13} /> Fast Charger Hub
                </span>
                <span className="flex items-center gap-1.5 text-emerald-400 font-bold">
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 inline-block shadow-[0_0_8px_#10b981]" /> Dest [B]
                </span>
              </div>

              {/* Glowing Animated Highway Line */}
              <div className="relative h-2 bg-slate-800 rounded-full overflow-hidden p-0.5 border border-slate-700">
                <div className="h-full bg-gradient-to-r from-cyan-400 via-emerald-400 to-teal-300 rounded-full w-full animate-pulse shadow-[0_0_10px_#00f0ff]" />
              </div>
            </div>

            {/* Tagline */}
            <p className="text-xs sm:text-sm text-slate-400 italic font-sans tracking-wide">
              “Every kilometre. Every charge. Every decision.”
            </p>
          </div>
        )}
      </div>

      {/* Bottom Telemetry Boot Footer */}
      <footer className="relative z-10 px-6 py-4 flex flex-col sm:flex-row items-center justify-between gap-3 border-t border-cyan-950/80 bg-slate-950/80 backdrop-blur-md">
        {/* Dynamic Boot Logs */}
        <div className="flex items-center gap-2 text-xs font-mono">
          <span className="text-cyan-400 font-bold">[SYS]</span>
          <span className="text-slate-300 tracking-wider uppercase">{bootLog}</span>
          <span className="inline-block w-2 h-3 bg-cyan-400 animate-pulse" />
        </div>

        {/* Battery Calibration Progress */}
        <div className="flex items-center gap-3 w-full sm:w-64">
          <Battery size={16} className="text-cyan-400 shrink-0" />
          <div className="flex-1 h-2 bg-slate-900 rounded-full overflow-hidden p-0.5 border border-slate-700">
            <div
              className="h-full bg-gradient-to-r from-cyan-500 via-teal-400 to-emerald-400 rounded-full transition-all duration-700 shadow-[0_0_8px_#00f0ff]"
              style={{ width: `${batteryFill}%` }}
            />
          </div>
          <span className="text-xs font-mono font-bold text-cyan-300 w-10 text-right">
            {batteryFill}%
          </span>
        </div>
      </footer>
    </div>
  );
}
