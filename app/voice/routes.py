"""
Voice chat WebSocket routes.

Provides a WebSocket endpoint at /ws/voice that handles real-time
audio streaming for the voice chat feature. Uses flask-sock for
WebSocket support within the existing Flask/gunicorn setup.

Protocol (JSON messages over WebSocket):
  Client → Server:
    {"type": "config", "role": "teacher"|"student", "thread_id": "...", ...}
    {"type": "audio", "data": "<base64 PCM16 audio>"}
    {"type": "stop"}

  Server → Client:
    {"type": "transcript", "text": "user said..."}
    {"type": "response", "text": "AI said..."}
    {"type": "audio", "data": "<base64 PCM16 audio>"}
    {"type": "state", "state": "listening"|"thinking"|"speaking"|"idle"}
    {"type": "error", "message": "..."}
"""
import asyncio
import base64
import json
import logging
import struct
import threading
from io import BytesIO

from flask import Blueprint, session

logger = logging.getLogger(__name__)

bp = Blueprint("voice", __name__)

# Will be initialized by init_voice_websocket()
_sock = None


def init_voice_websocket(app):
    """Initialize flask-sock and register the voice WebSocket route."""
    global _sock
    try:
        from flask_sock import Sock
        _sock = Sock(app)

        @_sock.route("/ws/voice")
        def voice_chat(ws):
            """Handle a voice chat WebSocket session."""
            _handle_voice_session(ws)

        logger.info("Voice chat WebSocket registered at /ws/voice")
    except ImportError:
        logger.warning(
            "flask-sock not installed. Voice chat disabled. "
            "Install with: pip install flask-sock"
        )


def _handle_voice_session(ws):
    """
    Main voice chat session handler. Runs in a gunicorn thread.

    Manages the lifecycle of a voice chat session:
    1. Receives config message with role and context
    2. Streams audio back and forth
    3. Processes speech through the Pipecat pipeline
    """
    from app.voice.pipeline import (
        VoicePipelineConfig,
        call_llm_endpoint,
        strip_html_tags,
        SAMPLE_RATE,
    )

    config = None
    is_active = True

    # Send initial state
    _send_json(ws, {"type": "state", "state": "idle"})

    while is_active:
        try:
            raw = ws.receive(timeout=30)
            if raw is None:
                break

            msg = json.loads(raw)
            msg_type = msg.get("type")

            if msg_type == "config":
                # Initialize session configuration
                cookie_header = msg.get("cookie", "")
                config = VoicePipelineConfig(
                    role=msg.get("role", "student"),
                    session_cookie=cookie_header,
                    thread_id=msg.get("thread_id"),
                    conversation_id=msg.get("conversation_id"),
                    lesson_qa_id=msg.get("lesson_qa_id"),
                    base_url=msg.get("base_url", "http://127.0.0.1:5000"),
                )
                _send_json(ws, {"type": "state", "state": "listening"})
                logger.info("[VoiceChat] Session configured: role=%s", config.role)

            elif msg_type == "audio" and config:
                # Receive audio chunk and process through STT → LLM → TTS
                audio_b64 = msg.get("data", "")
                if not audio_b64:
                    continue

                audio_bytes = base64.b64decode(audio_b64)

                # Process in a background thread to not block the WebSocket
                _process_audio_chunk(ws, config, audio_bytes)

            elif msg_type == "transcribe" and config:
                # Complete audio blob for transcription (simpler mode)
                audio_b64 = msg.get("data", "")
                if not audio_b64:
                    continue

                audio_bytes = base64.b64decode(audio_b64)
                _send_json(ws, {"type": "state", "state": "thinking"})

                # Run transcription → LLM → TTS in a thread
                thread = threading.Thread(
                    target=_process_complete_utterance,
                    args=(ws, config, audio_bytes),
                    daemon=True,
                )
                thread.start()

            elif msg_type == "stop":
                is_active = False
                _send_json(ws, {"type": "state", "state": "idle"})

        except json.JSONDecodeError:
            _send_json(ws, {"type": "error", "message": "Invalid JSON"})
        except Exception as e:
            logger.error("[VoiceChat] WebSocket error: %s", e, exc_info=True)
            _send_json(ws, {"type": "error", "message": str(e)})
            break

    logger.info("[VoiceChat] Session ended")


