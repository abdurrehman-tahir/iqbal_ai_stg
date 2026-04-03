(function (window) {
  const STATES = Object.freeze({
    IDLE: 'IDLE',
    LISTENING: 'LISTENING',
    TRANSCRIBING: 'TRANSCRIBING',
    SENDING: 'SENDING',
    SPEAKING: 'SPEAKING'
  });

  function postState(prevState, state, meta) {
    fetch('/api/voice/state', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ prev_state: prevState, state: state, meta: meta || null })
    }).catch(function () {});
  }

  function VoiceStreamClient(options) {
    this.state = STATES.IDLE;
    this.options = options || {};
  }

  VoiceStreamClient.prototype.transition = function (nextState, meta) {
    if (!nextState || !STATES[nextState]) return false;
    const prev = this.state;
    this.state = nextState;
    postState(prev, nextState, meta || {});
    if (typeof this.options.onStateChange === 'function') {
      this.options.onStateChange(prev, nextState, meta || {});
    }
    return true;
  };

  VoiceStreamClient.prototype.canStartListening = function () {
    return this.state === STATES.IDLE;
  };

  VoiceStreamClient.prototype.canStartSpeaking = function () {
    return this.state === STATES.IDLE || this.state === STATES.SENDING;
  };

  VoiceStreamClient.prototype.forceStopForSpeaking = function (stopListeningFn, disableMicFn) {
    if (typeof stopListeningFn === 'function') stopListeningFn();
    if (typeof disableMicFn === 'function') disableMicFn(true);
    this.transition(STATES.SPEAKING, { reason: 'tts_start' });
  };

  VoiceStreamClient.prototype.finishSpeaking = function (disableMicFn) {
    if (typeof disableMicFn === 'function') disableMicFn(false);
    this.transition(STATES.IDLE, { reason: 'tts_end' });
  };

  VoiceStreamClient.prototype.getUserMediaConstraints = function () {
    return {
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      }
    };
  };

  VoiceStreamClient.STATES = STATES;
  window.VoiceStreamClient = VoiceStreamClient;
})(window);
