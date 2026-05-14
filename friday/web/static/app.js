const chat = document.getElementById("chat");
const form = document.getElementById("form");
const input = document.getElementById("input");
const btnSend = document.getElementById("btnSend");
const btnClear = document.getElementById("btnClear");
const btnVoice = document.getElementById("btnVoice");
const speakingIndicator = document.getElementById("speakingIndicator");
const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const voiceStack = document.getElementById("voiceStack");
const llmStack = document.getElementById("llmStack");
const phaseFeed = document.getElementById("phaseFeed");
const versionTag = document.getElementById("versionTag");
const badgeMemory = document.getElementById("badgeMemory");
const badgeTts    = document.getElementById("badgeTts");
const badgeStt    = document.getElementById("badgeStt");

if (window.marked && window.hljs) {
  marked.use({
    renderer: {
      // marked v9+: code() receives a single object {text, lang, escaped}
      code({ text, lang }) {
        const language = (lang && hljs.getLanguage(lang)) ? lang : 'plaintext';
        const highlighted = hljs.highlight(text || '', { language }).value;
        return `<pre><code class="hljs language-${language}">${highlighted}</code></pre>`;
      }
    }
  });
}

function safeParse(md) {
  try {
    return window.DOMPurify
      ? DOMPurify.sanitize(marked.parse(md))
      : marked.parse(md);
  } catch {
    // Fallback: escape and render as plain text
    return md.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }
}


let isVoiceMode = false;
let recognition = null;

// ── Audio queue (sentence-level streaming TTS) ───────────────────────────────
let _currentAudio = null;
let _audioQueue    = [];
let _isPlaying     = false;
let _ttsSentBuf    = '';   // accumulates tokens until a sentence boundary
let _speakAbort    = null; // AbortController for the current /api/speak fetch

