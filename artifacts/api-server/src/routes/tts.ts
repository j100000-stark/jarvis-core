/**
 * POST /api/tts        — Server-side ElevenLabs TTS proxy (streams audio/mpeg).
 * GET  /api/tts/health — REAL synthesis test: performs an actual short
 *                        ElevenLabs synthesis and reports a structured,
 *                        sanitized status. Never reports READY unless real
 *                        synthesis succeeded.
 *
 * The ElevenLabs API key is read from process.env and NEVER sent to the
 * browser. Error responses carry a structured failure category so the
 * frontend terminal and Python self-repair can act on the true root cause.
 *
 * Env vars:
 *   ELEVENLABS_API_KEY   — ElevenLabs secret key (required)
 *   ELEVENLABS_VOICE_ID  — voice to use (required)
 *   ELEVENLABS_MODEL     — model ID (default: eleven_flash_v2_5)
 *
 * Failure categories (spec Phase 4):
 *   TTS_API_KEY_MISSING  — ELEVENLABS_API_KEY not set            → 503
 *   TTS_AUTH_FAILED      — upstream 401/403                       → 502
 *   TTS_VOICE_NOT_FOUND  — voice ID missing or upstream 404       → 502/503
 *   TTS_MODEL_INVALID    — upstream 400 mentioning the model      → 502
 *   TTS_UPSTREAM_ERROR   — any other upstream non-200             → 502
 *   TTS_NETWORK_ERROR    — connection-level failure               → 502
 *   TTS_INVALID_AUDIO    — 200 but non-audio Content-Type/empty   → 502
 *   INVALID_TEXT         — empty text after cleaning              → 400
 *   (TTS_PLAYBACK_ERROR is a frontend-only category.)
 */

import { Router, type IRouter } from "express";
import https from "https";
import type { ClientRequest } from "http";

const router: IRouter = Router();

const ELEVENLABS_HOST = "api.elevenlabs.io";
const DEFAULT_MODEL = "eleven_flash_v2_5";
const MAX_CHARS = 5_000;

// ── Sanitization ─────────────────────────────────────────────────────────────

