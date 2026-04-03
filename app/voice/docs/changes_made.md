# TTS / STT / STS — Changes Made

**Date:** 2026-04-03
**Branch:** `stag_upd_abd_test`

---

## Path A — Fix & Upgrade the Existing Pipeline

### A1: Upgrade STT (openai-whisper to faster-whisper)

| File | Change |
|---|---|
| `app/utils/whisper_stt.py` | Replaced `openai-whisper` (base model, ~20-40s on CPU) with `faster-whisper` (CTranslate2, int8 quantization, ~2-5s). Old implementation commented out with explanation. Same function signature (`transcribe_audio()`) preserved. |
| `app/routes/chat.py` (lines 22-47) | Removed duplicate Whisper model loader (`_get_whisper_model()`) that wasted ~1.5GB RAM. `/api/stt` now imports `transcribe_audio` from the shared `whisper_stt.py` module. Old code commented out. |
| `app/routes/chat.py` (line 750) | Removed hardcoded `language="en"`. faster-whisper now auto-detects language. |

**API contract preserved:** `POST /api/stt` still accepts `multipart/form-data` with `audio` field, still returns `{"text": "..."}`.

---

### A2: Upgrade TTS (gTTS to piper-tts)

| File | Change |
|---|---|
| `app/utils/piper_tts.py` | **New file.** Piper TTS utility — loads `en_US-lessac-medium` voice model, synthesizes to WAV. Auto-downloads model on first use. |
| `app/routes/chat.py` (lines 839-910) | `/api/tts` now tries piper-tts first (local, neural, no network). Falls back to gTTS if piper is unavailable. Old gTTS imports moved to lazy fallback inside the function. |
| `app/routes/chat.py` (lines 14-15) | Top-level `from gtts import gTTS` and `from langdetect import detect` commented out (moved to lazy import in fallback path). |

**API contract preserved:** `POST /api/tts` still accepts `{"text": "..."}`. Returns `audio/wav` when piper is available, `audio/mpeg` when falling back to gTTS. Both are playable by the browser's `Audio()` element.

---

### A3: Fix Student Dashboard STT

| File | Change |
|---|---|
| `templates/student_dashboard.html` (lines 3507-3542) | Commented out `webkitSpeechRecognition` initialization block. Added explanation comment. |
| `templates/student_dashboard.html` (lines 5852-5916) | Commented out old `toggleVoiceInput()` (Web Speech API). Replaced with MediaRecorder-based implementation that: records audio, sends to `POST /api/stt`, fills textarea with transcript, and **auto-sends** the message. |
| `templates/student_dashboard.html` (line 3225) | Added `mediaRecorder`, `audioChunks`, `mediaStream`, `isSpeaking` global variables. |

**Teacher dashboard:** No STT changes needed — it already used MediaRecorder + `/api/stt`.

---

### A5: Prevent Mic/Speaker Feedback Loop

| File | Change |
|---|---|
| `templates/teacher_dashboard.html` (line 3404) | Added `isSpeaking` state variable. |
| `templates/teacher_dashboard.html` (`toggleVoiceInput()`) | Added `if (isSpeaking) return` guard. Added `echoCancellation: true, noiseSuppression: true` to getUserMedia. |
| `templates/teacher_dashboard.html` (`toggleTextToSpeech()`) | Added: `isSpeaking = true` on play, `stopVoiceInput()`, disable mic button. On ended/error: `isSpeaking = false`, re-enable mic. |
| `templates/teacher_dashboard.html` (`addAssistantMessage()` auto-TTS block) | Same guards: lock mic before auto-TTS plays, unlock on ended/error. |
| `templates/student_dashboard.html` (`toggleVoiceInput()`) | Added `if (isSpeaking) return` guard. |
| `templates/student_dashboard.html` (`toggleTextToSpeech()`) | Added: `isSpeaking = true` on speak, disable mic. `utterance.onend`/`onerror`: `isSpeaking = false`, re-enable mic. Replaced `alert()` with `showToast()`. |

**State flow:** `IDLE -> LISTENING -> TRANSCRIBING -> SENDING -> SPEAKING -> IDLE`. Mic and speaker never overlap.

---

### A6: Comment Out Dead RAG Audio Code

| File | Change |
|---|---|
| `app/routes/rag_routes.py` (lines 836-842) | Commented out the early `400` rejection block that returned `VOICE_NOT_SUPPORTED` before the transcription code could run. Added comment explaining it was shadowing the code below. |

---

### Dependencies

| File | Change |
|---|---|
| `requirements.txt` | Added: `faster-whisper`, `piper-tts`, `pipecat-ai[silero,whisper,kokoro]`, `flask-sock`. Commented out: `openai-whisper`, `gTTS`. |

---

## Path B — New Voice Chat Mode (Pipecat)

### New Files Created

| File | Purpose |
|---|---|
| `app/voice/__init__.py` | Package init with architecture documentation. |
| `app/voice/pipeline.py` | Pipecat pipeline definition: VAD + STT + LLM bridge + TTS. The `LLMBridgeProcessor` routes through existing Flask API endpoints (`/api/rag/chat` for teacher, `/api/lessons/ask_question` for student). |
| `app/voice/routes.py` | Flask blueprint with WebSocket endpoint at `/ws/voice` via flask-sock. Handles session lifecycle: config, audio streaming, transcription, LLM call, TTS synthesis. |
| `app/utils/piper_tts.py` | Piper TTS utility (also used by Path A's `/api/tts`). |
| `static/js/voice_chat.js` | Client-side voice chat: WebSocket connection, MediaRecorder audio capture, audio playback, modal UI with state visualization (listening/thinking/speaking). |

### Modified Files

| File | Change |
|---|---|
| `app/__init__.py` (lines 293-295) | Registered voice blueprint + initialized flask-sock via `init_voice_websocket(app)`. |
| `templates/teacher_dashboard.html` (line 2943) | Added headset button: `startVoiceChat({ role: 'teacher', ... })`. Added `<script>` tag for `voice_chat.js`. |
| `templates/student_dashboard.html` (line 3004) | Added headset button: `startVoiceChat({ role: 'student', ... })`. Added `<script>` tag for `voice_chat.js`. |

---

## What Was NOT Changed

- Teacher dashboard STT flow (already MediaRecorder + `/api/stt`)
- Teacher dashboard TTS flow (`/api/tts`)
- Teacher dashboard auto-TTS on AI response
- Student dashboard TTS (stays browser `speechSynthesis`)
- `sendMessage()` / `sendLessonQAMessageInMain()` logic
- All LLM/RAG/lesson/prompt logic
- Auth/admin/RBAC
- Database models
- `chat.html` (legacy, untouched)
- gunicorn worker config (stays `gthread`)
- nginx config (existing `/ws/` block covers voice WebSocket)
- docker-compose.yml (no new containers)
