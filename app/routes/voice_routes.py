from flask import Blueprint, jsonify, request, session, current_app
from app.utils.auth import login_required
import logging

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
    state = str(payload.get('state') or '').upper()
    prev_state = str(payload.get('prev_state') or '').upper()

    if state not in _VALID_STATES:
        return jsonify({'success': False, 'error': 'Invalid state'}), 400

    user_id = session.get('user_id')
    logger.info('voice_state_transition user_id=%s prev=%s next=%s meta=%s', user_id, prev_state, state, payload.get('meta'))
    return jsonify({'success': True})
