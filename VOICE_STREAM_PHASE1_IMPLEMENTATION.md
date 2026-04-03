# Voice Streaming Phase 1 Implementation Log

## Feature request
Implement Phase 1 foundations for unified teacher+student voice behavior with anti-feedback protection:
- shared client-side state machine
- mic/speaker overlap prevention
- telemetry hooks
- feature-flagged backend voice session/state endpoints

## Scope implemented in this change
1. Added backend voice blueprint (`/api/voice/*`) for feature/capability discovery and state telemetry.
2. Added shared voice state-machine client script.
3. Integrated shared state-machine protections into both teacher and student dashboards.
4. Added configuration environment variables for feature rollout and tuning.
5. Added Phase 1B hardening telemetry hooks (state-transition validation, invalid transition reporting, timing metrics).

## Step-by-step log
1. Created `app/routes/voice_routes.py` with:
   - `GET /api/voice/session` capability response
   - `POST /api/voice/state` state transition telemetry
2. Registered `voice_bp` in `app/__init__.py` under `/api/voice`.
3. Added `static/js/voice-stream-client.js`:
   - state machine constants: `IDLE/LISTENING/TRANSCRIBING/SENDING/SPEAKING`
   - transition telemetry helper
   - `canStartListening`, `canStartSpeaking`
   - `forceStopForSpeaking`, `finishSpeaking`
   - `getUserMedia` constraints with echo cancellation safeguards
4. Updated `templates/teacher_dashboard.html`:
   - load shared voice client script
   - initialize `voiceClient`
   - block LISTENING if voice state is not idle
   - use echo/noise/AGC constraints for mic capture
   - transition states during STT request flow
   - disable mic while TTS plays and re-enable after completion/error
5. Updated `templates/student_dashboard.html`:
   - load shared voice client script
   - initialize `voiceClient`
   - block LISTENING when speaking/processing
   - prevent recognition auto-restart unless state remains LISTENING
   - force stop listening before speaking and re-enable mic after TTS
6. Added Phase 1 voice env vars in `app/config.py`.
7. Hardened `voice-stream-client.js` with:
   - allowed state-transition graph enforcement
   - invalid-transition telemetry events
   - client timers (`startTimer/endTimer`) for latency metrics
8. Updated telemetry endpoint (`/api/voice/state`) to support event types:
   - `transition`, `metric`, `event`, `invalid_transition`
9. Added Phase 1B UI telemetry in teacher/student dashboards:
   - mic-blocked events during non-idle states
   - forced-stop events when speaking starts
   - STT and TTS timing metrics

## Environment variables introduced
- `VOICE_STREAM_ENABLED` (default: `false`)
  - Enables new live voice mode behavior on backend session/capabilities.
  - Set to `true` to roll out streaming path.
- `VOICE_BARGE_IN_ENABLED` (default: `true`)
  - Enables interruption-oriented behavior policy for live voice sessions.
  - Set `false` if you need non-interruptive playback behavior.
- `VOICE_PROVIDER` (default: `internal`)
  - Selects voice orchestrator provider profile (`internal` or `pipecat`).
  - Keep `internal` until provider integration is fully validated.
- `VOICE_MODE_DEFAULT_MODEL` (default: empty)
  - Optional model identifier for voice mode routing.
  - Example: set a faster model for live voice while preserving default text model.
- `VOICE_MAX_ASSISTANT_CHARS` (default: `900`)
  - Soft cap for assistant response length in voice mode.
  - Lower values reduce latency and improve turn-taking.

## Tuning guidance
- Start in staging:
  - `VOICE_STREAM_ENABLED=false` (verify no regression)
  - `VOICE_PROVIDER=internal`
- Beta rollout:
  - `VOICE_STREAM_ENABLED=true` for limited users
  - Monitor state telemetry and turn-latency metrics
- Optimize latency:
  - reduce `VOICE_MAX_ASSISTANT_CHARS`
  - set `VOICE_MODE_DEFAULT_MODEL` to a faster model if needed

## Notes / follow-up
- This change adds Phase 1 scaffolding and UI safety controls.
- This update also includes Phase 1B hardening telemetry and transition validation.
- Next step is live websocket audio event loop and server-side streaming handlers behind the same feature flags.

## Screenshot note
- UI screenshots were not attached in this iteration because a browser screenshot tool was not available in the current execution environment.
- No local browser automation stack was installed as part of this task (intentionally, to avoid ad-hoc environment drift).
- Once browser tooling is available in CI/dev agent context, capture updated teacher/student dashboard screenshots for:
  1. mic disabled during TTS
  2. state-transition behavior
  3. voice-mode toggle and error states

## Glossary / clarification of terms used in updates

### What “telemetry” means here
In this implementation, **telemetry** means lightweight runtime signals sent from browser -> backend for visibility/debugging.  
It is **not** user content logging; it is event/metric metadata about voice state transitions and durations.

Examples:
- `transition`: state moved (e.g., `LISTENING -> TRANSCRIBING`)
- `event`: notable behavior (e.g., mic blocked during speaking)
- `metric`: measured duration in milliseconds (e.g., STT roundtrip)
- `invalid_transition`: blocked state change that violates the allowed state graph

### Teacher dashboard telemetry (what was meant)
- **blocked-mic events**: user clicked mic while state is non-idle, so listening is blocked and event is reported.
- **STT roundtrip timing**: timer around `/api/stt` request (start before request, stop on response/error).
- **forced-stop-for-TTS events**: when speaking starts, active listening is forcibly stopped and event is reported.

### Student dashboard telemetry (what was meant)
- **blocked-mic events**: user attempted to start listening while state was not eligible.
- **listening/toggle timing**: duration from start-listening to stop-listening in current implementation.
- **TTS playback timing**: duration of speech synthesis playback (including manual stop/end events).
- **forced-stop before speaking**: listening is stopped before TTS playback starts to prevent feedback loops.
