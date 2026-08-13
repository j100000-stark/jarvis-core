/**
 * NeuralCore — Cinematic living neural network, Canvas 2D.
 *
 * Architecture:
 *  - 80 neurons on a Fibonacci sphere, each with independent organic motion
 *    (per-neuron phase, frequency, amplitude — never in sync)
 *  - Connections activate/fade naturally; each can carry traveling energy pulses
 *  - Neural cascade system: neuron → connection → neuron → … (frame-based queue)
 *  - Cinematic startup sequence: black → point → neurons form → connections appear → idle
 *  - All state transitions are smoothly lerped (no hard cuts)
 *  - visibilitychange pause to save battery on iPhone
 *  - DPR capped at 2; targets 60 fps on Safari/iPhone
 *
 * External API is identical to V0: just pass `state: CoreState` and optionally `size`.
 * No Three.js, no external deps.
 */

import { useEffect, useRef, useCallback } from 'react';

// ── Public types ──────────────────────────────────────────────────────────────

export type CoreState =
  | 'idle'
  | 'listening'
  | 'thinking'
  | 'executing'
  | 'speaking'
  | 'offline'
  | 'alert';

export interface NeuralCoreProps {
  state: CoreState;
  size?: number;
}

// ── Color type ────────────────────────────────────────────────────────────────

interface RGB { r: number; g: number; b: number }
const rgb = (r: number, g: number, b: number): RGB => ({ r, g, b });

// ── State configuration (targets — animation lerps toward these) ──────────────

interface StateCfg {
  primary:     RGB;
  accent:      RGB;
  glow:        number; // shadowBlur ceiling
  rotSpeed:    number; // Y-rotation rad/frame
  firingRate:  number; // cascade frequency multiplier
  connAlpha:   number; // connection base alpha multiplier
  nodeAlpha:   number; // node brightness ceiling
  partAlpha:   number; // ambient particle alpha
  inward:      number; // 0-1, particles pulled toward core (listening)
  breathAmp:   number; // organic breathing amplitude multiplier
  energySpeed: number; // pulse travel speed multiplier
}

const STATE_CFG: Record<CoreState, StateCfg> = {
  idle: {
    primary:     rgb(0, 108, 200),
    accent:      rgb(0, 160, 255),
    glow: 14,  rotSpeed: 0.0014, firingRate: 1,
    connAlpha: 0.20, nodeAlpha: 0.70, partAlpha: 0.32,
    inward: 0, breathAmp: 1.0, energySpeed: 1.0,
  },
  listening: {
    primary:     rgb(0, 155, 255),
    accent:      rgb(0, 220, 255),
    glow: 28,  rotSpeed: 0.0028, firingRate: 2.8,
    connAlpha: 0.38, nodeAlpha: 0.88, partAlpha: 0.55,
    inward: 0.38, breathAmp: 1.7, energySpeed: 1.4,
  },
  thinking: {
    primary:     rgb(0, 200, 255),
    accent:      rgb(60, 240, 255),
    glow: 40,  rotSpeed: 0.0068, firingRate: 5.5,
    connAlpha: 0.55, nodeAlpha: 1.00, partAlpha: 0.78,
    inward: 0, breathAmp: 1.9, energySpeed: 2.1,
  },
  executing: {
    primary:     rgb(0, 240, 160),
    accent:      rgb(0, 255, 200),
    glow: 45,  rotSpeed: 0.0072, firingRate: 6.5,
    connAlpha: 0.58, nodeAlpha: 1.00, partAlpha: 0.82,
    inward: 0, breathAmp: 2.1, energySpeed: 2.4,
  },
  speaking: {
    primary:     rgb(0, 220, 200),
    accent:      rgb(0, 255, 220),
    glow: 34,  rotSpeed: 0.0042, firingRate: 3.8,
    connAlpha: 0.44, nodeAlpha: 0.96, partAlpha: 0.68,
    inward: 0, breathAmp: 2.6, energySpeed: 1.9,
  },
  offline: {
    primary:     rgb(18, 38, 65),
    accent:      rgb(14, 28, 50),
    glow:  4,  rotSpeed: 0.0003, firingRate: 0.08,
    connAlpha: 0.05, nodeAlpha: 0.26, partAlpha: 0.09,
    inward: 0, breathAmp: 0.25, energySpeed: 0.25,
  },
  alert: {
    primary:     rgb(215, 95, 0),
    accent:      rgb(255, 135, 0),
    glow: 50,  rotSpeed: 0.0080, firingRate: 4.5,
    connAlpha: 0.58, nodeAlpha: 1.00, partAlpha: 0.80,
    inward: 0, breathAmp: 2.3, energySpeed: 2.6,
  },
};

