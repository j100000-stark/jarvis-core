/**
 * AlertCard — compact floating alert panel for system events.
 *
 * Alert severity colors:
 *   warning  → amber  (degraded, high load, limited resource)
 *   error    → red    (failure, connection lost, recovery attempt)
 *   critical → deep red + strong glow (critical system failure)
 *
 * Only the affected subsystem event turns amber/red.
 * The Neural Core receives a brief reactive pulse (handled in home.tsx).
 * This card never turns the entire screen red.
 */

import { X, AlertTriangle, AlertCircle, Zap } from 'lucide-react';

// ── Types ────────────────────────────────────────────────────────────────────

export type AlertSeverity = 'warning' | 'error' | 'critical';

export interface AlertEntry {
  id: string;
  title: string;
  body: string;
  severity: AlertSeverity;
  ts: number;
}

// ── Severity styles ──────────────────────────────────────────────────────────

interface SevStyle {
  bg: string;
  border: string;
  glow: string;
  title: string;
  body: string;
  icon: string;
}

const SEV_STYLE: Record<AlertSeverity, SevStyle> = {
  warning: {
    bg:     'rgba(180,90,0,0.14)',
    border: 'rgba(255,150,0,0.32)',
    glow:   '0 0 16px rgba(255,130,0,0.14)',
    title:  'rgba(255,165,0,0.98)',
    body:   'rgba(255,200,110,0.78)',
    icon:   'rgba(255,150,0,0.90)',
  },
  error: {
    bg:     'rgba(160,20,0,0.14)',
    border: 'rgba(255,60,40,0.38)',
    glow:   '0 0 16px rgba(255,50,30,0.18)',
    title:  'rgba(255,80,60,1.00)',
    body:   'rgba(255,145,125,0.82)',
    icon:   'rgba(255,60,40,0.95)',
  },
  critical: {
    bg:     'rgba(140,0,0,0.20)',
    border: 'rgba(255,20,20,0.55)',
    glow:   '0 0 24px rgba(255,10,10,0.25)',
    title:  'rgba(255,30,30,1.00)',
    body:   'rgba(255,120,100,0.88)',
    icon:   'rgba(255,20,20,1.00)',
  },
};

// ── Sub-components ───────────────────────────────────────────────────────────

function AlertIcon({ severity }: { severity: AlertSeverity }) {
  if (severity === 'critical') return <Zap size={11} />;
  if (severity === 'error') return <AlertCircle size={11} />;
  return <AlertTriangle size={11} />;
}

// ── AlertCard ────────────────────────────────────────────────────────────────

interface AlertCardProps {
  alerts: AlertEntry[];
  onDismiss: (id: string) => void;
}

export function AlertCard({ alerts, onDismiss }: AlertCardProps) {
  if (!alerts.length) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {alerts.map((alert) => {
        const s = SEV_STYLE[alert.severity];
        return (
          <div
            key={alert.id}
            className="jarvis-rise"
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 8,
              borderRadius: 12,
              padding: '9px 12px',
              background: s.bg,
              border: `1px solid ${s.border}`,
              boxShadow: s.glow,
              backdropFilter: 'blur(16px)',
            }}
          >
            {/* Icon */}
            <span style={{ color: s.icon, marginTop: 1, flexShrink: 0 }}>
              <AlertIcon severity={alert.severity} />
            </span>

            {/* Text */}
            <div style={{ minWidth: 0, flex: 1 }}>
              <p
                style={{
                  fontFamily: "'Space Mono', monospace",
                  fontSize: 9,
                  letterSpacing: '0.14em',
                  textTransform: 'uppercase',
                  fontWeight: 700,
                  color: s.title,
                  margin: 0,
                  lineHeight: 1.4,
                }}
              >
                {alert.title}
              </p>
              {alert.body && (
                <p
                  style={{
                    fontSize: 11,
                    lineHeight: 1.5,
                    color: s.body,
                    margin: '3px 0 0',
                  }}
                >
                  {alert.body}
                </p>
              )}
            </div>

            {/* Dismiss */}
            <button
              type="button"
              onClick={() => onDismiss(alert.id)}
              style={{
                flexShrink: 0,
                marginTop: 1,
                color: s.icon,
                opacity: 0.55,
                background: 'none',
                border: 'none',
                padding: 0,
                cursor: 'pointer',
                lineHeight: 1,
              }}
              aria-label="Dismiss alert"
            >
              <X size={11} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

// ── Factory helper ───────────────────────────────────────────────────────────

let _alertN = 0;

export function mkAlert(
  title: string,
  body: string,
  severity: AlertSeverity = 'warning',
): AlertEntry {
  return {
    id: `al-${Date.now()}-${_alertN++}`,
    title,
    body,
    severity,
    ts: Date.now(),
  };
}
