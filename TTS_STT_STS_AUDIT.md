# TTS/STT/STS Feature Audit (Teacher Dashboard + Student Dashboard)

## Clarifying questions (to refine next iteration)
1. Should **student voice** also be server-side (Whisper + backend TTS), or do you want to keep browser-native voice for cost reasons?
2. Do you want strict support for **Urdu + English mixed speech** for both STT and TTS?
3. Is the target UX push-to-talk, full duplex streaming, or a turn-based walkie-talkie style?

## Clarification update (based on stakeholder answers)
- ✅ Student voice should be unified with backend speech stack.
- ✅ Urdu is not a hard requirement now, but should remain a forward-compatible design constraint.
- ✅ Top priority is **streaming/full-duplex conversational STS** with minimal effort.

### Direct answer: Do we need to change core model QWEN3-32B?
- **Short answer: No, not required for Phase 1 full-duplex UX.**
- You can keep current core chat model/provider routing and add a voice streaming layer around it first.
- Model change only becomes necessary if latency/quality SLOs are not met after streaming pipeline + prompt/response shaping optimizations.

## Phase summary (what changes in each phase)

### Phase 1A — Streaming shell (fastest delivery)
- Goal: enable near full-duplex behavior quickly without replacing core LLM routing.
- Changes:
  - Add shared voice streaming client for both dashboards.
  - Add voice streaming backend endpoints (session + websocket stream).
  - Keep existing chat intelligence routes/services (RAG/Lesson) behind the voice layer.
  - Emit partial transcripts and start TTS playback in chunks.
- **Pipecat in Phase 1A:** **No** (keep in-process Flask + WS path for minimal effort).

### Phase 1B — Conversation hardening
- Goal: make voice interaction feel natural and robust.
- Changes:
  - Add barge-in (interrupt active TTS when user speaks).
  - Add voice-mode response shaping (shorter chunkable responses).
  - Add timing/quality telemetry per voice turn.
- **Pipecat in Phase 1B:** **No** by default; evaluate only if quality/latency remains inadequate.

### Phase 2 — Model/perf optimization (only if needed)
- Goal: hit latency/quality targets after real traffic validation.
- Changes:
  - Keep Qwen3-32B for quality-sensitive paths.
  - Optionally use a faster model for voice turns only if latency remains high.
  - Tune provider/model selection policy specifically for voice mode.

## Phase 1 feasibility check (will it actually meet requirements?)

### Requirement check against your goals
1. **Streaming/full-duplex conversational feel**
   - Phase 1 supports this via websocket transport, partial STT, chunked TTS playback, and barge-in in 1B.
2. **Minimal effort**
   - Phase 1 avoids replacing core RAG/Lesson/LLM routing; it wraps existing intelligence with a voice stream layer.
3. **Single-VM simplicity**
   - Works with nginx + gunicorn + systemd using one app process group plus optional voice worker process.

### What Phase 1 WILL deliver (realistically)
- Near real-time interaction (partial transcript + early audio playback).
- Unified teacher/student voice behavior.
- Backward-compatible fallback to existing `/api/stt` and `/api/tts`.

### What Phase 1 WILL NOT fully solve
- Studio-grade voice naturalness and perfect interruption quality under heavy load.
- True sub-200ms end-to-end latency in all network/server conditions.
- These are Phase 2+ tuning targets.

### Phase 1 acceptance criteria (go/no-go)
- p95 `stt_first_partial_ms` < 1200 ms
- p95 `llm_first_token_ms` < 1800 ms
- p95 `tts_first_audio_ms` < 1200 ms
- Barge-in interruption success > 90%
- Error rate < 3% across 30-minute mixed teacher/student sessions

If these pass, Phase 1 is considered successful for initial rollout.

## Parallel feature strategy (recommended): keep existing voice + add streaming voice

Yes — running streaming voice as a **separate feature path** alongside the existing voice flow is the safest rollout plan.

