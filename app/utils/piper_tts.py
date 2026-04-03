"""
Local text-to-speech using piper-tts (VITS-based neural TTS).
Runs fully offline on CPU. No API keys or network required.

Replaces gTTS for better voice quality:
  - Neural VITS-based voices (much more natural than gTTS's concatenative synthesis)
  - Fully local — no Google network dependency or rate limits
  - Supports multiple languages via downloadable voice models

Falls back to gTTS if piper-tts is not installed (e.g. macOS dev environment).
"""
import io
import logging
import os
import wave
from typing import Optional

logger = logging.getLogger(__name__)

# Directory to store downloaded piper voice models
_MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "piper_models")

# Default voice model (English, high quality)
_DEFAULT_VOICE = "en_US-lessac-medium"
_DEFAULT_VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx"
_DEFAULT_CONFIG_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json"

_piper_voice = None
_piper_available = None


def _ensure_model_downloaded():
    """Download the default piper voice model if not present."""
    os.makedirs(_MODELS_DIR, exist_ok=True)
    model_path = os.path.join(_MODELS_DIR, f"{_DEFAULT_VOICE}.onnx")
    config_path = os.path.join(_MODELS_DIR, f"{_DEFAULT_VOICE}.onnx.json")

    if os.path.isfile(model_path) and os.path.isfile(config_path):
        return model_path, config_path

    import urllib.request
    for url, dest in [(_DEFAULT_VOICE_URL, model_path), (_DEFAULT_CONFIG_URL, config_path)]:
        if not os.path.isfile(dest):
            logger.info("Downloading piper voice model: %s", os.path.basename(dest))
            urllib.request.urlretrieve(url, dest)
            logger.info("Downloaded: %s", dest)

    return model_path, config_path


def _load_piper_voice():
    """Lazy-load the piper voice model once."""
    global _piper_voice, _piper_available
    if _piper_available is False:
        return None
    if _piper_voice is not None:
        return _piper_voice
    try:
        from piper.voice import PiperVoice
        model_path, config_path = _ensure_model_downloaded()
        _piper_voice = PiperVoice.load(model_path, config_path=config_path)
        _piper_available = True
        logger.info("Loaded piper voice: %s", _DEFAULT_VOICE)
        return _piper_voice
    except ImportError as e:
        logger.warning("piper-tts not installed: %s. Falling back to gTTS.", e)
        _piper_available = False
        return None
    except Exception as e:
        logger.exception("Failed to load piper voice: %s", e)
        _piper_available = False
        return None


def synthesize_speech(text: str) -> Optional[io.BytesIO]:
    """
    Synthesize speech from text using piper-tts.

    Returns a BytesIO containing WAV audio data, or None if piper is unavailable.
    Caller should fall back to gTTS if None is returned.
    """
    voice = _load_piper_voice()
    if voice is None:
        return None
    try:
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wav_file:
            voice.synthesize(text, wav_file)
        wav_buffer.seek(0)
        return wav_buffer
    except Exception as e:
        logger.exception("Piper synthesis failed: %s", e)
        return None


def is_available() -> bool:
    """Check if piper-tts is available without loading the model."""
    if _piper_available is not None:
        return _piper_available
    try:
        import piper.voice  # noqa: F401
        return True
    except ImportError:
        return False
