/**
 * POST /api/tts
 *
 * Server-side ElevenLabs TTS proxy.  The ElevenLabs API key is read from
 * process.env and NEVER sent to the browser.  Audio is streamed back as
 * audio/mpeg so the browser can start playing before the full synthesis
 * completes.
 *
 * Env vars (required at synthesis time):
 *   ELEVENLABS_API_KEY   — ElevenLabs secret key
 *   ELEVENLABS_VOICE_ID  — voice to use
 *   ELEVENLABS_MODEL     — model ID (default: eleven_flash_v2_5)
 *
 * Error codes:
 *   TTS_NOT_CONFIGURED  — missing env var(s)  → 503
 *   INVALID_TEXT        — empty / too long     → 400
 *   TTS_ERROR           — ElevenLabs failure   → 502
 */

import { Router, type IRouter } from "express";
import https from "https";

const router: IRouter = Router();

const ELEVENLABS_HOST = "api.elevenlabs.io";
const DEFAULT_MODEL = "eleven_flash_v2_5";
const MAX_CHARS = 5_000;

// ── Text cleaning (mirrors jarvis/tts/provider.py) ────────────────────────────

function cleanForSpeech(text: string): string {
  return text
    // Fenced code blocks
    .replace(/```[\s\S]*?```/g, " ")
    // Inline code
    .replace(/`[^`\n]+`/g, "")
    // Markdown headings
    .replace(/^#{1,6}\s+/gm, "")
    // Bold / italic / strikethrough
    .replace(/\*{1,3}([^*\n]+)\*{1,3}/g, "$1")
    .replace(/_{1,3}([^_\n]+)_{1,3}/g, "$1")
    .replace(/~~([^~\n]+)~~/g, "$1")
    // Links [label](url) → label
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    // Images
    .replace(/!\[[^\]]*\]\([^)]+\)/g, "")
    // Horizontal rules
    .replace(/^[-*_]{3,}\s*$/gm, "")
    // List markers
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+\.\s+/gm, "")
    // Collapse blank lines
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

// ── Route ─────────────────────────────────────────────────────────────────────

router.post("/tts", (req, res): void => {
  const apiKey  = process.env.ELEVENLABS_API_KEY;
  const voiceId = process.env.ELEVENLABS_VOICE_ID;
  const modelId = process.env.ELEVENLABS_MODEL ?? DEFAULT_MODEL;

  // ── Config guard ─────────────────────────────────────────────────────────
  if (!apiKey) {
    res.status(503).json({
      error: "TTS not configured: ELEVENLABS_API_KEY is missing.",
      code: "TTS_NOT_CONFIGURED",
    });
    return;
  }
  if (!voiceId) {
    res.status(503).json({
      error: "TTS not configured: ELEVENLABS_VOICE_ID is missing.",
      code: "TTS_NOT_CONFIGURED",
    });
    return;
  }

  // ── Input validation ──────────────────────────────────────────────────────
  const rawText = typeof req.body?.text === "string" ? (req.body.text as string) : "";
  const text = cleanForSpeech(rawText).slice(0, MAX_CHARS);

  if (!text) {
    res.status(400).json({
      error: "text is required and must be non-empty after markdown cleaning.",
      code: "INVALID_TEXT",
    });
    return;
  }

  // ── Build ElevenLabs request ──────────────────────────────────────────────
  const payload = JSON.stringify({
    text,
    model_id: modelId,
    voice_settings: { stability: 0.5, similarity_boost: 0.75 },
  });

  const path = `/v1/text-to-speech/${encodeURIComponent(voiceId)}/stream`;

  const options: https.RequestOptions = {
    hostname: ELEVENLABS_HOST,
    path,
    method: "POST",
    headers: {
      "xi-api-key": apiKey,          // stays server-side — never forwarded to browser
      "Content-Type": "application/json",
      "Accept": "audio/mpeg",
      "Content-Length": Buffer.byteLength(payload),
    },
  };

  // ── Proxy + stream ────────────────────────────────────────────────────────
  const upstream = https.request(options, (upstreamRes) => {
    const statusCode = upstreamRes.statusCode ?? 0;

    if (statusCode !== 200) {
      // Collect error body and return a clean error response
      const chunks: Buffer[] = [];
      upstreamRes.on("data", (chunk: Buffer) => chunks.push(chunk));
      upstreamRes.on("end", () => {
        if (res.headersSent) return;
        const body = Buffer.concat(chunks).toString("utf8").slice(0, 400);
        req.log.warn({ statusCode, body }, "ElevenLabs TTS API error");
        res.status(502).json({
          error: `ElevenLabs returned HTTP ${statusCode}: ${body}`,
          code: "TTS_ERROR",
        });
      });
      return;
    }

    // Stream audio directly to the browser
    res.setHeader("Content-Type", "audio/mpeg");
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("X-TTS-Provider", "elevenlabs");
    res.setHeader("X-TTS-Model", modelId);

    upstreamRes.pipe(res);

    upstreamRes.on("error", (err: Error) => {
      req.log.error({ err: err.message }, "ElevenLabs stream error mid-pipe");
      // Headers already sent at this point — we can only destroy
      res.destroy(err);
    });
  });

  upstream.on("error", (err: Error) => {
    req.log.error({ err: err.message }, "ElevenLabs connection error");
    if (!res.headersSent) {
      res.status(502).json({
        error: `ElevenLabs connection failed: ${err.message}`,
        code: "TTS_ERROR",
      });
    }
  });

  // Abort upstream if client disconnects
  req.on("close", () => {
    if (!res.writableEnded) upstream.destroy();
  });

  upstream.write(payload);
  upstream.end();
});

export default router;
