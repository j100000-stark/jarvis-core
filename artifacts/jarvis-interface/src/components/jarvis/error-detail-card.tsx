/**
 * ErrorDetailCard — compact expandable diagnostic card for execution failures.
 *
 * Shown in the main console (not inside the chat sheet) when a goal execution
 * fails with a structured error from the backend.  All fields are pre-sanitized
 * server-side; this component just renders them.
 *
 * Visual contract:
 *   - Collapsed: single-line pill showing error code + component (red tint).
 *   - Expanded:  shows type, component, step (if any), message, and recovery hint.
 *   - Never full-screen; lives in the same vertical stack as alert cards.
 */
import { useState } from 'react';
import { AlertTriangle, ChevronDown, ChevronRight, RefreshCw, XCircle } from 'lucide-react';

// Re-export so home.tsx and chat-sheet.tsx can share a single source of truth.
export interface ExecutionDiagnostic {
  code: string;
  type: string;
  message: string;
  component: string;
  step: string | null;
  recoverable: boolean;
  incidentId: number;
  operation: string;
  timestamp: string;
}

interface ErrorDetailCardProps {
  diagnostic: ExecutionDiagnostic;
  onDismiss?: () => void;
}

export function ErrorDetailCard({ diagnostic, onDismiss }: ErrorDetailCardProps) {
  const [expanded, setExpanded] = useState(false);

  const bg       = 'rgba(160,20,0,0.12)';
  const border   = 'rgba(255,60,20,0.25)';
  const dimRed   = 'rgba(255,80,40,0.70)';
  const dimText  = 'rgba(255,160,120,0.85)';
  const mutedRed = 'rgba(255,100,60,0.45)';

  return (
    <div
      style={{
        borderRadius: 10,
        border: `1px solid ${border}`,
        background: bg,
        overflow: 'hidden',
      }}
      data-testid="error-detail-card"
    >
      {/* ── Header row (always visible) ── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 12px',
        }}
      >
        {/* Toggle */}
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          style={{
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            padding: 0,
            textAlign: 'left',
          }}
          aria-label={expanded ? 'Collapse error detail' : 'Expand error detail'}
        >
          <XCircle size={12} style={{ color: dimRed, flexShrink: 0 }} />

          <span
            style={{
              fontFamily: "'Space Mono', monospace",
              fontSize: 9,
              textTransform: 'uppercase',
              letterSpacing: '0.16em',
              color: dimRed,
              flex: 1,
            }}
          >
            {diagnostic.code}
            <span style={{ color: mutedRed }}> · {diagnostic.component}</span>
            {diagnostic.step && (
              <span style={{ color: mutedRed }}> · step:{diagnostic.step}</span>
            )}
          </span>

          {diagnostic.recoverable ? (
            <RefreshCw size={10} style={{ color: 'rgba(255,160,60,0.65)', flexShrink: 0 }} />
          ) : (
            <AlertTriangle size={10} style={{ color: dimRed, flexShrink: 0 }} />
          )}

          {expanded
            ? <ChevronDown size={12} style={{ color: mutedRed, flexShrink: 0 }} />
            : <ChevronRight size={12} style={{ color: mutedRed, flexShrink: 0 }} />
          }
        </button>

        {/* Dismiss */}
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            style={{
              background: 'none',
              border: 'none',
              color: mutedRed,
              cursor: 'pointer',
              padding: '0 2px',
              lineHeight: 1,
              fontSize: 14,
              flexShrink: 0,
            }}
            aria-label="Dismiss error"
          >
            ×
          </button>
        )}
      </div>

      {/* ── Expanded detail ── */}
      {expanded && (
        <div
          style={{
            padding: '4px 12px 12px',
            borderTop: `1px solid rgba(255,60,20,0.12)`,
            display: 'flex',
            flexDirection: 'column',
            gap: 10,
          }}
        >
          {/* Message */}
          <div>
            <Label>Message</Label>
            <p style={{ color: dimText, fontSize: 12, lineHeight: 1.6, margin: 0 }}>
              {diagnostic.message}
            </p>
          </div>

          {/* Grid: type, component, step */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
            <Field label="Exception type" value={diagnostic.type} />
            <Field label="Component"      value={diagnostic.component} />
            {diagnostic.step && (
              <Field label="Failing step" value={diagnostic.step} />
            )}
            <Field label="Incident #" value={String(diagnostic.incidentId)} />
          </div>

          {/* Recovery hint */}
          <div
            style={{
              borderRadius: 7,
              padding: '7px 10px',
              background: diagnostic.recoverable
                ? 'rgba(255,140,0,0.08)'
                : 'rgba(180,20,0,0.10)',
              border: `1px solid ${
                diagnostic.recoverable
                  ? 'rgba(255,160,0,0.18)'
                  : 'rgba(200,40,0,0.22)'
              }`,
            }}
          >
            <p
              style={{
                fontFamily: "'Space Mono', monospace",
                fontSize: 9,
                textTransform: 'uppercase',
                letterSpacing: '0.14em',
                color: diagnostic.recoverable
                  ? 'rgba(255,165,0,0.75)'
                  : 'rgba(255,80,50,0.65)',
                margin: '0 0 3px',
              }}
            >
              {diagnostic.recoverable ? '↩ Recovery' : '✕ Not recoverable'}
            </p>
            <p
              style={{
                fontSize: 11,
                color: diagnostic.recoverable
                  ? 'rgba(255,185,80,0.80)'
                  : 'rgba(255,120,90,0.75)',
                margin: 0,
                lineHeight: 1.5,
              }}
            >
              {diagnostic.recoverable
                ? 'A retry or rephrased goal may succeed. Check the execution steps above for specifics.'
                : 'Manual intervention required. Verify your provider configuration and restart JARVIS.'}
            </p>
          </div>

          {/* Timestamp */}
          <p
            style={{
              fontFamily: "'Space Mono', monospace",
              fontSize: 8,
              color: 'rgba(255,100,60,0.30)',
              margin: 0,
              textAlign: 'right',
            }}
          >
            {diagnostic.timestamp}
          </p>
        </div>
      )}
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Label({ children }: { children: React.ReactNode }) {
  return (
    <p
      style={{
        fontFamily: "'Space Mono', monospace",
        fontSize: 8,
        textTransform: 'uppercase',
        letterSpacing: '0.14em',
        color: 'rgba(255,100,60,0.40)',
        margin: '0 0 3px',
      }}
    >
      {children}
    </p>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <Label>{label}</Label>
      <p
        style={{
          fontFamily: "'Space Mono', monospace",
          fontSize: 10,
          color: 'rgba(255,160,120,0.80)',
          margin: 0,
          wordBreak: 'break-all',
        }}
      >
        {value}
      </p>
    </div>
  );
}
