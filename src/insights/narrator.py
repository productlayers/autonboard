"""
Narrator — Live step-by-step narration using the browser's Web Speech API.
Zero API cost, no key required — runs entirely in the browser via JS injection.

Voice parameters are tuned per persona technical literacy:
    High   → faster rate, slightly lower pitch (confident, clipped)
    Medium → default rate and pitch
    Low    → slower rate, slightly higher pitch (deliberate, warmer)
"""
import json


# Voice parameters keyed by technical_literacy
_VOICE_PARAMS = {
    "high":   {"rate": 1.15, "pitch": 0.9},
    "medium": {"rate": 1.0,  "pitch": 1.0},
    "low":    {"rate": 0.85, "pitch": 1.1},
}
_DEFAULT_PARAMS = _VOICE_PARAMS["medium"]


def voice_for_persona(persona) -> dict:
    """Return Web Speech API voice params matched to persona's technical literacy."""
    if persona is None:
        return _DEFAULT_PARAMS
    literacy = getattr(persona, "technical_literacy", "") or ""
    return _VOICE_PARAMS.get(literacy.lower(), _DEFAULT_PARAMS)


class Narrator:
    """Generates browser-native TTS via Web Speech API (no API key needed)."""

    def __init__(self, voice: dict | None = None):
        self.params = voice if voice is not None else _DEFAULT_PARAMS

    def narrate(self, text: str) -> str | None:
        """
        Return a JS snippet that speaks `text` via window.speechSynthesis.
        Returns None if text is too short to bother narrating.
        Caller should inject via st_components.html(..., height=0).
        """
        if not text or len(text.strip()) < 5:
            return None
        # Cap at 300 chars — keeps narration tight per step
        clipped = text.strip()[:300]
        safe = json.dumps(clipped)  # proper JS string escaping
        rate = self.params.get("rate", 1.0)
        pitch = self.params.get("pitch", 1.0)
        return f"""
        <script>
          (function() {{
            window.speechSynthesis.cancel();  // stop any in-progress narration
            var u = new SpeechSynthesisUtterance({safe});
            u.rate = {rate};
            u.pitch = {pitch};
            u.lang = "en-US";
            window.speechSynthesis.speak(u);
          }})();
        </script>
        """
