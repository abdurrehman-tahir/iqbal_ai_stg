# TTS / STT / STS — Setup, Run & Testing Guide

**Date:** 2026-04-03
**Branch:** `stag_upd_abd_test`

---

## 1. Environment Variables Reference

All voice/speech ENV variables, their meaning, and how to tweak them. Add these to your `.env` file or set them in `docker-compose.yml`.

### STT (Speech-to-Text) — faster-whisper

| Variable | Default | Description |
|---|---|---|
| `WHISPER_MODEL_SIZE` | `base` | Whisper model size. Options: `tiny` (fastest, least accurate), `base`, `small`, `medium`, `large-v3`, `large-v3-turbo` (best quality, slowest). `base` is the sweet spot for CPU. Use `large-v3-turbo` on GPU for best quality. |
| `WHISPER_DEVICE` | `cpu` | Inference device. `cpu` for CPU-only servers. `cuda` if you have an NVIDIA GPU with CUDA installed. |
| `WHISPER_COMPUTE_TYPE` | `int8` | Quantization type. `int8` = fastest on CPU, lowest memory. `float16` = GPU only, good balance. `float32` = highest accuracy, most RAM. |

**Tuning tips:**
- On the staging server (16 vCPUs, 64GB RAM, no GPU): keep defaults (`base`, `cpu`, `int8`). This gives ~2-5s transcription for a 5s clip.
- If you add a GPU later: set `WHISPER_DEVICE=cuda` and `WHISPER_COMPUTE_TYPE=float16`. Consider `WHISPER_MODEL_SIZE=large-v3-turbo` for best quality.
- For faster but less accurate results: `WHISPER_MODEL_SIZE=tiny`.

### TTS (Text-to-Speech) — piper-tts

| Variable | Default | Description |
|---|---|---|
| `PIPER_VOICE` | `en_US-lessac-medium` | Piper voice model name. Format: `{lang}_{REGION}-{speaker}-{quality}`. Browse voices: https://rhasspy.github.io/piper-samples/ |
| `PIPER_MODELS_DIR` | `<project_root>/piper_models` | Directory where voice model `.onnx` files are stored. Models auto-download on first use. |

**Available voices (examples):**
- `en_US-lessac-medium` — US English, female, medium quality (default)
- `en_US-amy-medium` — US English, female
- `en_GB-alan-medium` — British English, male
- `en_US-ryan-medium` — US English, male

**Tuning tips:**
- Change `PIPER_VOICE` to any voice from the piper samples page. The model auto-downloads on first `/api/tts` call.
- On macOS (local dev), piper-tts may not be available (Linux binary). The code falls back to gTTS automatically.
- Set `PIPER_MODELS_DIR` to a persistent volume in Docker so models survive container rebuilds.

### Voice Chat (Pipecat STS Pipeline)

| Variable | Default | Description |
|---|---|---|
| `VOICE_CHAT_TTS_VOICE` | `af_heart` | Kokoro TTS voice for voice chat mode. Options: `af_heart`, `af_bella`, `af_nicole`, `am_adam`, `am_michael`, etc. |
| `VOICE_CHAT_LLM_TIMEOUT` | `120` | Seconds to wait for LLM response during voice chat before timing out. |
| `VOICE_CHAT_TTS_SAMPLE_RATE` | `22050` | Audio sample rate for TTS output. Kokoro outputs 24000Hz; piper outputs 22050Hz. Match this to whichever TTS is active. |

---

## 2. Local Development Setup (macOS)

### Prerequisites

- Python 3.10+ (tested with 3.13)
- ffmpeg (`brew install ffmpeg`) — required by faster-whisper for audio decoding
- PostgreSQL running locally (or SQLite via `DATABASE_URL=sqlite:///instance/chatbot.db`)
- A `.env` file in the project root

### Step 1: Install Dependencies

```bash
cd /path/to/iqbal_ai_stg

# Install base dependencies
pip install -r requirements.txt

# Note: piper-tts may fail on macOS (it ships Linux binaries).
# This is expected — the code falls back to gTTS automatically.
# If pip install fails for piper-tts, install everything else:
pip install faster-whisper flask-sock "pipecat-ai[silero,whisper,kokoro]"
```

### Step 2: Set ENV Variables

Add to your `.env` file (or export in your shell):

```bash
# --- Voice / Speech (optional — all have sensible defaults) ---
WHISPER_MODEL_SIZE=base
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
# PIPER_VOICE=en_US-lessac-medium    # Won't work on macOS; gTTS fallback is used
# PIPER_MODELS_DIR=                   # Leave empty for auto
VOICE_CHAT_TTS_VOICE=af_heart
VOICE_CHAT_LLM_TIMEOUT=120
VOICE_CHAT_TTS_SAMPLE_RATE=22050
```

