"""Tests for the ElevenLabs TTS provider (jarvis.tts).

All network calls are fully mocked — no actual HTTP requests are made.
"""

from __future__ import annotations

import io
import json
import os
import unittest
import urllib.error
from typing import Optional
from unittest.mock import MagicMock, patch


# ── Mock HTTP response helper ─────────────────────────────────────────────────

class _MockHTTPResponse:
    """Minimal context-manager mock for urllib.request.urlopen responses."""

    def __init__(
        self,
        body: bytes,
        content_type: str = "audio/mpeg",
    ) -> None:
        self._body = body
        self.headers = _Headers({"Content-Type": content_type})

    def read(self, n: int = -1) -> bytes:
        return self._body if n < 0 else self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _Headers:
    def __init__(self, mapping: dict[str, str]) -> None:
        self._map = mapping

    def get(self, key: str, default: str = "") -> str:
        return self._map.get(key, default)


def _http_error(code: int, body: bytes = b"Bad Request") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://api.elevenlabs.io/v1/text-to-speech/voice/stream",
        code=code,
        msg=f"HTTP Error {code}",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(body),
    )


# ── Import the module under test (guarded so discovery error is clear) ────────

try:
    from jarvis.tts import ElevenLabsTTSProvider, TTSError, TTSProvider
    from jarvis.tts.provider import TTSProvider as _BaseProvider
    _IMPORT_OK = True
except ImportError as _e:
    _IMPORT_OK = False
    _IMPORT_ERROR = _e


# ── Test classes ──────────────────────────────────────────────────────────────

@unittest.skipUnless(_IMPORT_OK, f"jarvis.tts import failed: {_e if not _IMPORT_OK else ''}")
class TestElevenLabsSuccessfulSynthesis(unittest.TestCase):
    """1 — Successful synthesis returns MP3 bytes."""

    def test_synthesis_returns_bytes(self):
        fake_audio = b"\xff\xfb\x90\x00" + b"\x00" * 256  # fake MP3 header + payload
        mock_response = _MockHTTPResponse(fake_audio, content_type="audio/mpeg")

        provider = ElevenLabsTTSProvider(
            api_key="test-key",
            voice_id="voice-abc",
            model_id="eleven_flash_v2_5",
        )

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = provider.synthesize("Hello, I am JARVIS.")

        self.assertIsInstance(result, bytes)
        self.assertEqual(result, fake_audio)

    def test_synthesis_sends_correct_headers(self):
        fake_audio = b"\xff\xfb" + b"\x00" * 64
        mock_response = _MockHTTPResponse(fake_audio)

        provider = ElevenLabsTTSProvider(
            api_key="sk-test-key-123",
            voice_id="voice-xyz",
        )

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_open:
            provider.synthesize("Test speech.")

        request_arg = mock_open.call_args[0][0]
        # urllib.request.Request capitalises header names (xi-api-key → Xi-api-key)
        self.assertIn("Xi-api-key", request_arg.headers)
        self.assertEqual(request_arg.headers["Xi-api-key"], "sk-test-key-123")
        self.assertEqual(request_arg.get_method(), "POST")

    def test_clean_text_is_used_not_raw_markdown(self):
        """synthesize() should strip markdown before sending to ElevenLabs."""
        fake_audio = b"\xff\xfb" + b"\x00" * 64
        mock_response = _MockHTTPResponse(fake_audio)

        provider = ElevenLabsTTSProvider(api_key="k", voice_id="v")

        captured_payload: list[bytes] = []

        def fake_urlopen(req, timeout=None):
            captured_payload.append(req.data)
            return mock_response

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            provider.synthesize("**Bold text** and `inline code`.")

        payload = json.loads(captured_payload[0].decode("utf-8"))
        self.assertNotIn("**", payload["text"])
        self.assertNotIn("`", payload["text"])
        self.assertIn("Bold text", payload["text"])


