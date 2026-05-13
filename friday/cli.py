"""
cli.py  —  F.R.I.D.A.Y  Terminal Interface
Always-on VAD voice  |  Interruptible TTS  |  Streaming LLM
"""

# ── Encoding fix — MUST be first ──────────────────────────────────────────────
import io, os, sys, warnings, logging
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
os.environ["HF_HUB_VERBOSITY"] = "error"
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)
# Silence noisy loggers from HF / mem0 / spaCy
for _logger_name in ("huggingface_hub", "sentence_transformers", "mem0", "chromadb", "spacy"):
    logging.getLogger(_logger_name).setLevel(logging.ERROR)
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import asyncio
import random
import threading
import time
from datetime import datetime
from functools import partial
from pathlib import Path

# ── Path / env ────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.chdir(HERE)
from dotenv import load_dotenv
load_dotenv(HERE / ".env")

from backend.voice_dashboard import render_voice_pipeline_panel
from backend.voice_state import PipelineStage, VoicePipelineModel

# ── Rich ──────────────────────────────────────────────────────────────────────
from rich.console import Console
from rich.panel   import Panel
from rich.text    import Text
from rich.table   import Table
from rich.columns import Columns
from rich.rule    import Rule
from rich.align   import Align
from rich.live    import Live
from rich.markup  import escape
from rich         import box

# ── Internal ─────────────────────────────────────────────────────────────────
# Deferred: backend is imported AFTER boot banner shows to minimize perceived lag
brain = None
rag   = None

# ─────────────────────────────────────────────────────────────────────────────
#  Theme
# ─────────────────────────────────────────────────────────────────────────────
C_CYAN    = "bright_cyan"
C_GOLD    = "yellow"
C_RED     = "bright_red"
C_WHITE   = "bright_white"
C_DIM     = "grey50"
C_GREEN   = "bright_green"
C_MAGENTA = "magenta"

HUD_BOX   = box.HEAVY
INNER_BOX = box.SIMPLE_HEAVY

console = Console(highlight=False, markup=True)

# ─────────────────────────────────────────────────────────────────────────────
#  Shared state
# ─────────────────────────────────────────────────────────────────────────────
# Set this to immediately stop active TTS playback AND streaming
interrupt_event = threading.Event()

# Holds the active ContinuousListener so TTS consumer can update echo reference
_active_listener = None

# Live voice pipeline dashboard (Rich) + STT hooks
voice_pipeline_viz = None

# In-memory chat log
chat_log: list[dict] = []


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")

def _log(role: str, text: str):
    chat_log.append({"role": role, "text": text, "ts": _ts()})

def hud_command_bar() -> str:
    return f"  [{C_DIM}]Commands: [V]oice toggle  |  [I]ngest  |  [C]lear  |  [S]tatus  |  [Q]uit[/{C_DIM}]"

# ─────────────────────────────────────────────────────────────────────────────
#  Boot sequence
# ─────────────────────────────────────────────────────────────────────────────
def boot_sequence():
    console.clear()
    try:
        from backend.brain import _chat_stream_config
    except Exception:
        console.print(f"  [bold {C_RED}]FATAL: could not load brain module[/]")
        sys.exit(1)

    _url, key, model, provider = _chat_stream_config()
    if not key or "your_" in key.lower():
        console.print(
            f"  [bold {C_RED}]FATAL: no LLM API key for {provider}.[/]\n"
            f"  [{C_DIM}]Set OPENROUTER_API_KEY (and optional OPENROUTER_MODEL) or GROQ_API_KEY in .env[/]"
        )
        sys.exit(1)

    console.print(
        f"\n  [bold {C_CYAN}]F.R.I.D.A.Y ONLINE[/]  //  {_ts()}  //  "
        f"[bold {C_GREEN}]{provider}[/]  [dim]·[/dim]  [bold {C_WHITE}]{model}[/]"
    )
    console.print(f"  [{C_DIM}]Loading modules...[/{C_DIM}]\n")
    console.print(hud_command_bar())
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
#  Status dashboard
# ─────────────────────────────────────────────────────────────────────────────
def show_status():
    console.print(f"\n  [bold {C_GOLD}]SYSTEM STATUS[/]")
    try:
        from backend.brain import _chat_stream_config
        _u, _k, active_model, active_provider = _chat_stream_config()
    except Exception:
        active_model, active_provider = "?", "?"

    rows = [
        ("LLM BACKEND",     f"{active_provider} / {active_model}"),
        ("VECTOR STORE",    "CHROMA-DB LOCAL"),
        ("WHISPER STT",     os.getenv("FRIDAY_WHISPER_MODEL", "small") + " " + os.getenv("FRIDAY_WHISPER_COMPUTE", "int8")),
        ("VAD ENGINE",      "WEBRTC 30ms"),
        ("TTS BACKEND",     os.getenv("FRIDAY_TTS_BACKEND", "auto")),
        ("EDGE-TTS",        "en-GB-SoniaNeural"),
        ("MEMORY",          f"{len(chat_log)} msgs in session"),
    ]
    if _active_listener:
        rows.append(("UTTERANCES",   str(_active_listener._utterance_count)))
        rows.append(("LAST STT",     f"{_active_listener._last_transcription_ms:.0f}ms"))
        rows.append(("NOISE GATE",   f"{_active_listener.dynamic_threshold:.5f}"))
    for name, metric in rows:
        console.print(f"  [{C_CYAN}]{name:<15}[/] : [{C_WHITE}]{metric}[/]")
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
#  HUD panels for conversation
# ─────────────────────────────────────────────────────────────────────────────
def print_user_msg(text: str, source: str = "KEYBOARD"):
    icon = "[MIC]" if source == "VOICE" else ""
    color = C_MAGENTA if source == "VOICE" else C_GOLD
    console.print(f"\n  [bold {color}]You {icon}[/] > {escape(text)}")


