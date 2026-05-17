"""
Narrator — Generates TTS audio for live step-by-step narration during audits.
Uses the OpenAI-compatible /v1/audio/speech endpoint via OpenRouter.
"""
import os

from openai import OpenAI


class Narrator:
    """Synchronous TTS wrapper for live narration during agent runs."""

    def __init__(self, voice: str = "nova"):
        self.client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY", "dummy"),
            base_url=os.getenv("OPENAI_BASE_URL"),
        )
        self.voice = voice
        self.tts_model = "openai/tts-1"  # OpenRouter model path

    def narrate(self, text: str) -> bytes | None:
        """Convert text to speech. Returns raw MP3 bytes, or None on failure."""
        if not text or len(text.strip()) < 5:
            return None
        try:
            response = self.client.audio.speech.create(
                model=self.tts_model,
                voice=self.voice,
                input=text[:500],  # Cap at 500 chars to keep latency low
                response_format="mp3",
            )
            return response.content
        except Exception:
            # TTS is non-critical — fail silently so the audit continues
            return None
