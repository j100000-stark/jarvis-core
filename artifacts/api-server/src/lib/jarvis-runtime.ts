import { spawnSync } from "node:child_process";
import path from "node:path";

export type JarvisRuntimeStatus = {
  connected: boolean;
  providerConfigured: boolean;
  providerName: string;
  version: string;
  externalApisEnabled: boolean;
  error: string | null;
};

export type JarvisExecutionStep = {
  stepId: string;
  objective: string;
  tool: string;
  output: string;
  error: string | null;
  verified: boolean;
  verification: string;
};

export type JarvisGoalResult = {
  success: boolean;
  goal: string;
  response: string;
  providerName: string;
  demoMode: boolean;
  demoLabel: string | null;
  planGoal: string | null;
  planProvider: string | null;
  executionSteps: JarvisExecutionStep[];
  failure: string | null;
};

export type JarvisSystemReport = {
  demoMode: boolean;
  demoLabel: string | null;
  health: Array<{
    component: string;
    healthy: boolean;
    state: string;
    details: string;
  }>;
  network: {
    connectivity: "online" | "degraded" | "offline" | "local_only" | "recovering";
    reachableHosts: string[];
    unreachableHosts: string[];
    details: string;
  };
  recentIncidents: Array<{
    identifier: string;
    serviceName: string;
    reason: string;
    restartCount: number;
    timestamp: string;
    resolved: boolean;
  }>;
  security: {
    alertCount: number;
    findingCount: number;
    highestSeverity: string;
    lastAssessmentAt: string | null;
  };
  recentAgentActivity: Array<{
    taskId: string;
    agentName: string;
    success: boolean;
    summary: string;
    timestamp: string;
  }>;
};

type ProcessResult = {
  ok: boolean;
  output: string;
  error: string | null;
};

const workspaceRoot =
  process.env.JARVIS_WORKSPACE_ROOT ?? path.resolve(__dirname, "../../..");
const pythonCommand = process.env.JARVIS_PYTHON ?? "python3";

function runJarvis(args: string[]): ProcessResult {
  const result = spawnSync(pythonCommand, ["-m", "jarvis", ...args], {
    cwd: workspaceRoot,
    env: process.env,
    encoding: "utf8",
    timeout: 120_000,
    maxBuffer: 1024 * 1024,
  });

  if (result.error) {
    return { ok: false, output: "", error: result.error.message };
  }

  const output = `${result.stdout ?? ""}`.trim();
  const errorOutput = `${result.stderr ?? ""}`.trim();
  if (result.status !== 0) {
    return {
      ok: false,
      output,
      error: errorOutput || `JARVIS exited with status ${result.status ?? "unknown"}.`,
    };
  }

  return { ok: true, output, error: null };
}

function parseStatus(output: string): JarvisRuntimeStatus {
  const lineValue = (label: string, fallback: string): string => {
    const line = output.split("\n").find((item) => item.startsWith(label));
    return line ? line.slice(label.length).trim() : fallback;
  };

  const providerName = lineValue("Brain provider:", "unknown");
  const version = lineValue("JARVIS ", "unknown");
  const externalApisEnabled =
    lineValue("External APIs:", "disabled").toLowerCase() === "enabled";

  return {
    connected: true,
    providerConfigured: providerName !== "unconfigured" && providerName !== "unknown",
    providerName,
    version,
    externalApisEnabled,
    error: null,
  };
}

export function getJarvisStatus(): JarvisRuntimeStatus {
  const result = runJarvis(["--once", "status"]);
  if (!result.ok) {
    return {
      connected: false,
      providerConfigured: false,
      providerName: "unavailable",
      version: "unknown",
      externalApisEnabled: false,
      error: result.error ?? "JARVIS runtime is unavailable.",
    };
  }
  return parseStatus(result.output);
}

export function sendJarvisGoalJson(goal: string):
  | JarvisGoalResult
  | { kind: "runtime_unavailable" | "brain_unavailable"; error: string }
{
  const status = getJarvisStatus();
  if (!status.connected) {
    return { kind: "runtime_unavailable", error: status.error ?? "JARVIS runtime is unavailable." };
  }
  // Demo brains are always "configured" — allow them through
  const isDemoProvider = status.providerName === "demo";
  if (!status.providerConfigured && !isDemoProvider) {
    return {
      kind: "brain_unavailable",
      error:
        "No Brain or local AI provider is configured. " +
        "Set JARVIS_LOCAL_PROVIDER_ENABLED=true or JARVIS_DEMO_MODE=true.",
    };
  }

  const result = runJarvis(["--goal-json", goal]);
  if (!result.ok) {
    return { kind: "runtime_unavailable", error: result.error ?? "JARVIS could not process the goal." };
  }

  try {
    const parsed = JSON.parse(result.output) as JarvisGoalResult;
    return parsed;
  } catch {
    return { kind: "runtime_unavailable", error: "JARVIS returned malformed JSON." };
  }
}

export function getJarvisSystemReport(): JarvisSystemReport | { error: string } {
  const result = runJarvis(["--system-report"]);
  if (!result.ok) {
    return { error: result.error ?? "JARVIS runtime is unavailable." };
  }
  try {
    const parsed = JSON.parse(result.output) as JarvisSystemReport;
    return parsed;
  } catch {
    return { error: "JARVIS returned malformed system report JSON." };
  }
}