// ── Geometry types ────────────────────────────────────────────────────────────

interface Neuron {
  bx: number; by: number; bz: number;  // base unit-sphere position
  ph: [number,number,number,number];    // 4 independent noise phases
  fr: [number,number,number,number];    // 4 independent noise frequencies (rad/frame)
  noiseAmp:   number;   // organic displacement magnitude
  size:       number;   // base dot radius (px at scale=1)
  brightness: number;   // individual luminosity factor
  flickerPh:  number;   // micro-flicker phase
  flickerFr:  number;   // micro-flicker frequency
  birthT:     number;   // ms since start when neuron is born (startup)
  activation: number;   // 0-1, decays each frame
}

interface Connection {
  a: number; b: number;       // neuron indices
  baseAlpha:    number;       // inherent opacity
  currentAlpha: number;       // rendered opacity (lerped)
  targetAlpha:  number;       // lerp target
  birthT:       number;       // ms since start when connection is born
  pulses:       Pulse[];
}

interface Pulse {
  t:       number;  // position 0=a-side 1=b-side
  speed:   number;  // per-frame step
  alpha:   number;
  forward: boolean; // a→b
}

interface CascadeEvent {
  atFrame:   number;
  neuronIdx: number;
  depth:     number;
}

// ── Math helpers ──────────────────────────────────────────────────────────────

function fibSphere(n: number): Array<[number, number, number]> {
  const gold = Math.PI * (3 - Math.sqrt(5));
  return Array.from({ length: n }, (_, i) => {
    const y = 1 - (i / (n - 1)) * 2;
    const rr = Math.sqrt(Math.max(0, 1 - y * y));
    const th = gold * i;
    return [Math.cos(th) * rr, y, Math.sin(th) * rr] as [number, number, number];
  });
}

function lerp(a: number, b: number, t: number) { return a + (b - a) * t; }

function lerpRGB(a: RGB, b: RGB, t: number): RGB {
  return { r: lerp(a.r, b.r, t), g: lerp(a.g, b.g, t), b: lerp(a.b, b.b, t) };
}

function cs(c: RGB, a: number): string {
  return `rgba(${c.r | 0},${c.g | 0},${c.b | 0},${a.toFixed(3)})`;
}

/** Rotate point (x,y,z) by ax around X-axis then ay around Y-axis */
function rot(
  x: number, y: number, z: number, ax: number, ay: number
): [number, number, number] {
  const cy = Math.cos(ay), sy = Math.sin(ay);
  const x1 = x * cy - z * sy, z1 = x * sy + z * cy;
  const cx2 = Math.cos(ax), sx2 = Math.sin(ax);
  return [x1, y * cx2 - z1 * sx2, y * sx2 + z1 * cx2];
}

/** Perspective-project onto canvas */
function prj(rx: number, ry: number, rz: number, cx: number, cy: number, R: number) {
  const fov = 2.7;
  const s = fov / (fov + rz * 0.45);
  return { px: cx + rx * R * s, py: cy + ry * R * s, depth: rz, scale: s };
}

// ── Component ─────────────────────────────────────────────────────────────────

