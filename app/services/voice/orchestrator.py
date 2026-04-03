from typing import Iterator, Dict, Optional
from io import BytesIO

from gtts import gTTS
from langdetect import detect
from langchain_core.messages import HumanMessage

from app.utils.rag_service import chatbot
from app.utils.whisper_stt import transcribe_audio


class VoiceOrchestrator:
    """Phase-2 orchestrator scaffold for chunked assistant streaming."""

    def __init__(self, chunk_size: int = 80):
        self.chunk_size = max(20, min(int(chunk_size), 240))

    def chunk_text(self, text: str) -> Iterator[str]:
        text = str(text or '').strip()
        if not text:
            return iter(())
        return (text[i:i + self.chunk_size] for i in range(0, len(text), self.chunk_size))

    def stream_assistant_text_events(self, text: str) -> Iterator[Dict[str, str]]:
        for chunk in self.chunk_text(text):
            yield {'type': 'assistant_text_chunk', 'chunk': chunk}
        yield {'type': 'done'}

    def transcribe_file(self, file_path: str) -> Optional[str]:
        return transcribe_audio(file_path)

    def generate_assistant_text(self, *, message: str, thread_id: str) -> str:
        state = chatbot.invoke(
            {"messages": [HumanMessage(content=str(message or '').strip())]},
            config={"configurable": {"thread_id": str(thread_id)}}
        )
        messages = state.get("messages", []) if isinstance(state, dict) else []
        if not messages:
            return ""
        last = messages[-1]
        if hasattr(last, 'content'):
            return str(last.content or '').strip()
        if isinstance(last, dict):
            return str(last.get('content') or '').strip()
        return str(last).strip()

    def synthesize_tts_bytes(self, text: str) -> bytes:
        text = str(text or '').strip()
        if not text:
            return b""
        try:
            lang = detect(text)
        except Exception:
            lang = "en"
        tts = gTTS(text=text, lang=lang)
        audio = BytesIO()
        tts.write_to_fp(audio)
        audio.seek(0)
        return audio.read()
