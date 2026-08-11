/**
 * JARVIS Cinematic Home — iPhone-first dark interface.
 *
 * Layout (portrait):
 *   ┌─────────────────────────┐
 *   │  JARVIS        [🛡] [⋯]  │  ← top bar
 *   │  ● STANDBY / PROCESSING  │  ← state chip
 *   │                          │
 *   │       ◎ Neural Core      │  ← full-width canvas
 *   │                          │
 *   │   "No provider…"         │  ← status label
 *   │   ≈≈ Waveform ≈≈         │
 *   │                          │
 *   │  [chat]  [●mic]  [sys]   │  ← bottom nav
 *   └─────────────────────────┘
 *
 * All positive labels (READY, CONNECTED, SECURE) are only shown when
 * the backend actually reports them.  DEMO MODE is prominently labelled.
 * Execution trace (agents, steps, tool outputs, verification) is shown
 * inside the chat sheet for every assistant response.
 */

import { useMemo, useState, useEffect, useRef } from 'react';
import { Activity, MessageSquare, Mic, MoreHorizontal, Shield, Wifi, WifiOff } from 'lucide-react';
import {
  getGetJarvisStatusQueryKey,
  getHealthCheckQueryKey,
  useGetJarvisStatus,
  useHealthCheck,
  useSendJarvisMessage,
} from '@workspace/api-client-react';
import { NeuralCore, type CoreState } from '@/components/jarvis/neural-core';
import { Waveform } from '@/components/jarvis/waveform';
import { ChatSheet, type Message } from '@/components/jarvis/chat-sheet';
import { SystemSheet } from '@/components/jarvis/system-sheet';

// ---- State chip config ----

const STATE_META: Record<CoreState, { label: string; color: string; dim: string }> = {
  idle:      { label: 'Standby',    color: '#0099dd', dim: 'rgba(0,153,221,0.15)' },
  listening: { label: 'Listening',  color: '#00aaff', dim: 'rgba(0,170,255,0.15)' },
  thinking:  { label: 'Processing', color: '#00ddff', dim: 'rgba(0,220,255,0.15)' },
  speaking:  { label: 'Responding', color: '#00ffcc', dim: 'rgba(0,255,200,0.15)' },
  offline:   { label: 'Offline',    color: '#335566', dim: 'rgba(30,50,70,0.3)'   },
  alert:     { label: 'Alert',      color: '#ff7700', dim: 'rgba(255,100,0,0.15)' },
};

// ---- Provider type derived from providerName ----

type ProviderType = 'demo' | 'real-llm' | 'local-llm' | 'none';

function deriveProviderType(providerName: string | undefined): ProviderType {
  if (!providerName || providerName === 'unconfigured') return 'none';
  if (providerName === 'demo') return 'demo';
  if (providerName.startsWith('llm:')) return 'real-llm';
  if (providerName.startsWith('local:')) return 'local-llm';
  return 'none';
}

function deriveModelLabel(providerName: string | undefined): string | null {
  if (!providerName) return null;
  if (providerName.startsWith('llm:')) {
    const parts = providerName.split(':');
    return parts.slice(2).join(':') || null;  // e.g. "gpt-4o-mini"
  }
  if (providerName.startsWith('local:')) return providerName.slice('local:'.length) || null;
  return null;
}

// ---- Status text derivation ----

function deriveStatus(
  connected: boolean | undefined,
  providerType: ProviderType,
  providerName: string | undefined,
  pending: boolean,
  isLoading: boolean,
): { line1: string; line2: string | null } {
  const modelLabel = deriveModelLabel(providerName);
  if (isLoading)                 return { line1: 'Connecting to runtime…',  line2: null };
  if (!connected)                return { line1: 'Runtime unreachable',      line2: 'Start the local JARVIS process' };
  if (providerType === 'none')   return { line1: 'No provider configured',   line2: 'Connect a local model or enable LLM mode' };
  if (providerType === 'demo')   return { line1: 'DEMO MODE',                line2: 'Scripted responses — no real AI' };
  if (providerType === 'real-llm' && pending) return { line1: 'Thinking…', line2: modelLabel };
  if (providerType === 'real-llm') return { line1: 'REAL LLM', line2: modelLabel };
  if (providerType === 'local-llm' && pending) return { line1: 'Processing…', line2: modelLabel };
  if (providerType === 'local-llm') return { line1: 'LOCAL LLM', line2: modelLabel };
  if (pending)                   return { line1: 'Processing goal…',        line2: providerName ?? null };
  return                                { line1: 'Ready',                    line2: providerName ?? null };
}

