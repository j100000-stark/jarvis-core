/**
 * SystemPanel — renders health, network, recovery, security, and agent activity
 * from the /jarvis/system API endpoint.
 *
 * If demo mode is active it shows a prominent DEMO MODE banner.
 * Does NOT fabricate data — all values come from the live API response.
 */
import {
  Activity,
  AlertTriangle,
  CheckCircle,
  Clock,
  Network,
  RefreshCw,
  Shield,
  XCircle,
} from 'lucide-react';
import { type ReactNode } from 'react';
import {
  getGetJarvisSystemQueryKey,
  useGetJarvisSystem,
} from '@workspace/api-client-react';

export function SystemPanel() {
  const system = useGetJarvisSystem({
    query: {
      queryKey: getGetJarvisSystemQueryKey(),
      refetchInterval: 30_000,
      refetchOnWindowFocus: true,
    },
  });

  const data = system.data;
  const isLoading = system.isLoading && !data;

  return (
    <div className="space-y-4" data-testid="panel-system">
      {/* Demo mode banner */}
      {data?.demoMode && (
        <div
          className="flex items-center gap-2.5 rounded-xl border border-[hsl(var(--accent)/.6)] bg-[hsl(var(--accent)/.12)] px-4 py-3"
          data-testid="banner-demo-mode"
        >
          <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-[hsl(var(--accent))] font-mono text-[10px] font-bold text-[hsl(var(--accent-foreground))]">D</span>
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-[hsl(78_58%_30%)]">Demo mode active</p>
            <p className="text-[12px] font-medium text-[hsl(var(--foreground))]">
              {data.demoLabel ?? 'DEMO MODE — NO REAL AI CONNECTED'}
            </p>
          </div>
        </div>
      )}

      {/* Health checks */}
      <SectionCard title="Component Health" icon={<CheckCircle size={14} />}>
        {isLoading ? (
          <LoadingRows count={3} />
        ) : !data ? (
          <EmptyState message="Runtime unreachable" />
        ) : data.health.length === 0 ? (
          <EmptyState message="No health checks registered" />
        ) : (
          <div className="space-y-2">
            {data.health.map((h) => (
              <div
                key={h.component}
                className="flex items-center justify-between gap-3"
                data-testid={`health-${h.component}`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  {h.healthy ? (
                    <span className="size-2 rounded-full bg-[hsl(var(--accent))] shrink-0" />
                  ) : (
                    <span className="size-2 rounded-full bg-[hsl(var(--destructive))] shrink-0" />
                  )}
                  <span className="truncate text-[13px] font-medium">{h.component}</span>
                </div>
                <div className="text-right shrink-0">
                  <span className={`font-mono text-[11px] ${h.healthy ? 'text-[hsl(78_58%_30%)]' : 'text-[hsl(var(--destructive))]'}`}>
                    {h.state}
                  </span>
                  {h.details && (
                    <p className="text-[10px] text-[hsl(var(--muted-foreground))] max-w-[160px] truncate">{h.details}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      {/* Network state */}
      <SectionCard title="Network" icon={<Network size={14} />}>
        {isLoading ? (
          <LoadingRows count={2} />
        ) : !data ? (
          <EmptyState message="Runtime unreachable" />
        ) : (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[13px] text-[hsl(var(--muted-foreground))]">Connectivity</span>
              <ConnectivityBadge value={data.network.connectivity} />
            </div>
            {data.network.details && (
              <p className="text-[11px] text-[hsl(var(--muted-foreground))] leading-relaxed">{data.network.details}</p>
            )}
          </div>
        )}
      </SectionCard>

      {/* Recent incidents */}
      <SectionCard title="Recent Incidents" icon={<AlertTriangle size={14} />}>
        {isLoading ? (
          <LoadingRows count={2} />
        ) : !data || data.recentIncidents.length === 0 ? (
          <EmptyState message="No recovery incidents recorded" positive />
        ) : (
          <div className="space-y-2">
            {data.recentIncidents.slice(0, 5).map((inc) => (
              <div key={inc.identifier} className="rounded-lg border border-[hsl(var(--border)/.6)] bg-[hsl(var(--card)/.5)] px-3 py-2" data-testid={`incident-${inc.identifier}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[10px] text-[hsl(var(--muted-foreground))]">{inc.identifier}</span>
                  <span className="font-mono text-[10px] text-[hsl(var(--muted-foreground))]">×{inc.restartCount}</span>
                </div>
                <p className="mt-0.5 text-[12px] font-medium">{inc.serviceName}</p>
                <p className="text-[11px] text-[hsl(var(--muted-foreground))] truncate">{inc.reason}</p>
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      {/* Security summary */}
      <SectionCard title="Security" icon={<Shield size={14} />}>
        {isLoading ? (
          <LoadingRows count={2} />
        ) : !data ? (
          <EmptyState message="Runtime unreachable" />
        ) : (
          <div className="grid grid-cols-2 gap-x-4 gap-y-2">
            <Metric label="Alerts" value={String(data.security.alertCount)} />
            <Metric label="Findings" value={String(data.security.findingCount)} />
            <Metric label="Max severity" value={data.security.highestSeverity} />
            <Metric label="Last check" value={data.security.lastAssessmentAt ?? 'Never'} />
          </div>
        )}
      </SectionCard>

      {/* Agent activity */}
      <SectionCard title="Agent Activity" icon={<Activity size={14} />}>
        {isLoading ? (
          <LoadingRows count={2} />
        ) : !data || data.recentAgentActivity.length === 0 ? (
          <EmptyState message="No recent agent activity" />
        ) : (
          <div className="space-y-2">
            {data.recentAgentActivity.slice(0, 5).map((act) => (
              <div key={act.taskId} className="rounded-lg border border-[hsl(var(--border)/.6)] bg-[hsl(var(--card)/.5)] px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[12px] font-medium">{act.agentName}</span>
                  {act.success ? (
                    <CheckCircle size={12} className="text-[hsl(var(--accent))] shrink-0" />
                  ) : (
                    <XCircle size={12} className="text-[hsl(var(--destructive))] shrink-0" />
                  )}
                </div>
                <p className="text-[11px] text-[hsl(var(--muted-foreground))] leading-relaxed line-clamp-2">{act.summary}</p>
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      {/* Refresh indicator */}
      <div className="flex items-center justify-between px-1">
        <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground)/.6)]">
          Auto-refreshes every 30 s
        </span>
        {system.isFetching && (
          <RefreshCw size={10} className="animate-spin text-[hsl(var(--muted-foreground)/.6)]" />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function SectionCard({
  title,
  icon,
  children,
}: {
  title: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-[hsl(var(--border)/.75)] bg-[hsl(var(--card)/.7)] p-4">
      <div className="mb-3 flex items-center gap-2 text-[hsl(var(--muted-foreground))]">
        {icon}
        <span className="font-mono text-[10px] uppercase tracking-[0.18em]">{title}</span>
      </div>
      {children}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="font-mono text-[9px] uppercase tracking-[0.13em] text-[hsl(var(--muted-foreground))]">{label}</p>
      <p className="mt-0.5 text-[12px] font-medium truncate">{value}</p>
    </div>
  );
}

function ConnectivityBadge({ value }: { value: string }) {
  const colorMap: Record<string, string> = {
    // UNKNOWN = no live probe yet — neutral, never styled as a failure
    unknown: 'border-[hsl(var(--muted-foreground)/.4)] bg-[hsl(var(--muted)/.5)] text-[hsl(var(--muted-foreground))]',
    online: 'border-[hsl(var(--accent)/.5)] bg-[hsl(var(--accent)/.1)] text-[hsl(78_58%_30%)]',
    degraded: 'border-[hsl(34_77%_57%/.5)] bg-[hsl(34_77%_57%/.1)] text-[hsl(34_77%_35%)]',
    offline: 'border-[hsl(var(--destructive)/.4)] bg-[hsl(var(--destructive)/.08)] text-[hsl(var(--destructive))]',
    local_only: 'border-[hsl(var(--primary)/.4)] bg-[hsl(var(--primary)/.07)] text-[hsl(var(--primary))]',
    recovering: 'border-[hsl(var(--muted-foreground)/.4)] bg-[hsl(var(--muted)/.5)] text-[hsl(var(--muted-foreground))]',
  };
  const cls = colorMap[value] ?? colorMap.offline;
  return (
    <span className={`rounded-full border px-2.5 py-1 font-mono text-[9px] uppercase tracking-[0.13em] ${cls}`}>
      {value.replace('_', ' ')}
    </span>
  );
}

function LoadingRows({ count }: { count: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="h-5 animate-pulse rounded-md bg-[hsl(var(--muted)/.5)]" />
      ))}
    </div>
  );
}

function EmptyState({ message, positive = false }: { message: string; positive?: boolean }) {
  return (
    <p className={`text-[12px] ${positive ? 'text-[hsl(78_58%_30%)]' : 'text-[hsl(var(--muted-foreground))]'}`}>
      {message}
    </p>
  );
}