### Step 3: Run the App

```bash
python run.py
# or with a specific port:
python run.py 5000
```

The app starts at `http://localhost:5000`. The voice WebSocket is at `ws://localhost:5000/ws/voice`.

### Step 4: First-Run Model Downloads

On the first request to each service, models download automatically:
- **faster-whisper** (`/api/stt`): Downloads Whisper `base` model (~150MB). Takes ~30s on first call.
- **piper-tts** (`/api/tts`): Downloads piper voice model (~65MB). Skipped on macOS (falls back to gTTS).
- **Kokoro TTS** (voice chat): Downloads ONNX model on first voice chat session.

After first download, models are cached and load instantly.

---

## 3. Staging Server Setup (104.219.55.160)

### Server Details

- **OS:** Ubuntu (Docker)
- **Hardware:** 16 vCPUs, 64GB RAM
- **Stack:** docker-compose (nginx + Flask + Postgres + Milvus + Redis + Celery)
- **Deploy:** git pull + docker-compose rebuild

### Step 1: SSH and Pull Latest Code

```bash
ssh root@104.219.55.160
cd /path/to/iqbal_ai_stg    # adjust to actual project path on server
git pull origin stag_upd_abd_test
```

### Step 2: Add Voice ENV Variables to docker-compose.yml

In `docker-compose.yml`, add these to the `flask_app1` service `environment` section:

```yaml
# Voice / Speech
- WHISPER_MODEL_SIZE=base
- WHISPER_DEVICE=cpu
- WHISPER_COMPUTE_TYPE=int8
- PIPER_VOICE=en_US-lessac-medium
- PIPER_MODELS_DIR=/app/piper_models
- VOICE_CHAT_TTS_VOICE=af_heart
- VOICE_CHAT_LLM_TIMEOUT=120
- VOICE_CHAT_TTS_SAMPLE_RATE=22050
```

**Note:** `PIPER_MODELS_DIR=/app/piper_models` ensures models are stored inside the `/app` volume mount, surviving container restarts. Since `docker-compose.yml` mounts `.:/app`, the `piper_models/` directory will persist on the host.

### Step 3: Rebuild and Restart

```bash
docker-compose build flask_app1
docker-compose up -d flask_app1
```

Or to rebuild everything:

```bash
docker-compose up -d --build
```

### Step 4: Verify Startup Logs

```bash
docker-compose logs -f flask_app1 2>&1 | grep -i -E "whisper|piper|voice|kokoro|flask-sock"
```

Expected log lines on healthy startup:

```
Voice chat WebSocket registered at /ws/voice
```

On first STT request:

```
Loaded faster-whisper model: base (device=cpu, compute_type=int8)
```

On first TTS request:

```
Downloading piper voice model: en_US-lessac-medium.onnx
Downloaded: /app/piper_models/en_US-lessac-medium.onnx
Loaded piper voice: en_US-lessac-medium
```

### Infrastructure Notes

- **nginx**: Already configured for WebSocket proxying at `/ws/` (see `nginx.conf` lines 39-50). No changes needed.
- **gunicorn**: Uses `gthread` workers (9 workers x 8 threads = 72 slots). `flask-sock` hijacks one thread per active voice chat session. No worker config changes needed.
- **ffmpeg**: Already installed in the Docker image (`Dockerfile` line 9). Required by faster-whisper.

---

## 4. Testing Each Change

### 4.1 Test STT — faster-whisper (Path A1)

**What changed:** `openai-whisper` replaced by `faster-whisper` (4-8x faster, auto language detection).

#### Via UI (Teacher Dashboard)

1. Go to `/teacher-dashboard`
2. Click the microphone button
3. Speak for 3-5 seconds
4. Click the microphone button again to stop
5. **Expected:** Transcript appears in the text input within 2-5 seconds (was 20-40s before)

#### Via UI (Student Dashboard)

1. Go to `/student-dashboard`
2. Click the microphone button
3. Speak for 3-5 seconds
4. Click the microphone button again to stop
5. **Expected:** Transcript appears in the text input and the message auto-sends

#### Via curl (API)

```bash
# Record a short audio clip (or use any .webm/.wav/.mp3 file)
curl -X POST http://localhost:5000/api/stt \
  -F "audio=@test_audio.webm" \
  -H "Cookie: session=YOUR_SESSION_COOKIE"

# Expected response:
# {"text": "whatever you said in the audio"}
```