### Rollout design
- Keep current routes/UI behavior as default:
  - `/api/stt`, `/api/tts`, existing dashboard voice handlers.
- Add new streaming path behind feature flag:
  - `VOICE_STREAM_ENABLED=true`
  - New WS route and new UI control toggle (“Live Voice Beta”).
- Users can switch between:
  - **Classic Voice** (existing turn-based flow)
  - **Live Voice** (streaming/full-duplex path)

### Why this is better
- Lower risk: no forced migration.
- Faster validation: compare classic vs streaming quality/latency side-by-side.
- Easy rollback: disable flag without touching legacy path.

### Planned migration sequence
1. Internal QA on Live Voice only.
2. Pilot subset of users/teachers.
3. Broader rollout when metrics beat classic mode.
4. Deprecate classic only after sustained success.

## Phase 1 anti-feedback safety design (required)

This is required to prevent AI voice playback from being re-captured and re-sent.

### Required client state machine (both dashboards)
- `IDLE -> LISTENING -> TRANSCRIBING -> SENDING -> SPEAKING -> IDLE`
- Hard rule: **mic and speaker states never overlap**.
- If transition to `SPEAKING` occurs:
  - force-stop any active recording session
  - disable mic button/UI and block new LISTENING transitions
- On `SPEAKING` end/error:
  - re-enable mic button
  - transition back to `IDLE`

### Required safeguards
1. `getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }})`
2. Centralized guard in shared voice client:
   - `canStartListening() === (state === IDLE)`
   - `canStartSpeaking() === (state === IDLE || state === SENDING)`
3. If TTS starts while LISTENING/TRANSCRIBING:
   - stop recorder and discard partial chunks for that turn.
4. Auto-TTS path must respect same gate logic (especially teacher dashboard).

### Current gap check (why this is needed)
- Teacher dashboard has backend auto-TTS and separate mic control but no strict cross-state lock that guarantees mutual exclusion for all async branches.
- Student dashboard currently relies on browser speech APIs and can restart recognition in `onend`; without a unified state machine this can re-open LISTENING unexpectedly.

### Phase 1 implementation tasks for this safeguard
- Put state machine in `static/js/voice-stream-client.js` and make both dashboards use it.
- Replace direct mic/speaker handlers in:
  - `templates/teacher_dashboard.html`
  - `templates/student_dashboard.html`
- Add telemetry events:
  - `voice_state_transition`
  - `mic_blocked_during_speaking`
  - `recording_force_stopped_for_tts`

### Acceptance tests for feedback-loop prevention
1. Start mic, trigger assistant response with auto-TTS:
   - recorder stops before first TTS audio chunk plays.
2. While TTS is active:
   - mic button disabled and click attempts ignored/logged.
3. After TTS ends:
   - mic re-enabled and LISTENING can be started manually.
4. Repeat on both teacher and student dashboards.

## Future-proof model/provider strategy (Pipecat + adapters)

Goal: keep voice orchestration stable even if core models/providers change.

### Compatibility stance for planning
- Do **not** hardcode roadmap around one provider/model family.
- Use provider abstraction boundaries so Qwen/OpenAI/Claude/Gemini can be swapped with minimal app-level changes.
- Re-validate supported provider services at implementation time (Pipecat service availability can evolve quickly).

### Verified service coverage to track in compatibility matrix
- OpenAI service
- Qwen service (OpenAI-compatible interface)
- Anthropic Claude service
- Google Gemini service

These should be pinned as tested integrations in the project’s versioned provider matrix.

### Recommended architecture contract
Implement internal interfaces and map providers behind adapters:
- `LLMVoiceAdapter` (generate tokens/chunks, tool-call support capability flags)
- `STTAdapter` (stream/turn transcription)
- `TTSAdapter` (chunked synthesis, interrupt support)

