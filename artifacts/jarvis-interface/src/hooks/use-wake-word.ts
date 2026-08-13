/**
 * useWakeWord — local wake-word detection in STANDBY (spec Phase 2).
 *
 * Listens continuously with the browser's Web Speech API while enabled and
 * detects "Jarvis", "Hey Jarvis", "Ehi Jarvis", "Jarvis, ci sei?" (EN + IT).
 * The wake phrase is stripped from the utterance; any remaining words are
 * delivered as the command so "Jarvis, che ore sono?" submits immediately.
 *
 * TRUTHFUL STATE (spec): status only becomes "listening" after the browser
 * fires the recognition engine's `onstart` — never merely because start()
 * was called. Every lifecycle transition is reported via onLifecycle so the
 * terminal reflects REAL engine state:
 *   RECOGNITION_CREATED / RECOGNITION_STARTED / RECOGNITION_RESULT /
 *   RECOGNITION_END / RECOGNITION_ERROR / RECOGNITION_RESTART /
 *   WAKE_WORD_DETECTED
 *
 * Privacy: recognition runs through the PLATFORM speech API only — no audio
 * is ever streamed to the JARVIS server. (On iOS Safari the platform API may
 * use Apple's servers; that is a platform property we surface honestly.)
 *
 * iOS Safari limitation (honest fallback, spec requirement): continuous
 * recognition is unreliable — Safari stops sessions after short silences and
 * throttles rapid restarts. We restart with capped backoff; after repeated
 * failures we report "paused" so the UI shows
 * "WAKE WORD PAUSED — TAP MIC TO REACTIVATE". reset() re-arms the loop
 * (wire it to the mic button). We never fake an active wake-word state.
 */

import { useCallback, useEffect, useRef, useState } from "react";

type WakeWordStatus = "inactive" | "starting" | "listening" | "paused" | "unsupported";

type WakeWordLifecycleEvent =
  | "RECOGNITION_CREATED"
  | "RECOGNITION_STARTED"
  | "RECOGNITION_RESULT"
  | "RECOGNITION_END"
  | "RECOGNITION_ERROR"
  | "RECOGNITION_RESTART"
  | "WAKE_WORD_DETECTED";

// ── Minimal Web Speech API typings (mirrors use-voice.ts) ────────────────────

interface SpeechRecognitionResult {
  readonly isFinal: boolean;
  readonly length: number;
  readonly [index: number]: { readonly transcript: string; readonly confidence: number };
}
interface SpeechRecognitionResultList {
  readonly length: number;
  readonly [index: number]: SpeechRecognitionResult;
}
interface SpeechRecognitionEvent extends Event {
  readonly resultIndex: number;
  readonly results: SpeechRecognitionResultList;
}
interface SpeechRecognitionErrorEvent extends Event {
  readonly error: string;
  readonly message: string;
}
interface ISpeechRecognition extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onstart: ((ev: Event) => void) | null;
  onresult: ((ev: SpeechRecognitionEvent) => void) | null;
  onerror: ((ev: SpeechRecognitionErrorEvent) => void) | null;
  onend: ((ev: Event) => void) | null;
  start(): void;
  stop(): void;
}
type SpeechRecognitionCtor = new () => ISpeechRecognition;

interface UseWakeWordOptions {
  /** Only run detection while true (STANDBY, not while listening/speaking). */
  enabled: boolean;
  /**
   * Fired when the wake word is heard. `command` is the utterance with the
   * wake phrase stripped ("" when the user only said the wake word).
   */
  onWake: (command: string) => void;
  /** Fired once when the status changes. */
  onStatusChange?: (status: WakeWordStatus) => void;
  /** Real engine lifecycle events for terminal instrumentation. */
  onLifecycle?: (event: WakeWordLifecycleEvent, detail?: string) => void;
}

