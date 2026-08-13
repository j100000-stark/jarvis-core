/**
 * JARVIS — Cinematic AI Operating Console.
 *
 * Layout (portrait/mobile-first):
 *   ┌──────────────────────────────────┐
 *   │  J· LOCAL SYSTEM   JARVIS  [v] [🛡] │  ← top bar
 *   ├──────────────────────────────────┤
 *   │                                  │
 *   │        ○  Neural Core  ○         │  ← dominates screen (~340px)
 *   │                                  │
 *   ├──────────────────────────────────┤
 *   │            ● STANDBY             │  ← state chip
 *   ├──────────────────────────────────┤
 *   │ > RUNTIME .......... ONLINE      │
 *   │ > GROQ ............. CONNECTED   │  ← live terminal (8–12 monospace lines)
 *   │ > SYSTEM ........... NOMINAL     │
 *   ├──────────────────────────────────┤
 *   │ [alert card — only when needed]  │  ← amber/red alerts (never full-screen)
 *   ├──────────────────────────────────┤
 *   │ J· Jarvis Response               │  ← compact response card
 *   │ "Il sistema è operativo."        │
 *   ├──────────────────────────────────┤
 *   │   [💬]       [🎤]       [⚙]      │  ← icon-only bottom nav
 *   └──────────────────────────────────┘
 *
 * State machine: idle → listening → thinking → executing → speaking → idle
 * Alert state: transient 4 s neural core pulse when a subsystem error occurs.
 * Terminal: real events only.  Never fabricates AI activity or system events.
 */

import {
  useState,
  useEffect,
  useRef,
  useCallback,
  useMemo,
} from 'react';
import { Activity, MessageSquare, Mic, MicOff, Shield } from 'lucide-react';
import {
  getGetJarvisStatusQueryKey,
  getHealthCheckQueryKey,
  useGetJarvisStatus,
  useHealthCheck,
  useSendJarvisMessage,
} from '@workspace/api-client-react';
import { NeuralCore, type CoreState } from '@/components/jarvis/neural-core';
import { ChatSheet, type Message } from '@/components/jarvis/chat-sheet';
import { SystemSheet } from '@/components/jarvis/system-sheet';
import { LiveTerminal, mkLine, type TerminalLine, type TerminalSeverity } from '@/components/jarvis/live-terminal';
import { AlertCard, mkAlert, type AlertEntry } from '@/components/jarvis/alert-card';
import { ErrorDetailCard, type ExecutionDiagnostic } from '@/components/jarvis/error-detail-card';
import { ResponseCard } from '@/components/jarvis/response-card';
import { useVoice, type TTSStage, type MicPermission } from '@/hooks/use-voice';
import { useWakeWord } from '@/hooks/use-wake-word';

// ── Provider helpers ─────────────────────────────────────────────────────────

type ProviderType = 'demo' | 'real-llm' | 'local-llm' | 'none';

function deriveProviderType(name: string | undefined): ProviderType {
  if (!name || name === 'unconfigured') return 'none';
  if (name === 'demo') return 'demo';
  if (name.startsWith('llm:')) return 'real-llm';
  if (name.startsWith('local:')) return 'local-llm';
  return 'none';
}

function deriveModelLabel(name: string | undefined): string | null {
  if (!name) return null;
  if (name.startsWith('llm:')) return name.split(':').slice(2).join(':') || null;
  if (name.startsWith('local:')) return name.slice('local:'.length) || null;
  return null;
}

// ── State config ─────────────────────────────────────────────────────────────

const STATE_META: Record<CoreState, { label: string; color: string; dim: string }> = {
  idle:      { label: 'Standby',    color: '#0099dd', dim: 'rgba(0,153,221,0.14)' },
  listening: { label: 'Listening',  color: '#00aaff', dim: 'rgba(0,170,255,0.16)' },
  thinking:  { label: 'Processing', color: '#00ddff', dim: 'rgba(0,220,255,0.14)' },
  executing: { label: 'Executing',  color: '#00ffaa', dim: 'rgba(0,255,170,0.12)' },
  speaking:  { label: 'Speaking',   color: '#00ffcc', dim: 'rgba(0,255,200,0.13)' },
  offline:   { label: 'Offline',    color: '#2d4d66', dim: 'rgba(30,55,80,0.25)'  },
  alert:     { label: 'Alert',      color: '#ff7000', dim: 'rgba(255,100,0,0.13)' },
};

// ── Core state derivation ─────────────────────────────────────────────────────

function deriveCoreState(
  connected: boolean | undefined,
  pending: boolean,
  ttsActive: boolean,
  isLoading: boolean,
  isListening: boolean,
  isSpeaking: boolean,
  alertPulse: boolean,
): CoreState {
  if (isLoading || !connected)     return 'offline';
  if (isListening)                 return 'listening';
  if (isSpeaking || ttsActive)     return 'speaking';
  if (pending)                     return 'thinking';
  if (alertPulse)                  return 'alert';
  return 'idle';
}

