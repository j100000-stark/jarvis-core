/**
 * ChatSheet — slide-up conversation drawer.
 *
 * Renders the conversation history with optional execution step detail
 * for each JARVIS assistant response.  The execution trace shows:
 *   - agents selected  (derived from planGoal / executionSteps)
 *   - each step: id, objective, tool, output, verification status
 *   - final result / failure
 *
 * Execution steps are collapsed by default and expand on tap so the
 * interface stays minimal.
 */
import { ArrowUp, CheckCircle, ChevronDown, ChevronRight, Mic, Terminal, X, XCircle } from 'lucide-react';
import { type FormEvent, type KeyboardEvent, useRef, useState } from 'react';

// ---- Types (mirrors JarvisGoalResult from jarvis-runtime.ts) ----

export interface ExecutionStep {
  stepId: string;
  objective: string;
  tool: string;
  output: string;
  error: string | null;
  verified: boolean;
  verification: string;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  body: string;
  providerName?: string;
  time: string;
  demoMode?: boolean;
  demoLabel?: string | null;
  executionSteps?: ExecutionStep[];
  planGoal?: string | null;
  failure?: string | null;
}

interface ChatSheetProps {
  open: boolean;
  onClose: () => void;
  messages: Message[];
  goal: string;
  onGoalChange: (v: string) => void;
  onSend: () => void;
  disabled: boolean;
  isPending: boolean;
  sendError: string | null;
}

