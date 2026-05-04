/**
 * app.js — FRIDAY voice-first frontend
 * Backend: Groq Cloud via WebSocket
 * TTS: Web Speech API — sentence-streaming for low latency
 * STT: Whisper via /api/transcribe
 */

// ── DOM ──────────────────────────────────────────────────────────────────────
const chatContainer    = document.getElementById('chat-container');
const msgInput         = document.getElementById('msg-input');
const sendBtn          = document.getElementById('send-btn');
const micBtn           = document.getElementById('mic-btn');
const typeMicBtn       = document.getElementById('type-mic-btn');
const stateLabel       = document.getElementById('state-label');
const voiceHint        = document.getElementById('voice-hint');
const micIcon          = document.getElementById('mic-icon');
const stopIcon         = document.getElementById('stop-icon');
const canvas           = document.getElementById('waveform-canvas');
const wCtx             = canvas.getContext('2d');
const modelSelect      = document.getElementById('model-select');
const currentModelLabel = document.getElementById('current-model-label');
const modelSwitchBtn   = document.getElementById('model-switch-btn');
const modelStatus      = document.getElementById('model-status');
const dropZone         = document.getElementById('drop-zone');
const ingestBtn        = document.getElementById('ingest-btn');
const uptimeVal        = document.getElementById('uptime-val');
const settingsBtn      = document.getElementById('settings-btn');
const settingsPanel    = document.getElementById('settings-panel');
const settingsOverlay  = document.getElementById('settings-overlay');
const settingsClose    = document.getElementById('settings-close');

// ── State Machine ────────────────────────────────────────────────────────────
const S = { IDLE: 'idle', LISTENING: 'listening', THINKING: 'thinking', SPEAKING: 'speaking' };
let appState = S.IDLE;

const LABELS = { idle: 'STANDBY', listening: 'LISTENING...', thinking: 'PROCESSING...', speaking: 'SPEAKING' };
const HINTS  = { idle: 'Tap to speak with FRIDAY', listening: 'Tap again to stop', thinking: 'FRIDAY is thinking...', speaking: 'FRIDAY is speaking...' };

function setState(s) {
    appState = s;
    document.body.setAttribute('data-state', s);
    stateLabel.textContent = LABELS[s];
    voiceHint.textContent  = HINTS[s];
    micIcon.style.display  = s === S.LISTENING ? 'none'  : 'block';
    stopIcon.style.display = s === S.LISTENING ? 'block' : 'none';
    typeMicBtn.classList.toggle('active', s === S.LISTENING);
    if (s === S.SPEAKING && !interruptMonitor) startInterruptMonitor();
}

// ── Settings Drawer ──────────────────────────────────────────────────────────
function openSettings()  { settingsPanel.classList.add('open'); settingsOverlay.classList.add('open'); }
function closeSettings() { settingsPanel.classList.remove('open'); settingsOverlay.classList.remove('open'); }
settingsBtn.addEventListener('click', openSettings);
settingsClose.addEventListener('click', closeSettings);
settingsOverlay.addEventListener('click', closeSettings);

// ── WebSocket ────────────────────────────────────────────────────────────────
let ws;
let currentSystemMsg  = null;
let typingIndicatorEl = null;
let sentenceBuffer    = '';
let streamDone        = false;

function connectWebSocket() {
    ws = new WebSocket('ws://' + window.location.host + '/ws/chat');
    ws.onopen  = () => console.log('WS connected');
    ws.onclose = () => { console.log('WS closed — retrying…'); setTimeout(connectWebSocket, 3000); };

    ws.onmessage = ({ data: text }) => {
        if (typingIndicatorEl) { typingIndicatorEl.remove(); typingIndicatorEl = null; }

        if (text === '[DONE]') {
            streamDone = true;
            if (sentenceBuffer.trim()) { enqueueSentence(sentenceBuffer.trim()); sentenceBuffer = ''; }
            currentSystemMsg = null;
            return;
        }
        if (text.startsWith('[Error:')) {
            appendMessage(text, 'system'); setState(S.IDLE); sentenceBuffer = ''; return;
        }

        if (!currentSystemMsg) {
            currentSystemMsg = document.createElement('div');
            currentSystemMsg.className = 'message system';
            const c = document.createElement('div');
            c.className = 'msg-content';
            currentSystemMsg.appendChild(c);
            chatContainer.appendChild(currentSystemMsg);
        }

        currentSystemMsg.querySelector('.msg-content').innerHTML += text.replace(/\n/g, '<br>');
        scrollToBottom();

        sentenceBuffer += text;
        flushSentences();
    };
}