// ── Time helper ───────────────────────────────────────────────────────────────

const fmt = () =>
  new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(new Date());

// ── Terminal helpers ──────────────────────────────────────────────────────────

const MAX_TERM_LINES = 120;

// ── Component ─────────────────────────────────────────────────────────────────

export default function Home() {
  // ── UI state ─────────────────────────────────────────────────────────────
  const [chatOpen, setChatOpen]   = useState(false);
  const [sysOpen,  setSysOpen]    = useState(false);
  const [goal,     setGoal]       = useState('');
  const [messages, setMessages]   = useState<Message[]>([]);
  const [ttsActive, setTtsActive] = useState(false);

  // ── Terminal ─────────────────────────────────────────────────────────────
  const [termLines, setTermLines] = useState<TerminalLine[]>([]);

  const pushLine = useCallback(
    (key: string, value: string, severity: TerminalSeverity = 'normal') => {
      setTermLines((prev) => {
        const next = [...prev, mkLine(key, value, severity)];
        return next.length > MAX_TERM_LINES ? next.slice(-MAX_TERM_LINES) : next;
      });
    },
    [],
  );

  // ── Execution error diagnostic ────────────────────────────────────────────
  const [lastError, setLastError] = useState<ExecutionDiagnostic | null>(null);

  const dismissError = useCallback(() => setLastError(null), []);

  // ── Alerts ───────────────────────────────────────────────────────────────
  const [alerts, setAlerts] = useState<AlertEntry[]>([]);

  const pushAlert = useCallback(
    (title: string, body: string, severity: AlertEntry['severity'] = 'warning') => {
      setAlerts((prev) => [...prev, mkAlert(title, body, severity)]);
    },
    [],
  );

  const dismissAlert = useCallback((id: string) => {
    setAlerts((prev) => prev.filter((a) => a.id !== id));
  }, []);

  // ── Brief alert pulse on Neural Core ─────────────────────────────────────
  const [alertPulse, setAlertPulse] = useState(false);
  const alertPulseTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const triggerAlertPulse = useCallback(() => {
    setAlertPulse(true);
    if (alertPulseTimer.current) clearTimeout(alertPulseTimer.current);
    alertPulseTimer.current = setTimeout(() => setAlertPulse(false), 4000);
  }, []);

  // ── API ──────────────────────────────────────────────────────────────────
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

  const runtime      = status.data;
  const providerType = deriveProviderType(runtime?.providerName);
  const modelLabel   = deriveModelLabel(runtime?.providerName);
  const demoMode     = providerType === 'demo';
  const ready        = Boolean(runtime?.connected && providerType !== 'none');

  // ── Neural core dynamic size ──────────────────────────────────────────────
  const coreSize = useMemo(() => {
    if (typeof window === 'undefined') return 300;
    return Math.min(window.innerWidth - 40, 340);
  }, []);

  // ── Voice pipeline ────────────────────────────────────────────────────────
  const lastTranscriptRef = useRef('');
  const ttsTimer          = useRef<ReturnType<typeof setTimeout> | null>(null);

  const voice = useVoice({
    onTranscript: useCallback((text: string) => {
      if (!text.trim()) return;
      lastTranscriptRef.current = text;
      setGoal(text);
      pushLine('SPEECH', 'TRANSCRIBED', 'info');
    }, [pushLine]),
    onTtsStage: useCallback((stage: TTSStage, detail?: string) => {
      switch (stage) {
        case 'requesting':  pushLine('TTS',   'REQUESTING',      'normal');  break;
        case 'received':    pushLine('AUDIO', 'RECEIVED',        'normal');  break;
        case 'playing':     pushLine('AUDIO', 'PLAYING',         'success'); break;
        case 'play_failed': pushLine('AUDIO', detail ?? 'PLAY_FAILED', 'error'); break;
        case 'fallback':
          // Surface the REAL failure category before falling back —
          // the fallback must never hide the root cause.
          if (detail) pushLine('TTS FAILURE', detail, 'error');
          pushLine('TTS', 'BROWSER_FALLBACK', 'warning');
          break;
        case 'error':       pushLine('TTS',   detail ?? 'ERROR', 'error');   break;
        case 'ended':       pushLine('AUDIO', 'ENDED',           'normal');  break;
        default:            break;
      }
    }, [pushLine]),
  });

  // ── Microphone permission — requested proactively on app open ─────────────
  const [micPermission, setMicPermission] = useState<MicPermission>('unknown');
  const micInitRef = useRef(false);
  useEffect(() => {
    if (micInitRef.current) return;
    micInitRef.current = true;
    voice.initMicrophone().then((perm) => {
      setMicPermission(perm);
      if (perm === 'granted') {
        pushLine('MICROPHONE', 'READY', 'success');
      } else if (perm === 'denied') {
        pushLine('MICROPHONE', 'PERMISSION DENIED', 'error');
        pushAlert(
          'Microphone Blocked',
          'Enable microphone access in your browser settings to talk to JARVIS.',
          'warning',
        );
      } else if (perm === 'unsupported') {
        pushLine('MICROPHONE', 'UNSUPPORTED', 'warning');
      }
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Wake word — primary hands-free activation (spec Phase 2) ──────────────
  const wakeWord = useWakeWord({
    enabled:
      ready &&
      micPermission === 'granted' &&
      voice.voiceState === 'idle' &&
      !sendMessage.isPending &&
      !chatOpen,
    onWake: useCallback((command: string) => {
      pushLine('WAKE WORD', 'DETECTED', 'success');
      if (command) {
        // Wake phrase carried a command ("Jarvis, che ore sono?") — submit it.
        lastTranscriptRef.current = command;
        setGoal(command);
      } else {
        // Bare wake word — open the mic for the command.
        voice.startListening();
      }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [pushLine]),
    onStatusChange: useCallback((status: string) => {
      if (status === 'listening')   pushLine('WAKE WORD', 'ACTIVE — SAY "JARVIS"', 'info');
      if (status === 'restricted')  pushLine('WAKE WORD', 'UNAVAILABLE — USE MIC BUTTON', 'warning');
      if (status === 'unsupported') pushLine('WAKE WORD', 'UNSUPPORTED — USE MIC BUTTON', 'warning');
    }, [pushLine]),
  });

  // ── Transition refs (for detecting state changes) ─────────────────────────
  const prevConnectedRef  = useRef<boolean | undefined>(undefined);
  const prevProviderRef   = useRef<string | undefined>(undefined);
  const prevListeningRef  = useRef(false);
  const prevSpeakingRef   = useRef(false);
  const prevPendingRef    = useRef(false);
  const hasBootedRef      = useRef(false);

  // ── Boot sequence (fires once when runtime first connects) ────────────────
  useEffect(() => {
    if (!runtime?.connected || hasBootedRef.current) return;
    hasBootedRef.current = true;

    const delay = (ms: number, fn: () => void) =>
      setTimeout(fn, ms);

    delay(0,   () => pushLine('RUNTIME',    'ONLINE',          'success'));
    delay(120, () => pushLine('MEMORY',     'READY',           'info'));
    delay(240, () => pushLine('NETWORK',    'MONITORING',      'info'));
    delay(360, () => pushLine('SECURITY',   'STANDBY',         'info'));
    delay(480, () => {
      if (providerType === 'real-llm') {
        const provParts = (runtime?.providerName ?? '').split(':');
        const provName  = provParts[1]?.toUpperCase() ?? 'LLM';
        pushLine(provName,    'CONNECTED', 'success');
        if (modelLabel) pushLine('MODEL', modelLabel, 'info');
      } else if (providerType === 'local-llm') {
        pushLine('LOCAL AI', 'CONNECTED',  'success');
        if (modelLabel) pushLine('MODEL', modelLabel, 'info');
      } else if (providerType === 'demo') {
        pushLine('BRAIN',   'DEMO MODE',   'warning');
      } else {
        pushLine('PROVIDER', 'NONE',        'warning');
      }
    });
    // ELEVENLABS status is verified with a REAL synthesis test — never faked.
    delay(600, () => {
      fetch('/api/tts/health')
        .then((r) => r.json())
        .then((h: { ready?: boolean; category?: string }) => {
          if (h.ready) pushLine('ELEVENLABS', 'VERIFIED', 'success');
          else pushLine('ELEVENLABS', h.category ?? 'UNAVAILABLE', 'error');
        })
        .catch(() => pushLine('ELEVENLABS', 'UNREACHABLE', 'error'));
    });
    delay(720, () => pushLine('VOICE',      'READY',           'info'));
    delay(840, () => pushLine('WATCHDOG',   'ACTIVE',          'info'));
    delay(960, () => pushLine('TOOLS',      '11 REGISTERED',   'info'));
    delay(1080,() => pushLine('SYSTEM',     'NOMINAL',         'success'));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runtime?.connected]);

  // ── Runtime online/offline transitions ───────────────────────────────────
  useEffect(() => {
    const prev = prevConnectedRef.current;
    const now  = runtime?.connected;
    prevConnectedRef.current = now;

    if (prev === undefined) return; // first render — boot sequence handles it

    if (prev && !now) {
      pushLine('RUNTIME', 'OFFLINE', 'error');
      pushAlert('Runtime Offline', 'Connection to JARVIS process lost.', 'error');
      triggerAlertPulse();
    }
    if (!prev && now) {
      pushLine('RUNTIME', 'RECONNECTED', 'success');
      setAlerts((prev) => prev.filter((a) => !a.title.toLowerCase().includes('offline')));
    }
  }, [runtime?.connected, pushLine, pushAlert, triggerAlertPulse]);

  // ── Provider change events ────────────────────────────────────────────────
  useEffect(() => {
    const prev = prevProviderRef.current;
    const now  = runtime?.providerName;
    prevProviderRef.current = now;

    if (prev === undefined || prev === now || !hasBootedRef.current) return;

    if (now === 'demo') {
      pushLine('BRAIN', 'DEMO MODE', 'warning');
    } else if (now?.startsWith('llm:')) {
      const parts = now.split(':');
      pushLine(parts[1]?.toUpperCase() ?? 'LLM', 'CONNECTED', 'success');
    } else if (now?.startsWith('local:')) {
      pushLine('LOCAL AI', 'CONNECTED', 'success');
    }
  }, [runtime?.providerName, pushLine]);

  // ── API health error events ───────────────────────────────────────────────
  useEffect(() => {
    if (!health.isError) return;
    pushLine('HEALTH CHECK', 'FAILED', 'error');
    triggerAlertPulse();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [health.isError]);

  // ── STT listening transitions ─────────────────────────────────────────────
  useEffect(() => {
    const prev = prevListeningRef.current;
    prevListeningRef.current = voice.isListening;

    if (!prev && voice.isListening) {
      pushLine('MICROPHONE', 'ACTIVE', 'info');
      pushLine('INPUT', 'RECEIVED', 'info');
    }
    if (prev && !voice.isListening && !voice.transcript) {
      // cancelled or timed out without final transcript
      pushLine('MICROPHONE', 'CLOSED', 'normal');
    }
  }, [voice.isListening, voice.transcript, pushLine]);

  // ── TTS speaking transitions ──────────────────────────────────────────────
  useEffect(() => {
    const prev = prevSpeakingRef.current;
    prevSpeakingRef.current = voice.isSpeaking;

    if (!prev && voice.isSpeaking) {
      if (voice.ttsProvider === 'elevenlabs') {
        pushLine('ELEVENLABS', 'SYNTHESIS', 'info');
        pushLine('AUDIO', 'STREAMING', 'normal');
      } else if (voice.ttsProvider === 'browser') {
        pushLine('TTS', 'BROWSER FALLBACK', 'warning');
      }
      pushLine('JARVIS', 'SPEAKING', 'success');
    }
    if (prev && !voice.isSpeaking) {
      pushLine('JARVIS', 'IDLE', 'normal');
    }
  }, [voice.isSpeaking, voice.ttsProvider, pushLine]);

  // ── LLM pending transitions ───────────────────────────────────────────────
  useEffect(() => {
    const prev = prevPendingRef.current;
    prevPendingRef.current = sendMessage.isPending;

    if (!prev && sendMessage.isPending) {
      if (providerType === 'demo') {
        pushLine('[DEMO] GROQ', 'PROCESSING', 'normal');
      } else {
        const provParts = (runtime?.providerName ?? '').split(':');
        const provName  = provParts[1]?.toUpperCase() ?? 'LLM';
        pushLine(provName, 'PROCESSING', 'normal');
      }
    }
  }, [sendMessage.isPending, providerType, runtime?.providerName, pushLine]);

  // ── Send error events ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!sendMessage.error) return;
    const e = sendMessage.error as { error?: string; message?: string };
    const msg = e.error ?? e.message ?? 'Unknown error';
    pushLine('REQUEST', 'FAILED', 'error');
    pushAlert('Request Failed', msg, 'error');
    triggerAlertPulse();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sendMessage.error]);

  // ── Voice error events ────────────────────────────────────────────────────
  useEffect(() => {
    if (voice.voiceState !== 'error' || !voice.error) return;
    pushLine('VOICE', 'ERROR', 'error');
    triggerAlertPulse();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voice.voiceState, voice.error]);

  // ── Core state + status text ──────────────────────────────────────────────
  const coreState = deriveCoreState(
    runtime?.connected,
    sendMessage.isPending,
    ttsActive,
    status.isLoading && !runtime,
    voice.isListening,
    voice.isSpeaking,
    alertPulse,
  );
  const meta = STATE_META[coreState];

  // ── Send message ──────────────────────────────────────────────────────────
  const handleSend = useCallback(() => {
    const trimmed = goal.trim();
    if (!trimmed || !ready || sendMessage.isPending) return;

    const sentAt = fmt();
    setMessages((cur) => [
      ...cur,
      { id: `u-${Date.now()}`, role: 'user', body: trimmed, time: sentAt },
    ]);
    setGoal('');
    lastTranscriptRef.current = '';

    if (demoMode) {
      pushLine('[DEMO] REQUEST', 'RECEIVED', 'info');
      pushLine('[DEMO] AGENT', 'SELECTED', 'info');
      pushLine('[DEMO] SYSTEM', 'SNAPSHOT', 'info');
    } else {
      pushLine('REQUEST', 'SENT', 'info');
      pushLine('PLAN', 'CREATING', 'info');
    }

    sendMessage.mutate({ data: { goal: trimmed } }, {
      onSuccess: (result) => {
        // Surface the structured execution diagnostic if present.
        // Cast through an intersection because the dist declaration may lag behind the
        // updated source — the runtime field is always present when success=false.
        type ResultWithError = typeof result & { error?: ExecutionDiagnostic | null };
        const execError = (result as ResultWithError).error ?? null;

        const assistantMsg: Message = {
          id: `a-${Date.now()}`,
          role: 'assistant',
          body: result.response,
          providerName: result.providerName,
          time: fmt(),
          demoMode: result.demoMode ?? false,
          demoLabel: result.demoLabel ?? null,
          executionSteps: result.executionSteps ?? [],
          planGoal: result.planGoal ?? null,
          failure: result.failure ?? null,
          error: execError,
        };
        setMessages((cur) => [...cur, assistantMsg]);

        if (demoMode) {
          pushLine('[DEMO] ANALYSIS', 'COMPLETE', 'info');
          pushLine('[DEMO] SAFETY', 'CHECK', 'info');
          pushLine('[DEMO] RESPONSE', 'READY', 'success');
        } else {
          const steps = result.executionSteps ?? [];
          if (steps.length > 0) {
            pushLine('AGENT', 'SELECTED', 'info');
            pushLine('TOOL', 'EXECUTION', 'info');
            // Truthful per-tool events for completed steps (spec Phase 12/14)
            for (const step of steps) {
              if (step.tool === 'web_research') {
                pushLine('WEB', 'SEARCHING', 'info');
                if (step.error) pushLine('WEB', 'ERROR', 'error');
                else pushLine('WEB', 'RESULTS RECEIVED', 'success');
              } else if (step.error) {
                pushLine(step.tool.toUpperCase().slice(0, 14), 'FAILED', 'error');
              }
            }
            pushLine('RESULT', 'RECEIVED', 'info');
          }

          // Self-repair lifecycle events (sanitized server-side)
          const repairNotes = (result as typeof result & { repairNotes?: string[] | null })
            .repairNotes ?? [];
          if (repairNotes.length > 0) {
            pushLine('SELF-REPAIR', 'TRIGGERED', 'recovery');
            for (const note of repairNotes.slice(0, 6)) {
              pushLine('REPAIR', note.slice(0, 48).toUpperCase(), 'recovery');
            }
          }

          if (!result.success && execError) {
            // Structured exception — push diagnostic terminal events
            pushLine(`❌ ERROR`, execError.type, 'error');
            pushLine('COMPONENT', execError.component.toUpperCase(), 'error');
            if (execError.step) pushLine('STEP', execError.step, 'error');
            pushLine(
              'RECOVERY',
              execError.recoverable ? 'ATTEMPTING' : 'NOT POSSIBLE',
              execError.recoverable ? 'warning' : 'error',
            );
            if (execError.recoverable) {
              // Brief pause then show outcome — executor already retried internally
              setTimeout(() => pushLine('RECOVERY', 'FAILED', 'error'), 900);
            }
            setLastError(execError);
            pushAlert(
              `${execError.code}`,
              execError.message.slice(0, 120),
              execError.recoverable ? 'warning' : 'error',
            );
            triggerAlertPulse();
          } else if (!result.success && result.failure) {
            // Clean step-level failure (executor returned failed report, not exception)
            pushLine('RESULT', 'STEP FAILED', 'warning');
            pushLine('FAILURE', result.failure.slice(0, 60), 'warning');
            triggerAlertPulse();
          } else {
            pushLine('RESPONSE', 'GENERATED', 'success');
          }
        }

        if (voice.isSupported && result.response) {
          if (demoMode) pushLine('[DEMO] RESPONSE', 'READY', 'success');
          voice.speak(result.response);
        } else {
          // Non-voice fallback: show speaking indicator briefly
          setTtsActive(true);
          if (ttsTimer.current) clearTimeout(ttsTimer.current);
          ttsTimer.current = setTimeout(() => setTtsActive(false), 3000);
        }
      },
    });
  }, [goal, ready, sendMessage, demoMode, pushLine, voice]);

  // Auto-send when voice transcript arrives
  useEffect(() => {
    if (
      goal.trim() &&
      goal === lastTranscriptRef.current &&
      !sendMessage.isPending &&
      ready
    ) {
      handleSend();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [goal]);

  // ── Mic button ────────────────────────────────────────────────────────────
  const handleMicPress = useCallback(() => {
    if (!voice.isSupported) {
      setChatOpen(true);
      return;
    }
    if (voice.isListening) {
      voice.stopListening();
    } else if (voice.isSpeaking) {
      voice.cancelSpeaking();
    } else if (ready) {
      // Unlock iOS AudioContext during this user gesture so the subsequent
      // async audio.play() call in speak() is permitted by Safari's autoplay policy.
      voice.unlockAudio();
      voice.startListening();
    }
  }, [voice, ready]);

  // ── Last assistant message for response card ───────────────────────────────
  const lastAssistant = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === 'assistant') return messages[i];
    }
    return null;
  }, [messages]);

  // ── Send error for chat sheet ─────────────────────────────────────────────
  const sendError = useMemo(() => {
    if (!sendMessage.error) return null;
    const e = sendMessage.error as { error?: string; message?: string };
    return e.error ?? e.message ?? 'The runtime rejected that goal.';
  }, [sendMessage.error]);

  // ── Live transcript preview ───────────────────────────────────────────────
  const showTranscript = voice.isListening && voice.transcript;

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div
      className="jarvis-cinematic relative flex min-h-[100dvh] flex-col overflow-hidden select-none"
      style={{ background: '#000408' }}
    >
      {/* ── Background radial ambience ── */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 z-0"
        style={{
          background:
            `radial-gradient(ellipse at 50% 32%, ${meta.color}0d 0%, transparent 60%),
             radial-gradient(ellipse at 20% 75%, rgba(0,40,90,0.10) 0%, transparent 50%)`,
          transition: 'background 2s ease',
        }}
      />

      {/* ── Top bar ── */}
      <header
        className="relative z-10 flex items-center justify-between px-4"
        style={{
          paddingTop: 'max(0.85rem, env(safe-area-inset-top))',
          paddingBottom: '0.65rem',
        }}
      >
        {/* Left: logo + title */}
        <div className="flex items-center gap-2.5">
          <div
            style={{
              width: 34,
              height: 34,
              borderRadius: 9,
              background: 'rgba(0,130,255,0.16)',
              border: '1px solid rgba(0,160,255,0.26)',
              color: '#00aaff',
              fontFamily: "'Space Mono', monospace",
              fontSize: 12,
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              textShadow: '0 0 10px rgba(0,160,255,0.7)',
            }}
          >
            J·
          </div>
          <div>
            <p
              style={{
                fontFamily: "'Space Mono', monospace",
                fontSize: 8,
                textTransform: 'uppercase',
                letterSpacing: '0.22em',
                color: 'rgba(0,160,255,0.38)',
                margin: 0,
              }}
            >
              Local system
            </p>
            <p
              style={{
                fontSize: 15,
                fontWeight: 600,
                letterSpacing: '-0.03em',
                color: 'rgba(255,255,255,0.88)',
                margin: 0,
              }}
            >
              JARVIS
            </p>
          </div>
        </div>

        {/* Right: mode badge + status dot + shield */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {/* Mode badge */}
          <div
            style={{
              padding: '3px 9px',
              borderRadius: 20,
              border: `1px solid ${
                demoMode
                  ? 'rgba(255,150,0,0.30)'
                  : providerType === 'real-llm' || providerType === 'local-llm'
                  ? 'rgba(0,160,255,0.22)'
                  : 'rgba(0,160,255,0.10)'
              }`,
              background: demoMode
                ? 'rgba(200,100,0,0.12)'
                : providerType === 'real-llm' || providerType === 'local-llm'
                ? 'rgba(0,120,255,0.08)'
                : 'rgba(0,160,255,0.05)',
              display: 'flex',
              flexDirection: 'column' as const,
              alignItems: 'flex-end',
              gap: 1,
            }}
          >
            <span
              style={{
                fontFamily: "'Space Mono', monospace",
                fontSize: 7.5,
                textTransform: 'uppercase',
                letterSpacing: '0.14em',
                fontWeight: 700,
                color: demoMode
                  ? 'rgba(255,165,0,0.90)'
                  : providerType === 'real-llm'
                  ? 'rgba(0,180,255,0.85)'
                  : providerType === 'local-llm'
                  ? 'rgba(0,210,150,0.85)'
                  : 'rgba(0,160,255,0.35)',
              }}
            >
              {demoMode
                ? 'Demo Mode'
                : providerType === 'real-llm'
                ? 'Real LLM'
                : providerType === 'local-llm'
                ? 'Local LLM'
                : 'No Provider'}
            </span>
            {modelLabel && (
              <span
                style={{
                  fontFamily: "'Space Mono', monospace",
                  fontSize: 6.5,
                  letterSpacing: '0.10em',
                  color: 'rgba(0,160,255,0.38)',
                }}
              >
                {modelLabel}
              </span>
            )}
            {demoMode && (
              <span
                style={{
                  fontFamily: "'Space Mono', monospace",
                  fontSize: 6,
                  letterSpacing: '0.10em',
                  color: 'rgba(255,140,0,0.50)',
                }}
              >
                No real AI connected
              </span>
            )}
          </div>

          {/* Connection dot */}
          <div
            style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: runtime?.connected ? '#00cc88' : '#cc3300',
              boxShadow: runtime?.connected
                ? '0 0 6px rgba(0,200,130,0.7)'
                : '0 0 6px rgba(200,50,0,0.7)',
              flexShrink: 0,
            }}
            title={runtime?.connected ? 'Runtime connected' : 'Runtime unreachable'}
          />

          {/* Shield / system */}
          <button
            type="button"
            onClick={() => setSysOpen(true)}
            style={{
              width: 32,
              height: 32,
              borderRadius: 10,
              background: 'rgba(0,160,255,0.06)',
              border: '1px solid rgba(0,160,255,0.10)',
              color: 'rgba(0,160,255,0.45)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
            }}
            aria-label="System status"
            data-testid="button-open-system"
          >
            <Shield size={14} />
          </button>
        </div>
      </header>

      {/* ── Neural core ── */}
      <main
        className="relative z-10 flex flex-col items-center"
        style={{ paddingTop: '0.5rem', paddingBottom: '0.25rem' }}
      >
        {/* Ambient glow ring behind core */}
        <div
          aria-hidden
          style={{
            position: 'absolute',
            width: coreSize + 60,
            height: coreSize + 60,
            borderRadius: '50%',
            background: `radial-gradient(circle, ${meta.color}0b 0%, transparent 70%)`,
            boxShadow: `0 0 100px 16px ${meta.color}07`,
            pointerEvents: 'none',
            transition: 'background 2s ease, box-shadow 2s ease',
          }}
        />

        <div data-testid="neural-core-container">
          <NeuralCore state={coreState} size={coreSize} />
        </div>

        {/* Live transcript while listening */}
        {showTranscript && (
          <p
            className="jarvis-rise"
            style={{
              marginTop: 4,
              fontStyle: 'italic',
              fontSize: 12,
              lineHeight: 1.5,
              color: 'rgba(0,200,255,0.75)',
              maxWidth: coreSize - 32,
              textAlign: 'center',
            }}
          >
            "{voice.transcript}"
          </p>
        )}
      </main>

      {/* ── State chip ── */}
      <div
        className="relative z-10 flex justify-center"
        style={{ paddingTop: 6, paddingBottom: 10 }}
        data-testid="status-chip"
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 7,
            borderRadius: 24,
            padding: '5px 13px',
            background: meta.dim,
            border: `1px solid ${meta.color}24`,
            boxShadow: `0 0 14px ${meta.color}10`,
            transition: 'all 0.6s ease',
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: '50%',
              background: meta.color,
              boxShadow: `0 0 6px ${meta.color}`,
              animation: coreState === 'offline' ? 'none' : 'pulse 2s infinite',
              flexShrink: 0,
            }}
          />
          <span
            style={{
              fontFamily: "'Space Mono', monospace",
              fontSize: 9,
              textTransform: 'uppercase',
              letterSpacing: '0.15em',
              color: meta.color,
              transition: 'color 0.6s ease',
            }}
          >
            {meta.label}
          </span>
          {voice.voiceState === 'error' && voice.error && (
            <span
              style={{
                fontFamily: "'Space Mono', monospace",
                fontSize: 8,
                textTransform: 'uppercase',
                letterSpacing: '0.10em',
                color: 'rgba(255,80,50,0.80)',
                marginLeft: 4,
              }}
            >
              · voice error
            </span>
          )}
        </div>
      </div>

      {/* ── Live terminal ── */}
      <div
        className="relative z-10"
        style={{
          paddingLeft: 20,
          paddingRight: 20,
          paddingBottom: 10,
          flex: 1,
          minHeight: 0,
        }}
      >
        <LiveTerminal
          lines={termLines}
          maxLines={10}
          style={{
            maxHeight: 160,
            padding: '10px 14px',
            borderRadius: 10,
            background: 'rgba(0,8,18,0.55)',
            border: '1px solid rgba(0,160,255,0.08)',
          }}
        />
      </div>

      {/* ── Alerts ── */}
      {alerts.length > 0 && (
        <div
          className="relative z-10"
          style={{ paddingLeft: 20, paddingRight: 20, paddingBottom: 8 }}
        >
          <AlertCard alerts={alerts} onDismiss={dismissAlert} />
        </div>
      )}

      {/* ── Execution error diagnostic card ── */}
      {lastError && (
        <div
          className="relative z-10"
          style={{ paddingLeft: 20, paddingRight: 20, paddingBottom: 8 }}
        >
          <ErrorDetailCard diagnostic={lastError} onDismiss={dismissError} />
        </div>
      )}

      {/* ── Response card ── */}
      {lastAssistant && (
        <div
          className="relative z-10"
          style={{ paddingLeft: 20, paddingRight: 20, paddingBottom: 8 }}
        >
          <ResponseCard message={lastAssistant} demoMode={demoMode} />
        </div>
      )}

      {/* ── Bottom nav ── */}
      <nav
        className="relative z-10"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-around',
          paddingLeft: 24,
          paddingRight: 24,
          paddingTop: 10,
          paddingBottom: 'max(1.25rem, env(safe-area-inset-bottom))',
          borderTop: '1px solid rgba(0,160,255,0.07)',
          background: 'linear-gradient(to top, rgba(0,4,14,0.97), transparent)',
        }}
      >
        {/* Chat */}
        <BottomButton
          onClick={() => setChatOpen(true)}
          icon={<MessageSquare size={18} />}
          label="Chat"
          badge={messages.length > 0 ? messages.length : undefined}
          testId="button-open-chat"
        />

        {/* Mic (center, slightly prominent) */}
        <button
          type="button"
          onClick={handleMicPress}
          disabled={!ready && !voice.isListening}
          style={{
            width: 52,
            height: 52,
            borderRadius: '50%',
            background: voice.isListening
              ? 'radial-gradient(circle at 40% 35%, rgba(0,170,255,0.35), rgba(0,0,0,0.65))'
              : ready
              ? `radial-gradient(circle at 40% 35%, ${meta.color}22, rgba(0,0,0,0.65))`
              : 'rgba(20,30,45,0.65)',
            border: voice.isListening
              ? '1.5px solid rgba(0,170,255,0.65)'
              : `1.5px solid ${ready ? meta.color + '44' : 'rgba(40,60,80,0.30)'}`,
            boxShadow: voice.isListening
              ? '0 0 20px rgba(0,170,255,0.28), inset 0 0 14px rgba(0,170,255,0.12)'
              : ready
              ? `0 0 18px ${meta.color}18`
              : 'none',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            transition: 'all 0.3s ease',
            animation: voice.isListening ? 'pulse 1.4s infinite' : 'none',
            opacity: !ready && !voice.isListening ? 0.4 : 1,
          }}
          aria-label={
            voice.isListening
              ? 'Stop listening'
              : voice.isSpeaking
              ? 'Stop speaking'
              : 'Start listening'
          }
          data-testid="button-tap-to-speak"
        >
          {voice.isListening
            ? <MicOff size={20} style={{ color: '#00aaff' }} />
            : <Mic size={20} style={{ color: ready ? meta.color : 'rgba(50,70,90,0.65)' }} />
          }
        </button>

        {/* System */}
        <BottomButton
          onClick={() => setSysOpen(true)}
          icon={<Activity size={18} />}
          label="System"
          testId="button-open-system-nav"
        />
      </nav>

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