/** Normalize: lowercase, strip accents, collapse punctuation/whitespace. */
function normalizeUtterance(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[.,!?;:'"«»]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

// Wake phrase at the START of the normalized utterance; tolerant of common
// mis-transcriptions ("jarvis" → "jarvys"/"jervis") and Italian lead-ins.
const WAKE_RE =
  /^\s*(?:hey|ehi|hi|ok|ei)?\s*(?:jarvis|jarvys|jervis|gervis|giarvis)\b\s*/i;
// "Jarvis, ci sei?" → wake with no command
const PRESENCE_RE = /^(?:ci sei|sei li|are you there|you there)\s*$/i;

const MAX_CONSECUTIVE_FAILURES = 4;

function getRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function useWakeWord({ enabled, onWake, onStatusChange, onLifecycle }: UseWakeWordOptions) {
  const [status, setStatus] = useState<WakeWordStatus>("inactive");

  const recRef = useRef<ISpeechRecognition | null>(null);
  const enabledRef = useRef(enabled);
  const failuresRef = useRef(0);
  const restartTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startingRef = useRef(false); // duplicate-start guard
  const onWakeRef = useRef(onWake);
  const onStatusRef = useRef(onStatusChange);
  const onLifecycleRef = useRef(onLifecycle);
  const lastWakeAtRef = useRef(0);
  onWakeRef.current = onWake;
  onStatusRef.current = onStatusChange;
  onLifecycleRef.current = onLifecycle;
  enabledRef.current = enabled;

  const emit = useCallback((event: WakeWordLifecycleEvent, detail?: string) => {
    onLifecycleRef.current?.(event, detail);
  }, []);

  const setAndReport = useCallback((s: WakeWordStatus) => {
    setStatus((prev) => {
      if (prev !== s) onStatusRef.current?.(s);
      return s;
    });
  }, []);

  const stop = useCallback(() => {
    if (restartTimerRef.current) {
      clearTimeout(restartTimerRef.current);
      restartTimerRef.current = null;
    }
    startingRef.current = false;
    const rec = recRef.current;
    recRef.current = null;
    if (rec) {
      rec.onstart = null;
      rec.onresult = null;
      rec.onend = null;
      rec.onerror = null;
      try {
        rec.stop();
      } catch {
        /* already stopped */
      }
      // Truthful handoff: handlers are detached, so the engine's own onend
      // will never reach the terminal — report the real end here instead.
      emit("RECOGNITION_END", "stopped (handoff)");
    }
  }, [emit]);

  /**
   * Synchronously release the mic and clear the failure budget WITHOUT
   * starting a new session. Call this from the mic-button gesture BEFORE
   * starting command STT so the two recognizers never overlap; the wake loop
   * re-arms automatically via the `enabled` effect once voice returns to idle.
   */
  const pause = useCallback(() => {
    stop();
    failuresRef.current = 0;
    lastWakeAtRef.current = 0;
    setAndReport("inactive");
  }, [stop, setAndReport]);

  const start = useCallback(() => {
    const Ctor = getRecognitionCtor();
    if (!Ctor) {
      setAndReport("unsupported");
      return;
    }
    // Single-instance + duplicate-start guards
    if (recRef.current || startingRef.current || !enabledRef.current) return;
    startingRef.current = true;

    const rec = new Ctor();
    recRef.current = rec;
    let sessionStartedAt = Date.now(); // reset when the engine ACTUALLY starts
    let engineStarted = false;
    // Italian primary (spec); recognizers transcribe English wake words fine.
    rec.continuous = true;      // where supported; iOS ends sessions anyway
    rec.interimResults = true;  // iOS Safari may never deliver isFinal
    rec.lang = "it-IT";
    emit("RECOGNITION_CREATED");

    const handleDetection = (rawText: string, isFinal: boolean) => {
      const text = normalizeUtterance(rawText);
      const match = WAKE_RE.exec(text);
      if (!match) return false;
      // Bare wake word in an interim result: wait for the final result so a
      // trailing command ("jarvis che ore sono") isn't cut off — unless the
      // engine never finalizes (handled by the final/interim call order).
      const command0 = text.slice(match[0].length).trim();
      if (!isFinal && command0 === "") return false;
      // Debounce: one wake per 2 s (Safari can duplicate results)
      const now = Date.now();
      if (now - lastWakeAtRef.current < 2000) return true;
      lastWakeAtRef.current = now;

      let command = command0;
      if (PRESENCE_RE.test(command)) command = "";
      emit("WAKE_WORD_DETECTED", command || "(bare)");
      // Release the mic BEFORE handing off — the command STT session must
      // be the single owner of recognition (no competing sessions).
      stop();
      setAndReport("inactive");
      onWakeRef.current(command);
      return true;
    };

    rec.onstart = () => {
      // TRUTHFUL: only now is the engine actually running.
      engineStarted = true;
      startingRef.current = false;
      sessionStartedAt = Date.now();
      emit("RECOGNITION_STARTED");
      setAndReport("listening");
    };

    rec.onresult = (event: SpeechRecognitionEvent) => {
      failuresRef.current = 0;
      emit("RECOGNITION_RESULT");
      // Pass 1: final results (preferred — full command available)
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (!result.isFinal) continue;
        if (handleDetection(result[0]?.transcript ?? "", true)) return;
      }
      // Pass 2: interim results with a command after the wake word —
      // iOS Safari can fail to finalize; do not miss "jarvis <command>".
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) continue;
        if (handleDetection(result[0]?.transcript ?? "", false)) return;
      }
    };

    rec.onerror = (event: SpeechRecognitionErrorEvent) => {
      emit("RECOGNITION_ERROR", event.error);
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        failuresRef.current = MAX_CONSECUTIVE_FAILURES; // permission — do not loop
      } else if (event.error !== "no-speech" && event.error !== "aborted") {
        failuresRef.current += 1;
      }
    };

    rec.onend = () => {
      if (recRef.current !== rec) return; // intentionally stopped
      recRef.current = null;
      startingRef.current = false;
      emit("RECOGNITION_END");
      if (!enabledRef.current) {
        setAndReport("inactive");
        return;
      }
      // Sessions that never started or die almost immediately count as
      // failures — otherwise Safari's instant-end loop restarts forever.
      if (!engineStarted || Date.now() - sessionStartedAt < 2000) {
        failuresRef.current += 1;
      }
      if (failuresRef.current >= MAX_CONSECUTIVE_FAILURES) {
        // Honest degradation: continuous recognition is not viable here
        // (typical on iOS Safari). Mic button remains the reliable path.
        setAndReport("paused");
        return;
      }
      // Browsers end continuous sessions after silence — restart with
      // capped exponential backoff.
      const backoff = Math.min(250 * 2 ** failuresRef.current, 5000);
      emit("RECOGNITION_RESTART", `in ${backoff}ms`);
      restartTimerRef.current = setTimeout(() => {
        restartTimerRef.current = null;
        start();
      }, backoff);
    };

    try {
      rec.start();
      // status stays "starting" until onstart proves the engine is running
      setAndReport("starting");
    } catch (e) {
      recRef.current = null;
      startingRef.current = false;
      emit("RECOGNITION_ERROR", e instanceof Error ? e.message : "start() threw");
      failuresRef.current += 1;
      if (failuresRef.current >= MAX_CONSECUTIVE_FAILURES) {
        setAndReport("paused");
      } else {
        restartTimerRef.current = setTimeout(start, 500);
      }
    }
  }, [setAndReport, stop, emit]);

  useEffect(() => {
    enabledRef.current = enabled;
    if (enabled) {
      failuresRef.current = 0;
      start();
    } else {
      stop();
      setAndReport(getRecognitionCtor() ? "inactive" : "unsupported");
    }
    return stop;
  }, [enabled, start, stop, setAndReport]);

  return { status, pause };
}

export type { WakeWordStatus, WakeWordLifecycleEvent };