@unittest.skipUnless(_IMPORT_OK, "jarvis.tts import failed")
class TestElevenLabsAPIFailure(unittest.TestCase):
    """2 — HTTP errors from ElevenLabs are wrapped in TTSError."""

    def _provider(self):
        return ElevenLabsTTSProvider(api_key="key", voice_id="vid")

    def test_http_401_raises_tts_error(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(401, b"Unauthorized")):
            with self.assertRaises(TTSError) as ctx:
                self._provider().synthesize("Hi.")
        self.assertIn("401", str(ctx.exception))

    def test_http_429_raises_tts_error(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(429, b"Rate limited")):
            with self.assertRaises(TTSError):
                self._provider().synthesize("Hi.")

    def test_http_500_raises_tts_error(self):
        with patch("urllib.request.urlopen", side_effect=_http_error(500, b"Internal Server Error")):
            with self.assertRaises(TTSError) as ctx:
                self._provider().synthesize("Hi.")
        self.assertIn("500", str(ctx.exception))

    def test_connection_error_raises_tts_error(self):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
            with self.assertRaises(TTSError) as ctx:
                self._provider().synthesize("Hi.")
        self.assertIn("connection", str(ctx.exception).lower())


@unittest.skipUnless(_IMPORT_OK, "jarvis.tts import failed")
class TestElevenLabsMissingAPIKey(unittest.TestCase):
    """3 — Missing API key raises TTSError immediately (no HTTP call)."""

    def test_missing_key_raises_before_network(self):
        provider = ElevenLabsTTSProvider(api_key="", voice_id="voice-abc")
        self.assertFalse(provider.is_configured())

        with patch("urllib.request.urlopen") as mock_open:
            with self.assertRaises(TTSError) as ctx:
                provider.synthesize("Hello.")
            mock_open.assert_not_called()

        self.assertIn("API key", str(ctx.exception))

    def test_missing_key_from_env_raises(self):
        clean_env = {k: v for k, v in os.environ.items() if k != "ELEVENLABS_API_KEY"}
        with patch.dict(os.environ, clean_env, clear=True):
            provider = ElevenLabsTTSProvider(voice_id="vid")
            with self.assertRaises(TTSError):
                provider.synthesize("Hi.")

    def test_is_configured_false_without_key(self):
        provider = ElevenLabsTTSProvider(api_key="", voice_id="vid")
        self.assertFalse(provider.is_configured())

    def test_is_configured_true_with_both(self):
        provider = ElevenLabsTTSProvider(api_key="key", voice_id="vid")
        self.assertTrue(provider.is_configured())


@unittest.skipUnless(_IMPORT_OK, "jarvis.tts import failed")
class TestElevenLabsMissingVoiceID(unittest.TestCase):
    """4 — Missing voice ID raises TTSError immediately (no HTTP call)."""

    def test_missing_voice_id_raises_before_network(self):
        provider = ElevenLabsTTSProvider(api_key="valid-key", voice_id="")
        self.assertFalse(provider.is_configured())

        with patch("urllib.request.urlopen") as mock_open:
            with self.assertRaises(TTSError) as ctx:
                provider.synthesize("Hello.")
            mock_open.assert_not_called()

        self.assertIn("voice", str(ctx.exception).lower())

    def test_is_configured_false_without_voice_id(self):
        provider = ElevenLabsTTSProvider(api_key="key", voice_id="")
        self.assertFalse(provider.is_configured())


