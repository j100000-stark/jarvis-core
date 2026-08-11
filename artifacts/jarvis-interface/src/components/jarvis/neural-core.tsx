/**
 * NeuralCore — animated 3D neural AI core rendered on Canvas 2D.
 *
 * A living, breathing artificial neural network sphere with:
 * - 90 nodes distributed on a sphere (Fibonacci golden angle)
 * - Depth-sorted edges with energy flow pulses
 * - 3 concentric rotating rings at different orbital speeds
 * - 160 floating ambient particles
 * - State-driven color, speed, and intensity
 *
 * States: idle | listening | thinking | speaking | offline | alert
 * All animation is driven by requestAnimationFrame; no external deps.
 */

import { useEffect, useRef, useCallback } from 'react';

export type CoreState =
  | 'idle'
  | 'listening'
  | 'thinking'
  | 'speaking'
  | 'offline'
  | 'alert';

interface StateConfig {
  primary: string;       // main core / node color (hex)
  secondary: string;     // edge / ring color
  glow: number;          // shadowBlur intensity
  rotationSpeed: number; // rad/frame base
  pulseSpeed: number;    // pulse sine frequency
  nodeAlpha: number;     // node opacity ceiling
  edgeAlpha: number;     // edge opacity ceiling
  particleAlpha: number;
}

const STATE_CONFIG: Record<CoreState, StateConfig> = {
  idle: {
    primary:      '#0077cc',
    secondary:    '#004488',
    glow:         18,
    rotationSpeed:0.0018,
    pulseSpeed:   0.018,
    nodeAlpha:    0.70,
    edgeAlpha:    0.18,
    particleAlpha:0.35,
  },
  listening: {
    primary:      '#00aaff',
    secondary:    '#0066cc',
    glow:         28,
    rotationSpeed:0.0035,
    pulseSpeed:   0.038,
    nodeAlpha:    0.85,
    edgeAlpha:    0.30,
    particleAlpha:0.55,
  },
  thinking: {
    primary:      '#00ddff',
    secondary:    '#00aacc',
    glow:         42,
    rotationSpeed:0.0065,
    pulseSpeed:   0.07,
    nodeAlpha:    1.0,
    edgeAlpha:    0.55,
    particleAlpha:0.80,
  },
  speaking: {
    primary:      '#00ffcc',
    secondary:    '#00ccaa',
    glow:         36,
    rotationSpeed:0.005,
    pulseSpeed:   0.055,
    nodeAlpha:    0.95,
    edgeAlpha:    0.44,
    particleAlpha:0.70,
  },
  offline: {
    primary:      '#1a3050',
    secondary:    '#0d1e2e',
    glow:         6,
    rotationSpeed:0.0005,
    pulseSpeed:   0.006,
    nodeAlpha:    0.30,
    edgeAlpha:    0.08,
    particleAlpha:0.12,
  },
  alert: {
    primary:      '#ff7700',
    secondary:    '#cc4400',
    glow:         50,
    rotationSpeed:0.006,
    pulseSpeed:   0.10,
    nodeAlpha:    1.0,
    edgeAlpha:    0.60,
    particleAlpha:0.85,
  },
};

interface Node {
  x: number; y: number; z: number;   // unit sphere coords
  phase: number;                       // individual pulse offset
  size: number;                        // base radius
}

interface Particle {
  x: number; y: number; z: number;
  speed: number;
  phase: number;
  orbitR: number;
  orbitTheta: number;
  orbitPhi: number;
}

interface Pulse {
  edge: number;   // index into edges[]
  t: number;      // 0..1 position along edge
  speed: number;
  alpha: number;
}

/** Fibonacci/golden-angle sphere distribution (gives even coverage) */
function fibonacciSphere(n: number): Node[] {
  const golden = Math.PI * (3 - Math.sqrt(5));
  return Array.from({ length: n }, (_, i) => {
    const y = 1 - (i / (n - 1)) * 2;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const theta = golden * i;
    return {
      x: Math.cos(theta) * r,
      y,
      z: Math.sin(theta) * r,
      phase: Math.random() * Math.PI * 2,
      size: 1.4 + Math.random() * 1.6,
    };
  });
}

