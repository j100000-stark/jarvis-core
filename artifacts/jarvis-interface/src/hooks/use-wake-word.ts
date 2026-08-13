/**
 * useWakeWord — local wake-word detection in STANDBY (spec Phase 2).
 *
 * Listens continuously with the browser's Web Speech API while enabled and
 * detects "Jarvis", "Hey Jarvis", "Ehi Jarvis", "Jarvis, ci sei?" (EN + IT).
 * The wake phrase is stripped from the utterance; any remaining words are
 * delivered as the command so "Jarvis, che ore sono?" submits immediately.
 *
 * Privacy: recognition runs through the PLATFORM speech API only — no audio
 * is ever streamed to the JARVIS server. (On iOS Safari the platform API may
 * use Apple's servers; that is a platform property we surface honestly.)
 *
 * iOS Safari limitation (honest fallback, spec requirement): continuous
 * recognition is unreliable — Safari stops sessions after short silences and
 * throttles rapid restarts. We restart with backoff; after repeated failures
 * we report "restricted" so the UI can tell the user the mic button is the
 * reliable path. We never fake an active wake-word state.
 */

import { useCallback, useEffect, useRef, useState } from "react";

type WakeWordStatus = "inactive" | "listening" | "restricted" | "unsupported";

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
  /** Fired once when detection degrades to "restricted" or "unsupported". */
  onStatusChange?: (status: WakeWordStatus) => void;
}

// Wake phrase at the START of the utterance; tolerant of common
// mis-transcriptions ("jarvis" → "jarvys"/"jervis") and Italian lead-ins.
const WAKE_RE =
  /^\s*(?:hey|ehi|hi|ok)?[\s,]*(?:jarvis|jarvys|jervis|gervis)\b[\s,!.?]*/i;
// "Jarvis, ci sei?" → wake with no command
const PRESENCE_RE = /^(?:ci sei|sei l[ìi]|are you there|you there)[\s?!.]*$/i;

const MAX_CONSECUTIVE_FAILURES = 4;

function getRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function useWakeWord({ enabled, onWake, onStatusChange }: UseWakeWordOptions) {
  const [status, setStatus] = useState<WakeWordStatus>("inactive");

  const recRef = useRef<ISpeechRecognition | null>(null);
  const enabledRef = useRef(enabled);
  const failuresRef = useRef(0);
  const restartTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onWakeRef = useRef(onWake);
  const onStatusRef = useRef(onStatusChange);
  const lastWakeAtRef = useRef(0);
  onWakeRef.current = onWake;
  onStatusRef.current = onStatusChange;
  enabledRef.current = enabled;

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
    const rec = recRef.current;
    recRef.current = null;
    if (rec) {
      rec.onresult = null;
      rec.onend = null;
      rec.onerror = null;
      try {
        rec.stop();
      } catch {
        /* already stopped */
      }
    }
  }, []);

  const start = useCallback(() => {
    const Ctor = getRecognitionCtor();
    if (!Ctor) {
      setAndReport("unsupported");
      return;
    }
    if (recRef.current || !enabledRef.current) return;

    const rec = new Ctor();
    recRef.current = rec;
    const sessionStartedAt = Date.now();
    rec.continuous = true;
    rec.interimResults = false;
    rec.lang = navigator.language?.startsWith("it") ? "it-IT" : "en-US";

    rec.onresult = (event: SpeechRecognitionEvent) => {
      failuresRef.current = 0;
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (!result.isFinal) continue;
        const text = (result[0]?.transcript ?? "").trim();
        const match = WAKE_RE.exec(text);
        if (!match) continue;
        // Debounce: one wake per 2 s (Safari can duplicate finals)
        const now = Date.now();
        if (now - lastWakeAtRef.current < 2000) continue;
        lastWakeAtRef.current = now;

        let command = text.slice(match[0].length).trim();
        if (PRESENCE_RE.test(command)) command = "";
        // Release the mic BEFORE handing off — the command STT session must
        // be the single owner of recognition (no competing sessions).
        stop();
        setAndReport("inactive");
        onWakeRef.current(command);
        return;
      }
    };

    rec.onerror = (event: SpeechRecognitionErrorEvent) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        failuresRef.current = MAX_CONSECUTIVE_FAILURES; // permission — do not loop
      } else if (event.error !== "no-speech" && event.error !== "aborted") {
        failuresRef.current += 1;
      }
    };

    rec.onend = () => {
      if (recRef.current !== rec) return; // intentionally stopped
      recRef.current = null;
      if (!enabledRef.current) {
        setAndReport("inactive");
        return;
      }
      // Sessions that die almost immediately count as failures even without
      // an error event — otherwise Safari's instant-end loop restarts forever.
      if (Date.now() - sessionStartedAt < 2000) {
        failuresRef.current += 1;
      }
      if (failuresRef.current >= MAX_CONSECUTIVE_FAILURES) {
        // Honest degradation: continuous recognition is not viable here
        // (typical on iOS Safari). Mic button remains the reliable path.
        setAndReport("restricted");
        return;
      }
      // Browsers end continuous sessions after silence — restart with
      // capped exponential backoff.
      const backoff = Math.min(250 * 2 ** failuresRef.current, 5000);
      restartTimerRef.current = setTimeout(() => {
        restartTimerRef.current = null;
        start();
      }, backoff);
    };

    try {
      rec.start();
      setAndReport("listening");
    } catch {
      recRef.current = null;
      failuresRef.current += 1;
      if (failuresRef.current >= MAX_CONSECUTIVE_FAILURES) {
        setAndReport("restricted");
      } else {
        restartTimerRef.current = setTimeout(start, 500);
      }
    }
  }, [setAndReport]);

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

  return { status };
}

export type { WakeWordStatus };
