/**
 * useVoice — Voice pipeline for JARVIS V1.
 *
 * STT:  Browser Web Speech API (SpeechRecognition / webkitSpeechRecognition)
 * TTS:  ElevenLabs via /api/tts backend endpoint (API key stays server-side)
 *       → fallback to browser SpeechSynthesis when backend is unavailable
 *
 * State machine:
 *   idle → listening  (startListening)
 *   listening → idle  (stopListening or final transcript received)
 *   idle → speaking   (speak called)
 *   speaking → idle   (audio ended / synthesis complete)
 *   any → error       (recognition or TTS error)
 *   unsupported       (browser has no STT/TTS support)
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

export interface UseVoiceOptions {
  /** Called when STT produces a final transcript. */
  onTranscript: (text: string) => void;
  /** BCP-47 language tag for both STT and browser TTS (default: browser locale). */
  lang?: string;
}

export interface UseVoice {
  voiceState: VoiceState;
  isListening: boolean;
  isSpeaking: boolean;
  /** false when the browser lacks SpeechRecognition or SpeechSynthesis. */
  isSupported: boolean;
  error: string | null;
  /** Interim transcript while listening (cleared when final transcript fires). */
  transcript: string;
  /** Which TTS provider handled the last speak() call. */
  ttsProvider: TTSProvider;
  startListening: () => void;
  stopListening: () => void;
  speak: (text: string) => void;
  cancelSpeaking: () => void;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useVoice({ onTranscript, lang }: UseVoiceOptions): UseVoice {
  const [voiceState, setVoiceState] = useState<VoiceState>(
    isSupportedBrowser ? "idle" : "unsupported",
  );
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ttsProvider, setTtsProvider] = useState<TTSProvider>("none");

  const recognitionRef = useRef<ISpeechRecognition | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioBlobUrlRef = useRef<string | null>(null);
  const onTranscriptRef = useRef(onTranscript);
  onTranscriptRef.current = onTranscript;

  // ── Helpers ────────────────────────────────────────────────────────────────

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

  // ── Cleanup on unmount ─────────────────────────────────────────────────────

  useEffect(() => {
    return () => {
      try { recognitionRef.current?.stop(); } catch { /* ignore */ }
      stopAudio();
      if (hasSynthesis) window.speechSynthesis.cancel();
    };
  }, [stopAudio]);

  // ── startListening ─────────────────────────────────────────────────────────

  const startListening = useCallback(() => {
    if (!isSupportedBrowser) return;
    if (voiceState === "listening") return;

    // Cancel any active audio before listening (avoids feedback)
    stopAudio();
    if (hasSynthesis) window.speechSynthesis.cancel();
    if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch { /* ignore */ }
    }

    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) return;

    const rec = new Ctor();
    rec.continuous = false;
    rec.interimResults = true;
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
      setTranscript(final || interim);
      if (final) {
        setVoiceState("idle");
        onTranscriptRef.current(final.trim());
      }
    };

    rec.onerror = (event: SpeechRecognitionErrorEvent) => {
      setError(`Voice error: ${event.error}`);
      setVoiceState("error");
      setTranscript("");
    };

    rec.onend = () => {
      setVoiceState((prev) => (prev === "listening" ? "idle" : prev));
    };

    recognitionRef.current = rec;
    try {
      rec.start();
    } catch (e) {
      setError(`Could not start microphone: ${e}`);
      setVoiceState("error");
    }
  }, [voiceState, lang, stopAudio]);

  // ── stopListening ──────────────────────────────────────────────────────────

  const stopListening = useCallback(() => {
    if (!recognitionRef.current) return;
    try { recognitionRef.current.stop(); } catch { /* ignore */ }
    recognitionRef.current = null;
    setVoiceState("idle");
  }, []);

  // ── speak ──────────────────────────────────────────────────────────────────

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

      setVoiceState("speaking");
      setError(null);

      const clean = cleanForSpeech(text);
      if (!clean) {
        setVoiceState("idle");
        return;
      }

      // ── 1. Try ElevenLabs via backend ─────────────────────────────────────
      fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: clean }),
      })
        .then(async (resp) => {
          if (!resp.ok) {
            // Parse error info without exposing the raw response to users
            let msg = `HTTP ${resp.status}`;
            try {
              const data = (await resp.json()) as { error?: string };
              if (data.error) msg = data.error;
            } catch { /* ignore */ }
            throw new Error(msg);
          }
          return resp.blob();
        })
        .then((blob) => {
          const url = URL.createObjectURL(blob);
          audioBlobUrlRef.current = url;

          const audio = new Audio(url);
          audioRef.current = audio;

          audio.onended = () => {
            stopAudio();
            setVoiceState("idle");
          };

          audio.onerror = () => {
            stopAudio();
            setError("ElevenLabs audio playback failed.");
            setVoiceState("error");
          };

          setTtsProvider("elevenlabs");
          audio.play().catch((playErr) => {
            // play() can be blocked by browser autoplay policy
            stopAudio();
            console.warn("[JARVIS voice] Audio play() blocked:", playErr);
            setError("Audio playback was blocked by the browser. Tap to speak again.");
            setVoiceState("error");
          });
        })
        .catch((err: unknown) => {
          // ── 2. Fall back to browser SpeechSynthesis ───────────────────────
          const msg = err instanceof Error ? err.message : String(err);
          console.warn(
            `[JARVIS voice] ElevenLabs TTS unavailable (${msg}), falling back to browser SpeechSynthesis.`,
          );

          if (!hasSynthesis) {
            setError(`TTS unavailable: ${msg}`);
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
            setVoiceState("idle");
          };
          utterance.onerror = (e: SpeechSynthesisErrorEvent) => {
            if (e.error !== "interrupted") {
              setError(`Browser TTS error: ${e.error}`);
              setVoiceState("error");
            } else {
              setVoiceState("idle");
            }
          };

          setTtsProvider("browser");
          window.speechSynthesis.speak(utterance);
        });
    },
    [lang, stopAudio],
  );

  // ── cancelSpeaking ─────────────────────────────────────────────────────────

  const cancelSpeaking = useCallback(() => {
    stopAudio();
    if (hasSynthesis) window.speechSynthesis.cancel();
    setVoiceState("idle");
  }, [stopAudio]);

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
  };
}
