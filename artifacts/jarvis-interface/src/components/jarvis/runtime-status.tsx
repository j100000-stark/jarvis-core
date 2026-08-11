import { Activity, Check, CircleAlert, Cpu, RefreshCw, WifiOff } from 'lucide-react';
import type { ReactNode } from 'react';

type RuntimeStatusProps = {
  connected?: boolean;
  providerConfigured?: boolean;
  providerName?: string;
  version?: string;
  externalApisEnabled?: boolean;
  runtimeError?: string | null;
  isLoading: boolean;
  isError: boolean;
  onRefresh: () => void;
  isRefreshing: boolean;
};

export function RuntimeStatus({
  connected,
  providerConfigured,
  providerName,
  version,
  externalApisEnabled,
  runtimeError,
  isLoading,
  isError,
  onRefresh,
  isRefreshing,
}: RuntimeStatusProps) {
  const isLive = connected && providerConfigured;
  const title = isLoading
    ? 'Reading runtime'
    : isError
      ? 'Status unavailable'
      : isLive
        ? 'Local brain online'
        : connected
          ? 'No provider configured'
          : 'Runtime offline';
  const statusTone = isLive ? 'live' : isError ? 'error' : 'quiet';

  return (
    <section className="rounded-[1.35rem] border border-[hsl(var(--sidebar-border))] bg-[hsl(var(--sidebar))] p-4 text-[hsl(var(--sidebar-foreground))] shadow-[var(--shadow-md)]" data-testid="card-runtime-status">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className={`mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-xl ${statusTone === 'live' ? 'bg-[hsl(var(--accent))] text-[hsl(var(--accent-foreground))]' : 'bg-white/10 text-white/75'}`}>
            {statusTone === 'error' ? <CircleAlert size={17} /> : statusTone === 'live' ? <Check size={18} strokeWidth={2.5} /> : <Cpu size={17} />}
          </div>
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-white/50">Runtime state</p>
            <h2 className="mt-1 text-[15px] font-semibold tracking-[-0.02em]" data-testid="status-runtime-title">{title}</h2>
          </div>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={isRefreshing}
          className="flex size-10 shrink-0 items-center justify-center rounded-xl text-white/55 transition hover:bg-white/10 hover:text-white disabled:opacity-40"
          aria-label="Refresh runtime status"
          data-testid="button-refresh-status"
        >
          <RefreshCw size={16} className={isRefreshing ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-white/10 pt-4">
        <RuntimeMetric label="Connection" value={isLoading ? '—' : connected ? 'Reachable' : 'Unavailable'} icon={connected ? <WifiOff size={12} className="rotate-180" /> : <WifiOff size={12} />} />
        <RuntimeMetric label="Provider" value={isLoading ? '—' : providerConfigured ? providerName || 'Configured' : 'Not configured'} icon={<Activity size={12} />} />
        <RuntimeMetric label="Version" value={isLoading ? '—' : version || 'Unknown'} />
        <RuntimeMetric label="External APIs" value={isLoading ? '—' : externalApisEnabled ? 'Enabled' : 'Disabled'} />
      </div>

      {(runtimeError || isError) && (
        <p className="mt-4 rounded-xl border border-[hsl(var(--destructive)/.28)] bg-[hsl(var(--destructive)/.11)] px-3 py-2 text-xs leading-relaxed text-[hsl(4_78%_78%)]" data-testid="text-runtime-error">
          {runtimeError || 'The runtime did not answer. This surface will keep trying.'}
        </p>
      )}
    </section>
  );
}

function RuntimeMetric({ label, value, icon }: { label: string; value: string; icon?: ReactNode }) {
  return (
    <div className="min-w-0" data-testid={`metric-${label.toLowerCase().replace(/\s+/g, '-')}`}>
      <div className="flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.14em] text-white/40">
        {icon}
        <span>{label}</span>
      </div>
      <p className="mt-1 truncate text-[12px] font-medium text-white/80">{value}</p>
    </div>
  );
}