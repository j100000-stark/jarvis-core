import { ArrowUp, Mic } from 'lucide-react';
import { type FormEvent, type KeyboardEvent, useRef } from 'react';

type ComposerProps = {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled: boolean;
  isPending: boolean;
};

export function Composer({ value, onChange, onSubmit, disabled, isPending }: ComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const canSubmit = value.trim().length > 0 && !disabled && !isPending;

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (canSubmit) onSubmit();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      if (canSubmit) onSubmit();
    }
  };

  return (
    <form onSubmit={handleSubmit} className="rounded-[1.35rem] border border-[hsl(var(--border))] bg-[hsl(var(--card)/.88)] p-2 shadow-[var(--shadow-sm)] backdrop-blur-xl" data-testid="form-message-composer">
      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled || isPending}
          rows={1}
          maxLength={4000}
          placeholder={disabled ? 'Waiting for a local provider…' : 'Give JARVIS a goal'}
          className="min-h-12 max-h-36 flex-1 resize-none bg-transparent px-3 py-3 text-[15px] leading-6 text-[hsl(var(--foreground))] outline-none placeholder:text-[hsl(var(--muted-foreground)/.72)] disabled:cursor-not-allowed disabled:opacity-55"
          aria-label="Message JARVIS"
          data-testid="input-message-goal"
        />
        <div className="flex shrink-0 items-center gap-1.5 pb-1">
          <button
            type="button"
            disabled
            className="flex size-11 items-center justify-center rounded-xl text-[hsl(var(--muted-foreground)/.55)]"
            aria-label="Voice input coming later"
            data-testid="button-microphone"
          >
            <Mic size={19} />
          </button>
          <button
            type="submit"
            disabled={!canSubmit}
            className="flex size-11 items-center justify-center rounded-xl bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] transition hover:bg-[hsl(var(--primary)/.88)] active:scale-95 disabled:cursor-not-allowed disabled:bg-[hsl(var(--muted))] disabled:text-[hsl(var(--muted-foreground))]"
            aria-label="Send goal"
            data-testid="button-send-message"
          >
            {isPending ? <span className="flex gap-1" aria-label="Sending"><i className="jarvis-dot-pulse size-1.5 rounded-full bg-current" /><i className="jarvis-dot-pulse size-1.5 rounded-full bg-current [animation-delay:120ms]" /><i className="jarvis-dot-pulse size-1.5 rounded-full bg-current [animation-delay:240ms]" /></span> : <ArrowUp size={19} strokeWidth={2.4} />}
          </button>
        </div>
      </div>
      <div className="flex items-center justify-between px-3 pb-1 pt-1">
        <span className="font-mono text-[9px] uppercase tracking-[0.13em] text-[hsl(var(--muted-foreground)/.7)]">Local session / private by default</span>
        <span className="hidden font-mono text-[9px] uppercase tracking-[0.13em] text-[hsl(var(--muted-foreground)/.7)] sm:inline">⌘ ↵ to send</span>
      </div>
    </form>
  );
}