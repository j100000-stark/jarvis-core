/**
 * LiveTerminal — scrolling monospace activity log.
 *
 * Severity color system:
 *   normal   → blue/cyan      (routine status)
 *   info     → light blue     (informational events)
 *   success  → cyan-green     (completed / healthy)
 *   warning  → amber          (degraded / watchout)
 *   error    → red            (failure)
 *   critical → bright red     (critical failure)
 *   recovery → amber          (recovery in progress)
 *
 * Older lines fade out gradually.  Newest line is full opacity.
 */

import { useEffect, useRef } from 'react';

// ── Public types ─────────────────────────────────────────────────────────────

export type TerminalSeverity =
  | 'normal'
  | 'info'
  | 'success'
  | 'warning'
  | 'error'
  | 'critical'
  | 'recovery';

export interface TerminalLine {
  id: string;
  text: string;   // full pre-formatted string e.g. "> RUNTIME .......... ONLINE"
  severity: TerminalSeverity;
  ts: number;     // Date.now()
}

// ── Severity styling ─────────────────────────────────────────────────────────

const SEV_COLOR: Record<TerminalSeverity, string> = {
  normal:   'rgba(0,160,255,0.55)',
  info:     'rgba(100,210,255,0.70)',
  success:  'rgba(0,210,155,0.80)',
  warning:  'rgba(255,165,0,0.90)',
  error:    'rgba(255,70,50,0.95)',
  critical: 'rgba(255,30,30,1.00)',
  recovery: 'rgba(255,150,0,0.85)',
};

const SEV_GLOW: Record<TerminalSeverity, string | undefined> = {
  normal:   undefined,
  info:     undefined,
  success:  'rgba(0,180,130,0.12)',
  warning:  'rgba(255,140,0,0.22)',
  error:    'rgba(255,60,40,0.30)',
  critical: 'rgba(255,20,20,0.42)',
  recovery: 'rgba(255,130,0,0.20)',
};

// ── Component ────────────────────────────────────────────────────────────────

interface LiveTerminalProps {
  lines: TerminalLine[];
  /** Number of lines to display (older lines scroll off). Default 12. */
  maxLines?: number;
  style?: React.CSSProperties;
}

export function LiveTerminal({ lines, maxLines = 12, style }: LiveTerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  const displayed = lines.slice(-maxLines);

  // Auto-scroll to bottom when new lines arrive
  useEffect(() => {
    const el = containerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines.length]);

  return (
    <div
      ref={containerRef}
      style={{
        fontFamily: "'Space Mono', 'Courier New', monospace",
        fontSize: '9.5px',
        lineHeight: '1.75',
        letterSpacing: '0.02em',
        overflowY: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        ...style,
      }}
    >
      {displayed.map((line, i) => {
        // Newest = last item (highest index). Fade older lines.
        const age = displayed.length - 1 - i; // 0 = newest
        const opacity = Math.max(0.18, 1 - age * 0.085);
        const color = SEV_COLOR[line.severity];
        const glow = SEV_GLOW[line.severity];
        return (
          <div
            key={line.id}
            style={{
              color,
              opacity,
              textShadow: glow ? `0 0 8px ${glow}` : undefined,
              transition: 'opacity 0.5s ease',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {line.text}
          </div>
        );
      })}
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Format as "> KEY .......... VALUE" with dots padding to column 22. */
export function termLine(key: string, value: string): string {
  const COL = 20;
  const k = key.toUpperCase().slice(0, COL - 2);
  const dots = '.'.repeat(Math.max(2, COL - k.length));
  return `> ${k} ${dots} ${value.toUpperCase()}`;
}

let _idN = 0;

/** Create a TerminalLine object ready to push into state. */
export function mkLine(
  key: string,
  value: string,
  severity: TerminalSeverity = 'normal',
): TerminalLine {
  return {
    id: `tl-${Date.now()}-${_idN++}`,
    text: termLine(key, value),
    severity,
    ts: Date.now(),
  };
}
