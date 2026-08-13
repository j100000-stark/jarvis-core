/**
 * useVoice — Voice pipeline for JARVIS V1.
 *
 * STT:  Browser Web Speech API (SpeechRecognition / webkitSpeechRecognition)
 *       iOS Safari fix: accumulates final transcript in a ref and submits in
 *       onend, because iOS sometimes fires onend without isFinal=true in onresult.
 *
 * TTS:  ElevenLabs via /api/tts backend endpoint (API key stays server-side)
 *       → fallback to browser SpeechSynthesis when backend is unavailable.
 *       SPEAKING state is only set when audio.play() actually resolves (not before
 *       the fetch starts), so the UI never shows SPEAKING for silent audio.
 *
 * iOS unlock: call unlockAudio() during a user gesture (mic button press) to
 *   pre-authorise future async audio.play() calls on iOS Safari.
 *
 * Security: ELEVENLABS_API_KEY never touches the browser.  The /api/tts
 * endpoint is a pure server-side proxy.
 */

import { useCallback, useEffect, useRef, useState } from "react";

// ── Web Speech API type declarations (self-contained, no lib.dom dependency) ──

interface SpeechRecognitionResult {
  readonly isFinal: boolean;
  readonly [index: number]: SpeechRecognitionAlternative;
}
interface SpeechRecognitionAlternative {
  readonly transcript: string;
  readonly confidence: number;
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
  maxAlternatives: number;
  onstart: ((ev: Event) => void) | null;
  onresult: ((ev: SpeechRecognitionEvent) => void) | null;
  onerror: ((ev: SpeechRecognitionErrorEvent) => void) | null;
  onend: ((ev: Event) => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type SpeechRecognitionCtor = new () => ISpeechRecognition;

// ── Browser feature detection (computed once at module load) ──────────────────

type WindowWithSpeech = Window & {
  SpeechRecognition?: SpeechRecognitionCtor;
  webkitSpeechRecognition?: SpeechRecognitionCtor;
};

function getSpeechRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as WindowWithSpeech;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const hasSynthesis =
  typeof window !== "undefined" && "speechSynthesis" in window;

const isSupportedBrowser =
  Boolean(getSpeechRecognitionCtor()) && hasSynthesis;

// ── Text cleaning (mirrors jarvis/tts/provider.py) ────────────────────────────

export function cleanForSpeech(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`[^`\n]+`/g, "")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/\*{1,3}([^*\n]+)\*{1,3}/g, "$1")
    .replace(/_{1,3}([^_\n]+)_{1,3}/g, "$1")
    .replace(/~~([^~\n]+)~~/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]+\)/g, "")
    .replace(/^[-*_]{3,}\s*$/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

// ── Public types ──────────────────────────────────────────────────────────────

export type VoiceState =
  | "idle"
  | "listening"
  | "speaking"
  | "error"
  | "unsupported";

/** Which TTS path was used for the most recent speak() call. */
export type TTSProvider = "elevenlabs" | "browser" | "none";

/**
 * Key stages emitted by speak() so the host can push terminal events.
 * All stages are best-effort; the host must not assume strict ordering.
 */
export type TTSStage =
  | "requesting"   // fetch('/api/tts') sent
  | "received"     // audio blob received from server
  | "playing"      // audio.play() resolved — audio is actually playing
  | "play_failed"  // audio.play() rejected (iOS autoplay policy, etc.)
  | "fallback"     // falling back to browser SpeechSynthesis
  | "ended"        // audio ended normally
  | "error";       // unexpected TTS error

/** Microphone permission state after proactive initialization. */
export type MicPermission = "granted" | "denied" | "unsupported" | "unknown";

export interface UseVoiceOptions {
  /** Called when STT produces a final transcript (may fire from onend on iOS). */
  onTranscript: (text: string) => void;
  /** BCP-47 language tag for both STT and browser TTS (default: browser locale). */
  lang?: string;
  /**
   * Called at key TTS pipeline stages.  Use to push terminal events without
   * coupling voice state into the UI layer.  ``detail`` carries a structured
   * failure category (e.g. "TTS_AUTH_FAILED") on fallback/error stages.
   */
  onTtsStage?: (stage: TTSStage, detail?: string) => void;
}

export interface UseVoice {
  voiceState: VoiceState;
  isListening: boolean;
  isSpeaking: boolean;
  /** false when the browser lacks SpeechRecognition or SpeechSynthesis. */
  isSupported: boolean;
  error: string | null;
  /** Interim transcript while listening (cleared when transcript is submitted). */
  transcript: string;
  /** Which TTS provider handled the last speak() call. */
  ttsProvider: TTSProvider;
  startListening: () => void;
  stopListening: () => void;
  speak: (text: string) => void;
  cancelSpeaking: () => void;
  /**
   * Unlock the iOS audio context.  Must be called synchronously inside a user
   * gesture (e.g. mic button click) before the async speak() chain runs.
   * Safe no-op on non-iOS browsers.
   */
  unlockAudio: () => void;
  /**
   * Proactively request microphone permission (spec: on first app open).
   * Uses the Permissions API where available to avoid re-prompting a user
   * who already denied, then getUserMedia to trigger the browser prompt.
   * Tracks are stopped immediately — no audio is recorded or uploaded.
   */
  initMicrophone: () => Promise<MicPermission>;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useVoice({ onTranscript, lang, onTtsStage }: UseVoiceOptions): UseVoice {
  const [voiceState, setVoiceState] = useState<VoiceState>(
    isSupportedBrowser ? "idle" : "unsupported",
  );
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ttsProvider, setTtsProvider] = useState<TTSProvider>("none");

  const recognitionRef      = useRef<ISpeechRecognition | null>(null);
  const audioRef            = useRef<HTMLAudioElement | null>(null);
  const audioBlobUrlRef     = useRef<string | null>(null);
  const onTranscriptRef     = useRef(onTranscript);
  const onTtsStageRef       = useRef(onTtsStage);
  onTranscriptRef.current   = onTranscript;
  onTtsStageRef.current     = onTtsStage;

  // Accumulated STT state — lives at hook level so onend can access them.
  const accumulatedFinalRef = useRef(""); // final transcript pieces across onresult events
  const lastInterimRef      = useRef(""); // last interim (iOS fallback when no isFinal fires)
  const silenceTimerRef     = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Duplicate-submission guard: never submit the same utterance twice in a row
  // within a short window (iOS can fire onend twice after Safari interruptions).
  const lastSubmittedRef    = useRef<{ text: string; at: number }>({ text: "", at: 0 });

  // ── Helpers ────────────────────────────────────────────────────────────

  /** Stop and release any active <audio> element from ElevenLabs playback. */
  const stopAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.onended = null;
      audioRef.current.onerror = null;
      audioRef.current = null;
    }
    if (audioBlobUrlRef.current) {
      URL.revokeObjectURL(audioBlobUrlRef.current);
      audioBlobUrlRef.current = null;
    }
  }, []);

  // ── Cleanup on unmount ─────────────────────────────────────────────────

  useEffect(() => {
    return () => {
      try { recognitionRef.current?.stop(); } catch { /* ignore */ }
      stopAudio();
      if (hasSynthesis) window.speechSynthesis.cancel();
    };
  }, [stopAudio]);

  // ── unlockAudio ────────────────────────────────────────────────────────

  /**
   * Play a zero-length silent buffer to unlock the AudioContext on iOS Safari.
   * Must be called synchronously during a user gesture (tap/click).
   * This pre-authorises subsequent async audio.play() calls in speak().
   */
  const unlockAudio = useCallback(() => {
    if (typeof window === "undefined") return;
    try {
      type WinWithAudio = Window & {
        AudioContext?: typeof AudioContext;
        webkitAudioContext?: typeof AudioContext;
      };
      const W = window as WinWithAudio;
      const Ctx = W.AudioContext ?? W.webkitAudioContext;
      if (!Ctx) return;
      const ctx = new Ctx();
      const buffer = ctx.createBuffer(1, 1, 22050);
      const src = ctx.createBufferSource();
      src.buffer = buffer;
      src.connect(ctx.destination);
      src.start(0);
      ctx.resume().catch(() => {});
      // Close after a brief tick — keeps context alive long enough for play() to inherit unlock
      setTimeout(() => ctx.close().catch(() => {}), 500);
    } catch { /* best-effort — never throw from a gesture handler */ }
  }, []);

  // ── startListening ─────────────────────────────────────────────────────

  const startListening = useCallback(() => {
    if (!isSupportedBrowser) return;
    if (voiceState === "listening") return;

    // Cancel any active audio before listening (avoids feedback loop)
    stopAudio();
    if (hasSynthesis) window.speechSynthesis.cancel();
    if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch { /* ignore */ }
    }

    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) return;

    // Reset accumulated transcript for this recognition session
    accumulatedFinalRef.current = "";
    lastInterimRef.current = "";

    const rec = new Ctor();
    rec.continuous = false;    // Single-utterance mode — avoids infinite listening
    rec.interimResults = true; // Show partial transcripts while speaking
    rec.lang = lang ?? navigator.language ?? "en-US";
    rec.maxAlternatives = 1;

    rec.onstart = () => {
      setVoiceState("listening");
      setTranscript("");
      setError(null);
    };

    rec.onresult = (event: SpeechRecognitionEvent) => {
      let interim = "";
      let final = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const item = event.results[i];
        if (item.isFinal) final += item[0].transcript;
        else interim += item[0].transcript;
      }
      // Accumulate final results; track last interim as iOS fallback
      if (final) accumulatedFinalRef.current += final;
      if (interim) lastInterimRef.current = interim;
      // Show the most complete text available to the user
      setTranscript(accumulatedFinalRef.current || interim);

      // ── Automatic speech-end detection (spec) ──────────────────────────
      // iOS Safari may never deliver isFinal. Once we have ANY useful
      // transcript, (re)start a short silence timer; when the user stops
      // speaking, stop the engine — onend submits the best transcript once.
      if (accumulatedFinalRef.current || lastInterimRef.current) {
        if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
        silenceTimerRef.current = setTimeout(() => {
          silenceTimerRef.current = null;
          try { rec.stop(); } catch { /* already stopped */ }
        }, 1600);
      }
    };

    rec.onerror = (event: SpeechRecognitionErrorEvent) => {
      // 'no-speech' and 'aborted' are normal — don't surface as errors
      if (event.error === "no-speech" || event.error === "aborted") {
        setVoiceState("idle");
        setTranscript("");
        return;
      }
      setError(`Voice error: ${event.error}`);
      setVoiceState("error");
      setTranscript("");
    };

    rec.onend = () => {
      if (silenceTimerRef.current) {
        clearTimeout(silenceTimerRef.current);
        silenceTimerRef.current = null;
      }
      // ── iOS Safari fix ────────────────────────────────────────────────
      // On iOS, recognition may end without onresult ever firing isFinal=true.
      // We submit whatever we accumulated: final transcript first, then fall
      // back to the last interim result if nothing final was produced.
      const accumulated = accumulatedFinalRef.current.trim();
      const fallback    = lastInterimRef.current.trim();
      accumulatedFinalRef.current = "";
      lastInterimRef.current = "";

      setTranscript("");
      setVoiceState((prev) => (prev === "listening" ? "idle" : prev));

      const toSubmit = accumulated || fallback;
      if (toSubmit) {
        // Duplicate prevention: identical text within 3 s is a Safari
        // double-onend artifact, not a new utterance.
        const now = Date.now();
        const last = lastSubmittedRef.current;
        if (toSubmit === last.text && now - last.at < 3000) return;
        lastSubmittedRef.current = { text: toSubmit, at: now };
        onTranscriptRef.current(toSubmit);
      }
    };

    recognitionRef.current = rec;
    try {
      rec.start();
    } catch (e) {
      setError(`Could not start microphone: ${e}`);
      setVoiceState("error");
    }
  }, [voiceState, lang, stopAudio]);

  // ── stopListening ──────────────────────────────────────────────────────

  const stopListening = useCallback(() => {
    if (!recognitionRef.current) return;
    try { recognitionRef.current.stop(); } catch { /* ignore */ }
    recognitionRef.current = null;
    setVoiceState("idle");
  }, []);

  // ── speak ──────────────────────────────────────────────────────────────

  const speak = useCallback(
    (text: string) => {
      if (!text.trim()) return;

      // Stop any ongoing recognition or audio first
      if (recognitionRef.current) {
        try { recognitionRef.current.stop(); } catch { /* ignore */ }
        recognitionRef.current = null;
      }
      stopAudio();
      if (hasSynthesis) window.speechSynthesis.cancel();
      setError(null);
      // NOTE: We do NOT set voiceState="speaking" here.
      // State only transitions to "speaking" when audio.play() actually resolves,
      // preventing the UI from showing SPEAKING for audio that was never played.

      const clean = cleanForSpeech(text);
      if (!clean) return;

      // Shared browser SpeechSynthesis fallback — used both when the backend
      // request fails AND when delivered audio cannot be decoded/played.
      const speakWithBrowser = (category: string, reason: string): void => {
        console.warn(
          `[JARVIS voice] ElevenLabs TTS failed (${category}: ${reason}), falling back to browser SpeechSynthesis.`,
        );
        // The fallback must never hide the real failure — the category is
        // surfaced to the terminal via onTtsStage before falling back.
        onTtsStageRef.current?.("fallback", category);

        if (!hasSynthesis) {
          setError(`TTS unavailable: ${reason}`);
          setVoiceState("error");
          return;
        }

        const utterance = new SpeechSynthesisUtterance(clean);
        utterance.lang = lang ?? navigator.language ?? "en-US";
        utterance.rate = 1.0;
        utterance.pitch = 0.95;
        utterance.volume = 1.0;

        utterance.onstart = () => {
          setTtsProvider("browser");
          setVoiceState("speaking");
        };
        utterance.onend = () => {
          onTtsStageRef.current?.("ended");
          setVoiceState("idle");
        };
        utterance.onerror = (e: SpeechSynthesisErrorEvent) => {
          if (e.error !== "interrupted") {
            onTtsStageRef.current?.("error");
            setError(`Browser TTS error: ${e.error}`);
            setVoiceState("error");
          } else {
            setVoiceState("idle");
          }
        };

        setTtsProvider("browser");
        window.speechSynthesis.speak(utterance);
      };

      // ── 1. Try ElevenLabs via backend ─────────────────────────────────
      onTtsStageRef.current?.("requesting");

      fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: clean }),
      })
        .then(async (resp) => {
          if (!resp.ok) {
            let msg = `HTTP ${resp.status}`;
            let category = "TTS_UPSTREAM_ERROR";
            try {
              const data = (await resp.json()) as { error?: string; code?: string };
              if (data.error) msg = data.error;
              if (data.code) category = data.code;
            } catch { /* ignore */ }
            const failure = new Error(msg) as Error & { category?: string };
            failure.category = category;
            throw failure;
          }
          return resp.blob();
        })
        .then((blob) => {
          onTtsStageRef.current?.("received");

          const url = URL.createObjectURL(blob);
          audioBlobUrlRef.current = url;

          const audio = new Audio(url);
          audioRef.current = audio;
          setTtsProvider("elevenlabs");

          audio.onended = () => {
            stopAudio();
            onTtsStageRef.current?.("ended");
            setVoiceState("idle");
          };

          audio.onerror = () => {
            stopAudio();
            onTtsStageRef.current?.("error", "TTS_PLAYBACK_ERROR");
            // Malformed/undecodable audio — still deliver speech via fallback.
            speakWithBrowser("TTS_PLAYBACK_ERROR", "audio element failed to decode/play");
          };

          // play() is async — enter SPEAKING only when it actually starts.
          // On iOS, audio unlock (unlockAudio called during mic button press)
          // must have run during a user gesture before this async call.
          audio.play()
            .then(() => {
              setVoiceState("speaking");
              onTtsStageRef.current?.("playing");
            })
            .catch((playErr) => {
              stopAudio();
              console.warn("[JARVIS voice] Audio play() blocked:", playErr);
              onTtsStageRef.current?.("play_failed", "TTS_PLAYBACK_ERROR");
              setError(
                "Audio playback blocked. Tap the microphone button, wait for the response, then try again.",
              );
              setVoiceState("error");
            });
        })
        .catch((err: unknown) => {
          // ── 2. Fall back to browser SpeechSynthesis ───────────────────
          const msg = err instanceof Error ? err.message : String(err);
          const category =
            (err as { category?: string })?.category ?? "TTS_NETWORK_ERROR";
          speakWithBrowser(category, msg);
        });
    },
    [lang, stopAudio],
  );

  // ── cancelSpeaking ─────────────────────────────────────────────────────

  const cancelSpeaking = useCallback(() => {
    stopAudio();
    if (hasSynthesis) window.speechSynthesis.cancel();
    setVoiceState("idle");
  }, [stopAudio]);

  // ── initMicrophone — proactive permission request (spec Phase 1) ───────

  const initMicrophone = useCallback(async (): Promise<MicPermission> => {
    if (
      typeof navigator === "undefined" ||
      !navigator.mediaDevices?.getUserMedia
    ) {
      return "unsupported";
    }
    // Permissions API first: avoids re-prompting a user who already decided.
    try {
      const status = await navigator.permissions?.query?.({
        name: "microphone" as PermissionName,
      });
      if (status?.state === "granted") return "granted";
      if (status?.state === "denied") return "denied";
    } catch {
      /* Permissions API missing 'microphone' (Safari/Firefox) — fall through */
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Permission granted — immediately release the mic. No audio is
      // recorded or uploaded; this only establishes permission.
      stream.getTracks().forEach((t) => t.stop());
      return "granted";
    } catch (err) {
      const name = err instanceof Error ? err.name : "";
      if (name === "NotAllowedError" || name === "SecurityError") return "denied";
      return "unknown";
    }
  }, []);

  return {
    voiceState,
    isListening: voiceState === "listening",
    isSpeaking: voiceState === "speaking",
    isSupported: isSupportedBrowser,
    error,
    transcript,
    ttsProvider,
    startListening,
    stopListening,
    speak,
    cancelSpeaking,
    unlockAudio,
    initMicrophone,
  };
}