Then expose one orchestrator contract to the app:
- `VoiceOrchestrator.handle_stream(session_id, audio_chunk)` -> events
  - `partial_transcript`
  - `assistant_text_chunk`
  - `assistant_audio_chunk`
  - `state_transition`
  - `error`

### Provider profile registry (future-proofing mechanism)
Add a registry/config map (not switch/case in UI logic):
- `provider_id` (openai | qwen | anthropic | gemini | ...)
- `transport` (native | openai_compatible)
- `supports_tools` (bool)
- `supports_audio_in` (bool)
- `supports_audio_out` (bool)
- `supports_interrupt` (bool)
- `recommended_voice_mode_model`

This avoids reworking dashboard code when core model changes.

### Rollout policy for future model changes
1. Keep classic + live voice dual-path.
2. Add new provider via adapter + provider profile.
3. Run shadow traffic / canary on live voice.
4. Promote only when latency/error/quality metrics pass Phase 1 gates.

### Implementation note
Even if Pipecat already supports several common providers, treat support as a versioned dependency:
- pin tested Pipecat version,
- capture tested provider/model matrix in repo docs,
- run a startup capability check and disable unsupported live-voice modes gracefully.

## Scope audited
- New UIs: `teacher_dashboard.html`, `student_dashboard.html`
- Voice APIs: `/api/stt`, `/api/tts`, and RAG `/api/rag/chat` audio handling
- Model/provider wiring used in chat stack (RAG + LLM routing)
- Config/dependencies affecting speech path

---

## 1) User-perspective behavior

### Teacher dashboard
- **STT path** is backend-based:
  - Mic click starts `MediaRecorder`, stops recording on second click, sends audio blob to `/api/stt`.
  - Transcribed text is placed into chat input.
- **TTS path** is backend-based:
  - Speaker click sends assistant text to `/api/tts`, gets MP3 blob, plays via `Audio()`.
- **Chat path**:
  - Text message sends to `/api/rag/chat` with `thread_id` / `conversation_id`.
  - Auto-read mode can call `/api/tts` on each assistant message.

### Student dashboard
- **STT path** is browser-native only:
  - Uses `SpeechRecognition` / `webkitSpeechRecognition` directly in browser.
  - No backend `/api/stt` use.
- **TTS path** is browser-native only:
  - Uses `window.speechSynthesis` and `SpeechSynthesisUtterance`.
  - No backend `/api/tts` use.
- **Chat path**:
  - Sends to lesson Q&A API `/api/lessons/ask_question`.

### What this feels like to users today
- Teacher and student voice experiences are inconsistent (different quality and capabilities).
- Teacher TTS quality depends on gTTS network generation and simplistic language detection.
- Student voice quality depends on browser/OS engine (varies widely by device).
- There is **no natural real-time STS conversation loop** in new dashboards.

---

## 2) End-to-end architecture (current)

### Current speech architecture

```text
[Teacher Browser]
  ├─(mic record webm)─> POST /api/stt
  │                    -> local Whisper base (CPU)
  │                    -> transcript
  ├─(text prompt)─────> POST /api/rag/chat
  │                    -> RAG + selected LLM provider
  │                    -> assistant text
  └─(assistant text)──> POST /api/tts
                       -> gTTS mp3
                       -> play in browser

[Student Browser]
  ├─SpeechRecognition (browser engine)
  ├─POST /api/lessons/ask_question (text)
  └─speechSynthesis (browser engine)
```

### Route/module mapping
- Dashboards are served from `chat` blueprint (`/teacher-dashboard`, `/student-dashboard`).
- Speech routes `/api/stt` and `/api/tts` are in `app/routes/chat.py`.
- Teacher chat uses `/api/rag/chat` in `app/routes/rag_routes.py`.
- Student chat uses `/api/lessons/ask_question` in `app/routes/lesson_routes.py`.

---

## 3) Backend services/models/external services used