# ─────────────────────────────────────────────────────────────────────────────
#  Sentence boundary detection
# ─────────────────────────────────────────────────────────────────────────────
import re as _re
_SENT_END = _re.compile(r'(?<=[.!?])\s')

def _split_sentences(buf: str) -> tuple[list[str], str]:
    """
    Split buf into complete sentences + leftover partial sentence.
    Returns ([complete, ...], remainder).
    """
    parts = _SENT_END.split(buf)
    if len(parts) <= 1:
        return [], buf          # no complete sentence yet
    complete  = parts[:-1]      # all but the last fragment
    remainder = parts[-1]       # partial sentence still being built
    return complete, remainder


# ─────────────────────────────────────────────────────────────────────────────
#  TTS consumer — plays sentences as soon as they arrive
# ─────────────────────────────────────────────────────────────────────────────
async def _tts_consumer(tts_q: asyncio.Queue, viz: VoicePipelineModel | None = None):
    """Background task: synthesize and play each sentence in order."""
    try:
        from backend.tts import synthesize, play_interruptible
    except ImportError:
        return

    loop = asyncio.get_running_loop()
    audio_tasks: asyncio.Queue = asyncio.Queue()

    async def synthesizer_worker():
        while True:
            sentence = await tts_q.get()
            if sentence is None:
                await audio_tasks.put((None, None))
                break
            if interrupt_event.is_set():
                continue
            task = asyncio.create_task(synthesize(sentence))
            await audio_tasks.put((sentence, task))

    synth_worker = asyncio.create_task(synthesizer_worker())

    try:
        while True:
            sentence, task = await audio_tasks.get()
            if sentence is None:
                break
            try:
                if viz:
                    viz.set_tts_backend(os.getenv("FRIDAY_TTS_BACKEND", "auto"))
                    viz.set_stage(PipelineStage.TTS_SYNTHESIZING)
                    viz.set_tts_sentence(sentence[:400])
                audio, suffix, echo_pcm = await task
                if audio and not interrupt_event.is_set():
                    if _active_listener and echo_pcm:
                        _active_listener.tts_reference_frame = echo_pcm[:960]
                    elif _active_listener:
                        _active_listener.tts_reference_frame = b""
                    if viz:
                        viz.set_stage(PipelineStage.TTS_PLAYING)
                    await loop.run_in_executor(
                        None,
                        partial(play_interruptible, audio, interrupt_event, suffix, echo_pcm),
                    )
            except Exception as e:
                console.print(f"  [{C_DIM}]TTS Error: {e}[/]")
                if viz:
                    viz.set_error(str(e))
    finally:
        synth_worker.cancel()
        try:
            await synth_worker
        except asyncio.CancelledError:
            pass
    if viz:
        viz.clear_tts_sentence()
        viz.set_stage(PipelineStage.LISTENING)


