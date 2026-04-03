"""
Voice chat package — real-time speech-to-speech conversation via Pipecat.

This package provides a WebSocket-based voice chat mode that runs alongside
the existing text chat. It uses:
  - Silero VAD for voice activity detection
  - faster-whisper for speech-to-text
  - Kokoro TTS for text-to-speech (local, ONNX-based)
  - The existing LLM endpoints (/api/rag/chat, /api/lessons/ask_question) for responses

Architecture:
  Browser ←WebSocket→ Flask (flask-sock) → Pipecat pipeline → LLM → TTS → Browser
"""