function _cleanForSpeech(raw) {
  let t = raw;

  // 1. Drop fenced code blocks (skip them entirely, don't say "code block")
  t = t.replace(/```[\s\S]*?```/g, '');

  // 2. Inline code → bare text
  t = t.replace(/`([^`]+)`/g, '$1');

  // 3. Markdown links → label only
  t = t.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');

  // 4. Remove bare URLs
  t = t.replace(/https?:\/\/\S+/g, '');

  // 5. Numbered list items → "First, ...", "Second, ..." etc.
  const ordinals = ['First','Second','Third','Fourth','Fifth','Sixth','Seventh','Eighth','Ninth','Tenth'];
  t = t.replace(/^\s*(\d+)[.):]\s+(.+)$/gm, (_, n, content) => {
    const word = ordinals[parseInt(n, 10) - 1] || `Number ${n}`;
    // Strip any trailing bold-colon pattern inside the item for natural flow
    const cleaned = content.replace(/\*{1,2}([^*]+)\*{1,2}\s*:\s*/g, '$1, ');
    return `${word}, ${cleaned}.`;
  });

  // 6. Bullet points → sentence. "- **Term**: desc" → "Term, desc."
  t = t.replace(/^[\s]*[-*\u2022]\s+(.+)$/gm, (_, item) => {
    const s = item
      .replace(/\*{1,2}([^*]+)\*{1,2}\s*:\s*/g, '$1, ')  // **Term**: → "Term, "
      .replace(/\*{1,2}([^*]+)\*{1,2}/g, '$1')            // remaining bold
      .replace(/_{1,2}([^_]+)_{1,2}/g, '$1')              // italic
      .trim();
    return s.endsWith('.') ? s : s + '.';
  });

  // 7. Headers → introduce as a statement
  t = t.replace(/#{1,6}\s+(.+)/g, '$1. ');

  // 8. Unwrap remaining bold / italic
  t = t.replace(/\*{1,2}([^*]+)\*{1,2}/g, '$1');
  t = t.replace(/_{1,2}([^_]+)_{1,2}/g, '$1');

  // 9. Table pipes → space
  t = t.replace(/\|/g, ' ');

  // 10. Colon after a word → comma ("types: A, B" → "types, A, B")
  t = t.replace(/(\w):\s+/g, '$1, ');

  // 11. Semicolons → full stop (stronger break)
  t = t.replace(/;\s*/g, '. ');

  // 12. Em-dash / en-dash / double-hyphen → comma pause
  t = t.replace(/[\u2014\u2013]|--/g, ', ');

  // 13. Remove stray bracket characters (content already extracted)
  t = t.replace(/[([{<>)\]}>]/g, '');

  // 14. Remove symbols that sound weird when spoken
  t = t.replace(/[#\\^~=+*_]/g, '');

  // 15. Collapse ellipsis to single period
  t = t.replace(/\.{2,}/g, '.');

  // 16. Collapse repeated commas / punctuation
  t = t.replace(/([,.]){2,}/g, '$1');
  t = t.replace(/,\s*\./g, '.');

  // 17. Normalise whitespace
  t = t.replace(/\n+/g, ' ').replace(/\s{2,}/g, ' ').trim();

  return t;
}

function _playNextAudio() {
  if (_isPlaying || _audioQueue.length === 0) return;
  _isPlaying = true;
  const { url, fallback } = _audioQueue.shift();
  const audio = new Audio(url);
  _currentAudio = audio;
  const done = () => {
    URL.revokeObjectURL(url);
    _currentAudio = null;
    _isPlaying = false;
    setSpeaking(false);
    _playNextAudio();
  };
  audio.onended = done;
  audio.onerror = () => { done(); _fallbackSpeak(fallback); };
  setSpeaking(true);
  audio.play().catch(() => { done(); _fallbackSpeak(fallback); });
}

async function _queueTTS(sentence) {
  const clean = _cleanForSpeech(sentence);
  if (!clean || clean.length < 4) return;
  try {
    const res = await fetch('/api/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: clean }),
    });
    if (!res.ok) throw new Error(`TTS ${res.status}`);
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    _audioQueue.push({ url, fallback: clean });
    _playNextAudio();
  } catch {
    _fallbackSpeak(clean);
  }
}

function _stopAllAudio() {
  // Abort any in-flight /api/speak request so its response is never played
  if (_speakAbort) { _speakAbort.abort(); _speakAbort = null; }
  if (_currentAudio) { _currentAudio.pause(); _currentAudio = null; }
  _audioQueue.forEach(({ url }) => URL.revokeObjectURL(url));
  _audioQueue = [];
  _isPlaying  = false;
  _ttsSentBuf = '';
  setSpeaking(false);
  if (window.speechSynthesis) window.speechSynthesis.cancel();
}

// Extract complete chunks from _ttsSentBuf and queue TTS immediately.
// Splits on: sentence-ending punctuation (.!?) OR a newline (each bullet = one line).
function _flushSentences(force = false) {
  // Match up to and including a sentence-ender OR up to a newline boundary
  const re = /^([\s\S]+?)([.!?](?=[\s"'\u201D]|$)|\n)/m;
  while (true) {
    const m = _ttsSentBuf.match(re);
    if (!m) break;
    const chunk = (m[1] + m[2]).trim();
    _ttsSentBuf = _ttsSentBuf.slice(m.index + m[0].length).trimStart();
    if (chunk) _queueTTS(chunk);  // fire and forget
  }
  if (force && _ttsSentBuf.trim()) {
    _queueTTS(_ttsSentBuf);
    _ttsSentBuf = '';
  }
}

if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRec();
  recognition.continuous = false;
  recognition.interimResults = true;
  
  recognition.onresult = (e) => {
    let interim = '';
    let final = '';
    for (let i = e.resultIndex; i < e.results.length; ++i) {
      if (e.results[i].isFinal) final += e.results[i][0].transcript;
      else interim += e.results[i][0].transcript;
    }
    input.value = final || interim;
    autoGrow();
  };
  
  recognition.onend = () => {
    btnVoice.classList.remove("recording");
    if (input.value.trim() && isVoiceMode) {
      form.requestSubmit();
    }
  };
}

btnVoice.addEventListener("click", () => {
  if (!recognition) {
    alert("Speech recognition is not supported in your browser. Please use Chrome.");
    return;
  }
  if (btnVoice.classList.contains("recording")) {
    recognition.stop();
    return;
  }
  isVoiceMode = true;
  btnVoice.classList.add("recording");
  input.value = "";
  recognition.start();
});

function autoGrow() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 180) + "px";
}

input.addEventListener("input", autoGrow);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

function scrollToBottom() {
  chat.scrollTop = chat.scrollHeight;
}

function removeWelcome() {
  const w = chat.querySelector(".welcome");
  if (w) w.remove();
}

function addMessage(role, text) {
  removeWelcome();
  const wrap = document.createElement("div");
  wrap.className = `msg ${role === "user" ? "user" : "ai"}`;
  const label = document.createElement("div");
  label.className = "msg-label";
  label.textContent = role === "user" ? "You" : "FRIDAY";
  const body = document.createElement("div");
  body.className = "msg-body";
  if (role === "ai" && window.marked && text) {
    body.innerHTML = safeParse(text);
  } else {
    body.textContent = text;
  }
  wrap.append(label, body);
  chat.appendChild(wrap);
  scrollToBottom();
  return { wrap, body };
}

function createStreamAnimator(messageWrap, bodyEl) {
  let targetText = "";
  let visibleCount = 0;
  let timer = null;
  let finished = false;

  const render = (showCursor = true) => {
    bodyEl.textContent = targetText.slice(0, visibleCount);
    if (showCursor) {
      const cursor = document.createElement("span");
      cursor.className = "jarvis-cursor";
      cursor.textContent = " ";
      bodyEl.appendChild(cursor);
    }
    scrollToBottom();
  };

  const stop = () => {
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
  };

  messageWrap.classList.add("jarvis-streaming");
  render(true);

  timer = setInterval(() => {
    if (finished) return;
    const remaining = targetText.length - visibleCount;
    if (remaining <= 0) return;
    const step = remaining > 180 ? 10 : remaining > 90 ? 6 : remaining > 35 ? 3 : 1;
    visibleCount = Math.min(targetText.length, visibleCount + step);
    render(true);
  }, 24);

  return {
    push(chunk) {
      if (finished || !chunk) return;
      targetText += chunk;
    },
    finalize(fullText) {
      finished = true;
      stop();
      messageWrap.classList.remove("jarvis-streaming");
      messageWrap.classList.add("jarvis-stabilized");
      if (window.marked) {
        bodyEl.innerHTML = safeParse(fullText);
      } else {
        bodyEl.textContent = fullText;
      }
      scrollToBottom();
      setTimeout(() => messageWrap.classList.remove("jarvis-stabilized"), 500);
    },
    fail(message) {
      finished = true;
      stop();
      messageWrap.classList.remove("jarvis-streaming");
      messageWrap.classList.remove("jarvis-stabilized");
      bodyEl.textContent = message;
      scrollToBottom();
    },
  };
}

function setBusy(busy, label = busy ? "Neural pipeline…" : "Online") {
  btnSend.disabled = busy;
  btnSend.classList.toggle("sending", busy);
  statusDot.classList.toggle("busy", busy);
  statusText.textContent = label;
}

function setSpeaking(speaking) {
  if (speakingIndicator) speakingIndicator.hidden = !speaking;
}

function clearPhaseFeed() {
  phaseFeed.innerHTML = "";
}

function pushPhase(ev) {
  const el = document.createElement("div");
  el.className = "phase-line";
  el.innerHTML = `
    <span class="ph-id">${escapeHtml(ev.id || "")}</span>
    <div class="ph-title">${escapeHtml(ev.title || "")}</div>
    <div class="ph-detail">${escapeHtml(ev.detail || "")}</div>`;
  phaseFeed.appendChild(el);
  phaseFeed.scrollTop = phaseFeed.scrollHeight;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderSpecGrid(dl, rows) {
  dl.innerHTML = "";
  for (const [dt, dd] of rows) {
    const a = document.createElement("dt");
    a.textContent = dt;
    const b = document.createElement("dd");
    b.textContent = dd;
    dl.append(a, b);
  }
}

function _setBadge(el, ready) {
  if (!el) return;
  el.className = `status-badge ${ready ? "active" : "loading"}`;
  el.textContent = ready ? "Active" : "Loading";
}

async function loadSystem() {
  try {
    const r = await fetch("/api/system");
    if (!r.ok) throw new Error("system");
    const d = await r.json();

    // Version pill
    const ui = d.ui || {};
    if (versionTag) versionTag.textContent = ui.version || "v2.0 Sentinel";

    // Readiness badges
    const rd = d.readiness || {};
    _setBadge(badgeMemory, rd.memory_ready);
    _setBadge(badgeTts,    rd.tts_ready);
    _setBadge(badgeStt,    rd.stt_ready ?? true);

    // Voice stack spec grid
    const v = d.voice || {};
    renderSpecGrid(voiceStack, [
      ["STT", `${v.stt_model || "?"} · ${v.stt_compute || ""}`.trim()],
      ["Device", v.stt_device || "cpu"],
      ["TTS", v.tts_backend || "auto"],
      ["Voice", v.tts_voice || "—"],
      ["VAD", `mode ${v.vad_mode ?? "2"}`],
    ]);

    // LLM stack spec grid
    const L = d.llm || {};
    renderSpecGrid(llmStack, [
      ["Provider", L.llm_provider || "—"],
      ["Model", L.llm_model || "—"],
      ["Host", L.llm_url_host || "—"],
      ["Turns", String(d.history_turns ?? 0)],
    ]);
  } catch {
    if (versionTag) versionTag.textContent = "v2.0 Sentinel";
    voiceStack.innerHTML = "<p class='ph-detail'>Could not load stack info.</p>";
  }
}

async function parseSSE(reader, decoder, handlers) {
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const raw = buffer.slice(0, idx).trim();
      buffer = buffer.slice(idx + 2);
      if (!raw.startsWith("data:")) continue;
      const data = raw.slice(5).trim();
      if (data === "[DONE]") return;
      let obj;
      try {
        obj = JSON.parse(data);
      } catch {
        continue;
      }
      if (obj.type === "error") throw new Error(obj.message || "Stream error");
      if (obj.type === "phase" && handlers.onPhase) handlers.onPhase(obj);
      if (obj.type === "token" && obj.text && handlers.onToken) handlers.onToken(obj.text);
    }
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;

  removeWelcome();
  addMessage("user", text);
  input.value = "";
  autoGrow();

  _stopAllAudio();   // cancel any audio from the previous response

  const aiMessage = addMessage("ai", "");
  const aiBody = aiMessage.body;
  const streamAnimator = createStreamAnimator(aiMessage.wrap, aiBody);
  clearPhaseFeed();
  setBusy(true);

  try {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, voice_mode: isVoiceMode }),
    });

    if (!res.ok) {
      const errText = await res.text();
      throw new Error(errText || res.statusText);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let full = "";
    let sawToken = false;

    await parseSSE(reader, decoder, {
      onPhase: (ev) => {
        pushPhase(ev);
        statusText.textContent = ev.title || "Working…";
      },
      onToken: (chunk) => {
        if (!sawToken) {
          sawToken = true;
          pushPhase({
            id: "stream",
            title: "Token stream",
            detail: "Primary language channel open · receiving deltas",
          });
        }
        full += chunk;
        streamAnimator.push(chunk);
      },
    });

    if (full.trim()) {
      streamAnimator.finalize(full);
      pushPhase({
        id: "commit",
        title: "Lattice sealed",
        detail: "Response materialized · dialogue core synchronized",
      });

      // Use LLM-powered prose conversion for high-quality speech.
      // AbortController ensures only one speak request is ever active —
      // if the user sends a new message, _stopAllAudio() aborts this fetch
      // before the response arrives, preventing double-audio playback.
      (async () => {
        const ctrl = new AbortController();
        _speakAbort = ctrl;          // register so _stopAllAudio() can cancel it
        try {
          const r = await fetch("/api/speak", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: full }),
            signal: ctrl.signal,     // tied to the abort controller
          });
          if (!r.ok) throw new Error(`speak ${r.status}`);
          const blob = await r.blob();
          // Only play if this request wasn't aborted by a newer message
          if (ctrl.signal.aborted) return;
          const url   = URL.createObjectURL(blob);
          const audio = new Audio(url);
          _currentAudio = audio;
          _speakAbort   = null;      // fetch done, clear controller
          audio.play();
          setSpeaking(true);
          audio.onended = () => { URL.revokeObjectURL(url); _currentAudio = null; setSpeaking(false); };
          audio.onerror = () => { URL.revokeObjectURL(url); _currentAudio = null; setSpeaking(false); };
        } catch (err) {
          if (err.name === "AbortError") return;  // intentionally cancelled — silent
          _flushSentences(true);                  // network/TTS error — use fallback
        }
      })();
    } else {
      streamAnimator.finalize(full);
    }
  } catch (err) {
    _stopAllAudio();
    streamAnimator.fail(`[Error: ${err.message || err}]`);
    pushPhase({
      id: "fault",
      title: "Subsystem fault",
      detail: String(err.message || err),
    });
  } finally {
    setBusy(false);
    isVoiceMode = false;
    await loadSystem();
  }
});

btnClear.addEventListener("click", async () => {
  try {
    await fetch("/api/clear", { method: "POST" });
    chat.innerHTML = `
      <div class="welcome">
        <p class="welcome-line anim-fade">Session cleared, sir.</p>
        <p class="welcome-sub anim-fade" style="animation-delay:200ms">Ask anything when ready.</p>
      </div>`;
    clearPhaseFeed();
    statusText.textContent = "Online";
    await loadSystem();
  } catch {
    statusText.textContent = "Clear failed";
  }
});

loadSystem();
