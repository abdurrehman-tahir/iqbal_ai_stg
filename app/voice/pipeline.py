"""
Pipecat voice pipeline for real-time speech-to-speech conversation.

Pipeline: Audio In → Silero VAD → faster-whisper STT → LLM (via HTTP) → Kokoro TTS → Audio Out

This module defines the pipeline configuration and the custom LLM processor
that routes through the existing Flask API endpoints.
"""
import asyncio
import json
import logging
import os
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# Audio configuration
SAMPLE_RATE = 16000
CHANNELS = 1

# Configurable via ENV variables (see app/config.py for docs):
#   VOICE_CHAT_TTS_VOICE       — Kokoro voice name (e.g. af_heart, am_adam)
#   VOICE_CHAT_LLM_TIMEOUT     — seconds to wait for LLM response
#   VOICE_CHAT_TTS_SAMPLE_RATE — TTS output sample rate
VOICE_CHAT_TTS_VOICE = os.environ.get("VOICE_CHAT_TTS_VOICE", "af_heart")
VOICE_CHAT_LLM_TIMEOUT = int(os.environ.get("VOICE_CHAT_LLM_TIMEOUT", "120"))
VOICE_CHAT_TTS_SAMPLE_RATE = int(os.environ.get("VOICE_CHAT_TTS_SAMPLE_RATE", "22050"))


class VoicePipelineConfig:
    """Configuration for a voice chat session."""

    def __init__(
        self,
        role: str = "student",
        session_cookie: Optional[str] = None,
        thread_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        lesson_qa_id: Optional[str] = None,
        base_url: str = "http://127.0.0.1:5000",
    ):
        self.role = role
        self.session_cookie = session_cookie
        self.thread_id = thread_id
        self.conversation_id = conversation_id
        self.lesson_qa_id = lesson_qa_id
        self.base_url = base_url

    @property
    def llm_endpoint(self) -> str:
        if self.role == "teacher":
            return f"{self.base_url}/api/rag/chat"
        return f"{self.base_url}/api/lessons/ask_question"


async def call_llm_endpoint(config: VoicePipelineConfig, text: str) -> str:
    """
    Call the existing Flask LLM endpoint with transcribed text.
    Returns the AI response text.

    This routes through the same API the dashboards use, so all business
    logic, context management, rate limiting, and prompt engineering is reused.
    """
    headers = {
        "Content-Type": "application/json",
    }
    if config.session_cookie:
        headers["Cookie"] = config.session_cookie

    if config.role == "teacher":
        payload = {
            "message": text,
            "thread_id": config.thread_id,
            "conversation_id": config.conversation_id,
        }
    else:
        payload = {
            "message": text,
            "lesson_qa_id": config.lesson_qa_id,
        }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                config.llm_endpoint,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=VOICE_CHAT_LLM_TIMEOUT),
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error("LLM endpoint returned %d: %s", resp.status, error_text)
                    return "I'm sorry, I couldn't process that. Please try again."

                data = await resp.json()

                # Update thread/conversation IDs from response
                if data.get("thread_id"):
                    config.thread_id = data["thread_id"]
                if data.get("conversation_id"):
                    config.conversation_id = data["conversation_id"]

                return data.get("message", "I didn't get a response. Please try again.")

    except asyncio.TimeoutError:
        logger.error("LLM endpoint timed out")
        return "The response took too long. Please try again."
    except Exception as e:
        logger.exception("Error calling LLM endpoint: %s", e)
        return "Something went wrong. Please try again."


def strip_html_tags(text: str) -> str:
    """Remove HTML tags from LLM response for TTS."""
    import re
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[#*_~`>|=\[\]{}()^]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


async def create_pipeline(config: VoicePipelineConfig):
    """
    Create and return a Pipecat pipeline for voice chat.

    The pipeline is:
      Transport (WebSocket audio) → Silero VAD → faster-whisper STT
        → Custom LLM processor → Kokoro TTS → Transport out

    Returns the pipeline and transport objects.
    """
    try:
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.pipeline.task import PipelineParams, PipelineTask
        from pipecat.services.whisper import WhisperSTTService
        from pipecat.audio.vad.silero import SileroVADAnalyzer
        from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
        from pipecat.frames.frames import (
            TextFrame,
            TranscriptionFrame,
            TTSSpeakFrame,
            Frame,
        )
    except ImportError as e:
        logger.error("Pipecat dependencies not installed: %s", e)
        raise RuntimeError(
            "pipecat-ai not installed. Run: pip install 'pipecat-ai[silero,whisper,kokoro]'"
        ) from e

    # STT: faster-whisper (local)
    stt = WhisperSTTService(model_size="base")

    # VAD: Silero
    vad = SileroVADAnalyzer(
        sample_rate=SAMPLE_RATE,
    )

    # TTS: Try Kokoro first, fall back to a simple approach
    tts = None
    try:
        from pipecat.services.kokoro import KokoroTTSService
        tts = KokoroTTSService(voice=VOICE_CHAT_TTS_VOICE)
        logger.info("Using Kokoro TTS for voice pipeline")
    except (ImportError, Exception) as e:
        logger.warning("Kokoro TTS unavailable (%s), TTS will be disabled in voice chat", e)

    # Custom processor: takes STT transcription, calls LLM, emits TTS text
    class LLMBridgeProcessor(FrameProcessor):
        """Bridges STT output to the Flask LLM endpoint and feeds response to TTS."""

        def __init__(self, voice_config: VoicePipelineConfig):
            super().__init__()
            self._config = voice_config

        async def process_frame(self, frame: Frame, direction: FrameDirection):
            await super().process_frame(frame, direction)

            if isinstance(frame, TranscriptionFrame):
                user_text = frame.text.strip()
                if not user_text:
                    return

                logger.info("[VoiceChat] User said: %s", user_text)

                # Call the existing LLM endpoint
                ai_response = await call_llm_endpoint(self._config, user_text)
                clean_response = strip_html_tags(ai_response)

                logger.info("[VoiceChat] AI response: %s", clean_response[:100])

                # Send to TTS
                if tts and clean_response:
                    await self.push_frame(TTSSpeakFrame(text=clean_response))
                else:
                    await self.push_frame(TextFrame(text=clean_response))
            else:
                await self.push_frame(frame, direction)

    llm_bridge = LLMBridgeProcessor(config)

    # Build pipeline components
    pipeline_components = [stt, llm_bridge]
    if tts:
        pipeline_components.append(tts)

    pipeline = Pipeline(pipeline_components)

    return pipeline, vad
