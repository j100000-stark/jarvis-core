/**
 * ResponseCard — compact, auto-collapsing JARVIS response card.
 *
 * Shows the latest assistant message inline below the terminal.
 * Collapses to a one-liner preview; tap to expand.
 * Full conversation history lives in ChatSheet.
 */

import { useState, useEffect } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import type { Message } from './chat-sheet';

interface ResponseCardProps {
  message: Message | null;
  demoMode: boolean;
}

export function ResponseCard({ message, demoMode }: ResponseCardProps) {
  const [expanded, setExpanded] = useState(false);

  // Auto-collapse when a new message arrives
  useEffect(() => {
    setExpanded(false);
  }, [message?.id]);

  if (!message || message.role !== 'assistant') return null;

  const PREVIEW_LEN = 95;
  const isLong = message.body.length > PREVIEW_LEN;
  const preview = isLong && !expanded
    ? message.body.slice(0, PREVIEW_LEN) + '…'
    : message.body;

  return (
    <div
      style={{
        borderRadius: 12,
        background: 'rgba(4,12,24,0.88)',
        border: '1px solid rgba(0,160,255,0.13)',
        backdropFilter: 'blur(16px)',
        overflow: 'hidden',
      }}
    >
      {/* Header row */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => setExpanded((v) => !v)}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setExpanded((v) => !v); }}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 12px',
          cursor: 'pointer',
          borderBottom: expanded ? '1px solid rgba(0,160,255,0.08)' : 'none',
          userSelect: 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {/* J· avatar */}
          <div
            style={{
              width: 20,
              height: 20,
              borderRadius: 6,
              background: 'rgba(0,130,255,0.22)',
              color: '#00aaff',
              fontFamily: "'Space Mono', monospace",
              fontSize: 8,
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            J·
          </div>

          <span
            style={{
              fontFamily: "'Space Mono', monospace",
              fontSize: 8,
              letterSpacing: '0.18em',
              textTransform: 'uppercase',
              color: demoMode ? 'rgba(255,160,0,0.60)' : 'rgba(0,160,255,0.50)',
            }}
          >
            {demoMode ? '[Demo] Response' : 'Jarvis Response'}
          </span>

          <span
            style={{
              fontFamily: "'Space Mono', monospace",
              fontSize: 7,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'rgba(0,160,255,0.25)',
            }}
          >
            {message.time}
          </span>
        </div>

        {isLong && (
          <span style={{ color: 'rgba(0,160,255,0.32)', flexShrink: 0 }}>
            {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </span>
        )}
      </div>

      {/* Body */}
      <div style={{ padding: '8px 12px 10px' }}>
        <p
          style={{
            fontSize: 12.5,
            lineHeight: 1.55,
            color: 'rgba(255,255,255,0.80)',
            margin: 0,
            wordBreak: 'break-word',
          }}
        >
          {preview}
        </p>

        {/* Failure notice */}
        {message.failure && (
          <p
            style={{
              marginTop: 6,
              fontFamily: "'Space Mono', monospace",
              fontSize: 9,
              textTransform: 'uppercase',
              letterSpacing: '0.12em',
              color: 'rgba(255,100,60,0.75)',
            }}
          >
            ✕ {message.failure}
          </p>
        )}
      </div>
    </div>
  );
}