function deriveCoreState(
  connected: boolean | undefined,
  providerType: ProviderType,
  pending: boolean,
  speakingFor: boolean,
  isLoading: boolean,
): CoreState {
  if (isLoading || !connected)       return 'offline';
  if (providerType === 'none')       return 'idle';
  if (pending)                       return 'thinking';
  if (speakingFor)                   return 'speaking';
  return 'idle';
}

const formatTime = () =>
  new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date());

// ---- Component ----

export default function Home() {
  const [goal, setGoal] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [chatOpen, setChatOpen] = useState(false);
  const [sysOpen, setSysOpen] = useState(false);
  const [speakingFor, setSpeakingFor] = useState(false);
  const [demoMode, setDemoMode] = useState(false);
  const speakingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const status = useGetJarvisStatus({
    query: {
      queryKey: getGetJarvisStatusQueryKey(),
      refetchInterval: 15_000,
      refetchOnWindowFocus: true,
    },
  });
  const health = useHealthCheck({
    query: {
      queryKey: getHealthCheckQueryKey(),
      refetchInterval: 30_000,
      refetchOnWindowFocus: true,
    },
  });
  const sendMessage = useSendJarvisMessage();
  const runtime = status.data;
  const providerType = deriveProviderType(runtime?.providerName);

  // Sync demoMode state from providerType
  useEffect(() => {
    setDemoMode(providerType === 'demo');
  }, [providerType]);

  const sendError = useMemo(() => {
    if (!sendMessage.error) return null;
    const e = sendMessage.error as { error?: string; message?: string };
    return e.error ?? e.message ?? 'The runtime rejected that goal.';
  }, [sendMessage.error]);

  const coreState = deriveCoreState(
    runtime?.connected,
    providerType,
    sendMessage.isPending,
    speakingFor,
    status.isLoading && !runtime,
  );

  const statusText = deriveStatus(
    runtime?.connected,
    providerType,
    runtime?.providerName ?? undefined,
    sendMessage.isPending,
    status.isLoading && !runtime,
  );

  const ready = Boolean(runtime?.connected && providerType !== 'none');

  const handleSend = () => {
    const trimmed = goal.trim();
    if (!trimmed || !ready || sendMessage.isPending) return;
    const sentAt = formatTime();
    setMessages((cur) => [
      ...cur,
      { id: `u-${Date.now()}`, role: 'user', body: trimmed, time: sentAt },
    ]);
    setGoal('');

    sendMessage.mutate({ data: { goal: trimmed } }, {
      onSuccess: (result) => {
        setMessages((cur) => [
          ...cur,
          {
            id: `a-${Date.now()}`,
            role: 'assistant',
            body: result.response,
            providerName: result.providerName,
            time: formatTime(),
            // Structured execution trace (new fields from extended API)
            demoMode: result.demoMode ?? false,
            demoLabel: result.demoLabel ?? null,
            executionSteps: result.executionSteps ?? [],
            planGoal: result.planGoal ?? null,
            failure: result.failure ?? null,
          },
        ]);
        setSpeakingFor(true);
        if (speakingTimer.current) clearTimeout(speakingTimer.current);
        speakingTimer.current = setTimeout(() => setSpeakingFor(false), 3000);
      },
    });
  };

  const meta = STATE_META[coreState];
  const coreSize = 320;

  return (
    <div
      className="jarvis-cinematic relative flex min-h-[100dvh] flex-col overflow-hidden select-none"
      style={{ background: '#000408' }}
    >
      {/* Background radial gradient */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 z-0"
        style={{
          background:
            'radial-gradient(ellipse at 50% 35%, rgba(0,60,120,0.22) 0%, transparent 65%), radial-gradient(ellipse at 20% 80%, rgba(0,40,90,0.12) 0%, transparent 50%)',
        }}
      />

      {/* ── Top bar ── */}
      <header
        className="relative z-10 flex items-center justify-between px-5"
        style={{ paddingTop: 'max(1rem, env(safe-area-inset-top))', paddingBottom: '0.75rem' }}
      >
        <div className="flex items-center gap-3">
          <div
            className="flex size-9 items-center justify-center rounded-[11px] font-mono text-[14px] font-bold"
            style={{
              background: 'rgba(0,130,255,0.18)',
              border: '1px solid rgba(0,160,255,0.28)',
              color: '#00aaff',
              textShadow: '0 0 12px rgba(0,160,255,0.8)',
            }}
          >
            J·
          </div>
          <div>
            <p className="font-mono text-[9px] uppercase tracking-[0.22em]" style={{ color: 'rgba(0,160,255,0.45)' }}>
              Local system
            </p>
            <p className="text-[16px] font-semibold tracking-[-0.04em]" style={{ color: 'rgba(255,255,255,0.9)' }}>
              JARVIS
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span
            className="rounded-full px-2 py-0.5 font-mono text-[8px] uppercase tracking-[0.14em]"
            style={{ background: 'rgba(0,160,255,0.08)', color: 'rgba(0,160,255,0.4)', border: '1px solid rgba(0,160,255,0.12)' }}
          >
            {runtime?.version ?? 'v0.1'}
          </span>
          <button
            type="button"
            onClick={() => setSysOpen(true)}
            className="flex size-9 items-center justify-center rounded-xl transition active:scale-95"
            style={{ color: 'rgba(0,160,255,0.5)', background: 'rgba(0,160,255,0.06)', border: '1px solid rgba(0,160,255,0.10)' }}
            aria-label="System status"
            data-testid="button-open-system"
          >
            <Shield size={16} />
          </button>
          <button
            type="button"
            className="flex size-9 items-center justify-center rounded-xl"
            style={{ color: 'rgba(255,255,255,0.25)' }}
            aria-label="More options"
          >
            <MoreHorizontal size={18} />
          </button>
        </div>
      </header>

      {/* ── State chip ── */}
      <div className="relative z-10 flex justify-center py-1.5">
        <div
          className="flex items-center gap-2 rounded-full px-3 py-1.5 font-mono text-[9px] uppercase tracking-[0.15em]"
          style={{
            background: meta.dim,
            border: `1px solid ${meta.color}28`,
            color: meta.color,
            boxShadow: `0 0 16px ${meta.color}14`,
          }}
          data-testid="status-chip"
        >
          <span
            className="size-1.5 rounded-full"
            style={{
              background: meta.color,
              boxShadow: `0 0 6px ${meta.color}`,
              animation: coreState === 'offline' ? 'none' : 'pulse 2s infinite',
            }}
          />
          {meta.label}
          {demoMode && <span style={{ color: 'rgba(255,180,0,0.7)', marginLeft: 4 }}>· demo</span>}
        </div>
      </div>

      {/* ── Neural core ── */}
      <main className="relative z-10 flex flex-1 flex-col items-center justify-center py-2">
        <div
          aria-hidden
          className="pointer-events-none absolute rounded-full"
          style={{
            width: coreSize + 80,
            height: coreSize + 80,
            background: `radial-gradient(circle, ${meta.color}0a 0%, transparent 70%)`,
            boxShadow: `0 0 120px 20px ${meta.color}08`,
          }}
        />
        <div className="relative" data-testid="neural-core-container">
          <NeuralCore state={coreState} size={coreSize} />
        </div>

        {/* Status text */}
        <div className="mt-5 flex flex-col items-center gap-1 px-6 text-center">
          <p
            className="text-[15px] font-medium tracking-[-0.02em]"
            style={{
              color: coreState === 'offline' ? 'rgba(80,120,160,0.7)'
                   : demoMode ? 'rgba(255,180,0,0.85)'
                   : 'rgba(255,255,255,0.85)',
            }}
            data-testid="text-status-line1"
          >
            {statusText.line1}
          </p>
          {statusText.line2 && (
            <p
              className="font-mono text-[10px] uppercase tracking-[0.16em]"
              style={{ color: 'rgba(0,160,255,0.4)' }}
              data-testid="text-status-line2"
            >
              {statusText.line2}
            </p>
          )}
        </div>

        {/* Waveform */}
        <div className="mt-4 flex items-center justify-center opacity-80">
          <Waveform state={coreState} width={200} height={36} />
        </div>
      </main>

      {/* ── Network strip ── */}
      <div className="relative z-10 flex justify-center pb-2">
        <div className="flex items-center gap-2" style={{ color: 'rgba(0,160,255,0.28)' }}>
          {runtime?.connected ? <Wifi size={11} /> : <WifiOff size={11} />}
          <span className="font-mono text-[8px] uppercase tracking-[0.14em]">
            {runtime?.connected ? 'Runtime reachable' : 'Runtime unreachable'}
          </span>
          {!runtime?.externalApisEnabled && runtime?.connected && (
            <span className="font-mono text-[8px] uppercase tracking-[0.14em]" style={{ color: 'rgba(0,160,255,0.2)' }}>
              · local only
            </span>
          )}
        </div>
      </div>

      {/* ── Bottom nav ── */}
      <nav
        className="relative z-10 flex items-center justify-around px-6"
        style={{
          paddingBottom: 'max(1.5rem, env(safe-area-inset-bottom))',
          paddingTop: '1rem',
          borderTop: '1px solid rgba(0,160,255,0.07)',
          background: 'linear-gradient(to top, rgba(0,4,12,0.95), transparent)',
        }}
      >
        <NavButton
          onClick={() => setChatOpen(true)}
          label="Chat"
          icon={<MessageSquare size={20} />}
          badge={messages.length > 0 ? messages.length : undefined}
          data-testid="button-open-chat"
        />

        {/* Central mic / tap-to-speak */}
        <button
          type="button"
          onClick={() => setChatOpen(true)}
          disabled={!ready}
          className="flex flex-col items-center gap-1.5 transition active:scale-95 disabled:opacity-40"
          aria-label="Tap to speak or type a goal"
          data-testid="button-tap-to-speak"
        >
          <div
            className="flex size-[68px] items-center justify-center rounded-full"
            style={{
              background: ready
                ? `radial-gradient(circle at 40% 35%, ${meta.color}28, rgba(0,0,0,0.7))`
                : 'rgba(30,40,50,0.7)',
              border: `2px solid ${ready ? meta.color + '55' : 'rgba(60,80,100,0.3)'}`,
              boxShadow: ready ? `0 0 28px ${meta.color}25, inset 0 0 18px ${meta.color}10` : 'none',
            }}
          >
            <Mic size={26} style={{ color: ready ? meta.color : 'rgba(60,80,100,0.7)' }} />
          </div>
          <span
            className="font-mono text-[8px] uppercase tracking-[0.14em]"
            style={{ color: ready ? 'rgba(0,160,255,0.45)' : 'rgba(60,80,100,0.5)' }}
          >
            {ready ? 'Tap to speak' : 'Not ready'}
          </span>
        </button>

        <NavButton
          onClick={() => setSysOpen(true)}
          label="System"
          icon={<Activity size={20} />}
          data-testid="button-open-system-nav"
        />
      </nav>

      {/* ── Demo MODE banner ── */}
      {demoMode && (
        <div
          className="pointer-events-none absolute bottom-[100px] left-0 right-0 z-20 flex justify-center"
          data-testid="banner-demo-mode"
        >
          <div
            className="rounded-full px-4 py-1.5"
            style={{
              background: 'rgba(200,120,0,0.14)',
              border: '1px solid rgba(255,160,0,0.35)',
              backdropFilter: 'blur(12px)',
            }}
          >
            <span
              className="font-mono text-[9px] uppercase tracking-[0.2em]"
              style={{ color: 'rgba(255,180,60,0.85)' }}
            >
              ◈ demo mode — no real ai connected
            </span>
          </div>
        </div>
      )}

      {/* ── Sheets ── */}
      <ChatSheet
        open={chatOpen}
        onClose={() => setChatOpen(false)}
        messages={messages}
        goal={goal}
        onGoalChange={setGoal}
        onSend={handleSend}
        disabled={!ready}
        isPending={sendMessage.isPending}
        sendError={sendError}
      />
      <SystemSheet open={sysOpen} onClose={() => setSysOpen(false)} />
    </div>
  );
}

// ---- Sub-components ----

interface NavButtonProps {
  onClick: () => void;
  label: string;
  icon: React.ReactNode;
  badge?: number;
  'data-testid'?: string;
}

function NavButton({ onClick, label, icon, badge, 'data-testid': testid }: NavButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="relative flex flex-col items-center gap-1.5 transition active:scale-95"
      aria-label={label}
      data-testid={testid}
    >
      <div
        className="flex size-12 items-center justify-center rounded-2xl"
        style={{
          background: 'rgba(0,160,255,0.07)',
          border: '1px solid rgba(0,160,255,0.10)',
          color: 'rgba(0,160,255,0.55)',
        }}
      >
        {icon}
      </div>
      {badge !== undefined && (
        <span
          className="absolute -top-1 -right-1 flex size-4 items-center justify-center rounded-full font-mono text-[8px] font-bold"
          style={{ background: '#0099cc', color: '#fff' }}
        >
          {badge > 9 ? '9+' : badge}
        </span>
      )}
      <span className="font-mono text-[8px] uppercase tracking-[0.14em]" style={{ color: 'rgba(0,160,255,0.35)' }}>
        {label}
      </span>
    </button>
  );
}
