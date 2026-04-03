/**
 * Voice Chat Client — WebSocket-based real-time speech-to-speech conversation.
 *
 * Opens a WebSocket to /ws/voice, streams audio from the microphone,
 * receives AI responses as audio, and manages the conversation loop.
 *
 * Uses Silero VAD (via @ricky0123/vad-web) for client-side voice activity
 * detection, or falls back to manual push-to-talk.
 *
 * States: idle → listening → thinking → speaking → listening → ...
 */

(function () {
  'use strict';

  // --- State ---
  let ws = null;
  let mediaStream = null;
  let mediaRecorder = null;
  let audioChunks = [];
  let isVoiceChatActive = false;
  let currentState = 'idle'; // idle, listening, thinking, speaking
  let audioContext = null;
  let audioQueue = [];
  let isPlaying = false;

  // --- Configuration ---
  const VOICE_CHAT_CONFIG = {
    wsUrl: (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/voice',
    sampleRate: 16000,
  };

  /**
   * Open the voice chat modal and start the session.
   * @param {Object} opts - Session options
   * @param {string} opts.role - 'teacher' or 'student'
   * @param {string} [opts.threadId] - RAG thread ID (teacher)
   * @param {string} [opts.conversationId] - Conversation ID
   * @param {string} [opts.lessonQaId] - Lesson QA ID (student)
   */
  window.startVoiceChat = function (opts) {
    opts = opts || {};
    if (isVoiceChatActive) {
      console.warn('[VoiceChat] Already active');
      return;
    }

    isVoiceChatActive = true;
    _showModal();
    _updateState('idle');
    _connectWebSocket(opts);
  };

  /**
   * Stop the voice chat session and close the modal.
   */
  window.stopVoiceChat = function () {
    isVoiceChatActive = false;
    _updateState('idle');
    _stopRecording();
    _closeWebSocket();
    _hideModal();
  };

  // --- WebSocket ---

  function _connectWebSocket(opts) {
    try {
      ws = new WebSocket(VOICE_CHAT_CONFIG.wsUrl);
    } catch (e) {
      console.error('[VoiceChat] WebSocket creation failed:', e);
      _showError('Could not connect to voice service');
      window.stopVoiceChat();
      return;
    }

    ws.onopen = function () {
      console.log('[VoiceChat] Connected');
      // Send session config
      ws.send(JSON.stringify({
        type: 'config',
        role: opts.role || 'student',
        thread_id: opts.threadId || null,
        conversation_id: opts.conversationId || null,
        lesson_qa_id: opts.lessonQaId || null,
        cookie: document.cookie,
        base_url: location.origin,
      }));
    };

    ws.onmessage = function (event) {
      try {
        var msg = JSON.parse(event.data);
        _handleServerMessage(msg);
      } catch (e) {
        console.error('[VoiceChat] Bad message:', e);
      }
    };

    ws.onclose = function () {
      console.log('[VoiceChat] Disconnected');
      if (isVoiceChatActive) {
        _showError('Connection lost. Please try again.');
        window.stopVoiceChat();
      }
    };

    ws.onerror = function (e) {
      console.error('[VoiceChat] WebSocket error:', e);
    };
  }

  function _closeWebSocket() {
    if (ws) {
      try {
        ws.send(JSON.stringify({ type: 'stop' }));
      } catch (e) { /* ignore */ }
      try {
        ws.close();
      } catch (e) { /* ignore */ }
      ws = null;
    }
  }

  // --- Server Message Handling ---

  function _handleServerMessage(msg) {
    switch (msg.type) {
      case 'state':
        _updateState(msg.state);
        if (msg.state === 'listening') {
          _startRecording();
        } else if (msg.state === 'thinking' || msg.state === 'speaking') {
          _stopRecording();
        }
        break;

      case 'transcript':
        _addTranscript('user', msg.text);
        break;

      case 'response':
        _addTranscript('assistant', msg.text);
        break;

      case 'audio':
        _playAudioData(msg.data, msg.sample_rate || 22050);
        break;

      case 'error':
        _showError(msg.message);
        break;
    }
  }

  // --- Audio Recording ---

  async function _startRecording() {
    if (mediaRecorder && mediaRecorder.state === 'recording') return;
    if (currentState === 'speaking') return;

    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, sampleRate: VOICE_CHAT_CONFIG.sampleRate }
      });

      mediaRecorder = new MediaRecorder(mediaStream);
      audioChunks = [];

      mediaRecorder.ondataavailable = function (e) {
        if (e.data.size > 0) audioChunks.push(e.data);
      };

      mediaRecorder.onstop = function () {
        if (audioChunks.length > 0 && ws && ws.readyState === WebSocket.OPEN) {
          var blob = new Blob(audioChunks, { type: mediaRecorder.mimeType || 'audio/webm' });
          var reader = new FileReader();
          reader.onload = function () {
            var base64 = reader.result.split(',')[1];
            ws.send(JSON.stringify({ type: 'transcribe', data: base64 }));
          };
          reader.readAsDataURL(blob);
        }
        audioChunks = [];
      };

      mediaRecorder.start();
      _updateVisualState('listening');
    } catch (e) {
      console.error('[VoiceChat] Mic error:', e);
      _showError('Microphone access denied');
    }
  }

  function _stopRecording() {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
      mediaRecorder.stop();
    }
    if (mediaStream) {
      mediaStream.getTracks().forEach(function (t) { t.stop(); });
      mediaStream = null;
    }
  }

  // --- Audio Playback ---

  function _playAudioData(base64Data, sampleRate) {
    if (!base64Data) {
      _updateState('listening');
      return;
    }

    try {
      var audioBytes = Uint8Array.from(atob(base64Data), function (c) { return c.charCodeAt(0); });

      // If it's a WAV file, play directly
      var blob = new Blob([audioBytes], { type: 'audio/wav' });
      var url = URL.createObjectURL(blob);
      var audio = new Audio(url);

      audio.onended = function () {
        URL.revokeObjectURL(url);
        _updateState('listening');
        // Auto-restart recording after AI finishes speaking
        if (isVoiceChatActive) {
          _startRecording();
        }
      };

      audio.onerror = function () {
        URL.revokeObjectURL(url);
        _updateState('listening');
      };

      _updateVisualState('speaking');
      audio.play().catch(function (e) {
        console.error('[VoiceChat] Playback error:', e);
        _updateState('listening');
      });
    } catch (e) {
      console.error('[VoiceChat] Audio decode error:', e);
      _updateState('listening');
    }
  }

  // --- UI ---

  function _showModal() {
    var modal = document.getElementById('voiceChatModal');
    if (modal) {
      modal.classList.remove('hidden');
      return;
    }

    // Create modal dynamically
    modal = document.createElement('div');
    modal.id = 'voiceChatModal';
    modal.className = 'fixed inset-0 z-[9999] flex items-center justify-center bg-black bg-opacity-60';
    modal.innerHTML = `
      <div class="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
        <!-- Header -->
        <div class="bg-gradient-to-r from-blue-600 to-indigo-600 px-6 py-4 flex items-center justify-between">
          <div class="flex items-center gap-3">
            <div class="w-10 h-10 bg-white bg-opacity-20 rounded-full flex items-center justify-center">
              <i class="fas fa-headset text-white text-lg"></i>
            </div>
            <div>
              <h3 class="text-white font-semibold text-lg">Voice Chat</h3>
              <p id="vcStateLabel" class="text-blue-100 text-sm">Connecting...</p>
            </div>
          </div>
          <button onclick="stopVoiceChat()" class="text-white hover:text-red-200 transition-colors p-2">
            <i class="fas fa-times text-xl"></i>
          </button>
        </div>

        <!-- Visualization -->
        <div class="px-6 py-8 flex flex-col items-center">
          <div id="vcVisualizer" class="w-24 h-24 rounded-full bg-gray-100 flex items-center justify-center mb-6 transition-all duration-300">
            <i id="vcIcon" class="fas fa-microphone text-3xl text-gray-400 transition-colors duration-300"></i>
          </div>

          <!-- Transcript area -->
          <div id="vcTranscripts" class="w-full max-h-48 overflow-y-auto space-y-2 mb-4">
            <p class="text-center text-gray-400 text-sm" id="vcPlaceholder">Speak to start a conversation...</p>
          </div>
        </div>

        <!-- Controls -->
        <div class="px-6 pb-6 flex justify-center gap-4">
          <button id="vcMicBtn" onclick="_vcToggleMic()" class="w-14 h-14 rounded-full bg-blue-600 text-white flex items-center justify-center hover:bg-blue-700 transition-colors shadow-lg">
            <i class="fas fa-microphone text-xl"></i>
          </button>
          <button onclick="stopVoiceChat()" class="w-14 h-14 rounded-full bg-red-500 text-white flex items-center justify-center hover:bg-red-600 transition-colors shadow-lg">
            <i class="fas fa-phone-slash text-xl"></i>
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
  }

  function _hideModal() {
    var modal = document.getElementById('voiceChatModal');
    if (modal) modal.classList.add('hidden');
  }

  function _updateState(state) {
    currentState = state;
    var label = document.getElementById('vcStateLabel');
    var stateLabels = {
      idle: 'Ready',
      listening: 'Listening...',
      thinking: 'Thinking...',
      speaking: 'Speaking...',
    };
    if (label) label.textContent = stateLabels[state] || state;
    _updateVisualState(state);
  }

  function _updateVisualState(state) {
    var viz = document.getElementById('vcVisualizer');
    var icon = document.getElementById('vcIcon');
    if (!viz || !icon) return;

    // Reset classes
    viz.className = 'w-24 h-24 rounded-full flex items-center justify-center mb-6 transition-all duration-300';

    switch (state) {
      case 'listening':
        viz.classList.add('bg-blue-100', 'animate-pulse');
        icon.className = 'fas fa-microphone text-3xl text-blue-600 transition-colors duration-300';
        break;
      case 'thinking':
        viz.classList.add('bg-yellow-100');
        icon.className = 'fas fa-brain text-3xl text-yellow-600 animate-pulse transition-colors duration-300';
        break;
      case 'speaking':
        viz.classList.add('bg-green-100', 'animate-pulse');
        icon.className = 'fas fa-volume-up text-3xl text-green-600 transition-colors duration-300';
        break;
      default:
        viz.classList.add('bg-gray-100');
        icon.className = 'fas fa-microphone text-3xl text-gray-400 transition-colors duration-300';
    }
  }

  function _addTranscript(role, text) {
    var container = document.getElementById('vcTranscripts');
    var placeholder = document.getElementById('vcPlaceholder');
    if (placeholder) placeholder.remove();
    if (!container) return;

    var div = document.createElement('div');
    div.className = role === 'user'
      ? 'text-right text-sm text-gray-700 bg-blue-50 rounded-lg px-3 py-2'
      : 'text-left text-sm text-gray-700 bg-gray-50 rounded-lg px-3 py-2';
    div.innerHTML = '<span class="font-medium text-xs text-gray-500 block mb-1">'
      + (role === 'user' ? 'You' : 'AI') + '</span>' + _escapeHtml(text);
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
  }

  function _showError(message) {
    if (typeof showToast === 'function') {
      showToast(message, 'error');
    } else {
      console.error('[VoiceChat]', message);
    }
  }

  function _escapeHtml(text) {
    var div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // Exposed for the mic button in the modal
  window._vcToggleMic = function () {
    if (currentState === 'listening') {
      _stopRecording();
    } else if (currentState === 'idle' || currentState === 'listening') {
      _startRecording();
    }
  };

})();