@unittest.skipUnless(_IMPORT_OK, "jarvis.tts import failed")
class TestElevenLabsMalformedResponse(unittest.TestCase):
    """5 — Non-audio Content-Type raises TTSError."""

    def test_json_content_type_raises(self):
        bad_response = _MockHTTPResponse(
            body=b'{"error": "invalid_request"}',
            content_type="application/json",
        )
        provider = ElevenLabsTTSProvider(api_key="key", voice_id="vid")
        with patch("urllib.request.urlopen", return_value=bad_response):
            with self.assertRaises(TTSError) as ctx:
                provider.synthesize("Hi.")
        self.assertIn("Content-Type", str(ctx.exception))

    def test_text_content_type_raises(self):
        bad_response = _MockHTTPResponse(
            body=b"error text",
            content_type="text/plain",
        )
        provider = ElevenLabsTTSProvider(api_key="key", voice_id="vid")
        with patch("urllib.request.urlopen", return_value=bad_response):
            with self.assertRaises(TTSError):
                provider.synthesize("Hi.")

    def test_empty_text_after_cleaning_raises(self):
        """If text becomes empty after cleaning, TTSError before network."""
        provider = ElevenLabsTTSProvider(api_key="key", voice_id="vid")
        with patch("urllib.request.urlopen") as mock_open:
            with self.assertRaises(TTSError) as ctx:
                provider.synthesize("```\nonly code\n```")
            mock_open.assert_not_called()
        self.assertIn("empty", str(ctx.exception).lower())


@unittest.skipUnless(_IMPORT_OK, "jarvis.tts import failed")
class TestElevenLabsFallbackBehavior(unittest.TestCase):
    """6 — is_configured() signals whether ElevenLabs or fallback should be used."""

    def test_unconfigured_provider_signals_fallback(self):
        provider = ElevenLabsTTSProvider(api_key="", voice_id="")
        self.assertFalse(provider.is_configured())

    def test_partial_config_voice_only_signals_fallback(self):
        provider = ElevenLabsTTSProvider(api_key="", voice_id="voice-abc")
        self.assertFalse(provider.is_configured())

    def test_partial_config_key_only_signals_fallback(self):
        provider = ElevenLabsTTSProvider(api_key="key-xyz", voice_id="")
        self.assertFalse(provider.is_configured())

    def test_fully_configured_provider_signals_no_fallback(self):
        provider = ElevenLabsTTSProvider(api_key="key", voice_id="vid")
        self.assertTrue(provider.is_configured())

    def test_tts_error_is_catchable_for_fallback(self):
        """Callers can catch TTSError to trigger fallback logic."""
        provider = ElevenLabsTTSProvider(api_key="key", voice_id="vid")
        with patch("urllib.request.urlopen", side_effect=_http_error(503)):
            try:
                provider.synthesize("Hi.")
                self.fail("Expected TTSError")
            except TTSError:
                pass  # expected — caller falls back to browser TTS


@unittest.skipUnless(_IMPORT_OK, "jarvis.tts import failed")
class TestSpeakingStateTransitions(unittest.TestCase):
    """7 — State behaviour: successful synthesis returns bytes; errors raise."""

    def test_successful_synthesis_returns_non_empty_bytes(self):
        fake_audio = b"\xff\xfb" + b"\x00" * 128
        mock_resp = _MockHTTPResponse(fake_audio)
        provider = ElevenLabsTTSProvider(api_key="k", voice_id="v")

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = provider.synthesize("JARVIS online and ready.")

        self.assertGreater(len(result), 0)

    def test_api_failure_raises_and_does_not_return_bytes(self):
        provider = ElevenLabsTTSProvider(api_key="k", voice_id="v")
        with patch("urllib.request.urlopen", side_effect=_http_error(500)):
            with self.assertRaises(TTSError):
                provider.synthesize("Hello.")

    def test_missing_config_raises_before_any_io(self):
        provider = ElevenLabsTTSProvider(api_key="", voice_id="")
        io_attempted = []
        with patch("urllib.request.urlopen", side_effect=lambda *a, **kw: io_attempted.append(True)):
            try:
                provider.synthesize("Hello.")
            except TTSError:
                pass
        self.assertEqual(io_attempted, [], "No I/O should occur when configuration is missing")

    def test_clean_for_speech_markdown_strip(self):
        """clean_for_speech removes standard markdown patterns."""
        raw = "## Heading\n**Bold** text and `code`.\n```python\nprint('hello')\n```"
        clean = ElevenLabsTTSProvider.clean_for_speech(raw)
        self.assertNotIn("##", clean)
        self.assertNotIn("**", clean)
        self.assertNotIn("`", clean)
        self.assertNotIn("```", clean)
        self.assertIn("Heading", clean)
        self.assertIn("Bold", clean)