/** Split buffer at sentence boundaries and queue each for TTS.
 *  Also flushes on comma/semicolon after ≥8 words for lower latency. */
function flushSentences() {
    const re = /([^.!?\n]*[.!?])(?=\s|$)|([^\n]+\n)/g;
    let m, last = 0;
    while ((m = re.exec(sentenceBuffer)) !== null) {
        const s = (m[1] || m[2]).trim();
        if (s) enqueueSentence(s);
        last = re.lastIndex;
    }
    // Early flush: long clause at comma boundary (≥8 words) to start speaking sooner
    const remaining = sentenceBuffer.slice(last);
    const commaMatch = remaining.match(/^(.{40,}?[,;])\s/);
    if (commaMatch) {
        enqueueSentence(commaMatch[1].trim());
        last += commaMatch[0].length;
    }
    sentenceBuffer = sentenceBuffer.slice(last);
}

// ── TTS — Kokoro via /api/tts ─────────────────────────────────────────────────
// Ordered slot queue: each sentence reserves an index before async fetch,
// guaranteeing playback order even when shorter sentences synthesise faster.

let ttsAudioCtx = null;
let ttsSlots    = [];     // Array of AudioBuffer | null | 'skip' — indexed by order
let ttsPlayIdx  = 0;      // Next slot index to play
let ttsNextIdx  = 0;      // Next slot index to allocate
let ttsPlaying  = false;
let voiceRate   = 1.0;

function getTTSContext() {
    if (!ttsAudioCtx || ttsAudioCtx.state === 'closed') {
        ttsAudioCtx = new AudioContext();
    }
    return ttsAudioCtx;
}

function cleanForSpeech(t) {
    return t
        .replace(/```[\s\S]*?```/g, 'code block')
        .replace(/`[^`]*`/g, '')
        .replace(/https?:\S+/g, '')
        .replace(/[*_]{1,2}/g, '')
        .replace(/\[(.*?)\]\(.*?\)/g, '$1')
        .replace(/[#>]/g, '')
        .replace(/\s+/g, ' ')
        .trim();
}

async function fetchTTSAudio(text) {
    try {
        const res = await fetch('/api/tts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, speed: voiceRate })
        });
        if (!res.ok) return null;
        const arrayBuf = await res.arrayBuffer();
        if (!arrayBuf.byteLength) return null;
        return await getTTSContext().decodeAudioData(arrayBuf);
    } catch (e) {
        console.error('[TTS]', e);
        return null;
    }
}

function _playNextSlot() {
    if (ttsPlaying) return;
    // Advance past any filled 'skip' slots
    while (ttsPlayIdx < ttsSlots.length && ttsSlots[ttsPlayIdx] === 'skip') {
        ttsPlayIdx++;
    }
    if (ttsPlayIdx >= ttsSlots.length) {
        // No more slots
        if (streamDone) { setState(S.IDLE); streamDone = false; }
        return;
    }
    const buf = ttsSlots[ttsPlayIdx];
    if (buf === null) return;   // slot not yet filled — wait
    ttsPlayIdx++;
    ttsPlaying = true;
    const ctx    = getTTSContext();
    const source = ctx.createBufferSource();
    source.buffer = buf;
    source.connect(ctx.destination);
    source.onended = () => { ttsPlaying = false; _playNextSlot(); };
    source.start(0);
}

async function enqueueSentence(sentence) {
    const text = cleanForSpeech(sentence);
    if (!text) return;
    setState(S.SPEAKING);

    // Reserve slot in order BEFORE async fetch
    const idx = ttsNextIdx++;
    ttsSlots[idx] = null;

    const buffer = await fetchTTSAudio(text);
    ttsSlots[idx] = buffer || 'skip';
    _playNextSlot();   // try to advance — will only play if it's our turn
}

function stopSpeech() {
    if (ttsAudioCtx) { try { ttsAudioCtx.close(); } catch {} ttsAudioCtx = null; }
    ttsSlots    = [];
    ttsPlayIdx  = 0;
    ttsNextIdx  = 0;
    ttsPlaying  = false;
    streamDone  = false;
    sentenceBuffer = '';
    setState(S.IDLE);
}

// ── Waveform Canvas ──────────────────────────────────────────────────────────
let audioContext, analyser, animId;
const CX = canvas.width / 2, CY = canvas.height / 2, R = 88;
const STATE_COLOR = { idle: '#22d3ee', listening: '#34d399', thinking: '#fbbf24', speaking: '#a78bfa' };

function hexRgba(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${n>>16},${(n>>8)&255},${n&255},${a})`;
}

