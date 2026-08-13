"""ElevenLabs TTS provider — server-side only, API key never leaves this module."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional

from .provider import TTSProvider, TTSError

_API_HOST = "api.elevenlabs.io"
_API_VERSION = "v1"
_DEFAULT_MODEL = "eleven_flash_v2_5"


class ElevenLabsTTSProvider(TTSProvider):
    """Synthesize speech via the ElevenLabs REST API using stdlib urllib only.

    Configuration is read from environment variables.  The API key is NEVER
    stored as a public attribute and NEVER included in ``repr()`` or logs.

    Environment variables:
        ELEVENLABS_API_KEY   — required for synthesis.
        ELEVENLABS_VOICE_ID  — required for synthesis.
        ELEVENLABS_MODEL     — optional; defaults to ``eleven_flash_v2_5``.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> None:
        # Store as a private attribute — never exposed
        self.__api_key: str = api_key if api_key is not None else os.environ.get("ELEVENLABS_API_KEY", "")
        self._voice_id: str = voice_id if voice_id is not None else os.environ.get("ELEVENLABS_VOICE_ID", "")
        self._model_id: str = model_id if model_id is not None else os.environ.get("ELEVENLABS_MODEL", _DEFAULT_MODEL)

    # ── Secret isolation ─────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"ElevenLabsTTSProvider("
            f"configured={self.is_configured()}, "
            f"voice_id={'<set>' if self._voice_id else '<missing>'}, "
            f"model_id={self._model_id!r})"
        )

    # Prevent accidental attribute access that could leak the key
    @property
    def api_key_configured(self) -> bool:
        """True if an API key is present (does not return the key itself)."""
        return bool(self.__api_key)

    # ── Public interface ─────────────────────────────────────────────────────

    def is_configured(self) -> bool:
        """Return True only when both API key and voice ID are present."""
        return bool(self.__api_key and self._voice_id)

    def synthesize(self, text: str) -> bytes:
        """Convert *text* to MP3 audio bytes via the ElevenLabs streaming API.

        Raises:
            TTSError: if the API key or voice ID is missing, if the HTTP
                      request fails, or if the response is not audio.
        """
        if not self.__api_key:
            raise TTSError(
                "ElevenLabs API key is not configured. "
                "Set the ELEVENLABS_API_KEY environment variable."
            )
        if not self._voice_id:
            raise TTSError(
                "ElevenLabs voice ID is not configured. "
                "Set the ELEVENLABS_VOICE_ID environment variable."
            )

        clean = self.clean_for_speech(text)
        if not clean:
            raise TTSError("Text is empty after cleaning — nothing to synthesize.")

        url = (
            f"https://{_API_HOST}/{_API_VERSION}"
            f"/text-to-speech/{self._voice_id}/stream"
        )
        payload = json.dumps(
            {
                "text": clean,
                "model_id": self._model_id,
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                },
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "xi-api-key": self.__api_key,  # stays server-side
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
                "Content-Length": str(len(payload)),
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                content_type: str = response.headers.get("Content-Type", "")
                if not content_type.startswith("audio/"):
                    preview = response.read(256)
                    raise TTSError(
                        f"ElevenLabs returned unexpected Content-Type {content_type!r}. "
                        f"Body preview: {preview!r}"
                    )
                return response.read()

        except urllib.error.HTTPError as exc:
            try:
                body = exc.read(512).decode("utf-8", errors="replace")
            except Exception:
                body = "<unreadable>"
            raise TTSError(
                f"ElevenLabs API returned HTTP {exc.code}: {body}"
            ) from exc

        except urllib.error.URLError as exc:
            raise TTSError(
                f"ElevenLabs API connection failed: {exc.reason}"
            ) from exc

    # ── Properties (no secrets) ──────────────────────────────────────────────

    @property
    def voice_id(self) -> str:
        """The configured voice ID (not a secret)."""
        return self._voice_id

    @property
    def model_id(self) -> str:
        """The configured model ID."""
        return self._model_id