## STT
- **Primary implementation in use**: `openai-whisper` local model (`base`) on CPU.
- Endpoint: `/api/stt` saves uploaded audio to temp `.webm`, transcribes with local Whisper, returns JSON text.
- There is also a shared utility `app/utils/whisper_stt.py` for lazy-loaded local Whisper.

## TTS
- **Primary implementation in use**: `gTTS` (Google TTS) in `/api/tts`.
- Flow: clean markdown-ish symbols -> detect language (`langdetect`) -> synthesize MP3 stream.

## STS (speech-to-speech)
- In new dashboards there is **no true streaming STS** pipeline.
- Teacher flow is effectively chained **STT -> text chat -> TTS** (turn-based).
- Student flow is **browser STT + text chat + browser TTS**.
- Two local scripts (`speechtospeech.py`, `speechtospeechsmall.py`) implement standalone SeamlessM4T CLI speech-to-speech experimentation, but they are not integrated into Flask routes/UI.

## LLM provider selection for chat
- LLM provider/model resolution is centralized in `llm_factory.get_chat_model()` using admin `active_provider` + encrypted API keys from DB.
- Providers configured include OpenAI/Groq/vLLM.

## Infra/runtime context
- Flask app registers blueprints for chat/rag/lessons and uses Celery optionally for ingestion, not for speech inference.
- Whisper + gTTS packages are installed in `requirements.txt`.

---

## 4) Key implementation gaps (why UX feels broken / low quality)

### High severity
1. **Teacher vs Student split-brain voice architecture**
   - Teacher uses backend STT/TTS; student uses browser-native speech APIs.
   - Outcome: inconsistent behavior, language support, and audio quality.

2. **RAG chat audio support is contradictory / effectively disabled**
   - `/api/rag/chat` immediately returns `VOICE_NOT_SUPPORTED` when audio exists, but later code attempts to transcribe audio with Whisper.
   - This is dead/inconsistent logic and blocks voice-to-RAG direct flow.

3. **No true low-latency STS loop**
   - Current system is request/response batch mode (record-stop-upload-transcribe-generate-synthesize-play).
   - Natural conversational feel is not possible in this architecture.

### Medium severity
4. **Whisper `base` on CPU + full-file upload causes turn latency**
   - Entire recording is uploaded then transcribed; no streaming partials.

5. **gTTS quality and robustness limits**
   - Basic voice quality and limited prosody/expressiveness.
   - Additional network dependency and potential variability.

6. **Language handling is shallow**
   - TTS uses `langdetect` on free text; code-switching (Urdu-English mixed) can be misdetected.

7. **Potential duplicate Whisper loading paths**
   - `chat.py` has its own `_get_whisper_model()` while `whisper_stt.py` also manages Whisper lifecycle.
   - Increases maintenance confusion and risk of divergent behavior.

### Low severity
8. **Legacy/experimental remnants create confusion**
   - Commented OpenAI Whisper route blocks, duplicate blueprint declaration pattern in `chat.py`, old/alternate student dashboard files.

9. **Realtime OpenAI session route exists but not wired into new dashboards**
   - `/auth/session` generates realtime session payload but current teacher/student pages do not use it.

---

## 5) Security/ops/cost observations
- Some default secrets are present in `app/config.py` (mail password fallback, default secret key). Must move to secure env-only values.
- Speech processing currently happens in web process, so spikes can impact request latency for normal web traffic.
- On single-VM deployment, isolating speech workers by process (systemd service) would improve stability without introducing microservices.

---

## 6) Recommended upgrade options (ROI ranked)

## Option A (highest ROI, minimal risk): unify turn-based backend speech stack
1. Make both teacher + student use the same backend STT/TTS APIs.
2. Remove contradictory audio handling in `/api/rag/chat`:
   - either explicitly unsupported (delete dead transcribe block), or
   - fully supported (accept audio, transcribe, route to same chat pipeline).
3. Consolidate Whisper loading to `app/utils/whisper_stt.py` only.
4. Add better TTS engine abstraction (provider interface), keep gTTS as fallback.

