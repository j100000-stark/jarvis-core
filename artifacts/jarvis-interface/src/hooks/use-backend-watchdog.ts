/**
 * useBackendWatchdog — automatic backend reconnect (spec §9).
 *
 * Monitors the API server heartbeat (`/api/healthz`) and, when the backend
 * workflow restarts or becomes temporarily unavailable, drives the honest
 * recovery sequence without requiring a manual page refresh:
 *
 *   BACKEND OFFLINE → RECONNECTING... → HEALTH CHECK → BACKEND ONLINE
 *     → RECONNECTING SERVICES → JARVIS READY
 *
 * Guarantees:
 *  - Exponential backoff while offline (1s → 15s cap), steady 10s heartbeat
 *    while online.
 *  - Events are emitted only on REAL probe results — never simulated.
 *  - Recovery triggers `onRecovered()` exactly once per outage so the host
 *    can restore state (refetch queries, reset recognition/TTS). Pending
 *    POST requests are never replayed — restoration is read-only.
 *  - No attempt to open tabs/windows (iOS security forbids it).
 */

import { useCallback, useEffect, useRef, useState } from "react";

type BackendStatus = "unknown" | "online" | "offline" | "reconnecting";

type WatchdogEvent =
  | "BACKEND_OFFLINE"
  | "RECONNECTING"
  | "HEALTH_CHECK"
  | "BACKEND_ONLINE"
  | "RECONNECTING_SERVICES"
  | "JARVIS_READY";

interface UseBackendWatchdogOptions {
  /** Heartbeat interval while healthy (ms). */
  intervalMs?: number;
  /** Terminal/event reporting. */
  onEvent?: (event: WatchdogEvent, detail?: string) => void;
  /** Called once per recovery — restore state here (read-only refetches). */
  onRecovered?: () => void;
}

const HEALTH_PATH = "/api/healthz";
const MAX_BACKOFF_MS = 15_000;

export function useBackendWatchdog({
  intervalMs = 10_000,
  onEvent,
  onRecovered,
}: UseBackendWatchdogOptions = {}) {
  const [status, setStatus] = useState<BackendStatus>("unknown");

  const statusRef = useRef<BackendStatus>("unknown");
  const attemptRef = useRef(0);
  const onEventRef = useRef(onEvent);
  const onRecoveredRef = useRef(onRecovered);
  onEventRef.current = onEvent;
  onRecoveredRef.current = onRecovered;

  const setBoth = useCallback((s: BackendStatus) => {
    statusRef.current = s;
    setStatus(s);
  }, []);

  const probe = useCallback(async (): Promise<boolean> => {
    const controller = new AbortController();
    const t = setTimeout(() => controller.abort(), 5000);
    try {
      const res = await fetch(HEALTH_PATH, {
        signal: controller.signal,
        cache: "no-store",
      });
      return res.ok;
    } catch {
      return false;
    } finally {
      clearTimeout(t);
    }
  }, []);

  useEffect(() => {
    // All lifecycle state is OWNED BY THIS EFFECT INSTANCE so Strict Mode
    // double-mounts / effect restarts can never strand the heartbeat: a
    // cancelled instance's in-flight probe cannot block the new instance.
    let cancelled = false;
    let inFlight = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const schedule = (ms: number) => {
      if (cancelled) return;
      if (timer) clearTimeout(timer);
      timer = setTimeout(tick, ms);
    };

    const tick = async () => {
      if (cancelled || inFlight) return;
      inFlight = true;
      const wasOffline =
        statusRef.current === "offline" || statusRef.current === "reconnecting";
      if (wasOffline) {
        attemptRef.current += 1;
        setBoth("reconnecting");
        onEventRef.current?.("RECONNECTING", `attempt ${attemptRef.current}`);
        onEventRef.current?.("HEALTH_CHECK");
      }
      const ok = await probe();
      inFlight = false;
      if (cancelled) return;

      if (ok) {
        if (wasOffline) {
          // Real recovery observed — restore state exactly once.
          onEventRef.current?.("BACKEND_ONLINE");
          onEventRef.current?.("RECONNECTING_SERVICES");
          attemptRef.current = 0;
          setBoth("online");
          try {
            onRecoveredRef.current?.();
          } finally {
            onEventRef.current?.("JARVIS_READY");
          }
        } else if (statusRef.current !== "online") {
          setBoth("online"); // first successful heartbeat — silent
        }
        schedule(intervalMs);
        return;
      }

      // Probe FAILED (real result — never assumed)
      if (!wasOffline) {
        onEventRef.current?.("BACKEND_OFFLINE");
        attemptRef.current = 0;
        setBoth("offline");
      }
      const backoff = Math.min(1000 * 2 ** attemptRef.current, MAX_BACKOFF_MS);
      schedule(backoff);
    };

    tick(); // immediate first heartbeat
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [intervalMs, probe, setBoth]);

  return { status };
}

export type { BackendStatus, WatchdogEvent };
