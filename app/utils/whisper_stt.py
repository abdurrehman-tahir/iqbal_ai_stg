"""
Local speech-to-text using faster-whisper (CTranslate2-optimized Whisper).
Runs on CPU with int8 quantization for 4-8x speedup over openai-whisper.
Used by /api/stt and RAG chat audio transcription.

Previously used openai-whisper 'base' model. Switched to faster-whisper for:
  - 4-8x faster transcription on CPU
  - Lower memory usage via int8 quantization
  - Same accuracy (same underlying Whisper model weights)
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# --- Old openai-whisper implementation (replaced by faster-whisper) ---
# import whisper
# WHISPER_DEVICE = "cpu"
# WHISPER_MODEL = "base"
# _whisper_model = None
# _whisper_available = None
# def _load_whisper_model():
#     global _whisper_model, _whisper_available
#     if _whisper_available is False:
#         return None
#     if _whisper_model is not None:
#         return _whisper_model
#     try:
#         _whisper_model = whisper.load_model(WHISPER_MODEL, device=WHISPER_DEVICE)
#         _whisper_available = True
#         logger.info("Loaded local Whisper model: %s (device=%s)", WHISPER_MODEL, WHISPER_DEVICE)
#         return _whisper_model
#     except ImportError as e:
#         logger.warning("openai-whisper not installed: %s", e)
#         _whisper_available = False
#         return None
#     except Exception as e:
#         logger.exception("Failed to load Whisper model: %s", e)
#         _whisper_available = False
#         return None
# --- End old implementation ---

WHISPER_MODEL_SIZE = "base"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"

_whisper_model = None
_whisper_available = None


def _load_whisper_model():
    """Lazy-load the faster-whisper model once, on CPU with int8 quantization."""
    global _whisper_model, _whisper_available
    if _whisper_available is False:
        return None
    if _whisper_model is not None:
        return _whisper_model
    try:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel(
            WHISPER_MODEL_SIZE,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
        _whisper_available = True
        logger.info(
            "Loaded faster-whisper model: %s (device=%s, compute_type=%s)",
            WHISPER_MODEL_SIZE, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE,
        )
        return _whisper_model
    except ImportError as e:
        logger.warning("faster-whisper not installed: %s. Install with: pip install faster-whisper", e)
        _whisper_available = False
        return None
    except Exception as e:
        logger.exception("Failed to load faster-whisper model: %s", e)
        _whisper_available = False
        return None


def transcribe_audio(audio_path: str, language: Optional[str] = None) -> Optional[str]:
    """
    Transcribe an audio file using faster-whisper (CPU, int8 quantization).

    :param audio_path: Path to the audio file (e.g. .webm, .mp3, .wav).
    :param language: Optional language code (e.g. "en"). Auto-detected if None.
    :return: Transcribed text, or None on failure.
    """
    if not audio_path or not os.path.isfile(audio_path):
        return None
    model = _load_whisper_model()
    if model is None:
        return None
    try:
        kwargs = {}
        if language:
            kwargs["language"] = language
        # faster-whisper returns (segments_generator, info)
        segments, info = model.transcribe(audio_path, **kwargs)
        text = " ".join(seg.text for seg in segments).strip()
        return text if text else None
    except Exception as e:
        logger.exception("faster-whisper transcription failed for %s: %s", audio_path, e)
        return None
