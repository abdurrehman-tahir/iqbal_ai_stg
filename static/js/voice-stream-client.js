(function (window) {
  const STATES = Object.freeze({
    IDLE: 'IDLE',
    LISTENING: 'LISTENING',
    TRANSCRIBING: 'TRANSCRIBING',
    SENDING: 'SENDING',
    SPEAKING: 'SPEAKING'
  });
  const ALLOWED = Object.freeze({
    IDLE: ['LISTENING', 'SPEAKING'],
    LISTENING: ['TRANSCRIBING', 'IDLE', 'SPEAKING'],
    TRANSCRIBING: ['SENDING', 'IDLE', 'SPEAKING'],
    SENDING: ['SPEAKING', 'IDLE'],
    SPEAKING: ['IDLE']
  });

  function postState(prevState, state, meta, eventType) {
    fetch('/api/voice/state', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        event_type: eventType || 'transition',
        prev_state: prevState,
        state: state,
        meta: meta || null
      })
    }).catch(function () {});
  }

  function VoiceStreamClient(options) {
    this.state = STATES.IDLE;
    this.options = options || {};
    this.strict = this.options.strictTransitions !== false;
    this.timers = {};
  }

  VoiceStreamClient.prototype.transition = function (nextState, meta) {
    if (!nextState || !STATES[nextState]) return false;
    const prev = this.state;
    if (this.strict && prev && ALLOWED[prev] && ALLOWED[prev].indexOf(nextState) === -1) {
      postState(prev, prev, { blocked_to: nextState, meta: meta || {} }, 'invalid_transition');
      return false;
    }
    this.state = nextState;
    postState(prev, nextState, meta || {}, 'transition');
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

  VoiceStreamClient.prototype.startTimer = function (name) {
    if (!name) return;
    this.timers[name] = Date.now();
  };

  VoiceStreamClient.prototype.endTimer = function (name, extraMeta) {
    if (!name || !this.timers[name]) return null;
    const duration = Date.now() - this.timers[name];
    delete this.timers[name];
    postState(this.state, this.state, Object.assign({ metric: name, duration_ms: duration }, extraMeta || {}), 'metric');
    return duration;
  };

  VoiceStreamClient.prototype.recordEvent = function (eventName, meta) {
    postState(this.state, this.state, Object.assign({ event: eventName }, meta || {}), 'event');
  };

  VoiceStreamClient.prototype.streamAssistantText = async function (text, onChunk, onDone) {
    const res = await fetch('/api/voice/assistant_stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ text: text })
    });
    if (!res.ok || !res.body) throw new Error('assistant_stream failed');

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() || '';
      for (const raw of parts) {
        const line = raw.split('\n').find(l => l.startsWith('data: '));
        if (!line) continue;
        try {
          const payload = JSON.parse(line.slice(6));
          if (payload.type === 'assistant_text_chunk' && typeof onChunk === 'function') onChunk(payload.chunk || '');
          if (payload.type === 'done' && typeof onDone === 'function') onDone();
        } catch (e) {}
      }
    }
  };

  VoiceStreamClient.STATES = STATES;
  window.VoiceStreamClient = VoiceStreamClient;
})(window);