export function ChatSheet({
  open,
  onClose,
  messages,
  goal,
  onGoalChange,
  onSend,
  disabled,
  isPending,
  sendError,
}: ChatSheetProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const canSend = goal.trim().length > 0 && !disabled && !isPending;

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      if (canSend) onSend();
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (canSend) onSend();
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col"
      style={{ background: 'rgba(0,0,0,0.85)' }}
    >
      {/* Backdrop */}
      <div className="flex-1 cursor-pointer" onClick={onClose} />

      {/* Sheet */}
      <div
        className="flex flex-col rounded-t-3xl border-t overflow-hidden"
        style={{
          background: 'rgba(4,10,20,0.97)',
          borderColor: 'rgba(0,160,255,0.18)',
          maxHeight: '82dvh',
          backdropFilter: 'blur(24px)',
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-5 py-4 border-b shrink-0"
          style={{ borderColor: 'rgba(0,160,255,0.10)' }}
        >
          <span
            className="font-mono text-[10px] uppercase tracking-[0.22em]"
            style={{ color: 'rgba(0,180,255,0.5)' }}
          >
            Live channel
          </span>
          <button
            type="button"
            onClick={onClose}
            className="flex size-8 items-center justify-center rounded-xl transition"
            style={{ color: 'rgba(0,180,255,0.5)' }}
            aria-label="Close chat"
          >
            <X size={16} />
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5 min-h-0">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <p
                className="font-mono text-[10px] uppercase tracking-[0.2em] mb-2"
                style={{ color: 'rgba(0,160,255,0.35)' }}
              >
                Awaiting instruction
              </p>
              <p
                className="text-sm leading-relaxed max-w-[260px]"
                style={{ color: 'rgba(255,255,255,0.4)' }}
              >
                {disabled
                  ? 'No provider configured. Connect a local model or enable demo mode.'
                  : 'Tell JARVIS what outcome you want. The pipeline will plan, execute, and verify.'}
              </p>

              {/* Suggested goals */}
              <div className="mt-6 flex flex-col gap-2 w-full max-w-[280px]">
                {[
                  'Check the system',
                  'Check network status',
                  'Run a security check',
                  'Give me a system report',
                ].map((suggestion) => (
                  <button
                    key={suggestion}
                    type="button"
                    disabled={disabled}
                    onClick={() => onGoalChange(suggestion)}
                    className="rounded-xl px-3.5 py-2.5 text-left text-[12px] transition"
                    style={{
                      background: 'rgba(0,160,255,0.06)',
                      border: '1px solid rgba(0,160,255,0.12)',
                      color: 'rgba(0,160,255,0.65)',
                      opacity: disabled ? 0.4 : 1,
                    }}
                    data-testid={`button-suggestion-${suggestion.toLowerCase().replaceAll(' ', '-')}`}
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {messages.map((msg) => (
                <MessageBubble key={msg.id} msg={msg} />
              ))}
              {isPending && <ThinkingBubble />}
              {sendError && (
                <div
                  className="rounded-xl px-4 py-3 text-sm"
                  style={{
                    background: 'rgba(255,80,0,0.1)',
                    border: '1px solid rgba(255,80,0,0.25)',
                    color: 'rgba(255,140,80,0.9)',
                  }}
                  data-testid="text-message-error"
                >
                  {sendError}
                </div>
              )}
            </>
          )}
        </div>

        {/* Composer */}
        <form
          onSubmit={handleSubmit}
          className="flex items-end gap-2 px-4 border-t"
          style={{
            borderColor: 'rgba(0,160,255,0.10)',
            paddingBottom: 'max(1.5rem, env(safe-area-inset-bottom))',
            paddingTop: '0.75rem',
          }}
          data-testid="form-message-composer"
        >
          <textarea
            ref={textareaRef}
            value={goal}
            onChange={(e) => onGoalChange(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={disabled || isPending}
            rows={1}
            maxLength={4000}
            placeholder={disabled ? 'Waiting for a local provider…' : 'Give JARVIS a goal'}
            className="flex-1 resize-none py-3 px-3 text-[14px] leading-6 outline-none rounded-xl"
            style={{
              minHeight: 44,
              maxHeight: 120,
              background: 'rgba(255,255,255,0.04)',
              color: 'rgba(255,255,255,0.9)',
              border: '1px solid rgba(0,160,255,0.15)',
            }}
            aria-label="Message JARVIS"
            data-testid="input-message-goal"
          />
          <button
            type="button"
            disabled
            className="flex size-11 shrink-0 items-center justify-center rounded-xl"
            style={{ color: 'rgba(0,160,255,0.3)' }}
            aria-label="Voice input (coming later)"
            data-testid="button-microphone"
          >
            <Mic size={18} />
          </button>
          <button
            type="submit"
            disabled={!canSend}
            className="flex size-11 shrink-0 items-center justify-center rounded-xl transition active:scale-95"
            style={
              canSend
                ? {
                    background: 'rgba(0,140,255,0.25)',
                    color: '#00aaff',
                    border: '1px solid rgba(0,160,255,0.35)',
                  }
                : {
                    background: 'rgba(255,255,255,0.05)',
                    color: 'rgba(0,160,255,0.25)',
                    border: '1px solid rgba(0,160,255,0.08)',
                  }
            }
            aria-label="Send goal"
            data-testid="button-send-message"
          >
            {isPending ? (
              <span className="flex gap-1">
                {[0, 1, 2].map((i) => (
                  <i
                    key={i}
                    className="size-1.5 rounded-full bg-current animate-pulse"
                    style={{ animationDelay: `${i * 120}ms` }}
                  />
                ))}
              </span>
            ) : (
              <ArrowUp size={18} strokeWidth={2.3} />
            )}
          </button>
        </form>
      </div>
    </div>
  );
}

// ---- Message bubble ----

function MessageBubble({ msg }: { msg: Message }) {
  return (
    <div
      className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
      data-testid={`message-${msg.role}-${msg.id}`}
    >
      {msg.role === 'assistant' && (
        <div
          className="mr-2 mt-1 flex size-7 shrink-0 items-center justify-center rounded-lg font-mono text-[10px] font-bold self-start"
          style={{ background: 'rgba(0,140,255,0.2)', color: '#00aaff' }}
        >
          J·
        </div>
      )}
      <div className="max-w-[85%] min-w-0">
        {/* Main bubble */}
        <div
          className="rounded-2xl px-4 py-3 text-[14px] leading-6"
          style={
            msg.role === 'user'
              ? {
                  background: 'rgba(0,130,255,0.22)',
                  color: 'rgba(255,255,255,0.9)',
                  borderRadius: '18px 18px 4px 18px',
                }
              : {
                  background: 'rgba(255,255,255,0.05)',
                  color: 'rgba(255,255,255,0.85)',
                  border: '1px solid rgba(0,160,255,0.12)',
                  borderRadius: '4px 18px 18px 18px',
                }
          }
        >
          <p className="whitespace-pre-wrap">{msg.body}</p>
        </div>

        {/* Execution trace (assistant only) */}
        {msg.role === 'assistant' && msg.executionSteps && msg.executionSteps.length > 0 && (
          <ExecutionTrace
            steps={msg.executionSteps}
            planGoal={msg.planGoal}
            failure={msg.failure}
            demoMode={msg.demoMode}
          />
        )}

        {/* Timestamp / provider */}
        <div
          className="mt-1 flex items-center gap-2 px-1 font-mono text-[9px] uppercase tracking-[0.12em]"
          style={{
            color: 'rgba(0,160,255,0.35)',
            justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
          }}
        >
          <span>{msg.time}</span>
          {msg.providerName && (
            <>
              <span>·</span>
              <span>{msg.providerName}</span>
            </>
          )}
          {msg.demoMode && (
            <>
              <span>·</span>
              <span style={{ color: 'rgba(255,160,0,0.6)' }}>demo</span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ---- Execution trace ----

interface ExecutionTraceProps {
  steps: ExecutionStep[];
  planGoal: string | null | undefined;
  failure: string | null | undefined;
  demoMode?: boolean;
}

function ExecutionTrace({ steps, planGoal, failure, demoMode }: ExecutionTraceProps) {
  const [expanded, setExpanded] = useState(false);
  const allVerified = steps.every((s) => s.verified);

  return (
    <div
      className="mt-2 rounded-xl overflow-hidden"
      style={{ border: '1px solid rgba(0,160,255,0.10)', background: 'rgba(0,8,18,0.6)' }}
    >
      {/* Collapse toggle */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2.5 transition"
        style={{ color: 'rgba(0,160,255,0.55)' }}
        aria-label={expanded ? 'Collapse execution trace' : 'Expand execution trace'}
      >
        <div className="flex items-center gap-2">
          <Terminal size={11} />
          <span className="font-mono text-[9px] uppercase tracking-[0.18em]">
            {steps.length} step{steps.length !== 1 ? 's' : ''} · {allVerified ? 'all verified' : failure ? 'failed' : 'partial'}
          </span>
          {demoMode && (
            <span
              className="rounded-full px-1.5 py-0.5 font-mono text-[7px] uppercase tracking-[0.12em]"
              style={{ background: 'rgba(200,120,0,0.15)', color: 'rgba(255,160,0,0.7)', border: '1px solid rgba(255,160,0,0.2)' }}
            >
              demo
            </span>
          )}
        </div>
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </button>

      {/* Steps */}
      {expanded && (
        <div className="px-3 pb-3 space-y-2">
          {planGoal && (
            <p
              className="font-mono text-[9px] uppercase tracking-[0.12em] pb-2 border-b"
              style={{ color: 'rgba(0,160,255,0.3)', borderColor: 'rgba(0,160,255,0.08)' }}
            >
              Goal: {planGoal}
            </p>
          )}

          {steps.map((step) => (
            <StepRow key={step.stepId} step={step} />
          ))}

          {failure && (
            <div
              className="rounded-lg px-3 py-2 mt-1"
              style={{ background: 'rgba(255,60,0,0.08)', border: '1px solid rgba(255,60,0,0.18)' }}
            >
              <p
                className="font-mono text-[9px] uppercase tracking-[0.12em] mb-0.5"
                style={{ color: 'rgba(255,100,50,0.7)' }}
              >
                Failure
              </p>
              <p className="text-[11px]" style={{ color: 'rgba(255,140,80,0.85)' }}>
                {failure}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StepRow({ step }: { step: ExecutionStep }) {
  return (
    <div
      className="rounded-lg px-3 py-2"
      style={{
        background: step.verified
          ? 'rgba(0,160,255,0.04)'
          : 'rgba(255,60,0,0.05)',
        border: `1px solid ${step.verified ? 'rgba(0,160,255,0.10)' : 'rgba(255,60,0,0.15)'}`,
      }}
    >
      {/* Step header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          {step.verified ? (
            <CheckCircle size={11} style={{ color: '#00aaff', flexShrink: 0 }} />
          ) : (
            <XCircle size={11} style={{ color: '#ff4400', flexShrink: 0 }} />
          )}
          <span
            className="font-mono text-[9px] uppercase tracking-[0.12em] truncate"
            style={{ color: 'rgba(0,160,255,0.5)' }}
          >
            {step.stepId}
          </span>
        </div>
        <span
          className="font-mono text-[8px] uppercase tracking-[0.1em] shrink-0"
          style={{ color: 'rgba(0,160,255,0.3)' }}
        >
          {step.tool}
        </span>
      </div>

      {/* Objective */}
      <p
        className="mt-1 text-[11px] leading-5"
        style={{ color: 'rgba(255,255,255,0.55)' }}
      >
        {step.objective}
      </p>

      {/* Output */}
      {step.output && (
        <p
          className="mt-1.5 text-[11px] leading-5 rounded-md px-2 py-1.5 font-mono"
          style={{
            background: 'rgba(0,0,0,0.35)',
            color: 'rgba(0,220,180,0.8)',
            wordBreak: 'break-word',
          }}
        >
          {step.output}
        </p>
      )}

      {/* Error */}
      {step.error && (
        <p
          className="mt-1.5 text-[11px] leading-5 rounded-md px-2 py-1.5"
          style={{ background: 'rgba(255,40,0,0.08)', color: 'rgba(255,120,80,0.85)' }}
        >
          {step.error}
        </p>
      )}

      {/* Verification */}
      {step.verification && (
        <p
          className="mt-1 font-mono text-[8px] uppercase tracking-[0.1em]"
          style={{ color: step.verified ? 'rgba(0,200,150,0.6)' : 'rgba(255,100,50,0.5)' }}
        >
          ✓ {step.verification}
        </p>
      )}
    </div>
  );
}

function ThinkingBubble() {
  return (
    <div className="flex justify-start gap-2" data-testid="message-assistant-loading">
      <div
        className="mr-2 mt-1 flex size-7 shrink-0 items-center justify-center rounded-lg font-mono text-[10px] font-bold"
        style={{ background: 'rgba(0,140,255,0.2)', color: '#00aaff' }}
      >
        J·
      </div>
      <div
        className="flex items-center gap-1.5 rounded-2xl px-4 py-3"
        style={{
          background: 'rgba(255,255,255,0.05)',
          border: '1px solid rgba(0,160,255,0.12)',
          borderRadius: '4px 18px 18px 18px',
        }}
      >
        {[0, 140, 280].map((d) => (
          <span
            key={d}
            className="size-1.5 rounded-full animate-pulse"
            style={{ background: '#00aaff', animationDelay: `${d}ms` }}
          />
        ))}
      </div>
    </div>
  );
}