function hex(color: string, alpha: number): string {
  const r = parseInt(color.slice(1, 3), 16);
  const g = parseInt(color.slice(3, 5), 16);
  const b = parseInt(color.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

/** Rotate a point by angleX (tilt) and angleY (spin) */
function rotate(
  x: number, y: number, z: number,
  ax: number, ay: number
): [number, number, number] {
  // Y-axis rotation (spin)
  const cosY = Math.cos(ay), sinY = Math.sin(ay);
  const x1 = x * cosY - z * sinY;
  const z1 = x * sinY + z * cosY;
  // X-axis rotation (tilt)
  const cosX = Math.cos(ax), sinX = Math.sin(ax);
  const y2 = y * cosX - z1 * sinX;
  const z2 = y * sinX + z1 * cosX;
  return [x1, y2, z2];
}

/** Perspective projection onto canvas */
function project(
  rx: number, ry: number, rz: number,
  cx: number, cy: number, R: number
): { px: number; py: number; depth: number; scale: number } {
  const fov = 2.8;
  const s = fov / (fov + rz * 0.5);
  return { px: cx + rx * R * s, py: cy + ry * R * s, depth: rz, scale: s };
}

interface NeuralCoreProps {
  state: CoreState;
  size?: number; // canvas logical pixels (will be doubled for HiDPI)
}

export function NeuralCore({ state, size = 320 }: NeuralCoreProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef<CoreState>(state);
  const frameRef = useRef<number>(0);

  // Keep state ref current without re-running the animation setup
  stateRef.current = state;

  const startAnimation = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctxOrNull = canvas.getContext('2d');
    if (!ctxOrNull) return;
    const ctx: CanvasRenderingContext2D = ctxOrNull;

    const DPR = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = size * DPR;
    canvas.height = size * DPR;
    ctx.scale(DPR, DPR);
    const W = size, H = size;
    const cx = W / 2, cy = H / 2;
    const R = W * 0.34; // sphere radius in canvas px

    // ---- Build geometry (once) ----
    const NODE_COUNT = 90;
    const nodes: Node[] = fibonacciSphere(NODE_COUNT);

    // Build edges: connect node pairs within ~0.85 unit distance
    const EDGE_THRESHOLD = 0.85;
    const edges: [number, number][] = [];
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const ni = nodes[i], nj = nodes[j];
        const d = Math.sqrt(
          (ni.x - nj.x) ** 2 + (ni.y - nj.y) ** 2 + (ni.z - nj.z) ** 2
        );
        if (d < EDGE_THRESHOLD) edges.push([i, j]);
      }
    }

    // Particles
    const particles: Particle[] = Array.from({ length: 160 }, () => ({
      x: (Math.random() - 0.5) * 2,
      y: (Math.random() - 0.5) * 2,
      z: (Math.random() - 0.5) * 2,
      speed: 0.0002 + Math.random() * 0.0006,
      phase: Math.random() * Math.PI * 2,
      orbitR: 1.05 + Math.random() * 0.45,
      orbitTheta: Math.random() * Math.PI * 2,
      orbitPhi: Math.random() * Math.PI * 2,
    }));

    // Energy pulses travelling along edges
    const pulses: Pulse[] = [];
    const MAX_PULSES = 24;

    let angleY = 0;
    const TILT = 0.22; // fixed x-axis tilt

    let t = 0;

    // Ring configs: radius multiplier, initial angle, own rotation speed, y-tilt
    const rings = [
      { r: 1.18, angle: 0, speed: 0.0008, tilt: 0.3 },
      { r: 1.35, angle: Math.PI / 3, speed: -0.0006, tilt: -0.5 },
      { r: 1.55, angle: Math.PI, speed: 0.0004, tilt: 1.1 },
    ];

    function spawnPulse() {
      if (pulses.length >= MAX_PULSES || edges.length === 0) return;
      pulses.push({
        edge: Math.floor(Math.random() * edges.length),
        t: 0,
        speed: 0.008 + Math.random() * 0.016,
        alpha: 0.5 + Math.random() * 0.5,
      });
    }

    function draw() {
      const cfg = STATE_CONFIG[stateRef.current];
      t += 1;
      angleY += cfg.rotationSpeed;

      // ---- Clear ----
      ctx.clearRect(0, 0, W, H);

      // ---- Ambient background glow (centered radial) ----
      const bgGrad = ctx.createRadialGradient(cx, cy, R * 0.2, cx, cy, R * 1.6);
      bgGrad.addColorStop(0, hex(cfg.primary, 0.06));
      bgGrad.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = bgGrad;
      ctx.fillRect(0, 0, W, H);

      // Pre-project all nodes
      const proj = nodes.map(n => {
        const [rx, ry, rz] = rotate(n.x, n.y, n.z, TILT, angleY);
        return { ...project(rx, ry, rz, cx, cy, R), phase: n.phase, size: n.size };
      });

      // ---- Edges (back to front by avg depth) ----
      const sortedEdges = [...edges]
        .map(([a, b]) => ({ a, b, depth: (proj[a].depth + proj[b].depth) / 2 }))
        .sort((x, y) => x.depth - y.depth);

      ctx.save();
      for (const { a, b, depth } of sortedEdges) {
        const pa = proj[a], pb = proj[b];
        const visDepth = (depth + 1) / 2; // 0..1, larger = front
        const alpha = cfg.edgeAlpha * visDepth * (0.4 + 0.6 * visDepth);
        if (alpha < 0.015) continue;

        const grad = ctx.createLinearGradient(pa.px, pa.py, pb.px, pb.py);
        grad.addColorStop(0, hex(cfg.primary, alpha * pa.scale));
        grad.addColorStop(1, hex(cfg.secondary, alpha * pb.scale));

        ctx.shadowColor = cfg.primary;
        ctx.shadowBlur = cfg.glow * 0.3 * visDepth;
        ctx.strokeStyle = grad;
        ctx.lineWidth = 0.6 * visDepth;
        ctx.beginPath();
        ctx.moveTo(pa.px, pa.py);
        ctx.lineTo(pb.px, pb.py);
        ctx.stroke();
      }
      ctx.restore();

      // ---- Energy pulses ----
      const pulse = Math.sin(t * cfg.pulseSpeed);
      const globalPulse = 0.7 + 0.3 * pulse;

      // Spawn pulses based on state intensity
      const spawnRate = cfg.pulseSpeed > 0.05 ? 3 : cfg.pulseSpeed > 0.03 ? 5 : 9;
      if (t % spawnRate === 0) spawnPulse();

      ctx.save();
      ctx.shadowColor = cfg.primary;
      ctx.shadowBlur = cfg.glow * 0.6;
      for (let i = pulses.length - 1; i >= 0; i--) {
        const p = pulses[i];
        p.t += p.speed * (cfg.rotationSpeed / 0.004 + 0.5);
        if (p.t > 1) { pulses.splice(i, 1); continue; }
        const [ai, bi] = edges[p.edge];
        const pa = proj[ai], pb = proj[bi];
        const px = pa.px + (pb.px - pa.px) * p.t;
        const py = pa.py + (pb.py - pa.py) * p.t;
        const depth = (proj[ai].depth + proj[bi].depth) / 2;
        const visDepth = (depth + 1) / 2;
        if (visDepth < 0.3) continue;
        const pAlpha = cfg.edgeAlpha * p.alpha * visDepth * globalPulse;
        ctx.fillStyle = hex(cfg.primary, pAlpha);
        ctx.beginPath();
        ctx.arc(px, py, 1.8 * visDepth, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();

      // ---- Rings ----
      ctx.save();
      for (const ring of rings) {
        ring.angle += ring.speed * (cfg.rotationSpeed / 0.004 + 0.3);
        const segments = 120;
        const r = R * ring.r;
        const tiltX = ring.tilt;

        ctx.beginPath();
        for (let i = 0; i <= segments; i++) {
          const theta = (i / segments) * Math.PI * 2 + ring.angle;
          const px0 = Math.cos(theta);
          const py0 = 0;
          const pz0 = Math.sin(theta);
          // Apply ring tilt
          const [rx, ry, rz] = rotate(px0, py0, pz0, tiltX, angleY * 0.4);
          const { px: sx, py: sy, depth, scale } = project(rx, ry, rz, cx, cy, r);
          const visDepth = (depth + 1) / 2;
          const alpha = cfg.edgeAlpha * 0.7 * visDepth * globalPulse;
          if (alpha < 0.01) { ctx.beginPath(); continue; }

          if (i === 0) ctx.moveTo(sx, sy);
          else ctx.lineTo(sx, sy);
        }
        ctx.closePath();
        ctx.shadowColor = cfg.primary;
        ctx.shadowBlur = cfg.glow * 0.5;
        ctx.strokeStyle = hex(cfg.secondary, cfg.edgeAlpha * 0.5 * globalPulse);
        ctx.lineWidth = 0.8;
        ctx.stroke();
      }
      ctx.restore();

      // ---- Nodes (depth sorted, back to front) ----
      const sortedNodes = [...proj.map((p, i) => ({ ...p, idx: i }))]
        .sort((a, b) => a.depth - b.depth);

      ctx.save();
      ctx.shadowColor = cfg.primary;
      for (const p of sortedNodes) {
        const visDepth = (p.depth + 1) / 2;
        const nodePulse = 0.75 + 0.25 * Math.sin(t * cfg.pulseSpeed + nodes[p.idx].phase);
        const alpha = cfg.nodeAlpha * visDepth * nodePulse * globalPulse;
        if (alpha < 0.05) continue;
        const r = nodes[p.idx].size * p.scale * nodePulse;
        ctx.shadowBlur = cfg.glow * visDepth * nodePulse;

        const ng = ctx.createRadialGradient(p.px, p.py, 0, p.px, p.py, r * 3);
        ng.addColorStop(0, hex('#ffffff', alpha));
        ng.addColorStop(0.3, hex(cfg.primary, alpha * 0.9));
        ng.addColorStop(1, hex(cfg.primary, 0));
        ctx.fillStyle = ng;
        ctx.beginPath();
        ctx.arc(p.px, p.py, r * 3, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = hex('#ffffff', alpha * 0.9);
        ctx.shadowBlur = cfg.glow * 0.4;
        ctx.beginPath();
        ctx.arc(p.px, p.py, r, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();

      // ---- Core inner glow / sphere body ----
      ctx.save();
      const coreGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 0.9);
      coreGrad.addColorStop(0, hex(cfg.primary, 0.12 * globalPulse));
      coreGrad.addColorStop(0.4, hex(cfg.primary, 0.06 * globalPulse));
      coreGrad.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = coreGrad;
      ctx.shadowColor = cfg.primary;
      ctx.shadowBlur = cfg.glow * 1.5;
      ctx.beginPath();
      ctx.arc(cx, cy, R * 0.9, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      // ---- Outer aura ----
      ctx.save();
      const auraAlpha = cfg.nodeAlpha * 0.08 * globalPulse;
      const auraGrad = ctx.createRadialGradient(cx, cy, R * 0.9, cx, cy, R * 1.7);
      auraGrad.addColorStop(0, hex(cfg.primary, auraAlpha * 0.8));
      auraGrad.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = auraGrad;
      ctx.beginPath();
      ctx.arc(cx, cy, R * 1.7, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      // ---- Ambient particles ----
      ctx.save();
      for (const p of particles) {
        p.orbitTheta += p.speed * (cfg.rotationSpeed / 0.004 + 0.5);
        const px0 = Math.cos(p.orbitTheta) * Math.sin(p.orbitPhi);
        const py0 = Math.cos(p.orbitPhi);
        const pz0 = Math.sin(p.orbitTheta) * Math.sin(p.orbitPhi);
        const [rx, ry, rz] = rotate(px0, py0, pz0, TILT, angleY * 0.6);
        const { px: sx, py: sy, depth, scale } = project(
          rx * p.orbitR, ry * p.orbitR, rz * p.orbitR, cx, cy, R
        );
        const visDepth = (depth + 1) / 2;
        const pAlpha = cfg.particleAlpha * visDepth * (0.4 + 0.6 * Math.abs(Math.sin(t * cfg.pulseSpeed * 0.5 + p.phase)));
        if (pAlpha < 0.04) continue;
        ctx.shadowColor = cfg.primary;
        ctx.shadowBlur = 4 * visDepth;
        ctx.fillStyle = hex(cfg.primary, pAlpha);
        ctx.beginPath();
        ctx.arc(sx, sy, 0.9 * scale, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();

      frameRef.current = requestAnimationFrame(draw);
    }

    frameRef.current = requestAnimationFrame(draw);
  }, [size]);

  useEffect(() => {
    startAnimation();
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
    };
  }, [startAnimation]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: size, height: size }}
      className="drop-shadow-[0_0_40px_rgba(0,160,255,0.25)]"
    />
  );
}
