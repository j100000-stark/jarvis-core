"""Abstract TTSProvider base class."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod


class TTSError(Exception):
    """Raised when TTS synthesis fails."""


class TTSProvider(ABC):
    """Abstract TTS provider interface.

    All concrete providers must implement ``is_configured()`` and
    ``synthesize()``.  The ``clean_for_speech()`` utility is shared.
    """

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if the provider has all required configuration."""
        ...

    @abstractmethod
    def synthesize(self, text: str) -> bytes:
        """Convert *text* to MP3 audio bytes.

        The caller is responsible for stripping markdown before calling this
        method, but the provider may call ``clean_for_speech`` internally for
        safety.

        Raises:
            TTSError: on any synthesis failure (configuration, network, API).
        """
        ...

    @staticmethod
    def clean_for_speech(text: str) -> str:
        """Strip markdown, code blocks, and metadata so only natural prose remains.

        This is a best-effort pass that makes TTS output more natural.  It
        handles the most common JARVIS response patterns without introducing
        a full Markdown parser.
        """
        # Remove fenced code blocks (``` ... ```)
        text = re.sub(r"```[\s\S]*?```", " ", text)
        # Remove inline code
        text = re.sub(r"`[^`\n]+`", "", text)
        # Remove Markdown headings (# Title → Title)
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # Remove bold / italic / strikethrough markers
        text = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", text)
        text = re.sub(r"_{1,3}([^_\n]+)_{1,3}", r"\1", text)
        text = re.sub(r"~~([^~\n]+)~~", r"\1", text)
        # Collapse Markdown links [label](url) → label
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        # Remove image syntax ![alt](url)
        text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
        # Remove horizontal rules
        text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
        # Strip bullet/numbered list markers (keep the text)
        text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
        # Collapse excessive newlines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