def _process_complete_utterance(ws, config, audio_bytes):
    """
    Process a complete utterance: STT → LLM → TTS.
    Runs in a background thread.
    """
    from app.voice.pipeline import call_llm_endpoint, strip_html_tags

    try:
        # Step 1: Transcribe audio
        transcript = _transcribe_audio_bytes(audio_bytes)
        if not transcript:
            _send_json(ws, {"type": "state", "state": "listening"})
            return

        _send_json(ws, {"type": "transcript", "text": transcript})

        # Step 2: Get LLM response
        _send_json(ws, {"type": "state", "state": "thinking"})
        loop = asyncio.new_event_loop()
        try:
            ai_response = loop.run_until_complete(call_llm_endpoint(config, transcript))
        finally:
            loop.close()

        clean_response = strip_html_tags(ai_response)
        _send_json(ws, {"type": "response", "text": clean_response})

        # Step 3: Synthesize speech
        _send_json(ws, {"type": "state", "state": "speaking"})
        tts_audio = _synthesize_response(clean_response)
        if tts_audio:
            _send_json(ws, {
                "type": "audio",
                "data": base64.b64encode(tts_audio).decode("ascii"),
                "sample_rate": 22050,  # Kokoro/piper output rate
            })

        _send_json(ws, {"type": "state", "state": "listening"})

    except Exception as e:
        logger.error("[VoiceChat] Utterance processing error: %s", e, exc_info=True)
        _send_json(ws, {"type": "error", "message": "Processing failed"})
        _send_json(ws, {"type": "state", "state": "listening"})


def _transcribe_audio_bytes(audio_bytes: bytes) -> str:
    """Transcribe raw audio bytes using faster-whisper."""
    import tempfile
    import os

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        from app.utils.whisper_stt import transcribe_audio
        text = transcribe_audio(tmp_path)
        return text or ""
    except Exception as e:
        logger.error("[VoiceChat] Transcription error: %s", e)
        return ""
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _synthesize_response(text: str) -> bytes:
    """Synthesize speech from text, return raw audio bytes."""
    if not text:
        return b""

    # Try Kokoro TTS via pipecat
    try:
        from pipecat.services.kokoro import KokoroTTSService
        import asyncio

        async def _synth():
            tts = KokoroTTSService(voice="af_heart")
            # Kokoro returns audio frames; collect them
            frames = []
            async for frame in tts.run_tts(text):
                if hasattr(frame, "audio"):
                    frames.append(frame.audio)
            return b"".join(frames)

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_synth())
        finally:
            loop.close()
    except (ImportError, Exception) as e:
        logger.debug("Kokoro TTS unavailable for voice chat: %s", e)

    # Fallback: piper-tts
    try:
        from app.utils.piper_tts import synthesize_speech
        wav_buffer = synthesize_speech(text)
        if wav_buffer:
            return wav_buffer.read()
    except Exception as e:
        logger.debug("Piper TTS fallback failed: %s", e)

    return b""


def _process_audio_chunk(ws, config, audio_bytes):
    """Process a streaming audio chunk. Reserved for future real-time VAD integration."""
    # For now, streaming audio chunks are accumulated client-side.
    # The client sends a "transcribe" message with the complete utterance
    # after VAD detects end-of-speech.
    pass


def _send_json(ws, data: dict):
    """Send a JSON message over WebSocket, handling errors gracefully."""
    try:
        ws.send(json.dumps(data))
    except Exception as e:
        logger.debug("[VoiceChat] Failed to send WebSocket message: %s", e)
