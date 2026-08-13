/**
 * useVoice — browser Web Speech API hook for JARVIS V1.
 *
 * Pipeline:
 *   MICROPHONE → SpeechRecognition → onTranscript callback
 *   response text → SpeechSynthesis → AUDIO
 *
 * State machine:
 *   idle → listening  (startListening called)
 *   listening → idle  (stopListening called or result received)
 *   idle → speaking   (speak called)
 *   speaking → idle   (utterance ends or cancelSpeaking called)
 *   any → error       (recognition or synthesis error)
 *
 * If the browser does not support the APIs, isSupported is false and all
 * methods are no-ops.  No fake audio is ever produced.
 *
 * Provider-agnostic: the speak() method can later be replaced by a cloud
 * TTS provider (ElevenLabs, Google Cloud, etc.) without changing callers.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

// ── Web Speech API type declarations ────────────────────────────────────────
// TypeScript's lib.dom.d.ts includes these but they may not be available in
// all tsconfig targets.  We declare what we use to keep the hook self-contained.

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

// ── Browser API feature detection ──────────────────────────────────────────

type WindowWithSpeech = Window & {
  SpeechRecognition?: SpeechRecognitionCtor;
  webkitSpeechRecognition?: SpeechRecognitionCtor;
};

function getSpeechRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === 'undefined') return null;
  const w = window as WindowWithSpeech;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const hasSynthesis =
  typeof window !== 'undefined' && 'speechSynthesis' in window;

const isSupportedBrowser = Boolean(getSpeechRecognitionCtor()) && hasSynthesis;

// ── Types ──────────────────────────────────────────────────────────────────

export type VoiceState = 'idle' | 'listening' | 'speaking' | 'error' | 'unsupported';

export interface UseVoiceOptions {
  /** Called when STT produces a final transcript. */
  onTranscript: (text: string) => void;
  /** BCP 47 language tag (default: browser locale). */
  lang?: string;
}

export interface UseVoice {
  voiceState: VoiceState;
  isListening: boolean;
  isSpeaking: boolean;
  /** false if the browser has no SpeechRecognition or SpeechSynthesis support. */
  isSupported: boolean;
  error: string | null;
  /** Interim transcript while listening. */
  transcript: string;
  startListening: () => void;
  stopListening: () => void;
  speak: (text: string) => void;
  cancelSpeaking: () => void;
}

// ── Hook ───────────────────────────────────────────────────────────────────

export function useVoice({ onTranscript, lang }: UseVoiceOptions): UseVoice {
  const [voiceState, setVoiceState] = useState<VoiceState>(
    isSupportedBrowser ? 'idle' : 'unsupported'
  );
  const [transcript, setTranscript] = useState('');
  const [error, setError] = useState<string | null>(null);

  const recognitionRef = useRef<ISpeechRecognition | null>(null);
  const onTranscriptRef = useRef(onTranscript);
  onTranscriptRef.current = onTranscript;

  // ── Cleanup on unmount ──────────────────────────────────────────────────

  useEffect(() => {
    return () => {
      try { recognitionRef.current?.stop(); } catch { /* ignore */ }
      if (hasSynthesis) window.speechSynthesis.cancel();
    };
  }, []);

  // ── startListening ──────────────────────────────────────────────────────

  const startListening = useCallback(() => {
    if (!isSupportedBrowser) return;
    if (voiceState === 'listening') return;

    // Cancel any active speech before listening to avoid feedback
    if (hasSynthesis) window.speechSynthesis.cancel();
    if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch { /* ignore */ }
    }

    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) return;

    const rec = new Ctor();
    rec.continuous = false;
    rec.interimResults = true;
    rec.lang = lang ?? navigator.language ?? 'en-US';
    rec.maxAlternatives = 1;

    rec.onstart = () => {
      setVoiceState('listening');
      setTranscript('');
      setError(null);
    };

    rec.onresult = (event: SpeechRecognitionEvent) => {
      let interim = '';
      let final = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const item = event.results[i];
        if (item.isFinal) {
          final += item[0].transcript;
        } else {
          interim += item[0].transcript;
        }
      }
      setTranscript(final || interim);
      if (final) {
        setVoiceState('idle');
        onTranscriptRef.current(final.trim());
      }
    };

    rec.onerror = (event: SpeechRecognitionErrorEvent) => {
      const msg = `Voice error: ${event.error}`;
      setError(msg);
      setVoiceState('error');
      setTranscript('');
    };

    rec.onend = () => {
      setVoiceState((prev) => (prev === 'listening' ? 'idle' : prev));
    };

    recognitionRef.current = rec;
    try {
      rec.start();
    } catch (e) {
      setError(`Could not start microphone: ${e}`);
      setVoiceState('error');
    }
  }, [voiceState, lang]);

  // ── stopListening ───────────────────────────────────────────────────────

  const stopListening = useCallback(() => {
    if (!recognitionRef.current) return;
    try { recognitionRef.current.stop(); } catch { /* ignore */ }
    recognitionRef.current = null;
    setVoiceState('idle');
  }, []);

  // ── speak ───────────────────────────────────────────────────────────────

  const speak = useCallback((text: string) => {
    if (!hasSynthesis || !text.trim()) return;

    // Stop any ongoing recognition before speaking
    if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch { /* ignore */ }
      recognitionRef.current = null;
    }
    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = lang ?? navigator.language ?? 'en-US';
    utterance.rate = 1.0;
    utterance.pitch = 0.95;
    utterance.volume = 1.0;

    utterance.onstart = () => setVoiceState('speaking');
    utterance.onend = () => setVoiceState('idle');
    utterance.onerror = (e: SpeechSynthesisErrorEvent) => {
      if (e.error !== 'interrupted') {
        setError(`TTS error: ${e.error}`);
        setVoiceState('error');
      } else {
        setVoiceState('idle');
      }
    };

    setVoiceState('speaking');
    window.speechSynthesis.speak(utterance);
  }, [lang]);

  // ── cancelSpeaking ──────────────────────────────────────────────────────

  const cancelSpeaking = useCallback(() => {
    if (!hasSynthesis) return;
    window.speechSynthesis.cancel();
    setVoiceState('idle');
  }, []);

  return {
    voiceState,
    isListening: voiceState === 'listening',
    isSpeaking: voiceState === 'speaking',
    isSupported: isSupportedBrowser,
    error,
    transcript,
    startListening,
    stopListening,
    speak,
    cancelSpeaking,
  };
}