# ─────────────────────────────────────────────────────────────────────────────
#  Streaming response + sentence-streaming TTS (zero extra lag)
# ─────────────────────────────────────────────────────────────────────────────
async def stream_and_display(
    user_msg: str, voice_mode: bool = False, viz: VoicePipelineModel | None = None
) -> str:
    """
    Stream tokens from Groq while simultaneously:
      - Printing them to the terminal live
      - Splitting into sentences and queuing them for TTS playback
    """

    def _reset_viz_after_stream():
        if not viz:
            return
        viz.clear_llm_buf()
        viz.set_stage(PipelineStage.LISTENING if voice_mode else PipelineStage.IDLE)

    if viz:
        viz.set_stage(PipelineStage.LLM_STREAMING)
        viz.clear_llm_buf()

    full = ""
    sent_buf = ""
    tts_q = asyncio.Queue() if voice_mode else None
    tts_task = asyncio.create_task(_tts_consumer(tts_q, viz)) if voice_mode else None

    gen = brain.stream_response(user_msg, voice_mode=voice_mode)

    with console.status(f"  [{C_CYAN}]Thinking...[/]", spinner="dots"):
        try:
            first = await gen.__anext__()
        except StopAsyncIteration:
            if tts_q:
                await tts_q.put(None)
            _reset_viz_after_stream()
            return ""

    if interrupt_event.is_set():
        if tts_q:
            await tts_q.put(None)
        _reset_viz_after_stream()
        return ""

    # Print response header — leading \n ensures we're on a fresh line
    # (user's typed text occupies the 'You > ' line; this separates cleanly)
    console.print(f"\n  [bold {C_CYAN}]FRIDAY[/] [dim]>[/dim] ", end="")
    console.file.flush()

    # Stream + collect sentences
    for chunk in [first]:
        full += chunk
        sent_buf += chunk
        if viz:
            viz.append_llm_token(chunk)
        console.print(chunk, end="", style=C_WHITE, highlight=False)

    async for chunk in gen:
        if interrupt_event.is_set():
            console.print(
                f"\n\n  [bold {C_RED}][INTERRUPTED BY SIR][/]", highlight=False)
            break
        full += chunk
        sent_buf += chunk
        if viz:
            viz.append_llm_token(chunk)
        console.print(chunk, end="", style=C_WHITE, highlight=False)

        if tts_q:
            complete, sent_buf = _split_sentences(sent_buf)
            for s in complete:
                s = s.strip()
                if s:
                    await tts_q.put(s)

    # Send any remaining partial sentence
    if tts_q and sent_buf.strip():
        await tts_q.put(sent_buf.strip())

    console.print()

    # Signal TTS consumer to finish
    if tts_q:
        await tts_q.put(None)

    # ── Visual separator between exchanges ───────────────────────────────────
    console.print()
    console.print(Rule(style="grey30", characters="─"))
    console.print()

    _reset_viz_after_stream()

    # Wait for TTS to finish (or be interrupted)
    if tts_task:
        try:
            await asyncio.wait_for(tts_task, timeout=180.0)
        except asyncio.TimeoutError:
            tts_task.cancel()

    return full


# ─────────────────────────────────────────────────────────────────────────────
#  Voice bridge — moves utterances from thread queue → asyncio queue
# ─────────────────────────────────────────────────────────────────────────────
async def voice_bridge(listener, voice_q: asyncio.Queue):
    """Runs as asyncio task; feeds utterances into voice_q."""
    loop = asyncio.get_running_loop()
    while True:
        txt = await loop.run_in_executor(None, listener.get, 0.1)
        if txt and txt.strip():
            await voice_q.put(txt.strip())
        else:
            await asyncio.sleep(0.01)


async def _voice_dashboard_tick(live: Live, stop: asyncio.Event):
    """Refresh Rich Live panel while waiting for voice or keyboard input."""
    while not stop.is_set():
        if voice_pipeline_viz is not None:
            live.update(render_voice_pipeline_panel(voice_pipeline_viz))
        await asyncio.sleep(0.12)


