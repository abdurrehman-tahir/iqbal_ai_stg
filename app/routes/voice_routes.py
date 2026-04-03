from flask import Blueprint, jsonify, request, session, current_app, Response, stream_with_context
from app.utils.auth import login_required
import logging
import json

logger = logging.getLogger(__name__)

bp = Blueprint('voice', __name__)

_VALID_STATES = {"IDLE", "LISTENING", "TRANSCRIBING", "SENDING", "SPEAKING"}


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
    payload = request.get_json(silent=True) or {}
    event_type = str(payload.get('event_type') or 'transition').lower()
    state = str(payload.get('state') or '').upper()
    prev_state = str(payload.get('prev_state') or '').upper()

    if event_type not in {'transition', 'metric', 'event', 'invalid_transition'}:
        return jsonify({'success': False, 'error': 'Invalid event type'}), 400

    if state not in _VALID_STATES:
        return jsonify({'success': False, 'error': 'Invalid state'}), 400

    user_id = session.get('user_id')
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

    chunk_size = int(payload.get('chunk_size') or 80)
    chunk_size = max(20, min(chunk_size, 240))

    def _event_stream():
        for i in range(0, len(text), chunk_size):
            chunk = text[i:i + chunk_size]
            event = {'type': 'assistant_text_chunk', 'chunk': chunk}
            yield f"data: {json.dumps(event)}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    headers = {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no'
    }
    return Response(stream_with_context(_event_stream()), headers=headers)