function drawFrame() {
    animId = requestAnimationFrame(drawFrame);
    wCtx.clearRect(0, 0, canvas.width, canvas.height);
    const col = STATE_COLOR[appState] || STATE_COLOR.idle;

    if (analyser && appState === S.LISTENING) {
        const buf = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteFrequencyData(buf);
        const bars = 80, step = (Math.PI * 2) / bars;
        for (let i = 0; i < bars; i++) {
            const val = buf[Math.floor(i * buf.length / bars)] / 255;
            const a   = val * Math.PI * 2 * i / bars - Math.PI / 2;
            const len = val * 52 + 3;
            wCtx.beginPath();
            wCtx.moveTo(CX + Math.cos(a) * R, CY + Math.sin(a) * R);
            wCtx.lineTo(CX + Math.cos(a) * (R + len), CY + Math.sin(a) * (R + len));
            wCtx.strokeStyle = hexRgba(col, val * 0.75 + 0.25);
            wCtx.lineWidth   = 2.5;
            wCtx.lineCap     = 'round';
            wCtx.stroke();
        }
    } else {
        // Ambient static ring
        wCtx.beginPath();
        wCtx.arc(CX, CY, R, 0, Math.PI * 2);
        wCtx.strokeStyle = hexRgba(col, 0.18);
        wCtx.lineWidth   = 1;
        wCtx.stroke();
    }
}
drawFrame();

// ── Voice Recording ──────────────────────────────────────────────────────────
let mediaRecorder, audioChunks = [], mediaStream, isRecording = false;

async function toggleVoice() {
    if (appState === S.LISTENING) { stopRecording(); return; }
    if (appState !== S.IDLE) return;
    if (ttsPlaying) stopSpeech();
    await startRecording();
}

async function startRecording() {
    try {
        mediaStream  = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioContext = new AudioContext();
        analyser     = audioContext.createAnalyser();
        analyser.fftSize = 256;
        audioContext.createMediaStreamSource(mediaStream).connect(analyser);

        mediaRecorder = new MediaRecorder(mediaStream);
        audioChunks   = [];
        mediaRecorder.ondataavailable = e => { if (e.data.size > 0) audioChunks.push(e.data); };
        mediaRecorder.onstop = sendAudio;
        mediaRecorder.start();
        isRecording  = true;
        setState(S.LISTENING);
        startVAD();
    } catch (e) {
        console.error('Mic:', e);
        appendMessage('⚠ Mic access denied or unavailable.', 'system');
    }
}

function stopRecording() {
    if (!isRecording) return;
    stopVAD();
    isRecording = false;
    mediaRecorder?.stop();
    mediaStream?.getTracks().forEach(t => t.stop());
    if (audioContext) { audioContext.close(); audioContext = null; analyser = null; }
    setState(S.THINKING);
}

async function sendAudio() {
    const fd = new FormData();
    fd.append('audio', new Blob(audioChunks, { type: 'audio/webm' }), 'rec.webm');
    try {
        const res  = await fetch('/api/transcribe', { method: 'POST', body: fd });
        const data = await res.json();
        if (data.status === 'success' && data.text?.trim()) {
            appendMessage(data.text, 'user');
            sendViaWS(data.text);
        } else setState(S.IDLE);
    } catch { setState(S.IDLE); }
}

// ── Chat Helpers ─────────────────────────────────────────────────────────────
function sendViaWS(text) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(text); showTyping();
}
function showTyping() {
    const m = document.createElement('div');
    m.className = 'message system';
    m.innerHTML = '<div class="msg-content"><div class="typing-dots"><span></span><span></span><span></span></div></div>';
    chatContainer.appendChild(m); scrollToBottom();
    typingIndicatorEl = m;
}
function appendMessage(text, sender) {
    const m = document.createElement('div');
    m.className = `message ${sender}`;
    m.innerHTML = `<div class="msg-content">${text.replace(/\n/g, '<br>')}</div>`;
    chatContainer.appendChild(m); scrollToBottom();
}
function scrollToBottom() { chatContainer.scrollTop = chatContainer.scrollHeight; }

function sendMessage() {
    const text = msgInput.value.trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
    if (ttsPlaying || appState === S.SPEAKING) stopSpeech();
    appendMessage(text, 'user');
    sendViaWS(text);
    msgInput.value = '';
    setState(S.THINKING);
}

// ── Event Listeners ──────────────────────────────────────────────────────────
micBtn.addEventListener('click', toggleVoice);
typeMicBtn.addEventListener('click', toggleVoice);
sendBtn.addEventListener('click', sendMessage);
msgInput.addEventListener('keypress', e => { if (e.key === 'Enter') sendMessage(); });