# ─────────────────────────────────────────────────────────────────────────────
#  Interrupt watcher — fires interrupt_event the MOMENT speech is detected
#  (before transcription, so TTS stops in ~30 ms — one VAD frame)
# ─────────────────────────────────────────────────────────────────────────────
def start_interrupt_watcher(listener, stop_watcher: threading.Event):
    """
    Background thread: watches listener.speech_started.
    Waits 300 ms after onset to confirm it's real speech (not a tick/click/echo).
    Only then fires interrupt_event to stop TTS.
    """
    CONFIRM_MS = 0.30   # must still be speaking after this delay to interrupt

    def _watch():
        while not stop_watcher.is_set():
            fired = listener.speech_started.wait(timeout=0.02)
            if fired and not stop_watcher.is_set():
                # Wait a moment — real speech persists; ticks/echo don't
                time.sleep(CONFIRM_MS)
                if listener.speech_started.is_set() and not stop_watcher.is_set():
                    interrupt_event.set()   # confirmed: still speaking → stop TTS
    t = threading.Thread(target=_watch, daemon=True, name="FRIDAY-InterruptWatch")
    t.start()
    return t




# ─────────────────────────────────────────────────────────────────────────────
#  Process one query (shared by keyboard + voice paths)
# ─────────────────────────────────────────────────────────────────────────────
async def handle_query(text: str, source: str = "KEYBOARD", voice_mode: bool = False):
    _log("user", text)
    # Only print user message for voice input — keyboard input is already visible after the prompt
    if source == "VOICE":
        print_user_msg(text, source)
    interrupt_event.clear()

    viz = voice_pipeline_viz if voice_mode else None
    if viz:
        viz.clear_error()

    try:
        response = await stream_and_display(text, voice_mode=voice_mode, viz=viz)
    except Exception as e:
        console.print(f"  [bold {C_RED}]ERROR: {escape(str(e))}[/]")
        return

    if response:
        _log("friday", response)


# ─────────────────────────────────────────────────────────────────────────────
#  Keyboard reader — runs in executor, feeds kbd_q
# ─────────────────────────────────────────────────────────────────────────────
async def keyboard_reader(kbd_q: asyncio.Queue):
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        await kbd_q.put(line.rstrip("\n"))


# ─────────────────────────────────────────────────────────────────────────────
#  Ingest
# ─────────────────────────────────────────────────────────────────────────────
def do_ingest():
    with console.status(f"  [{C_CYAN}]Scanning data directory...[/]", spinner="dots"):
        rag.ingest_files()
    _log("system", "Documents ingested.")
    console.print(f"  [bold {C_GREEN}]Ingestion complete.[/]\n")


