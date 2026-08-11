/**
 * Waveform — minimal animated audio wave indicator.
 * Uses Canvas 2D. State-driven amplitude.
 */
import { useEffect, useRef } from 'react';
import type { CoreState } from './neural-core';

const STATE_AMP: Record<CoreState, number> = {
  idle:      0.08,
  listening: 0.35,
  thinking:  0.55,
  speaking:  0.70,
  offline:   0.02,
  alert:     0.60,
};

const STATE_COLOR: Record<CoreState, string> = {
  idle:      '#0077cc',
  listening: '#00aaff',
  thinking:  '#00ddff',
  speaking:  '#00ffcc',
  offline:   '#1a3050',
  alert:     '#ff7700',
};

interface WaveformProps {
  state: CoreState;
  width?: number;
  height?: number;
}

export function Waveform({ state, width = 200, height = 36 }: WaveformProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frameRef = useRef<number>(0);
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctxOrNull = canvas.getContext('2d');
    if (!ctxOrNull) return;
    const ctx: CanvasRenderingContext2D = ctxOrNull;
    const DPR = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = width * DPR;
    canvas.height = height * DPR;
    ctx.scale(DPR, DPR);
    let t = 0;

    function draw() {
      t += 0.06;
      const s = stateRef.current;
      const amp = STATE_AMP[s] * (height * 0.42);
      const color = STATE_COLOR[s];
      ctx.clearRect(0, 0, width, height);

      const mid = height / 2;
      const bars = 28;
      const barW = 2;
      const gap = (width - bars * barW) / (bars + 1);

      for (let i = 0; i < bars; i++) {
        const x = gap + i * (barW + gap);
        const wave = Math.sin(t + i * 0.45) * Math.sin(t * 0.7 + i * 0.2);
        const h = Math.max(2, Math.abs(wave) * amp + 2);
        const alpha = 0.3 + 0.7 * Math.abs(wave);

        const r = parseInt(color.slice(1, 3), 16);
        const g = parseInt(color.slice(3, 5), 16);
        const b = parseInt(color.slice(5, 7), 16);

        const grad = ctx.createLinearGradient(x, mid - h, x, mid + h);
        grad.addColorStop(0, `rgba(${r},${g},${b},0)`);
        grad.addColorStop(0.5, `rgba(${r},${g},${b},${alpha})`);
        grad.addColorStop(1, `rgba(${r},${g},${b},0)`);

        ctx.shadowColor = color;
        ctx.shadowBlur = 6 * Math.abs(wave);
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.roundRect(x, mid - h, barW, h * 2, 1);
        ctx.fill();
      }
      frameRef.current = requestAnimationFrame(draw);
    }

    frameRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frameRef.current);
  }, [width, height]);

  return (
    <canvas
      ref={canvasRef}
      style={{ width, height, opacity: state === 'offline' ? 0.3 : 1 }}
    />
  );
}