@unittest.skipUnless(_IMPORT_OK, "jarvis.tts import failed")
class TestSecretIsolation(unittest.TestCase):
    """8 — The API key must never appear in repr, public attrs, or __dict__."""

    SECRET_KEY = "sk-super-secret-elevenlabs-key-xyz"

    def _provider(self):
        return ElevenLabsTTSProvider(
            api_key=self.SECRET_KEY,
            voice_id="voice-safe-id",
        )

    def test_repr_does_not_contain_api_key(self):
        provider = self._provider()
        representation = repr(provider)
        self.assertNotIn(self.SECRET_KEY, representation)

    def test_str_does_not_contain_api_key(self):
        provider = self._provider()
        self.assertNotIn(self.SECRET_KEY, str(provider))

    def test_public_attributes_do_not_expose_key(self):
        provider = self._provider()
        # voice_id and model_id are OK; api_key must not be accessible
        self.assertFalse(hasattr(provider, "api_key"))
        self.assertFalse(hasattr(provider, "key"))
        self.assertFalse(hasattr(provider, "_api_key"))

    def test_api_key_configured_flag_does_not_expose_key(self):
        provider = self._provider()
        flag = provider.api_key_configured
        self.assertIsInstance(flag, bool)
        self.assertTrue(flag)
        # The flag itself is not the key
        self.assertNotEqual(str(flag), self.SECRET_KEY)

    def test_env_var_not_leaked_via_provider(self):
        """API key taken from env should not be re-exposed on the provider object."""
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": self.SECRET_KEY}):
            provider = ElevenLabsTTSProvider(voice_id="vid")

        # Accessing all public interface — key must not surface
        self.assertNotIn(self.SECRET_KEY, repr(provider))
        self.assertTrue(provider.is_configured())

    def test_is_instance_of_abstract_provider(self):
        """ElevenLabsTTSProvider must implement the TTSProvider contract."""
        provider = self._provider()
        self.assertIsInstance(provider, TTSProvider)


@unittest.skipUnless(_IMPORT_OK, "jarvis.tts import failed")
class TestCleanForSpeech(unittest.TestCase):
    """Standalone tests for the shared clean_for_speech utility."""

    def _clean(self, text: str) -> str:
        return TTSProvider.clean_for_speech(text)

    def test_removes_code_blocks(self):
        result = self._clean("Before\n```python\ncode here\n```\nAfter")
        self.assertNotIn("```", result)
        self.assertNotIn("code here", result)
        self.assertIn("Before", result)
        self.assertIn("After", result)

    def test_removes_inline_code(self):
        result = self._clean("Use `kubectl get pods` to list pods.")
        self.assertNotIn("`", result)
        self.assertIn("list pods", result)

    def test_removes_headings(self):
        result = self._clean("# Main\n## Sub\nBody text.")
        self.assertNotIn("#", result)
        self.assertIn("Main", result)
        self.assertIn("Body text", result)

    def test_removes_bold_italic(self):
        result = self._clean("**Bold** and *italic* and ***both***.")
        self.assertNotIn("**", result)
        self.assertNotIn("*", result)
        self.assertIn("Bold", result)
        self.assertIn("italic", result)

    def test_removes_markdown_links(self):
        result = self._clean("See [the docs](https://example.com) for more.")
        self.assertNotIn("](", result)
        self.assertNotIn("https://", result)
        self.assertIn("the docs", result)

    def test_plain_text_unchanged(self):
        plain = "Hello, I am JARVIS. All systems nominal."
        result = self._clean(plain)
        self.assertEqual(result, plain)


if __name__ == "__main__":
    unittest.main()