// ── Stats ────────────────────────────────────────────────────────────────────
async function updateStats() {
    try {
        const d = await (await fetch('/api/stats')).json();
        document.getElementById('cpu-val').textContent = d.cpu_percent + '%';
        document.getElementById('ram-val').textContent = d.ram_percent + '%';
        if (uptimeVal) uptimeVal.textContent = d.uptime_formatted;
    } catch {}
}

// ── File Drop ────────────────────────────────────────────────────────────────
dropZone.addEventListener('dragover',  e => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', ()  => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', async e => {
    e.preventDefault(); dropZone.classList.remove('dragover');
    for (const file of e.dataTransfer.files) {
        const fd = new FormData(); fd.append('file', file);
        dropZone.textContent = `Uploading ${file.name}…`;
        try { await fetch('/api/upload', { method: 'POST', body: fd }); } catch {}
    }
    dropZone.textContent = 'Drop files to ingest into RAG';
});

ingestBtn?.addEventListener('click', async () => {
    ingestBtn.textContent = 'INGESTING...';
    try { await fetch('/api/ingest', { method: 'POST' }); ingestBtn.textContent = 'DONE ✓'; }
    catch { ingestBtn.textContent = 'ERROR'; }
    setTimeout(() => ingestBtn.textContent = 'FORCE INGEST DIRECTORY', 2000);
});

// ── Model Switcher ───────────────────────────────────────────────────────────
async function loadModels() {
    try {
        const d = await (await fetch('/api/models')).json();
        modelSelect.innerHTML = '';
        d.models.forEach(m => {
            const o = document.createElement('option');
            o.value = m; o.textContent = m;
            if (m === d.current) o.selected = true;
            modelSelect.appendChild(o);
        });
        if (currentModelLabel) currentModelLabel.textContent = d.current;
    } catch {}
}

modelSwitchBtn?.addEventListener('click', async () => {
    const model = modelSelect.value; if (!model) return;
    modelSwitchBtn.textContent = 'SWITCHING...';
    try {
        const d = await (await fetch('/api/set-model', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model })
        })).json();
        if (d.status === 'success') {
            if (currentModelLabel) currentModelLabel.textContent = d.model;
            modelStatus.textContent = `✓ ${d.model}`;
            setTimeout(() => modelStatus.textContent = '', 3000);
        } else modelStatus.textContent = d.error || 'Error';
    } catch { modelStatus.textContent = 'Network error'; }
    modelSwitchBtn.textContent = 'SWITCH MODEL';
});

// ── #15 Voice Speed Slider ────────────────────────────────────────────────────
voiceRate = 0.97; // initial value for speed slider

const speedSlider = document.getElementById('speed-slider');
const speedVal    = document.getElementById('speed-val');
if (speedSlider) {
    speedSlider.addEventListener('input', () => {
        voiceRate = parseFloat(speedSlider.value);
        speedVal.textContent = voiceRate.toFixed(2);
    });
}
// Speed is sent with each /api/tts request.

// ── #4 Silence Auto-Stop (VAD while recording) ───────────────────────────────
let vadInterval = null;
const SILENCE_THRESHOLD = 8;    // RMS below this = silence
const SILENCE_DURATION  = 1500; // ms of silence before auto-stop
let silenceStart = null;

function startVAD() {
    if (!analyser) return;
    silenceStart = null;
    vadInterval  = setInterval(() => {
        if (!analyser || appState !== S.LISTENING) { stopVAD(); return; }
        const buf = new Uint8Array(analyser.frequencyBinCount);
        analyser.getByteTimeDomainData(buf);
        const rms = Math.sqrt(buf.reduce((s, v) => s + (v - 128) ** 2, 0) / buf.length);
        if (rms < SILENCE_THRESHOLD) {
            if (!silenceStart) silenceStart = Date.now();
            else if (Date.now() - silenceStart > SILENCE_DURATION) {
                console.log('[VAD] Silence detected — auto-stopping');
                stopVAD(); stopRecording();
            }
        } else silenceStart = null;
    }, 100);
}

function stopVAD() { clearInterval(vadInterval); vadInterval = null; }

// ── #14 Interrupt by speaking while FRIDAY talks ─────────────────────────────
let interruptMonitor = null;

