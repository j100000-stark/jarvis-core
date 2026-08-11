import { useMemo, useState } from 'react';
import { Link } from 'wouter';
import { CircleHelp, Command, LockKeyhole, Sparkles } from 'lucide-react';
import {
  getGetJarvisStatusQueryKey,
  getHealthCheckQueryKey,
  useGetJarvisStatus,
  useHealthCheck,
  useSendJarvisMessage,
} from '@workspace/api-client-react';
import { Composer } from '@/components/jarvis/composer';
import { RuntimeStatus } from '@/components/jarvis/runtime-status';
import { SystemPanel } from '@/components/jarvis/system-panel';

type Message = {
  id: string;
  role: 'user' | 'assistant';
  body: string;
  providerName?: string;
  time: string;
};

const formatTime = () => new Intl.DateTimeFormat(undefined, {
  hour: 'numeric',
  minute: '2-digit',
}).format(new Date());

export default function Home() {
  const [goal, setGoal] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const status = useGetJarvisStatus({
    query: {
      queryKey: getGetJarvisStatusQueryKey(),
      refetchInterval: 15000,
      refetchOnWindowFocus: true,
    },
  });
  const health = useHealthCheck({
    query: {
      queryKey: getHealthCheckQueryKey(),
      refetchInterval: 30000,
      refetchOnWindowFocus: true,
    },
  });
  const sendMessage = useSendJarvisMessage();
  const runtime = status.data;
  const ready = Boolean(runtime?.connected && runtime?.providerConfigured);
  const isStatusReading = status.isLoading && !runtime;
  const emptyTitle = runtime?.connected && !runtime.providerConfigured
    ? 'The brain is not configured yet'
    : status.isError
      ? 'JARVIS is out of reach'
      : 'Start with a clear goal';
  const emptyBody = runtime?.connected && !runtime.providerConfigured
    ? 'The local runtime is reachable, but it has no provider to reason with. Add one locally, then refresh this panel.'
    : status.isError
      ? 'This interface cannot confirm the local runtime. Nothing will be sent until the connection is honest.'
      : 'Tell JARVIS what outcome you want. It will return the result from the configured local provider.';

  const sendError = useMemo(() => {
    if (!sendMessage.error) return null;
    const error = sendMessage.error as { error?: string; message?: string };
    return error.error || error.message || 'The local runtime rejected that goal.';
  }, [sendMessage.error]);

  const handleSend = () => {
    const trimmedGoal = goal.trim();
    if (!trimmedGoal || !ready || sendMessage.isPending) return;
    const sentAt = formatTime();
    setMessages((current) => [...current, {
      id: `user-${Date.now()}`,
      role: 'user',
      body: trimmedGoal,
      time: sentAt,
    }]);
    setGoal('');
    sendMessage.mutate({ data: { goal: trimmedGoal } }, {
      onSuccess: (result) => {
        setMessages((current) => [...current, {
          id: `assistant-${Date.now()}`,
          role: 'assistant',
          body: result.response,
          providerName: result.providerName,
          time: formatTime(),
        }]);
      },
    });
  };

  const refreshAll = () => {
    void status.refetch();
    void health.refetch();
  };

  return (
    <div className="jarvis-shell min-h-[100dvh] bg-[hsl(var(--background))] text-[hsl(var(--foreground))]">
      <div className="jarvis-grain" />
      <div className="mx-auto flex min-h-[100dvh] max-w-[1500px] flex-col lg:flex-row">
        {/* ---------------------------------------------------------------- */}
        {/* Sidebar */}
        {/* ---------------------------------------------------------------- */}
        <aside className="flex w-full shrink-0 flex-col bg-[hsl(var(--sidebar))] px-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] pt-[max(1.1rem,env(safe-area-inset-top))] text-[hsl(var(--sidebar-foreground))] lg:min-h-[100dvh] lg:w-[300px] lg:overflow-y-auto lg:px-7 lg:py-8">
          {/* Identity */}
          <div className="flex items-center justify-between lg:block">
            <Link href="/" className="group inline-flex items-center gap-3" data-testid="link-home">
              <div className="relative flex size-10 items-center justify-center rounded-[13px] bg-[hsl(var(--accent))] text-[hsl(var(--accent-foreground))] shadow-[0_0_0_5px_hsl(var(--accent)/.12)]">
                <span className="font-mono text-[15px] font-bold tracking-[-0.12em]">J·</span>
              </div>
              <div>
                <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-white/50">Local system</p>
                <p className="mt-0.5 text-[17px] font-semibold tracking-[-0.04em] text-white">JARVIS</p>
              </div>
            </Link>
            <span className="rounded-full border border-white/12 px-2.5 py-1 font-mono text-[9px] uppercase tracking-[0.17em] text-white/45 lg:hidden">iOS ready</span>
          </div>

          <div className="mt-8 hidden lg:block">
            <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-white/40">Control surface</p>
            <p className="mt-3 max-w-[210px] text-[25px] font-medium leading-[1.08] tracking-[-0.06em] text-white/95">
              Quietly capable.<br /><span className="text-white/45">Precisely yours.</span>
            </p>
          </div>

          {/* Runtime status card */}
          <div className="mt-5 lg:mt-8">
            <RuntimeStatus
              connected={runtime?.connected}
              providerConfigured={runtime?.providerConfigured}
              providerName={runtime?.providerName}
              version={runtime?.version}
              externalApisEnabled={runtime?.externalApisEnabled}
              runtimeError={runtime?.error}
              isLoading={isStatusReading}
              isError={status.isError}
              onRefresh={refreshAll}
              isRefreshing={status.isFetching || health.isFetching}
            />
          </div>

          {/* Session footer */}
          <div className="mt-5 hidden items-center justify-between font-mono text-[9px] uppercase tracking-[0.16em] text-white/35 lg:flex">
            <span>Session protected</span>
            <LockKeyhole size={12} />
          </div>
        </aside>

        {/* ---------------------------------------------------------------- */}
        {/* Main content */}
        {/* ---------------------------------------------------------------- */}
        <main className="flex min-h-0 flex-1 flex-col lg:flex-row">
          {/* Conversation column */}
          <div className="flex min-h-0 flex-1 flex-col">
            <header className="flex items-center justify-between border-b border-[hsl(var(--border)/.75)] px-5 py-4 sm:px-8 lg:px-12 lg:py-6">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-[hsl(var(--muted-foreground))]">Conversation / 01</p>
                <h1 className="mt-1 text-[21px] font-semibold tracking-[-0.05em] sm:text-[24px]">Live channel</h1>
              </div>
              <div className="flex items-center gap-2.5">
                <span className={`flex items-center gap-2 rounded-full border px-3 py-1.5 font-mono text-[9px] uppercase tracking-[0.13em] ${ready ? 'border-[hsl(var(--accent)/.5)] bg-[hsl(var(--accent)/.1)] text-[hsl(78_58%_30%)]' : 'border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))]'}`} data-testid="status-channel">
                  <span className={`size-1.5 rounded-full ${ready ? 'jarvis-dot-pulse bg-[hsl(var(--accent))]' : 'bg-[hsl(var(--muted-foreground)/.55)]'}`} />
                  {ready ? 'Ready' : 'Standby'}
                </span>
                <button type="button" className="flex size-10 items-center justify-center rounded-xl border border-transparent text-[hsl(var(--muted-foreground))] transition hover:border-[hsl(var(--border))] hover:text-[hsl(var(--foreground))]" aria-label="Conversation help" data-testid="button-conversation-help">
                  <CircleHelp size={18} />
                </button>
              </div>
            </header>

            <section className="flex min-h-0 flex-1 flex-col px-5 pb-4 pt-6 sm:px-8 lg:px-12 lg:pt-10">
              <div className="mx-auto flex w-full max-w-[850px] flex-1 flex-col">
                {messages.length === 0 ? (
                  <div className="jarvis-rise flex flex-1 flex-col justify-center py-8 sm:py-16" data-testid="empty-conversation">
                    <div className="mb-7 flex size-14 items-center justify-center rounded-2xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] text-[hsl(var(--primary))] shadow-[var(--shadow-sm)]">
                      <Sparkles size={23} strokeWidth={1.7} />
                    </div>
                    <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-[hsl(var(--muted-foreground))]">Awaiting instruction</p>
                    <h2 className="mt-3 max-w-[600px] text-[clamp(2.2rem,7vw,4.8rem)] font-semibold leading-[.94] tracking-[-0.08em]" data-testid="text-empty-title">{emptyTitle}</h2>
                    <p className="mt-6 max-w-[480px] text-[15px] leading-7 text-[hsl(var(--muted-foreground))]" data-testid="text-empty-description">{emptyBody}</p>
                    <div className="mt-8 flex flex-wrap gap-2">
                      {['Prepare a concise plan', 'Summarize my next steps'].map((suggestion) => (
                        <button key={suggestion} type="button" disabled={!ready} onClick={() => setGoal(suggestion)} className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--card)/.65)] px-3.5 py-2 text-left text-xs text-[hsl(var(--muted-foreground))] transition hover:border-[hsl(var(--accent)/.7)] hover:text-[hsl(var(--foreground))] disabled:cursor-not-allowed disabled:opacity-45" data-testid={`button-suggestion-${suggestion.toLowerCase().replaceAll(' ', '-')}`}>{suggestion}</button>
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="flex-1 space-y-7 overflow-y-auto pb-8 pr-1" data-testid="conversation-list">
                    {messages.map((message) => (
                      <article key={message.id} className={`jarvis-rise flex gap-3 ${message.role === 'user' ? 'justify-end' : 'justify-start'}`} data-testid={`message-${message.role}-${message.id}`}>
                        {message.role === 'assistant' && <div className="mt-1 flex size-8 shrink-0 items-center justify-center rounded-xl bg-[hsl(var(--primary))] font-mono text-[11px] font-bold text-[hsl(var(--primary-foreground))]">J·</div>}
                        <div className={`max-w-[min(88%,650px)] ${message.role === 'user' ? 'items-end' : 'items-start'}`}>
                          <div className={`rounded-2xl px-4 py-3.5 text-[15px] leading-7 ${message.role === 'user' ? 'rounded-br-md bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]' : 'rounded-bl-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] text-[hsl(var(--foreground))] shadow-[var(--shadow-sm)]'}`}>
                            <p className="whitespace-pre-wrap">{message.body}</p>
                          </div>
                          <div className={`mt-2 flex items-center gap-2 font-mono text-[9px] uppercase tracking-[0.12em] text-[hsl(var(--muted-foreground))] ${message.role === 'user' ? 'justify-end' : ''}`}>
                            <span>{message.time}</span>
                            {message.providerName && <><span>·</span><span>{message.providerName}</span></>}
                          </div>
                        </div>
                      </article>
                    ))}
                    {sendMessage.isPending && (
                      <article className="jarvis-rise flex gap-3" data-testid="message-assistant-loading">
                        <div className="mt-1 flex size-8 items-center justify-center rounded-xl bg-[hsl(var(--primary))] font-mono text-[11px] font-bold text-[hsl(var(--primary-foreground))]">J·</div>
                        <div className="flex items-center gap-1 rounded-2xl rounded-bl-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] px-5 py-4 shadow-[var(--shadow-sm)]">
                          <i className="jarvis-dot-pulse size-1.5 rounded-full bg-[hsl(var(--accent-foreground))]" />
                          <i className="jarvis-dot-pulse size-1.5 rounded-full bg-[hsl(var(--accent-foreground))] [animation-delay:140ms]" />
                          <i className="jarvis-dot-pulse size-1.5 rounded-full bg-[hsl(var(--accent-foreground))] [animation-delay:280ms]" />
                        </div>
                      </article>
                    )}
                    {sendError && <div className="rounded-xl border border-[hsl(var(--destructive)/.3)] bg-[hsl(var(--destructive)/.08)] px-4 py-3 text-sm text-[hsl(var(--destructive))]" data-testid="text-message-error">{sendError}</div>}
                  </div>
                )}

                <div className="mt-auto pt-4">
                  <Composer value={goal} onChange={setGoal} onSubmit={handleSend} disabled={!ready} isPending={sendMessage.isPending} />
                  <p className="mt-3 text-center font-mono text-[9px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground)/.7)]"><Command size={10} className="mr-1 inline-block -translate-y-px" /> JARVIS only acts on the goal you send</p>
                </div>
              </div>
            </section>
          </div>

          {/* System status rail — hidden on mobile, visible on large screens */}
          <aside
            className="hidden w-[320px] shrink-0 overflow-y-auto border-l border-[hsl(var(--border)/.6)] bg-[hsl(var(--background)/.5)] px-5 py-6 xl:block"
            data-testid="panel-system-rail"
          >
            <p className="mb-4 font-mono text-[10px] uppercase tracking-[0.2em] text-[hsl(var(--muted-foreground))]">System status</p>
            <SystemPanel />
          </aside>
        </main>
      </div>
    </div>
  );
}