**Expected impact**: consistency + easier debugging + immediate UX stabilization.

## Option B (medium effort, high UX gain): pseudo-streaming STS on existing models
1. Browser captures short chunks (e.g., 700–1200ms) via MediaRecorder.
2. Server performs incremental transcription + partial text updates.
3. LLM response starts early (token streaming), TTS starts sentence-by-sentence playback.

**Expected impact**: much more “natural” feel while keeping free/open models.

## Option C (highest UX ambition): full duplex realtime voice orchestration (Pipecat-style)
1. Add a voice orchestration layer (Pipecat or equivalent) with:
   - VAD
   - streaming ASR
   - interruption handling (barge-in)
   - streaming TTS output
2. Keep your current free models where possible via wrappers/adapters.
3. Run as separate local service/process on same VM and connect via WebSocket.

**Expected impact**: closest to natural STS assistant. Highest integration complexity.

---

## 6.1) Minimal-effort path to full-duplex STS (recommended execution plan)

This is the fastest path that preserves your current stack and single-VM deployment.

### Phase 1A (quickest unlock: 3–5 days) — “Streaming shell around existing intelligence”
1. Keep current **LLM core (Qwen/Groq/OpenAI/vLLM via `llm_factory`)** unchanged.
2. Add a new streaming voice endpoint pair under a new blueprint, e.g.:
   - `app/routes/voice_routes.py`
   - `GET /api/voice/session` (session metadata/capabilities)
   - `WS /api/voice/stream` (bi-directional audio/text events)
3. In both dashboards:
   - Replace old voice handlers with a shared voice client module:
     - `static/js/voice-stream-client.js`
   - Teacher and student both connect to the same WS voice stream.
4. Keep RAG/lesson orchestration as existing HTTP calls internally at first.
5. Start with pseudo full-duplex:
   - VAD-based utterance segmentation
   - partial transcripts emitted live
   - start TTS playback sentence-by-sentence while next LLM tokens continue.

### Phase 1B (hardening: +3–4 days)
1. Introduce interruption (“barge-in”):
   - user speech activity cancels active TTS playback and sends `interrupt` event.
2. Add low-latency guardrails:
   - max assistant chars per turn in voice mode
   - sentence chunking for immediate TTS start.
3. Add observability:
   - `stt_first_partial_ms`, `stt_final_ms`, `llm_first_token_ms`, `tts_first_audio_ms`, `turn_end_ms`.

### Phase 2 (optional model tuning) — only if needed
1. If voice turn latency remains high:
   - Use smaller/faster model for voice mode only (not all routes).
2. If content quality drops:
   - Keep Qwen3-32B for “final answer mode”, and use smaller model for live conversational turns.
3. Only then consider deeper provider/model migration.

---

## 6.2) Exact code-level changes to implement full-duplex STS

### Frontend changes
- `templates/teacher_dashboard.html`
  - Remove direct `/api/stt` upload + `/api/tts` fetch voice toggles.
  - Hook mic/speaker controls into `VoiceStreamClient`.
- `templates/student_dashboard.html`
  - Remove `SpeechRecognition` and `speechSynthesis` hard dependency for primary path.
  - Reuse same `VoiceStreamClient` for parity with teacher UX.
- `static/js/voice-stream-client.js` (new)
  - Handles:
    - mic capture (MediaStreamTrackProcessor / MediaRecorder chunking)
    - WS lifecycle/reconnect
    - emit `audio_chunk`, receive `partial_text`, `assistant_text_chunk`, `assistant_audio_chunk`
    - barge-in interrupt signaling

### Backend changes
- `app/routes/voice_routes.py` (new)
  - Session bootstrap + WS event handler
  - Auth check (`login_required`) + role gating where needed
  - Calls into services:
    - `app/services/voice/stt_service.py` (new)
    - `app/services/voice/tts_service.py` (new)
    - existing chat/RAG/lesson entrypoints