/** Strip anything secret-looking from upstream error text before logging/returning. */
function sanitize(text: string): string {
  let result = text;
  for (const value of Object.values(process.env)) {
    if (value && value.length >= 16) result = result.split(value).join("[REDACTED]");
  }
  return result
    .replace(/xi-api-key["':\s]*[A-Za-z0-9_-]+/gi, "xi-api-key: [REDACTED]")
    .replace(/\b[A-Za-z0-9]{32,}\b/g, "[REDACTED]");
}

/** Map an upstream HTTP status + body to a structured failure category. */
function categorizeUpstream(statusCode: number, body: string): string {
  if (statusCode === 401 || statusCode === 403) return "TTS_AUTH_FAILED";
  if (statusCode === 404) return "TTS_VOICE_NOT_FOUND";
  if (statusCode === 400 && /model/i.test(body)) return "TTS_MODEL_INVALID";
  if (statusCode === 422 && /voice/i.test(body)) return "TTS_VOICE_NOT_FOUND";
  if (statusCode === 422 && /model/i.test(body)) return "TTS_MODEL_INVALID";
  return "TTS_UPSTREAM_ERROR";
}

// ── Text cleaning (mirrors jarvis/tts/provider.py) ────────────────────────────

function cleanForSpeech(text: string): string {
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

// ── Config guard (shared) ─────────────────────────────────────────────────────

interface TtsConfig {
  apiKey: string;
  voiceId: string;
  modelId: string;
}

function readConfig():
  | { ok: true; config: TtsConfig }
  | { ok: false; category: string; error: string } {
  const apiKey = process.env.ELEVENLABS_API_KEY;
  const voiceId = process.env.ELEVENLABS_VOICE_ID;
  const modelId = process.env.ELEVENLABS_MODEL ?? DEFAULT_MODEL;
  if (!apiKey) {
    return {
      ok: false,
      category: "TTS_API_KEY_MISSING",
      error: "ELEVENLABS_API_KEY is not set.",
    };
  }
  if (!voiceId) {
    return {
      ok: false,
      category: "TTS_VOICE_NOT_FOUND",
      error: "ELEVENLABS_VOICE_ID is not set.",
    };
  }
  return { ok: true, config: { apiKey, voiceId, modelId } };
}

// ── Core synthesis (shared by /tts and /tts/health) ──────────────────────────

interface SynthesisFailure {
  category: string;
  error: string;
  statusCode?: number;
}

/**
 * Perform a real ElevenLabs synthesis. Calls onAudio with the upstream
 * response when synthesis begins successfully (status 200 + audio
 * Content-Type); calls onFailure with a structured category otherwise.
 */
function synthesize(
  config: TtsConfig,
  text: string,
  onAudio: (upstreamRes: NodeJS.ReadableStream & { headers: Record<string, unknown> }) => void,
  onFailure: (failure: SynthesisFailure) => void,
): ClientRequest {
  const payload = JSON.stringify({
    text,
    model_id: config.modelId,
    voice_settings: { stability: 0.5, similarity_boost: 0.75 },
  });

  const options: https.RequestOptions = {
    hostname: ELEVENLABS_HOST,
    path: `/v1/text-to-speech/${encodeURIComponent(config.voiceId)}/stream`,
    method: "POST",
    headers: {
      "xi-api-key": config.apiKey, // stays server-side — never forwarded
      "Content-Type": "application/json",
      Accept: "audio/mpeg",
      "Content-Length": Buffer.byteLength(payload),
    },
  };

  const upstream = https.request(options, (upstreamRes) => {
    const statusCode = upstreamRes.statusCode ?? 0;
    const contentType = String(upstreamRes.headers["content-type"] ?? "");

    if (statusCode !== 200) {
      const chunks: Buffer[] = [];
      upstreamRes.on("data", (chunk: Buffer) => chunks.push(chunk));
      upstreamRes.on("end", () => {
        const body = sanitize(Buffer.concat(chunks).toString("utf8").slice(0, 400));
        onFailure({
          category: categorizeUpstream(statusCode, body),
          error: `ElevenLabs returned HTTP ${statusCode}: ${body}`,
          statusCode,
        });
      });
      return;
    }

    if (!contentType.startsWith("audio/")) {
      const chunks: Buffer[] = [];
      upstreamRes.on("data", (chunk: Buffer) => chunks.push(chunk));
      upstreamRes.on("end", () => {
        const body = sanitize(Buffer.concat(chunks).toString("utf8").slice(0, 200));
        onFailure({
          category: "TTS_INVALID_AUDIO",
          error: `Expected audio/* Content-Type, got "${contentType}". Body: ${body}`,
          statusCode,
        });
      });
      return;
    }

    onAudio(upstreamRes as unknown as NodeJS.ReadableStream & { headers: Record<string, unknown> });
  });

  upstream.on("error", (err: Error) => {
    onFailure({
      category: "TTS_NETWORK_ERROR",
      error: `ElevenLabs connection failed: ${sanitize(err.message)}`,
    });
  });

  upstream.write(payload);
  upstream.end();
  return upstream;
}

// ── POST /api/tts ─────────────────────────────────────────────────────────────

router.post("/tts", (req, res): void => {
  const cfg = readConfig();
  if (!cfg.ok) {
    res.status(503).json({ error: cfg.error, code: cfg.category });
    return;
  }

  const rawText = typeof req.body?.text === "string" ? (req.body.text as string) : "";
  const text = cleanForSpeech(rawText).slice(0, MAX_CHARS);
  if (!text) {
    res.status(400).json({
      error: "text is required and must be non-empty after markdown cleaning.",
      code: "INVALID_TEXT",
    });
    return;
  }

  const upstream = synthesize(
    cfg.config,
    text,
    (upstreamRes) => {
      res.setHeader("Content-Type", "audio/mpeg");
      res.setHeader("Cache-Control", "no-store");
      res.setHeader("X-TTS-Provider", "elevenlabs");
      res.setHeader("X-TTS-Model", cfg.config.modelId);
      (upstreamRes as unknown as NodeJS.ReadableStream).pipe(res);
      (upstreamRes as unknown as NodeJS.EventEmitter).on("error", (err: Error) => {
        req.log.error({ err: sanitize(err.message) }, "ElevenLabs stream error mid-pipe");
        res.destroy(err); // headers already sent — can only destroy
      });
    },
    (failure) => {
      req.log.warn(
        { category: failure.category, statusCode: failure.statusCode },
        "ElevenLabs TTS failure",
      );
      if (!res.headersSent) {
        res.status(502).json({ error: failure.error, code: failure.category });
      }
    },
  );

  req.on("close", () => {
    if (!res.writableEnded) upstream.destroy();
  });
});

// ── GET /api/tts/health — REAL synthesis test ─────────────────────────────────

// Cache the health result so repeated requests (page reloads, probes) cannot
// trigger unbounded paid synthesis calls. One real test per 10 minutes.
const HEALTH_CACHE_MS = 10 * 60 * 1000;
let healthCache: { at: number; body: Record<string, unknown> } | null = null;

router.get("/tts/health", (req, res): void => {
  if (healthCache && Date.now() - healthCache.at < HEALTH_CACHE_MS) {
    res.status(200).json({ ...healthCache.body, cached: true });
    return;
  }
  const cfg = readConfig();
  if (!cfg.ok) {
    res.status(200).json({
      ready: false,
      category: cfg.category,
      error: cfg.error,
      model: process.env.ELEVENLABS_MODEL ?? DEFAULT_MODEL,
    });
    return;
  }

  let settled = false;
  const settle = (body: Record<string, unknown>): void => {
    if (settled) return;
    settled = true;
    // Cache successes for the full window; failures briefly (60 s) so a
    // transient outage doesn't stick but probes still can't spam synthesis.
    const at = body.ready
      ? Date.now()
      : Date.now() - HEALTH_CACHE_MS + 60_000;
    healthCache = { at, body };
    res.status(200).json(body);
  };

  let audioBytes = 0;
  const upstream = synthesize(
    cfg.config,
    "JARVIS online.",
    (upstreamRes) => {
      const stream = upstreamRes as unknown as NodeJS.ReadableStream & NodeJS.EventEmitter;
      stream.on("data", (chunk: Buffer) => {
        audioBytes += chunk.length;
      });
      stream.on("end", () => {
        if (audioBytes === 0) {
          settle({
            ready: false,
            category: "TTS_INVALID_AUDIO",
            error: "Synthesis returned HTTP 200 but zero audio bytes.",
            model: cfg.config.modelId,
          });
          return;
        }
        settle({ ready: true, audioBytes, model: cfg.config.modelId });
      });
      stream.on("error", (err: Error) => {
        settle({
          ready: false,
          category: "TTS_NETWORK_ERROR",
          error: sanitize(err.message),
          model: cfg.config.modelId,
        });
      });
    },
    (failure) => {
      settle({
        ready: false,
        category: failure.category,
        error: failure.error,
        model: cfg.config.modelId,
      });
    },
  );

  // Hard timeout — never leave the health check hanging
  const timer = setTimeout(() => {
    upstream.destroy();
    settle({
      ready: false,
      category: "TTS_NETWORK_ERROR",
      error: "ElevenLabs health check timed out after 15s.",
      model: cfg.config.modelId,
    });
  }, 15_000);
  res.on("finish", () => clearTimeout(timer));
});

export default router;
