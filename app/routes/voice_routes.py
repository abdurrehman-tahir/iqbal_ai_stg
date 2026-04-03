from flask import Blueprint, jsonify, request, session, current_app, Response, stream_with_context
from app.utils.auth import login_required
from app.services.voice import VoiceOrchestrator
import logging
import json
import base64
import tempfile
import os
import time

logger = logging.getLogger(__name__)

bp = Blueprint('voice', __name__)

_VALID_STATES = {"IDLE", "LISTENING", "TRANSCRIBING", "SENDING", "SPEAKING"}
_USER_STATE_RATE = {}
_RATE_WINDOW_SECONDS = 60
_RATE_MAX_EVENTS = 120


@bp.route('/session', methods=['GET'])
@login_required
def voice_session():
    """Return voice-session capabilities and server feature flags."""
    enabled = bool(current_app.config.get('VOICE_STREAM_ENABLED', False))
    return jsonify({
        'success': True,
        'voice_stream_enabled': enabled,
        'state_machine': ["IDLE", "LISTENING", "TRANSCRIBING", "SENDING", "SPEAKING", "IDLE"],
        'barge_in_enabled': bool(current_app.config.get('VOICE_BARGE_IN_ENABLED', True)),
        'echo_cancellation_required': True,
        'provider': current_app.config.get('VOICE_PROVIDER', 'internal'),
        'mode': 'live' if enabled else 'classic'
    })


@bp.route('/state', methods=['POST'])
@login_required
def track_voice_state():
    """Lightweight endpoint for client voice-state telemetry."""
    user_id = session.get('user_id')
    now = time.time()
    history = _USER_STATE_RATE.get(user_id, [])
    history = [t for t in history if now - t <= _RATE_WINDOW_SECONDS]
    if len(history) >= _RATE_MAX_EVENTS:
        return jsonify({'success': False, 'error': 'Rate limit exceeded'}), 429
    history.append(now)
    _USER_STATE_RATE[user_id] = history

    payload = request.get_json(silent=True) or {}
    if len(json.dumps(payload)) > 16_000:
        return jsonify({'success': False, 'error': 'Payload too large'}), 413
    event_type = str(payload.get('event_type') or 'transition').lower()
    state = str(payload.get('state') or '').upper()
    prev_state = str(payload.get('prev_state') or '').upper()

    if event_type not in {'transition', 'metric', 'event', 'invalid_transition'}:
        return jsonify({'success': False, 'error': 'Invalid event type'}), 400

    if state not in _VALID_STATES:
        return jsonify({'success': False, 'error': 'Invalid state'}), 400

    logger.info(
        'voice_telemetry user_id=%s event=%s prev=%s next=%s meta=%s',
        user_id, event_type, prev_state, state, payload.get('meta')
    )
    return jsonify({'success': True})


@bp.route('/assistant_stream', methods=['POST'])
@login_required
def assistant_stream():
    """
    Phase-2 kickoff endpoint:
    Streams assistant text chunks over SSE so frontend can start rendering
    incrementally while backend/transport is evolved to full duplex.
    """
    payload = request.get_json(silent=True) or {}
    text = str(payload.get('text') or '').strip()
    if not text:
        return jsonify({'success': False, 'error': 'text is required'}), 400
    max_chars = int(current_app.config.get('VOICE_MAX_ASSISTANT_CHARS', 900)) * 4
    if len(text) > max_chars:
        text = text[:max_chars]

    chunk_size = int(payload.get('chunk_size') or 80)
    orchestrator = VoiceOrchestrator(chunk_size=chunk_size)

    def _event_stream():
        for event in orchestrator.stream_assistant_text_events(text):
            yield f"data: {json.dumps(event)}\n\n"

    headers = {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no'
    }
    return Response(stream_with_context(_event_stream()), headers=headers)


@bp.route('/turn', methods=['POST'])
@login_required
def voice_turn():
    """
    Phase-3 orchestrated turn endpoint.
    Accepts either:
      - JSON: {message, thread_id, tts}
      - multipart/form-data: audio file + thread_id (+ optional tts=true)
    Returns transcription (if any), assistant text, and optional tts audio (base64 mp3).
    """
    orchestrator = VoiceOrchestrator(chunk_size=int(request.args.get('chunk_size', 80)))
    thread_id = None
    message = None
    transcription = None
    tts_enabled = False

    if request.is_json:
        payload = request.get_json(silent=True) or {}
        thread_id = str(payload.get('thread_id') or '').strip()
        message = str(payload.get('message') or '').strip()
        tts_enabled = bool(payload.get('tts', False))
    else:
        thread_id = str(request.form.get('thread_id') or '').strip()
        tts_enabled = str(request.form.get('tts') or '').lower() in {'1', 'true', 'yes'}
        audio_file = request.files.get('audio')
        if audio_file and audio_file.filename:
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
                    audio_file.save(tmp.name)
                    tmp_path = tmp.name
                transcription = orchestrator.transcribe_file(tmp_path)
                message = (transcription or '').strip()
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

    if not thread_id:
        return jsonify({'success': False, 'error': 'thread_id is required'}), 400
    if not message:
        return jsonify({'success': False, 'error': 'message or audio is required'}), 400

    response_text = orchestrator.generate_assistant_text(message=message, thread_id=thread_id)
    if not response_text:
        return jsonify({'success': False, 'error': 'Assistant response was empty'}), 500

    data = {
        'success': True,
        'thread_id': thread_id,
        'transcription': transcription,
        'message': response_text
    }
    if tts_enabled:
        audio_bytes = orchestrator.synthesize_tts_bytes(response_text)
        data['tts_audio_base64'] = base64.b64encode(audio_bytes).decode('ascii') if audio_bytes else None
    return jsonify(data)