#### Via Logs

Watch for these log lines:

```
Loaded faster-whisper model: base (device=cpu, compute_type=int8)
```

If you see `openai-whisper` or `import whisper` in logs, the old code is still running.

**Timing check:** The `/api/stt` response should complete in 2-5 seconds for a 5-second clip on CPU. If it takes >10s, check `WHISPER_MODEL_SIZE` (use `tiny` for faster results).

---

### 4.2 Test TTS — piper-tts (Path A2)

**What changed:** gTTS (robotic, cloud) replaced by piper-tts (neural, local). gTTS remains as automatic fallback.

#### Via UI (Teacher Dashboard)

1. Go to `/teacher-dashboard`
2. Send a message to the AI
3. Click the speaker button on the AI response
4. **Expected:** Natural-sounding voice plays the response. On macOS, you'll hear gTTS (robotic) because piper is Linux-only.

#### Via curl (API)

```bash
curl -X POST http://localhost:5000/api/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, this is a test of the text to speech system."}' \
  -H "Cookie: session=YOUR_SESSION_COOKIE" \
  --output test_output.wav

# Play the result:
# macOS: afplay test_output.wav
# Linux: aplay test_output.wav
```

#### Via Logs

**Piper active (staging/Linux):**
```
Loaded piper voice: en_US-lessac-medium
```

**Piper unavailable, gTTS fallback (macOS):**
```
piper-tts not installed: ... Falling back to gTTS.
```

**How to tell which TTS is running:**
- Check the `Content-Type` header in the response: `audio/wav` = piper, `audio/mpeg` = gTTS fallback.

---

### 4.3 Test Student STT Fix (Path A3)

**What changed:** Chrome-only Web Speech API replaced by MediaRecorder + `/api/stt`. Works in all browsers. Auto-sends after transcription.

#### Via UI (Firefox or Safari — the real test)

1. Open `/student-dashboard` in **Firefox** or **Safari**
2. Click the microphone button
3. Speak a question
4. Click the microphone button to stop
5. **Expected:** Transcript fills the input AND the message auto-sends (no need to click Send)
6. **Before this change:** Firefox/Safari showed an error or nothing happened

#### Via UI (Chrome — regression test)

1. Open `/student-dashboard` in Chrome
2. Same test as above
3. **Expected:** Same behavior — works the same as before but now uses the backend API instead of Web Speech API

---

### 4.4 Test Feedback Loop Protection (Path A5)

**What changed:** Mic and speaker never overlap. State machine prevents the AI's TTS audio from being captured by the mic and re-transcribed.

#### Teacher Dashboard Test

1. Go to `/teacher-dashboard`
2. Enable auto-TTS: click the speaker/volume button so it's active (highlighted)
3. Click the mic button and speak a message
4. Stop recording — the message sends
5. **Wait for the AI response** — it should auto-play via TTS
6. **While TTS is playing:**
   - The mic button should appear **disabled** (greyed out)
   - Clicking the mic button should do nothing
