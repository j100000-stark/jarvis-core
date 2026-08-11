/**
 * ChatSheet — slide-up conversation drawer.
 * Wraps the existing Composer and message history in a sheet overlay.
 * All API logic is passed in from the parent to avoid re-instantiating hooks.
 */
import { ArrowUp, Mic, X } from 'lucide-react';
import { type FormEvent, type KeyboardEvent, useRef } from 'react';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  body: string;
  providerName?: string;
  time: string;
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
    <div className="fixed inset-0 z-50 flex flex-col" style={{ background: 'rgba(0,0,0,0.85)' }}>
      {/* Backdrop tap to close */}
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
        {/* Handle */}
        <div className="flex items-center justify-between px-5 py-4 border-b" style={{ borderColor: 'rgba(0,160,255,0.10)' }}>
          <span className="font-mono text-[10px] uppercase tracking-[0.22em]" style={{ color: 'rgba(0,180,255,0.5)' }}>
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
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4 min-h-0">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <p className="font-mono text-[10px] uppercase tracking-[0.2em] mb-2" style={{ color: 'rgba(0,160,255,0.35)' }}>
                Awaiting instruction
              </p>
              <p className="text-sm leading-relaxed max-w-[260px]" style={{ color: 'rgba(255,255,255,0.4)' }}>
                {disabled
                  ? 'No provider configured. Connect a local model to begin.'
                  : 'Tell JARVIS what outcome you want.'}
              </p>
            </div>
          ) : (
            messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                data-testid={`message-${msg.role}-${msg.id}`}
              >
                {msg.role === 'assistant' && (
                  <div
                    className="mr-2 mt-1 flex size-7 shrink-0 items-center justify-center rounded-lg font-mono text-[10px] font-bold"
                    style={{ background: 'rgba(0,140,255,0.2)', color: '#00aaff' }}
                  >
                    J·
                  </div>
                )}
                <div className="max-w-[80%]">
                  <div
                    className="rounded-2xl px-4 py-3 text-[14px] leading-6"
                    style={
                      msg.role === 'user'
                        ? { background: 'rgba(0,130,255,0.22)', color: 'rgba(255,255,255,0.9)', borderRadius: '18px 18px 4px 18px' }
                        : { background: 'rgba(255,255,255,0.05)', color: 'rgba(255,255,255,0.85)', border: '1px solid rgba(0,160,255,0.12)', borderRadius: '18px 18px 18px 4px' }
                    }
                  >
                    <p className="whitespace-pre-wrap">{msg.body}</p>
                  </div>
                  <div className="mt-1 flex items-center gap-2 px-1 font-mono text-[9px] uppercase tracking-[0.12em]" style={{ color: 'rgba(0,160,255,0.35)', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
                    <span>{msg.time}</span>
                    {msg.providerName && <><span>·</span><span>{msg.providerName}</span></>}
                  </div>
                </div>
              </div>
            ))
          )}

          {isPending && (
            <div className="flex justify-start gap-2" data-testid="message-assistant-loading">
              <div
                className="mr-2 mt-1 flex size-7 shrink-0 items-center justify-center rounded-lg font-mono text-[10px] font-bold"
                style={{ background: 'rgba(0,140,255,0.2)', color: '#00aaff' }}
              >
                J·
              </div>
              <div
                className="flex items-center gap-1.5 rounded-2xl px-4 py-3"
                style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(0,160,255,0.12)' }}
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
          )}

          {sendError && (
            <div
              className="rounded-xl px-4 py-3 text-sm"
              style={{ background: 'rgba(255,80,0,0.1)', border: '1px solid rgba(255,80,0,0.25)', color: 'rgba(255,140,80,0.9)' }}
              data-testid="text-message-error"
            >
              {sendError}
            </div>
          )}
        </div>

        {/* Composer */}
        <form
          onSubmit={handleSubmit}
          className="flex items-end gap-2 px-4 pb-[max(1.5rem,env(safe-area-inset-bottom))] pt-3 border-t"
          style={{ borderColor: 'rgba(0,160,255,0.10)' }}
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
            className="flex-1 resize-none bg-transparent py-3 px-3 text-[14px] leading-6 outline-none rounded-xl"
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
            aria-label="Voice input coming later"
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
                ? { background: 'rgba(0,140,255,0.25)', color: '#00aaff', border: '1px solid rgba(0,160,255,0.35)' }
                : { background: 'rgba(255,255,255,0.05)', color: 'rgba(0,160,255,0.25)', border: '1px solid rgba(0,160,255,0.08)' }
            }
            aria-label="Send goal"
            data-testid="button-send-message"
          >
            {isPending
              ? <span className="flex gap-1">{[0,1,2].map(i => <i key={i} className="size-1.5 rounded-full bg-current animate-pulse" style={{ animationDelay: `${i * 120}ms` }} />)}</span>
              : <ArrowUp size={18} strokeWidth={2.3} />}
          </button>
        </form>
      </div>
    </div>
  );
}