function startInterruptMonitor() {
    if (!navigator.mediaDevices) return;
    navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
        const ctx   = new AudioContext();
        const src   = ctx.createMediaStreamSource(stream);
        const mon   = ctx.createAnalyser();
        mon.fftSize = 256;
        src.connect(mon);
        interruptMonitor = setInterval(() => {
            if (appState !== S.SPEAKING) {
                clearInterval(interruptMonitor);
                interruptMonitor = null;
                ctx.close();
                stream.getTracks().forEach(t=>t.stop());
                return;
            }
            const buf = new Uint8Array(mon.frequencyBinCount);
            mon.getByteTimeDomainData(buf);
            const rms = Math.sqrt(buf.reduce((s,v) => s + (v-128)**2, 0) / buf.length);
            if (rms > 18) {  // voice detected — interrupt FRIDAY
                console.log('[Interrupt] Voice detected while speaking');
                stopSpeech();
                clearInterval(interruptMonitor);
                interruptMonitor = null;
                ctx.close(); stream.getTracks().forEach(t=>t.stop());
                setTimeout(() => startRecording(), 150);
            }
        }, 80);
    }).catch(() => {});
}

// ── #1 Wake Word — "Hey FRIDAY" / "Friday" ───────────────────────────────────
let wakeRecognition = null;

function startWakeWord() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return;
    wakeRecognition = new SR();
    wakeRecognition.continuous    = true;
    wakeRecognition.interimResults = true;
    wakeRecognition.lang          = 'en-US';
    wakeRecognition.onresult = (e) => {
        const transcript = Array.from(e.results).map(r => r[0].transcript).join(' ').toLowerCase();
        if (transcript.includes('friday') && appState === S.IDLE) {
            console.log('[Wake] Wake word detected!');
            wakeRecognition.stop();
            appendMessage('🎙 Wake word detected', 'system');
            setTimeout(() => startRecording(), 300);
            // Restart wake word after interaction ends
            const waitForIdle = setInterval(() => {
                if (appState === S.IDLE) { clearInterval(waitForIdle); setTimeout(startWakeWord, 1000); }
            }, 500);
        }
    };
    wakeRecognition.onerror = (e) => { if (e.error !== 'no-speech') console.warn('[Wake]', e.error); };
    wakeRecognition.onend   = () => {};  // auto-restarts via the idle watcher above
    try { wakeRecognition.start(); console.log('[Wake] Listening for "Hey FRIDAY"…'); }
    catch {}
}

// ── #6 Memory Browser ─────────────────────────────────────────────────────────
const memoriesList = document.getElementById('memories-list');
const memCount     = document.getElementById('mem-count');

async function loadMemories() {
    if (!memoriesList) return;
    try {
        const d = await (await fetch('/api/memories')).json();
        memCount.textContent = `(${d.memories.length})`;
        memoriesList.innerHTML = '';
        if (!d.memories.length) { memoriesList.innerHTML = '<div style="color:var(--muted);font-size:12px;">No memories yet.</div>'; return; }
        d.memories.forEach(m => {
            const card = document.createElement('div');
            card.style.cssText = 'background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:6px;padding:8px 10px;display:flex;justify-content:space-between;align-items:flex-start;gap:8px;';
            card.innerHTML = `
                <div style="flex:1;min-width:0;">
                    <div style="font-family:var(--mono);font-size:9px;color:var(--muted);margin-bottom:3px;">${m.date}</div>
                    <div style="font-size:11px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${m.preview}</div>
                </div>
                <button data-file="${m.filename}" style="background:transparent;border:1px solid rgba(239,68,68,.3);color:#f87171;padding:2px 7px;border-radius:4px;cursor:pointer;font-size:10px;flex-shrink:0;">✕</button>`;
            card.querySelector('button').addEventListener('click', async (e) => {
                const fn = e.target.dataset.file;
                await fetch(`/api/memories/${fn}`, { method: 'DELETE' });
                loadMemories();
            });
            memoriesList.appendChild(card);
        });
    } catch {}
}

// ── #9 Tasks Panel ────────────────────────────────────────────────────────────
const tasksList = document.getElementById('tasks-list');

async function loadTasks() {
    if (!tasksList) return;
    try {
        const d = await (await fetch('/api/tasks')).json();
        if (!d.tasks.length) { tasksList.textContent = 'No pending tasks.'; return; }
        tasksList.innerHTML = d.tasks.map(t => `• ${t.task}`).join('<br>');
    } catch { tasksList.textContent = 'Could not load tasks.'; }
}

// Reload when settings opens
settingsBtn.addEventListener('click', () => { loadMemories(); loadTasks(); });

// ── #13 Token Usage Meter ─────────────────────────────────────────────────────
// Estimate tokens from chunk count (rough: 1 word ≈ 1.3 tokens)
let sessionTokens = 0;
const cpuChip = document.getElementById('cpu-val');

// ── Init ─────────────────────────────────────────────────────────────────────
connectWebSocket();
setInterval(updateStats, 3000);
updateStats();
loadModels();
startWakeWord();       // #1 Wake word