- `app/services/voice/stt_service.py` (new)
  - Streaming-compatible STT abstraction.
  - Initial fallback: chunked local Whisper (turn-level), then upgrade to true streaming ASR.
- `app/services/voice/tts_service.py` (new)
  - Sentence/chunk TTS generation and streaming output abstraction.
  - Keep gTTS fallback for compatibility; add pluggable provider interface.
- `app/__init__.py`
  - Register `voice_bp` with prefix `/api/voice`.
- `app/config.py`
  - Add voice-specific env toggles:
    - `VOICE_STREAM_ENABLED`
    - `VOICE_MODE_DEFAULT_MODEL`
    - `VOICE_MAX_ASSISTANT_CHARS`
    - `VOICE_BARGE_IN_ENABLED`

### Keep/remove decisions
- Keep `/api/stt` and `/api/tts` for fallback and non-WS clients.
- Deprecate browser-native student voice path after feature-flag verification.
- Resolve contradictory `/api/rag/chat` audio handling by choosing one behavior and deleting dead branch.

---

## 6.3) Should we adopt Pipecat now?

- **Recommendation:** start with in-process WS voice layer first, then evaluate Pipecat if interruption quality/latency is still poor.
- Why: minimal effort, fewer moving pieces, easier on single VM with nginx + gunicorn + systemd.
- Pipecat is still a strong Phase 2/3 option if you need production-grade conversational turn management quickly.

---

## 7) Suggested target architecture (single VM, simple ops)

```text
[Browser Teacher/Student]
   <-> WebSocket /voice/session
        |
        v
[Flask Voice Gateway Blueprint]
   -> [VAD + Streaming STT Service]
   -> [LLM Orchestrator (existing RAG/Lesson routes/services + llm_factory)]
   -> [Streaming TTS Service]
        |
        v
[Audio chunks back to browser]

Storage/infra on same VM:
- Postgres/SQLite (existing)
- Milvus/Chroma (existing RAG)
- systemd services for web + optional voice worker
- nginx reverse proxy
```

---

## 8) Concrete implementation plan (phased)

### Phase 1 (1–2 days)
- Normalize student dashboard to backend STT/TTS (feature flag).
- Refactor shared speech client JS module used by both dashboards.
- Fix `/api/rag/chat` audio contradiction.
- Add structured timing logs: stt_ms, llm_ms, tts_ms, roundtrip_ms.

### Phase 2 (3–5 days)
- Introduce `SpeechService` abstraction in backend:
  - `transcribe(audio)->text`
  - `synthesize(text)->audio`
- Plug in optional higher-quality OSS TTS/STT providers while retaining current defaults.
- Add queueing/worker isolation for speech tasks on single VM (systemd-managed process pool).

### Phase 3 (1–2 weeks)
- Prototype Pipecat-style session on one dashboard behind a feature flag.
- Add barge-in, chunked playback, and interruption-safe conversation state.
- Measure MOS-like user perception + latency metrics.

---

## 9) Quick wins to test immediately
1. Increase teacher recording UX quality:
   - min recording duration guard + waveform/level meter + clear states.
2. Use consistent sample rate and MIME handling (`audio/webm;codecs=opus`) everywhere.
3. Replace `alert()` in student speech errors with non-blocking toasts and retry hints.
4. Add client-side “speech diagnostics” panel (browser support, mic permissions, measured latency).

---

## 10) What I checked (documentation ingestion note)
I attempted to ingest the requested docs in order:
1. `DOCUMENTATION_INDEX.md`
2. `PROJECT_DOCUMENTATION.md`
3. `AI_Application_Workflow_Overview` doc
4. `DEVELOPER_QUICK_START.md`
5. `API_REFERENCE.md`
6. `Tech Stack.pdf`
7. `Plan - Expected - 1month.pdf`

Those files were not present at repo root in this environment. Audit was performed directly from source files and routing/config/dependency inspection.
