import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { Battery, Zap, Volume2, VolumeX, ChevronRight, Sparkles } from 'lucide-react';
import { playStartupHum, isAudioEnabled, setAudioEnabled } from '../utils/audioService';

interface Props {
  onComplete: () => void;
}

export default function EVCockpitBoot({ onComplete }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<'A' | 'B' | 'C' | 'D'>('A');
  const [bootLog, setBootLog] = useState<string>('CONNECTING HIGH-VOLTAGE VEHICLE BUS');
  const [soundOn, setSoundOn] = useState<boolean>(isAudioEnabled());
  const [batteryFill, setBatteryFill] = useState<number>(20);
  const [webGLFailed, setWebGLFailed] = useState<boolean>(false);

  // Check prefers-reduced-motion
  useEffect(() => {
    if (typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      onComplete();
    }
  }, [onComplete]);

  // Phase Sequencer (~3.8 seconds total, swift & elegant)
  useEffect(() => {
    const tA = setTimeout(() => {
      setPhase('B');
      setBootLog('INITIALIZING POWERTRAIN & ROAD TELEMETRY');
      setBatteryFill(50);
    }, 700);

    const tB = setTimeout(() => {
      setBootLog('CALIBRATING BATTERY UNCERTAINTY & CHARGING CORRIDORS');
      setBatteryFill(80);
    }, 1400);

    const tC = setTimeout(() => {
      setPhase('C');
      setBootLog('SYSTEM READY · WILL I MAKE IT ONLINE');
      setBatteryFill(100);
    }, 2100);

    const tD = setTimeout(() => {
      setPhase('D');
    }, 3200);

    const tEnd = setTimeout(() => {
      onComplete();
    }, 3700);

    return () => {
      clearTimeout(tA);
      clearTimeout(tB);
      clearTimeout(tC);
      clearTimeout(tD);
      clearTimeout(tEnd);
    };
  }, [onComplete]);

  // Keyboard shortcut: Escape to skip immediately
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onComplete();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onComplete]);

  const toggleSound = () => {
    const next = !soundOn;
    setSoundOn(next);
    setAudioEnabled(next);
    if (next) playStartupHum();
  };

  // Three.js Procedural Electric Vehicle Scene
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
      scene.fog = new THREE.FogExp2(0x0c1017, 0.08);

      const width = mountRef.current.clientWidth || window.innerWidth;
      const height = mountRef.current.clientHeight || window.innerHeight;

      camera = new THREE.PerspectiveCamera(40, width / height, 0.1, 100);
      camera.position.set(0, 1.5, 5.8);
      camera.lookAt(0, 0.35, 0);

      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      mountRef.current.appendChild(renderer.domElement);

      // Studio Lighting
      const ambientLight = new THREE.AmbientLight(0x1a2333, 1.8);
      scene.add(ambientLight);

      const topLight = new THREE.DirectionalLight(0xf97316, 2.0);
      topLight.position.set(2, 6, 4);
      scene.add(topLight);

      const rimLight = new THREE.DirectionalLight(0x06b6d4, 1.8);
      rimLight.position.set(-4, 3, -4);
      scene.add(rimLight);

      lightSweep = new THREE.PointLight(0xf97316, 3.5, 12);
      lightSweep.position.set(-4, 0.8, 2);
      scene.add(lightSweep);

      // Procedural Electric Vehicle Model
      carGroup = new THREE.Group();

      // Lower Body
      const bodyGeo = new THREE.BoxGeometry(3.6, 0.55, 1.65);
      const carMat = new THREE.MeshStandardMaterial({
        color: 0x121620,
        metalness: 0.85,
        roughness: 0.2,
      });
      const carBody = new THREE.Mesh(bodyGeo, carMat);
      carBody.position.y = 0.5;
      carGroup.add(carBody);

      // Cabin Greenhouse
      const cabinGeo = new THREE.CylinderGeometry(0.65, 0.95, 1.8, 4, 1, false, Math.PI / 4);
      const glassMat = new THREE.MeshPhysicalMaterial({
        color: 0x080b10,
        metalness: 0.1,
        roughness: 0.1,
        transmission: 0.8,
        transparent: true,
        opacity: 0.9,
      });
      const cabin = new THREE.Mesh(cabinGeo, glassMat);
      cabin.rotation.z = Math.PI / 2;
      cabin.position.set(-0.15, 0.92, 0);
      carGroup.add(cabin);

      // Orange LED Headlight Bar
      const headlightGeo = new THREE.BoxGeometry(0.08, 0.06, 1.45);
      const lightbarMat = new THREE.MeshBasicMaterial({ color: 0xf97316 });
      const headlight = new THREE.Mesh(headlightGeo, lightbarMat);
      headlight.position.set(1.8, 0.55, 0);
      carGroup.add(headlight);

      // Teal Taillight Bar
      const taillightMat = new THREE.MeshBasicMaterial({ color: 0x06b6d4 });
      const taillight = new THREE.Mesh(headlightGeo, taillightMat);
      taillight.position.set(-1.8, 0.65, 0);
      carGroup.add(taillight);

      // Wheels
      const wheelGeo = new THREE.CylinderGeometry(0.35, 0.35, 0.22, 24);
      const wheelMat = new THREE.MeshStandardMaterial({ color: 0x0a0d14, roughness: 0.7 });
      const rimMat = new THREE.MeshBasicMaterial({ color: 0xf97316, wireframe: true });

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

      scene.add(carGroup);

      // Studio Ground Grid
      const grid = new THREE.GridHelper(24, 32, 0x222938, 0x121620);
      grid.position.y = 0;
      scene.add(grid);

      // Ambient Particles
      const particleCount = 140;
      const particleGeo = new THREE.BufferGeometry();
      const posArray = new Float32Array(particleCount * 3);

      for (let i = 0; i < particleCount * 3; i += 3) {
        posArray[i] = (Math.random() - 0.5) * 12;
        posArray[i + 1] = Math.random() * 3.5;
        posArray[i + 2] = (Math.random() - 0.5) * 8;
      }
      particleGeo.setAttribute('position', new THREE.BufferAttribute(posArray, 3));
      const particleMat = new THREE.PointsMaterial({
        size: 0.03,
        color: 0xf97316,
        transparent: true,
        opacity: 0.5,
      });
      particles = new THREE.Points(particleGeo, particleMat);
      scene.add(particles);

      let clock = new THREE.Clock();

      const animate = () => {
        animationFrameId = requestAnimationFrame(animate);
        const elapsed = clock.getElapsedTime();

        carGroup.rotation.y = 0.35 + Math.sin(elapsed * 0.4) * 0.15;
        carGroup.position.y = Math.sin(elapsed * 1.2) * 0.02;

        lightSweep.position.x = Math.sin(elapsed * 1.5) * 4.0;
        lightSweep.position.z = 2.0 + Math.cos(elapsed * 1.5) * 1.2;

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
      };
    } catch {
      setWebGLFailed(true);
    }
  }, [phase]);

  return (
    <div 
      className={`fixed inset-0 z-[99999] flex flex-col justify-between overflow-hidden bg-[#0c1017] text-white transition-opacity duration-700 ${
        phase === 'D' ? 'opacity-0 pointer-events-none' : 'opacity-100 pointer-events-auto'
      }`}
    >
      {/* Top Bar */}
      <header className="relative z-10 flex items-center justify-between px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-8 h-8 rounded-xl bg-orange-500/10 border border-orange-500/30 text-orange-400">
            <Zap size={16} />
          </div>
          <div>
            <span className="text-xs font-mono font-bold tracking-wider text-orange-400 uppercase">
              WILL I MAKE IT? · EV INTELLIGENCE
            </span>
            <div className="flex items-center gap-2 text-[10px] text-slate-400 font-mono">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              <span>SYSTEM READY</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={toggleSound}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-mono rounded-xl border border-[#222938] bg-[#121620] text-slate-300 hover:text-white hover:border-slate-600 transition-colors"
          >
            {soundOn ? <Volume2 size={13} className="text-orange-400" /> : <VolumeX size={13} className="text-slate-500" />}
            <span className="hidden sm:inline">{soundOn ? 'Sound On' : 'Muted'}</span>
          </button>

          <button
            type="button"
            onClick={onComplete}
            className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-xl bg-orange-500 hover:bg-orange-600 text-white transition-all shadow-md shadow-orange-950/40"
          >
            <span>Skip Intro</span>
            <ChevronRight size={14} />
          </button>
        </div>
      </header>

      {/* Center 3D Viewport */}
      <div className="relative flex-1 w-full h-full flex items-center justify-center">
        {!webGLFailed && (
          <div ref={mountRef} className="absolute inset-0 w-full h-full" />
        )}

        {/* Phase C: Identity & Core Brand Reveal */}
        {phase === 'C' && (
          <div className="relative z-20 flex flex-col items-center text-center px-4 max-w-lg">
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-orange-500/10 border border-orange-500/30 text-orange-300 text-xs font-mono mb-2">
              <Sparkles size={12} className="text-orange-400" />
              Explainable EV Route Planning
            </div>
            <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-white mb-2">
              WILL I MAKE IT?
            </h1>
            <p className="text-xs sm:text-sm text-slate-400">
              Risk-aware energy predictions and charger reliability for Indian roads.
            </p>
          </div>
        )}
      </div>

      {/* Bottom Status Footer */}
      <footer className="relative z-10 px-6 py-4 flex flex-col sm:flex-row items-center justify-between gap-3 border-t border-[#1e2535] bg-[#0e1219]/90 backdrop-blur-md">
        <div className="flex items-center gap-2 text-xs font-mono">
          <span className="text-orange-400 font-bold">[BOOT]</span>
          <span className="text-slate-300 tracking-wider uppercase text-[11px]">{bootLog}</span>
        </div>

        <div className="flex items-center gap-3 w-full sm:w-56">
          <Battery size={15} className="text-orange-400 shrink-0" />
          <div className="flex-1 h-2 bg-[#171c28] rounded-full overflow-hidden p-0.5 border border-[#222938]">
            <div
              className="h-full bg-gradient-to-r from-orange-500 to-amber-400 rounded-full transition-all duration-500"
              style={{ width: `${batteryFill}%` }}
            />
          </div>
          <span className="text-xs font-mono font-bold text-orange-400 w-8 text-right">
            {batteryFill}%
          </span>
        </div>
      </footer>
    </div>
  );
}