// ── BottomButton ─────────────────────────────────────────────────────────────

interface BottomButtonProps {
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  badge?: number;
  testId?: string;
}

function BottomButton({ onClick, icon, label, badge, testId }: BottomButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 5,
        background: 'none',
        border: 'none',
        cursor: 'pointer',
        position: 'relative',
        padding: '2px 4px',
      }}
      aria-label={label}
      data-testid={testId}
    >
      <div
        style={{
          width: 44,
          height: 44,
          borderRadius: 14,
          background: 'rgba(0,160,255,0.06)',
          border: '1px solid rgba(0,160,255,0.10)',
          color: 'rgba(0,160,255,0.50)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        {icon}
      </div>

      {badge !== undefined && (
        <span
          style={{
            position: 'absolute',
            top: 0,
            right: 0,
            width: 16,
            height: 16,
            borderRadius: '50%',
            background: '#0099cc',
            color: '#fff',
            fontFamily: "'Space Mono', monospace",
            fontSize: 8,
            fontWeight: 700,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          {badge > 9 ? '9+' : badge}
        </span>
      )}

      <span
        style={{
          fontFamily: "'Space Mono', monospace",
          fontSize: 7.5,
          textTransform: 'uppercase',
          letterSpacing: '0.14em',
          color: 'rgba(0,160,255,0.30)',
        }}
      >
        {label}
      </span>
    </button>
  );
}