export function NeuralCore({ state, size = 320 }: NeuralCoreProps) {
  const canvasRef   = useRef<HTMLCanvasElement>(null);
  const stateRef    = useRef<CoreState>(state);
  const frameRef    = useRef<number>(0);
  const pausedRef   = useRef(false);
  stateRef.current  = state;

  const startAnimation = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d') as CanvasRenderingContext2D;
    if (!ctx) return;

    const DPR = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width  = size * DPR;
    canvas.height = size * DPR;
    ctx.scale(DPR, DPR);

    const W = size, H = size;
    const CX = W / 2, CY = H / 2;
    const R = W * 0.315; // sphere radius in logical px

    // ── Build neurons ─────────────────────────────────────────────────────

    const N = 80;
    const positions = fibSphere(N);

    const neurons: Neuron[] = positions.map(([bx, by, bz]) => ({
      bx, by, bz,
      ph: [
        Math.random() * Math.PI * 2, Math.random() * Math.PI * 2,
        Math.random() * Math.PI * 2, Math.random() * Math.PI * 2,
      ],
      fr: [
        0.00030 + Math.random() * 0.00040,
        0.00038 + Math.random() * 0.00050,
        0.00022 + Math.random() * 0.00035,
        0.00048 + Math.random() * 0.00060,
      ],
      noiseAmp:   0.055 + Math.random() * 0.095,
      size:       1.1  + Math.random() * 1.7,
      brightness: 0.50 + Math.random() * 0.50,
      flickerPh:  Math.random() * Math.PI * 2,
      flickerFr:  0.028 + Math.random() * 0.045,
      birthT: 0,       // assigned below
      activation: 0,
    }));

    // Startup birth order: neurons appear over 1500–2500 ms
    // Use a shuffled order so birth is organic, not front-to-back
    const birthOrder = Array.from({ length: N }, (_, i) => i)
      .sort(() => Math.random() - 0.5);
    birthOrder.forEach((ni, rank) => {
      neurons[ni].birthT = 1500 + (rank / N) * 1000;
    });

    // ── Build connections ─────────────────────────────────────────────────

    const MAX_PER_NODE = 6;
    const DIST_THR = 0.80;
    const connCount = new Array(N).fill(0);
    const connections: Connection[] = [];

    for (let i = 0; i < N; i++) {
      for (let j = i + 1; j < N; j++) {
        if (connCount[i] >= MAX_PER_NODE || connCount[j] >= MAX_PER_NODE) continue;
        const ni = neurons[i], nj = neurons[j];
        const d = Math.sqrt(
          (ni.bx - nj.bx) ** 2 + (ni.by - nj.by) ** 2 + (ni.bz - nj.bz) ** 2
        );
        if (d < DIST_THR) {
          const base = 0.07 + Math.random() * 0.17;
          connections.push({
            a: i, b: j,
            baseAlpha: base,
            currentAlpha: 0,
            targetAlpha: base,
            birthT: 2500 + Math.random() * 1000, // appear 2500–3500 ms
            pulses: [],
          });
          connCount[i]++;
          connCount[j]++;
        }
      }
    }

    // Per-neuron adjacency list (connection indices)
    const adj: number[][] = Array.from({ length: N }, () => []);
    connections.forEach((c, ci) => { adj[c.a].push(ci); adj[c.b].push(ci); });

    // ── Ambient particles ─────────────────────────────────────────────────

    const PARTS = 85;
    interface Particle { theta: number; phi: number; baseR: number; speed: number; phase: number; sz: number; bright: number }
    const particles: Particle[] = Array.from({ length: PARTS }, () => ({
      theta:  Math.random() * Math.PI * 2,
      phi:    Math.random() * Math.PI,
      baseR:  1.10 + Math.random() * 0.50,
      speed:  0.00025 + Math.random() * 0.00065,
      phase:  Math.random() * Math.PI * 2,
      sz:     0.45 + Math.random() * 0.75,
      bright: 0.28 + Math.random() * 0.72,
    }));

    // ── Animation state ───────────────────────────────────────────────────

    const startTime = performance.now();
    let angleY = 0;
    const TILT = 0.30; // fixed X-axis tilt

    let fc = 0; // frame counter

    // Neural cascade event queue
    const cascadeQ: CascadeEvent[] = [];
    let nextFireIn = 55 + Math.random() * 75; // frames until first cascade

    // Smooth config — starts at idle, lerps to target
    let cPrimary:     RGB    = { ...STATE_CFG.idle.primary };
    let cAccent:      RGB    = { ...STATE_CFG.idle.accent };
    let cGlow        = STATE_CFG.idle.glow;
    let cRotSpeed    = STATE_CFG.idle.rotSpeed;
    let cFiringRate  = STATE_CFG.idle.firingRate;
    let cConnAlpha   = STATE_CFG.idle.connAlpha;
    let cNodeAlpha   = STATE_CFG.idle.nodeAlpha;
    let cPartAlpha   = STATE_CFG.idle.partAlpha;
    let cInward      = STATE_CFG.idle.inward;
    let cBreathAmp   = STATE_CFG.idle.breathAmp;
    let cEnergySpeed = STATE_CFG.idle.energySpeed;

    // ── Cascade trigger ───────────────────────────────────────────────────

    function fireCascade(src: number, depth: number) {
      if (depth > 3) return;
      const conns = adj[src];
      if (!conns.length) return;
      const picks = Math.min(conns.length, 1 + (Math.random() < 0.38 ? 1 : 0));
      const chosen = [...conns].sort(() => Math.random() - 0.5).slice(0, picks);
      for (const ci of chosen) {
        const c = connections[ci];
        if (c.pulses.length >= 3) continue;
        const fwd = c.a === src;
        const spd = (0.007 + Math.random() * 0.013) * Math.max(0.5, cEnergySpeed);
        c.pulses.push({ t: fwd ? 0 : 1, speed: spd, alpha: 0.60 + Math.random() * 0.40, forward: fwd });
        c.targetAlpha = Math.min(0.95, c.baseAlpha * 4.5);
        const travelFrames = Math.ceil(1 / spd);
        const dest = fwd ? c.b : c.a;
        cascadeQ.push({ atFrame: fc + travelFrames, neuronIdx: dest, depth: depth + 1 });
      }
    }

    // ── Draw loop ─────────────────────────────────────────────────────────

    function draw(now: number) {
      if (pausedRef.current) {
        frameRef.current = requestAnimationFrame(draw);
        return;
      }

      const elapsed = now - startTime;
      const tgt = STATE_CFG[stateRef.current];

      // ── Lerp config (smooth state transitions) ─────────────────────────
      const LF = 0.022;
      cPrimary     = lerpRGB(cPrimary,    tgt.primary,  LF);
      cAccent      = lerpRGB(cAccent,     tgt.accent,   LF);
      cGlow        = lerp(cGlow,        tgt.glow,        LF);
      cRotSpeed    = lerp(cRotSpeed,    tgt.rotSpeed,    LF);
      cFiringRate  = lerp(cFiringRate,  tgt.firingRate,  LF);
      cConnAlpha   = lerp(cConnAlpha,   tgt.connAlpha,   LF);
      cNodeAlpha   = lerp(cNodeAlpha,   tgt.nodeAlpha,   LF);
      cPartAlpha   = lerp(cPartAlpha,   tgt.partAlpha,   LF);
      cInward      = lerp(cInward,      tgt.inward,      LF);
      cBreathAmp   = lerp(cBreathAmp,   tgt.breathAmp,   LF);
      cEnergySpeed = lerp(cEnergySpeed, tgt.energySpeed, LF);

      fc++;
      angleY += cRotSpeed;

      // ── Startup phase ──────────────────────────────────────────────────
      // phase 0: dark                  (0–500 ms)
      // phase 1: central point         (500–1500 ms)
      // phase 2: neurons born          (1500–2500 ms)
      // phase 3: connections appear    (2500–3500 ms)
      // phase 4: full operation        (3500 ms+)

      const phase =
        elapsed < 500  ? 0 :
        elapsed < 1500 ? 1 :
        elapsed < 2500 ? 2 :
        elapsed < 3500 ? 3 : 4;

      // ── Clear ──────────────────────────────────────────────────────────
      ctx.clearRect(0, 0, W, H);

      // ── Phase 0 — almost black ─────────────────────────────────────────
      if (phase === 0) {
        frameRef.current = requestAnimationFrame(draw);
        return;
      }

      // ── Phase 1 — tiny central point ───────────────────────────────────
      if (phase === 1) {
        const p = (elapsed - 500) / 1000; // 0-1
        const ptRadius = lerp(0, 5, Math.min(1, p * 2));
        const ptAlpha  = Math.min(1, p * 3);

        ctx.save();
        ctx.shadowColor = cs(cAccent, 1);
        ctx.shadowBlur  = 25 * ptAlpha;
        const pg = ctx.createRadialGradient(CX, CY, 0, CX, CY, ptRadius * 5);
        pg.addColorStop(0, cs(cAccent, ptAlpha));
        pg.addColorStop(0.5, cs(cPrimary, ptAlpha * 0.5));
        pg.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = pg;
        ctx.beginPath();
        ctx.arc(CX, CY, ptRadius * 5, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();

        frameRef.current = requestAnimationFrame(draw);
        return;
      }

      // ── Phase 2+ — full scene ──────────────────────────────────────────

      // Background ambient glow
      const bgFade = phase === 2 ? Math.min(1, (elapsed - 1500) / 600) : 1;
      const bg = ctx.createRadialGradient(CX, CY, R * 0.1, CX, CY, R * 1.9);
      bg.addColorStop(0, cs(cPrimary, 0.07 * bgFade));
      bg.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, W, H);

      // ── Organic breathing (layered sines — non-repetitive) ────────────
      const breathe =
        Math.sin(fc * 0.016) * 0.50 +
        Math.sin(fc * 0.010 + 1.3) * 0.30 +
        Math.sin(fc * 0.029 + 2.9) * 0.20;
      const globalBreath = 1 + breathe * 0.075 * cBreathAmp;

      // ── Neural cascade scheduler ──────────────────────────────────────
      nextFireIn -= cFiringRate * 0.018;
      if (nextFireIn <= 0) {
        const src = Math.floor(Math.random() * N);
        neurons[src].activation = Math.min(1, neurons[src].activation + 1);
        fireCascade(src, 0);
        nextFireIn = (28 + Math.random() * 85) / Math.max(0.5, cFiringRate);
      }

      // Process cascade arrivals
      for (let i = cascadeQ.length - 1; i >= 0; i--) {
        if (fc >= cascadeQ[i].atFrame) {
          const { neuronIdx, depth } = cascadeQ[i];
          cascadeQ.splice(i, 1);
          neurons[neuronIdx].activation = Math.min(1, neurons[neuronIdx].activation + 0.72);
          if (Math.random() < 0.28 - depth * 0.06) {
            fireCascade(neuronIdx, depth);
          }
        }
      }

      // ── Project neurons ────────────────────────────────────────────────
      type PN = { px: number; py: number; depth: number; scale: number; born: boolean; bFrac: number; idx: number };

      const projected: PN[] = neurons.map((n, i) => {
        // Organic displacement: product of two sines per axis → aperiodic motion
        const dx = Math.sin(fc * n.fr[0] + n.ph[0]) * Math.sin(fc * n.fr[2] + n.ph[2]) * n.noiseAmp;
        const dy = Math.sin(fc * n.fr[1] + n.ph[1]) * Math.sin(fc * n.fr[0] + n.ph[3]) * n.noiseAmp;
        const dz = Math.sin(fc * n.fr[2] + n.ph[2]) * Math.sin(fc * n.fr[3] + n.ph[1]) * n.noiseAmp;
        const [rx, ry, rz] = rot(n.bx + dx, n.by + dy, n.bz + dz, TILT, angleY);
        const p = prj(rx, ry, rz, CX, CY, R);
        const born = elapsed > n.birthT;
        const bFrac = born ? Math.min(1, (elapsed - n.birthT) / 380) : 0;
        return { ...p, born, bFrac, idx: i };
      });

      // ── Decay neuron activations, update flicker ───────────────────────
      for (const n of neurons) {
        n.activation *= 0.91;
        // Rare micro-flicker: spike activation briefly
        if (Math.sin(fc * n.flickerFr + n.flickerPh) > 0.94 && Math.random() < 0.07) {
          n.activation = Math.max(n.activation, 0.28);
        }
      }

      // ── Update connection alphas ───────────────────────────────────────
      for (const c of connections) {
        // Gradually restore target toward base alpha when not pumped
        c.targetAlpha = lerp(c.targetAlpha, c.baseAlpha * cConnAlpha, 0.014);
        c.currentAlpha = lerp(c.currentAlpha, c.targetAlpha, 0.09);
      }

      // ── Advance pulses ─────────────────────────────────────────────────
      for (const c of connections) {
        for (let i = c.pulses.length - 1; i >= 0; i--) {
          const p = c.pulses[i];
          const step = p.speed * Math.max(0.4, cEnergySpeed);
          p.t += p.forward ? step : -step;
          if (p.t > 1.02 || p.t < -0.02) c.pulses.splice(i, 1);
        }
      }

      // ── Draw connections (back-to-front) ───────────────────────────────
      const connsByDepth = connections
        .map((c, i) => ({
          c, i,
          avgDepth: (projected[c.a].depth + projected[c.b].depth) / 2,
        }))
        .sort((a, b) => a.avgDepth - b.avgDepth);

      ctx.save();
      for (const { c } of connsByDepth) {
        if (phase < 3 && elapsed < c.birthT) continue;
        const bFrac = Math.min(1, (elapsed - c.birthT) / 700);
        if (bFrac <= 0) continue;

        const pa = projected[c.a], pb = projected[c.b];
        if (!pa.born || !pb.born) continue;

        const avgD = (pa.depth + pb.depth) / 2;
        const visD = (avgD + 1) / 2;
        const alpha = c.currentAlpha * visD * bFrac * (0.35 + 0.65 * visD);
        if (alpha < 0.008) continue;

        // Connection line
        const grad = ctx.createLinearGradient(pa.px, pa.py, pb.px, pb.py);
        grad.addColorStop(0, cs(cPrimary, alpha * pa.scale));
        grad.addColorStop(1, cs(cAccent,  alpha * pb.scale * 0.65));
        ctx.shadowColor = cs(cPrimary, 0.25);
        ctx.shadowBlur  = cGlow * 0.22 * visD;
        ctx.strokeStyle = grad;
        ctx.lineWidth   = 0.45 + 0.45 * visD;
        ctx.beginPath();
        ctx.moveTo(pa.px, pa.py);
        ctx.lineTo(pb.px, pb.py);
        ctx.stroke();

        // Pulses on this connection
        if (c.pulses.length > 0) {
          ctx.shadowColor = cs(cAccent, 0.9);
          ctx.shadowBlur  = cGlow * 0.55;
          for (const p of c.pulses) {
            const tClamp = Math.max(0, Math.min(1, p.t));
            const ppx = pa.px + (pb.px - pa.px) * tClamp;
            const ppy = pa.py + (pb.py - pa.py) * tClamp;
            const pAlpha = p.alpha * visD * bFrac;
            if (pAlpha < 0.04) continue;

            // Soft glow around pulse
            const pulseR = 5.5 * visD;
            const pg = ctx.createRadialGradient(ppx, ppy, 0, ppx, ppy, pulseR);
            pg.addColorStop(0, cs(cAccent,   pAlpha * 0.85));
            pg.addColorStop(0.5, cs(cPrimary, pAlpha * 0.35));
            pg.addColorStop(1, 'rgba(0,0,0,0)');
            ctx.fillStyle = pg;
            ctx.beginPath();
            ctx.arc(ppx, ppy, pulseR, 0, Math.PI * 2);
            ctx.fill();

            // Bright core
            ctx.fillStyle = cs({ r: 230, g: 240, b: 255 }, pAlpha * 0.95);
            ctx.shadowBlur = 6;
            ctx.beginPath();
            ctx.arc(ppx, ppy, 1.4 * visD, 0, Math.PI * 2);
            ctx.fill();
          }
        }
      }
      ctx.restore();

      // ── Draw neurons (back-to-front) ───────────────────────────────────
      const nodesByDepth = [...projected].sort((a, b) => a.depth - b.depth);

      ctx.save();
      for (const p of nodesByDepth) {
        if (!p.born) continue;
        const n = neurons[p.idx];
        const visD = (p.depth + 1) / 2;

        // Composite brightness: base + activation spike + micro-flicker
        const actBoost   = n.activation * 0.55;
        const flickBoost = Math.sin(fc * n.flickerFr + n.flickerPh) > 0.88 ? 0.18 : 0;
        const breathNode = 0.70 + 0.20 * Math.sin(fc * 0.019 + n.ph[0] + angleY * 0.5);
        const alpha = Math.min(1,
          cNodeAlpha * n.brightness * visD * breathNode * globalBreath * p.bFrac
          + actBoost + flickBoost
        );
        if (alpha < 0.04) continue;

        const baseR = n.size * p.scale * globalBreath * p.bFrac;
        const activatedR = baseR + n.activation * 5 * visD;

        // Outer halo (no shadowBlur — cheaper, uses gradient)
        const haloR = activatedR * 4.5;
        const hg = ctx.createRadialGradient(p.px, p.py, 0, p.px, p.py, haloR);
        hg.addColorStop(0,   cs(cAccent,  Math.min(1, alpha * 0.55)));
        hg.addColorStop(0.4, cs(cPrimary, Math.min(1, alpha * 0.18)));
        hg.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.shadowBlur = 0;
        ctx.fillStyle  = hg;
        ctx.beginPath();
        ctx.arc(p.px, p.py, haloR, 0, Math.PI * 2);
        ctx.fill();

        // Core dot
        ctx.shadowColor = cs(cAccent, 0.9);
        ctx.shadowBlur  = cGlow * visD * 0.45 * (1 + n.activation * 0.8);
        // Slightly whiter when activated
        const dotWhite = Math.min(255, 210 + n.activation * 45) | 0;
        ctx.fillStyle  = cs({ r: dotWhite, g: dotWhite, b: 255 }, Math.min(1, alpha * 0.92));
        ctx.beginPath();
        ctx.arc(p.px, p.py, Math.max(0.5, activatedR), 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();

      // ── Core body glow ─────────────────────────────────────────────────
      const coreFade = phase >= 2 ? Math.min(1, (elapsed - 1500) / 900) : 0;
      if (coreFade > 0.01) {
        ctx.save();
        const cg = ctx.createRadialGradient(CX, CY, 0, CX, CY, R * 0.92);
        cg.addColorStop(0,   cs(cPrimary, 0.11 * globalBreath * coreFade));
        cg.addColorStop(0.45, cs(cPrimary, 0.04 * globalBreath * coreFade));
        cg.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle  = cg;
        ctx.shadowColor = cs(cPrimary, 0.35);
        ctx.shadowBlur  = cGlow * 2;
        ctx.beginPath();
        ctx.arc(CX, CY, R * 0.92, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }

      // ── Outer aura ─────────────────────────────────────────────────────
      if (coreFade > 0.01) {
        ctx.save();
        const ag = ctx.createRadialGradient(CX, CY, R * 0.85, CX, CY, R * 1.8);
        ag.addColorStop(0, cs(cPrimary, cNodeAlpha * 0.055 * globalBreath * coreFade));
        ag.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = ag;
        ctx.beginPath();
        ctx.arc(CX, CY, R * 1.8, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }

      // ── Ambient particles ──────────────────────────────────────────────
      if (phase >= 2) {
        const partFade = Math.min(1, (elapsed - 1500) / 1400);
        ctx.save();
        for (const p of particles) {
          p.theta += p.speed;
          const effectiveR = p.baseR * (1 - cInward * 0.48); // pull inward when listening
          const px0 = Math.cos(p.theta) * Math.sin(p.phi) * effectiveR;
          const py0 = Math.cos(p.phi) * effectiveR;
          const pz0 = Math.sin(p.theta) * Math.sin(p.phi) * effectiveR;
          const [rx, ry, rz] = rot(px0, py0, pz0, TILT, angleY * 0.58);
          const pp = prj(rx, ry, rz, CX, CY, R);
          const visD = (pp.depth + 1) / 2;
          const twinkle = 0.28 + 0.72 * Math.abs(Math.sin(fc * 0.011 + p.phase));
          const pAlpha = cPartAlpha * p.bright * visD * twinkle * partFade;
          if (pAlpha < 0.025) continue;
          ctx.shadowColor = cs(cPrimary, 0.5);
          ctx.shadowBlur  = 3 * visD;
          ctx.fillStyle   = cs(cAccent, pAlpha);
          ctx.beginPath();
          ctx.arc(pp.px, pp.py, p.sz * pp.scale, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.restore();
      }

      frameRef.current = requestAnimationFrame(draw);
    }

    frameRef.current = requestAnimationFrame(draw);

    // Pause when tab is backgrounded (saves battery on iPhone)
    const onVis = () => { pausedRef.current = document.hidden; };
    document.addEventListener('visibilitychange', onVis);

    return () => {
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [size]);

  useEffect(() => {
    const cleanup = startAnimation();
    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
      cleanup?.();
    };
  }, [startAnimation]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width: size, height: size }}
    />
  );
}
