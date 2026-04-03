# TTS / STT / STS — Full Feature Audit

**Date:** 2026-04-03
**Audited by:** Claude (AI-assisted code audit)
**Branch:** `stag_upd_abd_test`

---

## 1. Executive Summary

This document is a comprehensive audit of all speech features (Text-to-Speech, Speech-to-Text, Speech-to-Speech) in the Iqbal AI platform. The audit covers the codebase state before changes, all issues found, the improvement plan, implementation details, Pipecat research, and the resulting architecture.

**Key findings before changes:**
- STT was slow (20-40s per utterance on CPU) and hardcoded to English
- TTS used gTTS (robotic, network-dependent, rate-limited)
- Student dashboard used Chrome-only Web Speech API instead of the backend
- No feedback loop protection (mic could transcribe the AI's own voice)
- Two independent Whisper model instances wasting ~3GB RAM combined
- Dead code in RAG routes blocking audio support
- Standalone STS scripts (SeamlessM4T) were never integrated into the app
- OpenAI Realtime API endpoint existed but was incomplete (token only, no WebSocket)

---

## 2. Pre-Change State: What Existed

### 2.1 Active Frontend Templates

**`teacher_dashboard.html`** (active at `/teacher-dashboard`):
- **STT:** MediaRecorder API -> `POST /api/stt` (Whisper backend) -> fills textarea. No auto-send.
- **TTS:** `POST /api/tts` (gTTS backend) -> plays audio blob. Manual trigger.
- **Auto-TTS:** When speaker button is active, auto-reads new AI responses via `/api/tts` (line 7714).
- **Error handling:** Uses `showToast()` (good).
- **LLM endpoint:** `POST /api/rag/chat`

**`student_dashboard.html`** (active at `/student-dashboard`):
- **STT:** Browser Web Speech API (`webkitSpeechRecognition`) — Chrome/Edge only, no backend call, hardcoded `lang='en-US'`, `continuous: false`.
- **TTS:** Browser `window.speechSynthesis` (SpeechSynthesisUtterance) — client-side only, zero latency but voice quality varies by OS/browser.
- **Auto-TTS:** None. Manual click only.
- **Error handling:** Uses `alert()` for errors (poor UX).
- **LLM endpoint:** `POST /api/lessons/ask_question` via `sendLessonQAMessageInMain()`

**`chat.html`** (legacy at `/legacy/chat` only):
- Most comprehensive voice implementation with waveform visualization, recording timer, auto-send, auto-speak.
- **Not used in production.** The index route (`/`) redirects to role-specific dashboards.

### 2.2 Backend Endpoints

| Endpoint | Route File | Implementation | Status |
|---|---|---|---|
| `POST /api/stt` | `chat.py:718` | `openai-whisper` base model, CPU, `language="en"` hardcoded | Active |
| `POST /api/tts` | `chat.py:861` | gTTS + langdetect for auto language detection | Active |
| `GET /session` | `auth.py:368` | OpenAI Realtime API token generation (`gpt-4o-realtime-preview`) | Incomplete — token only |
| `POST /api/rag/chat` (audio) | `rag_routes.py:836` | Rejected all audio with 400 before transcription code could run | Broken |

### 2.3 Duplicate Whisper Loading

Two independent Whisper model instances existed:

1. **`chat.py:37-47`** — `_get_whisper_model()` — loaded `whisper.load_model("base", device="cpu")` for `/api/stt`
2. **`app/utils/whisper_stt.py:20-40`** — `_load_whisper_model()` — loaded `whisper.load_model("base", device="cpu")` for RAG routes

Each instance consumed ~1.5GB RAM. If both activated, 3GB wasted on two copies of the same model.

### 2.4 Standalone STS Scripts (Never Integrated)

| File | Model | Purpose |
|---|---|---|
| `speechtospeech.py` | `facebook/seamless-m4t-v2-large` | CLI: mic -> SeamlessM4Tv2 -> speaker |
| `speechtospeechsmall.py` | `facebook/seamless-m4t-medium` | CLI: mic -> SeamlessM4T v1/v2 -> speaker |

Both are fully functional locally but have zero connection to the Flask app. They require `sounddevice` and `torchaudio` (not in `requirements.txt`).

### 2.5 Dependencies (Before)

```
gTTS                    # Google Text-to-Speech (free, cloud, concatenative)
openai-whisper          # OpenAI Whisper (local, CPU, base model)
torch                   # PyTorch for Whisper inference
transformers            # HuggingFace (for experimental SeamlessM4T)
langdetect              # Language detection for TTS
```

---

## 3. Issues Found

### 3.1 Critical Issues

| # | Issue | Location | Impact |
|---|---|---|---|
| 1 | STT transcription takes 20-40s on CPU | `whisper_stt.py`, `chat.py` | Unusable latency for voice interaction |
| 2 | gTTS voice is robotic (concatenative synthesis) | `chat.py:877` | Poor user experience |
| 3 | Student dashboard STT is Chrome-only | `student_dashboard.html:3507` | Firefox/Safari users have no mic support |
| 4 | No feedback loop protection | Both dashboards | Mic can transcribe AI's own voice -> infinite loop |
| 5 | RAG audio blocked by dead code | `rag_routes.py:836-842` | Voice input explicitly rejected before transcription code |
| 6 | Duplicate Whisper model = 3GB RAM waste | `chat.py:37` + `whisper_stt.py:20` | OOM risk on servers |

### 3.2 Medium Issues

| # | Issue | Location | Impact |
|---|---|---|---|
| 7 | STT hardcoded to English | `chat.py:750` | Non-English audio mishandled |
| 8 | Student dashboard uses `alert()` for errors | `student_dashboard.html:5854,5911` | Bad UX, blocks UI |
| 9 | No auto-send after student STT | `student_dashboard.html:5852` | Extra click required |
| 10 | 100+ line system prompt hardcoded in auth.py | `auth.py:383-479` | Poor separation of concerns |
| 11 | OpenAI Realtime endpoint incomplete | `auth.py:368` | Token generated but no WebSocket |

### 3.3 Low Issues

| # | Issue | Location | Impact |
|---|---|---|---|
| 12 | No audio file size validation | `chat.py:728` | Large files could cause OOM |
| 13 | No rate limiting on STT/TTS endpoints | `chat.py:718,861` | Potential abuse |
| 14 | No TTS caching | `chat.py:861` | Regenerates same text repeatedly |
| 15 | gTTS requires internet connection | `chat.py:877` | Fails offline |

---

## 4. The Core Problem: Why It Didn't Feel Like STS

The "voice mode" was actually three disconnected sequential HTTP requests:

```
User clicks mic -> Web Speech API (browser, Google cloud) -> fills textarea
User clicks Send -> LLM response (3-8s)
User clicks speaker -> POST /api/tts -> gTTS (2-5s network) -> MP3 plays
User clicks mic again -> repeat

Total clicks per turn: 3
Total latency: 10-20s
```

Natural STS requires:
- **VAD** (voice activity detection) — no "click to start/stop"
- **Streaming STT** — see transcript while speaking
- **Streaming LLM** — response feeds directly into TTS
- **Streaming TTS** — first syllable plays before generation finishes
- **Automatic turn-taking** — mic reopens after AI finishes speaking
- **End-to-end latency < 2 seconds**

---

## 5. Improvement Plan: Path A + Path B

### Path A: Fix the Existing Pipeline

1. **A1 — STT upgrade:** `openai-whisper` -> `faster-whisper` (4-8x speedup, int8 quantization)
2. **A2 — TTS upgrade:** `gTTS` -> `piper-tts` (local neural VITS voices)
3. **A3 — Student STT fix:** Web Speech API -> MediaRecorder + `/api/stt`
4. **A4 — Student TTS:** Left as browser `speechSynthesis` (zero cost, zero latency)
5. **A5 — Feedback loop protection:** State machine for voice I/O in both dashboards
6. **A6 — RAG dead code:** Commented out the 400 rejection block

### Path B: Natural STS with Pipecat

New "Voice Chat" mode — additive feature alongside existing buttons.

Architecture: Embedded in Flask via `flask-sock` (WebSocket over existing gunicorn gthread workers).

Pipeline: `Silero VAD + SmartTurn -> faster-whisper STT -> LLM (via existing API) -> Kokoro TTS -> Audio out`

---

## 6. Pipecat Research: Provider Ecosystem

### Why Pipecat

Pipecat (`pipecat-ai`) is an open-source Python framework by Daily.co for real-time voice AI pipelines. It provides:
- Composable pipeline architecture (frame processors)
- Built-in VAD, STT, LLM, TTS adapters
- Pluggable — swap any component with a one-line change
- Handles turn-taking, interruptions, streaming at each stage
- 500-800ms typical voice-to-voice latency

### LLM Providers (30+)

| Provider | Service Class | Notes |
|---|---|---|
| **Groq** (QWEN3) | `GroqLLMService` | Direct support for `qwen/qwen3-32b` |
| **OpenAI** | `OpenAILLMService` | GPT-4o, plus any OpenAI-compatible endpoint via `base_url` |
| **Anthropic / Claude** | `AnthropicLLMService` | All Claude models |
| **Google Gemini** | `GoogleLLMService` | Gemini models, also Gemini Live for native STS |
| **Ollama** | `OllamaLLMService` | Local models |
| **vLLM** | `OpenAILLMService` with `base_url` | Any model served via vLLM |
| Others | Various | AWS Bedrock, Azure, DeepSeek, Mistral, Together AI, etc. |

### STT Providers

| Provider | Type | Notes |
|---|---|---|
| **faster-whisper** | Local | CPU/CUDA, models from tiny to large-v3-turbo |
| Deepgram | Cloud | First-class support |
| Groq Whisper | Cloud | Groq-hosted Whisper |
| OpenAI Whisper | Cloud | Via OpenAI API |

### TTS Providers

| Provider | Type | Notes |
|---|---|---|
| **Kokoro** | Local | Cross-platform, ONNX, <0.3s latency, auto-downloads models |
| **Piper** | Local | Linux-only, VITS neural voices |
| ElevenLabs | Cloud | Premium quality |
| OpenAI TTS | Cloud | Via API |
| 25+ others | Various | Cartesia, Deepgram, Azure, AWS Polly, etc. |

### VAD

| Provider | Notes |
|---|---|
| **Silero VAD** | Local, ONNX, ~1.8MB model, configurable confidence/timing |
| **SmartTurn** | Pipecat's own model — distinguishes real turn endings from mid-thought pauses |

### Future-Proofing

Swapping any component is a one-line service class change. If the core LLM changes from QWEN3 to Claude, OpenAI, or Gemini, the Pipecat pipeline just needs the service class updated. No restructuring required.

For the initial implementation, the pipeline calls the existing Flask API, making it completely model-agnostic — whatever the Flask app uses, Pipecat just sees text in / text out.

---

## 7. Post-Change Architecture

### Existing Pipeline (Path A)

```
Teacher Dashboard:
  Mic -> MediaRecorder (webm) -> POST /api/stt
    -> faster-whisper (base, CPU, int8, auto-detect lang)
    -> {"text": "..."} -> fills textarea
    -> User clicks Send -> POST /api/rag/chat -> LLM response
    -> Auto-TTS (if speaker active): POST /api/tts -> piper WAV -> Audio plays
    -> Feedback loop guard: mic disabled during playback

Student Dashboard:
  Mic -> MediaRecorder (webm) -> POST /api/stt
    -> faster-whisper -> {"text": "..."} -> fills textarea -> auto-sends
    -> POST /api/lessons/ask_question -> LLM response
    -> Speaker button: browser speechSynthesis (unchanged)
    -> Feedback loop guard: mic disabled during speech
```

### Voice Chat Mode (Path B)

```
User clicks headset button -> Opens modal
  -> WebSocket connects to /ws/voice
  -> Sends config (role, thread_id, etc.)
  -> State: LISTENING
    -> MediaRecorder captures audio
    -> User stops speaking (manual or VAD)
    -> Audio blob sent as base64 via WebSocket
  -> State: THINKING
    -> Server: faster-whisper transcribes
    -> Server: calls existing Flask LLM API
    -> Server: Kokoro/piper synthesizes response
  -> State: SPEAKING
    -> Audio blob sent back to browser
    -> Browser plays audio
  -> State: LISTENING (auto-restart)
    -> Conversation loop continues
  -> User clicks X -> WebSocket closes
```

### Deployment Architecture

```
nginx (reverse proxy)
  |
  |-- / (all routes)     -> gunicorn gthread (port 5000, 9 workers x 8 threads)
  |-- /ws/ (WebSocket)   -> same gunicorn (flask-sock hijacks WSGI connection)
  |
  Flask app
    |-- /api/stt          -> faster-whisper (shared model in whisper_stt.py)
    |-- /api/tts          -> piper-tts (with gTTS fallback)
    |-- /ws/voice         -> flask-sock WebSocket -> Pipecat pipeline
    |-- /api/rag/chat     -> LLM (unchanged)
    |-- /api/lessons/...  -> LLM (unchanged)
```

---

## 8. Files Inventory

### Modified Files

| File | Lines Changed | Risk Level |
|---|---|---|
| `app/utils/whisper_stt.py` | ~70 (rewritten) | Low — same interface |
| `app/routes/chat.py` | ~100 (STT + TTS) | Low — same API contracts |
| `app/routes/rag_routes.py` | ~15 (commented) | Very low |
| `templates/teacher_dashboard.html` | ~75 (guards) | Low — additive guards |
| `templates/student_dashboard.html` | ~240 (STT + guards) | Medium — mic button changed |
| `app/__init__.py` | ~5 (blueprint reg) | Very low |
| `requirements.txt` | ~15 | Low |

### New Files

| File | Lines | Purpose |
|---|---|---|
| `app/utils/piper_tts.py` | ~100 | Piper TTS utility with auto model download |
| `app/voice/__init__.py` | ~15 | Package init |
| `app/voice/pipeline.py` | ~170 | Pipecat pipeline + LLM bridge |
| `app/voice/routes.py` | ~230 | WebSocket voice chat endpoint |
| `static/js/voice_chat.js` | ~320 | Client-side voice chat UI + audio |
| `app/voice/docs/` | 3 files | Documentation (this audit, changes, setup guide) |

---

## 9. Before vs After Comparison

| Metric | Before | After (Path A) | After (Path B) |
|---|---|---|---|
| **STT latency** | 20-40s | 2-5s | 2-5s (same engine) |
| **STT language** | English only | Auto-detect | Auto-detect |
| **TTS quality** | Robotic (gTTS) | Neural (piper) | Neural (Kokoro) |
| **TTS network** | Required (Google) | Offline | Offline |
| **Student STT** | Chrome only | All browsers | All browsers |
| **Feedback loop** | No protection | Full state machine | Managed by pipeline |
| **Clicks per turn** | 3 (mic, send, speaker) | 2 (mic, send) | 0 (continuous) |
| **End-to-end latency** | 10-20s | 5-10s | 3-8s (target <2s) |
| **RAM (Whisper)** | ~3GB (2 instances) | ~1.5GB (1 instance) | Shared |
| **New dependencies** | 0 | 2 (faster-whisper, piper) | 4 (+pipecat, flask-sock) |
