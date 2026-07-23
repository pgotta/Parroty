"""
Pluggable TTS backends.

Every engine implements the same tiny interface so the rest of the app never
has to care which one is selected:

    engine = get_engine(name, **config)
    engine.synthesize(text, out_path, voice=..., speaker_wav=..., **params)

Engines:
    openai      -> cloud, paid, very easy, male/female via voice names
    elevenlabs  -> cloud, paid, best naturalness + cloning
    chatterbox  -> local, free, voice cloning from a sample (needs torch)

Heavy local deps (chatterbox-tts, torch) are imported lazily inside the engine
so the app still starts without them installed.
"""

from abc import ABC, abstractmethod


class TTSEngine(ABC):
    # Does this engine clone a voice from a provided sample file?
    supports_cloning: bool = False
    # Friendly voice list for engines with fixed voices (name -> gender).
    builtin_voices: dict = {}

    @abstractmethod
    def synthesize(self, text: str, out_path: str, voice: str = None,
                   speaker_wav: str = None, **params) -> str:
        """Render `text` to an audio file at `out_path`. Returns out_path."""
        raise NotImplementedError


def get_engine(name: str, **config) -> TTSEngine:
    name = (name or "").lower()
    if name == "openai":
        from .converters.openai_engine import OpenAIEngine
        return OpenAIEngine(**config)
    if name == "elevenlabs":
        from .converters.elevenlabs_engine import ElevenLabsEngine
        return ElevenLabsEngine(**config)
    if name == "chatterbox":
        try:
            from .converters.chatterbox_engine import ChatterboxEngine
            return ChatterboxEngine(**config)
        except ModuleNotFoundError as e:
            missing = getattr(e, "name", "") or str(e)
            raise RuntimeError(
                f"Chatterbox isn't fully installed in this environment "
                f"(missing '{missing}'). Make sure you installed BOTH packages "
                f"into the SAME venv that's running Parroty, in this order:\n"
                f"  pip install torch torchaudio\n"
                f"  pip install chatterbox-tts\n"
                f"Tip: activate your venv first, then run "
                f"'python -c \"import chatterbox, torch\"' to confirm they're "
                f"visible to this Python before trying again."
            ) from e
    raise ValueError(f"Unknown TTS engine: {name!r}")


# Static metadata for the UI (no heavy imports needed to show options).
#
# Chatterbox is a cloning model. Its built-in voices use bundled, anonymous
# CC BY 4.0 reference clips under app/assets/voices/, so they work fully
# locally and offline. Custom uploaded samples remain supported.
ENGINE_CATALOG = {
    "openai": {
        "label": "OpenAI (cloud, paid)",
        "cloning": False,
        "needs_key": True,
        "key_url": "https://platform.openai.com/api-keys",
        "voices": {
            "alloy": "neutral", "echo": "male", "fable": "male",
            "onyx": "male", "nova": "female", "shimmer": "female",
        },
    },
    "elevenlabs": {
        "label": "ElevenLabs (cloud, paid, best quality + cloning)",
        "cloning": True,
        "needs_key": True,
        "key_url": "https://elevenlabs.io/app/settings/api-keys",
        "voices": {
            "Rachel": "female", "Adam": "male",
            "Bella": "female", "Antoni": "male",
        },
    },
    "chatterbox": {
        "label": "Chatterbox (local, free, voice cloning)",
        "cloning": True,
        "needs_key": False,
        # Built-in voices use bundled reference clips (app/assets/voices/),
        # so they work fully offline with no API key.
        "builtin_voices": {
            "warm_female": {
                "label": "Warm female",
                "file": "builtin_warm_female.wav",
            },
            "mature_female": {
                "label": "Mature female",
                "file": "builtin_mature_female.wav",
            },
            "neutral_female": {
                "label": "Neutral female",
                "file": "builtin_neutral_female.wav",
            },
            "british_female": {
                "label": "British female",
                "file": "builtin_british_female.wav",
            },
            "warm_male": {
                "label": "Warm male",
                "file": "builtin_warm_male.wav",
            },
            "mature_deep_male": {
                "label": "Mature/deep male",
                "file": "builtin_mature_deep_male.wav",
            },
            "neutral_male": {
                "label": "Neutral male",
                "file": "builtin_neutral_male.wav",
            },
            "british_male": {
                "label": "British male",
                "file": "builtin_british_male.wav",
            },
        },
        # Model variant: speed vs quality.
        "models": {
            "standard": {"label": "Standard (best quality)", "default": True},
            "turbo":    {"label": "Turbo (much faster)", "default": False},
        },
        # Tunable generation parameters exposed in a collapsible panel.
        # (name -> {label, min, max, step, default})
        "params": {
            "exaggeration": {"label": "Exaggeration", "min": 0.25, "max": 2.0,
                             "step": 0.05, "default": 0.5,
                             "hint": "Neutral = 0.5. Extreme values can be unstable."},
            "cfg_weight":   {"label": "CFG / Pace", "min": 0.2, "max": 1.0,
                             "step": 0.05, "default": 0.5,
                             "hint": "Lower = slower, more deliberate pacing."},
            "temperature":  {"label": "Temperature", "min": 0.05, "max": 1.5,
                             "step": 0.05, "default": 0.8,
                             "hint": "Higher = more varied/expressive delivery."},
        },
    },
}