# ─────────────────────────────────────────────────────────────────────────────
#  Audio Visualizer
# ─────────────────────────────────────────────────────────────────────────────
def get_audio_spectrum(frame: bytes) -> str:
    """Returns a string of bars representing the FFT spectrum."""
    try:
        import numpy as np
        from scipy.fft import fft
    except ImportError:
        return ""
        
    if not frame:
        return ""
    
    audio = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
    # Quick RMS check to save CPU if silent
    if np.sqrt(np.mean(audio ** 2)) < 0.002:
        return ""
        
    fft_result = np.abs(fft(audio))[:len(audio)//2]
    
    if len(fft_result) == 0 or np.sum(fft_result) == 0:
        return ""
        
    # Normalize to 0-8 for bar chart
    normalized = (fft_result / np.max(fft_result) * 8).astype(int)
    
    blocks = [" ", " ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
    bars = "".join(blocks[min(8, bar)] for bar in normalized[::15])
    return bars

# ─────────────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────────────
async def main():
    global brain, rag, voice_pipeline_viz

    boot_sequence()

    # ── Deferred backend import (after banner shows — hides startup lag) ───────
    with console.status(f"  [{C_DIM}]Initializing systems...[/{C_DIM}]", spinner="dots"):
        from backend import brain as _brain, rag as _rag
        brain = _brain
        rag   = _rag
    console.print(f"  [{C_GREEN}]✓ Systems ready.[/{C_GREEN}]\n")

    # Shared queues
    kbd_q:   asyncio.Queue = asyncio.Queue()
    voice_q: asyncio.Queue = asyncio.Queue()

    voice_mode   = False
    listener     = None
    bridge_task  = None
    stop_watcher = threading.Event()   # controls the interrupt watcher thread

    # Start keyboard reader as background task
    asyncio.create_task(keyboard_reader(kbd_q))

    while True:
        # ── Drain stale keyboard input (typed while FRIDAY was thinking) ───────
        if not voice_mode:
            while not kbd_q.empty():
                try: kbd_q.get_nowait()
                except Exception: pass

        # ── Prompt ───────────────────────────────────────────────────────────
        if not voice_mode:
            # Use Rich console + explicit flush for correct ANSI state tracking
            console.print(f"\n  [bold {C_GOLD}]You[/] > ", end="")
            console.file.flush()

        # ── Wait for input (keyboard OR voice, optional Live dashboard) ───────
        kbd_task = asyncio.create_task(kbd_q.get())
        voice_task = asyncio.create_task(voice_q.get())
        dash_task = None

        if voice_mode and voice_pipeline_viz is not None:
            dash_stop = asyncio.Event()
            with Live(
                render_voice_pipeline_panel(voice_pipeline_viz),
                refresh_per_second=8,
                console=console,
                transient=True,
            ) as live:
                dash_task = asyncio.create_task(_voice_dashboard_tick(live, dash_stop))
                try:
                    done, pending = await asyncio.wait(
                        [kbd_task, voice_task, dash_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    dash_stop.set()
                    if dash_task:
                        dash_task.cancel()
                        try:
                            await dash_task
                        except asyncio.CancelledError:
                            pass
        else:
            done, pending = await asyncio.wait(
                [kbd_task], return_when=asyncio.FIRST_COMPLETED
            )
            voice_task.cancel()

        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

        completed = None
        for t in done:
            if t is not dash_task:
                completed = t
                break
        if completed is None:
            continue
        try:
            user_input = completed.result()
        except Exception:
            continue

        source = "VOICE" if completed is voice_task else "KEYBOARD"
        user_input = user_input.strip() if user_input else ""

        # If voice was detected while FRIDAY is still active → interrupt first
        if source == "VOICE" and not interrupt_event.is_set():
            interrupt_event.set()
            await asyncio.sleep(0.15)   # let stream/TTS notice

        if not user_input:
            continue

        cmd = user_input.lower()

        # ── Commands ─────────────────────────────────────────────────────────
        if cmd in ("q", "quit", "exit"):
            break

        if cmd == "v":
            voice_mode = not voice_mode
            if voice_mode:
                try:
                    from backend.voice_in import ContinuousListener

                    if voice_pipeline_viz is None:
                        voice_pipeline_viz = VoicePipelineModel()
                    if listener is None:
                        listener = ContinuousListener(viz=voice_pipeline_viz)
                    listener.start()
                    globals()["_active_listener"] = listener
                    if bridge_task is None or bridge_task.done():
                        bridge_task = asyncio.create_task(voice_bridge(listener, voice_q))
                    stop_watcher.clear()
                    start_interrupt_watcher(listener, stop_watcher)
                    console.print(
                        f"  [bold {C_MAGENTA}]Voice Mode ON — Live pipeline panel while listening.[/]"
                    )
                except ImportError as e:
                    console.print(f"  [bold {C_RED}]VAD not available: {e}[/]")
                    voice_mode = False
            else:
                stop_watcher.set()
                if listener:
                    listener.stop()
                globals()["_active_listener"] = None
                if bridge_task and not bridge_task.done():
                    bridge_task.cancel()
                console.print(f"  [bold {C_DIM}]Voice Mode Deactivated. Keyboard active.[/]")
            console.print()
            continue

        if cmd == "i":
            do_ingest(); continue

        if cmd == "c":
            brain.conversation_history.clear(); chat_log.clear()
            boot_sequence()
            if voice_mode:
                console.print(f"  [bold {C_MAGENTA}]Voice Mode Active[/]")
            continue

        if cmd == "s":
            show_status(); continue

        if cmd in ("h", "help", "?"):
            console.print(hud_command_bar()); continue

        # ── Process query ────────────────────────────────────────────────────
        await handle_query(user_input, source=source, voice_mode=voice_mode)

    # ── Shutdown ──────────────────────────────────────────────────────────────
    if listener:
        listener.stop()
    console.print()
    console.print(Panel(
        Align.center(Text(
            f"  [{_ts()}]  INITIATING SHUTDOWN SEQUENCE\n"
            f"  ALL SYSTEMS POWERING DOWN  //  TAKE CARE, SIR. TALK SOON!",
            style=f"bold {C_CYAN}", justify="center")),
        box=HUD_BOX, border_style=C_RED, padding=(1, 4)))
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print(f"\n  [{C_DIM}]INTERRUPTED — SHUTTING DOWN.[/{C_DIM}]\n")