7. **After TTS finishes:**
   - The mic button should re-enable
   - No phantom message should appear (i.e., the AI's own voice was NOT transcribed)

#### Student Dashboard Test

1. Go to `/student-dashboard`
2. Send a message and click the speaker button to hear the response
3. **While speech is playing:**
   - Click the mic button — it should do nothing
4. **After speech ends:**
   - Mic button re-enables

**What to watch for:** If you see a second message appear that looks like a transcript of what the AI just said, the feedback loop protection is broken.

---

### 4.5 Test RAG Audio Fix (Path A6)

**What changed:** Dead code in `rag_routes.py` that rejected all audio with 400 is now commented out.

#### Via curl

```bash
# Send an audio file to the RAG chat endpoint
curl -X POST http://localhost:5000/api/rag/chat \
  -F "audio=@test_audio.webm" \
  -F "thread_id=test-thread" \
  -H "Cookie: session=YOUR_SESSION_COOKIE"

# Expected: 200 with AI response (not a 400 VOICE_NOT_SUPPORTED error)
```

**Before this change:** This always returned `400 VOICE_NOT_SUPPORTED`.

---

### 4.6 Test Voice Chat Mode (Path B)

**What changed:** New "Voice Chat" button (headset icon) opens a WebSocket-based continuous conversation mode.

#### Via UI (Teacher Dashboard)

1. Go to `/teacher-dashboard`
2. Look for the **headset button** (near the mic/speaker buttons)
3. Click it — a voice chat modal should open
4. **Expected states:**
   - Modal opens with "Connecting..." then switches to "Listening..."
   - Speak into your mic
   - Click the mic button in the modal (or stop speaking — if VAD is active, it auto-detects)
   - State changes to "Thinking..." while the AI processes
   - State changes to "Speaking..." and audio plays
   - State returns to "Listening..." automatically
5. Click the X or phone-hangup button to close

#### Via UI (Student Dashboard)

Same test as teacher — the headset button is present on both dashboards.

#### Via Browser DevTools (WebSocket)

1. Open DevTools → Network → WS tab
2. Click the headset button
3. You should see a WebSocket connection to `/ws/voice`
4. Messages flowing:
   - Client sends: `{"type": "config", "role": "teacher", ...}`
   - Server sends: `{"type": "state", "state": "listening"}`
   - Client sends: `{"type": "transcribe", "data": "<base64 audio>"}`
   - Server sends: `{"type": "transcript", "text": "..."}`
   - Server sends: `{"type": "state", "state": "thinking"}`
   - Server sends: `{"type": "response", "text": "..."}`
   - Server sends: `{"type": "audio", "data": "<base64>"}`
   - Server sends: `{"type": "state", "state": "listening"}`

#### Via Logs

```bash
# Watch for voice chat activity
docker-compose logs -f flask_app1 2>&1 | grep "VoiceChat"
```

Expected:
```
[VoiceChat] Session configured: role=teacher
[VoiceChat] User said: <transcript>
[VoiceChat] AI response: <first 100 chars>
[VoiceChat] Session ended
```

**Troubleshooting voice chat:**
- If WebSocket fails to connect: check that nginx proxies `/ws/` correctly (see `nginx.conf` lines 39-50)
- If transcription is empty: check that mic permissions are granted in the browser
- If audio doesn't play back: check browser console for `[VoiceChat] Playback error` messages
- If LLM times out: increase `VOICE_CHAT_LLM_TIMEOUT` (default 120s)

---

## 5. Quick Verification Checklist

Run through this after deploying:

| # | Test | Command / Action | Expected |
|---|---|---|---|
| 1 | STT loads | Check startup logs for `faster-whisper` | `Loaded faster-whisper model: base` |
| 2 | TTS loads | First `/api/tts` call | `Loaded piper voice: en_US-lessac-medium` (Linux) or gTTS fallback (macOS) |
| 3 | Voice WS registered | Check startup logs | `Voice chat WebSocket registered at /ws/voice` |
| 4 | STT speed | Record 5s audio on teacher dashboard | Transcript appears in < 5s |
| 5 | Student STT works in Firefox | Open student dashboard in Firefox, use mic | Transcript fills input and auto-sends |
| 6 | No feedback loop | Enable auto-TTS on teacher, send voice message | Mic disabled during playback, no echo message |
| 7 | Voice chat opens | Click headset button | Modal opens, WebSocket connects |
| 8 | Voice chat round-trip | Speak in voice chat modal | Hear AI response, auto-returns to listening |

---

## 6. Rollback

All old code is commented out with explanations, not deleted. To roll back any change:

- **STT:** In `app/utils/whisper_stt.py`, uncomment the old `import whisper` block (lines 17-42), comment out the `faster-whisper` block. In `requirements.txt`, uncomment `openai-whisper`, comment out `faster-whisper`.
- **TTS:** In `app/routes/chat.py`, uncomment the top-level `from gtts import gTTS` import and remove the piper try/fallback block. In `requirements.txt`, uncomment `gTTS`, comment out `piper-tts`.
- **Student STT:** In `templates/student_dashboard.html`, uncomment the `webkitSpeechRecognition` block and old `toggleVoiceInput()`, comment out the new MediaRecorder version.
- **Voice Chat:** In `app/__init__.py`, comment out the 3 voice blueprint lines (294-297). The `/ws/voice` endpoint and headset buttons become inert.
- **Feedback loop guards:** Remove the `if (isSpeaking) return` guards and `isSpeaking` state management from both dashboard templates.

---

## 7. Known Limitations

| Limitation | Details | Workaround |
|---|---|---|
| piper-tts is Linux-only | Won't install on macOS | Automatic gTTS fallback. Test neural voice quality on staging. |
| No GPU acceleration | Staging server has no GPU | faster-whisper int8 on CPU is still 4-8x faster than old openai-whisper. |
| Voice chat is half-duplex | User speaks, then AI speaks (not simultaneous) | This is by design for the initial implementation. Full-duplex requires Pipecat transport layer. |
| First request is slow | Model download + loading on first call | Pre-warm by sending a test request after deploy. |
| Kokoro TTS may not install | Depends on platform/Python version | Falls back to piper-tts in voice chat route. |
