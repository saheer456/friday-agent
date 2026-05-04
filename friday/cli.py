"""
cli.py  —  F.R.I.D.A.Y  Holographic Terminal Interface
Iron Man / J.A.R.V.I.S aesthetic  |  Always-on VAD voice  |  Interruptible TTS
"""

# ── Encoding fix — MUST be first ──────────────────────────────────────────────
import io, os, sys
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import asyncio
import random
import threading
import time
from datetime import datetime
from pathlib import Path

# ── Path / env ────────────────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.chdir(HERE)
from dotenv import load_dotenv
load_dotenv(HERE / ".env")

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

# ── Internal ──────────────────────────────────────────────────────────────────
from backend import brain, rag

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

# In-memory chat log
chat_log: list[dict] = []


# ─────────────────────────────────────────────────────────────────────────────
#  ASCII art
# ─────────────────────────────────────────────────────────────────────────────
LOGO = (
    "  ███████ ██████  ██ ██████   █████  ██    ██ \n"
    "  ██      ██   ██ ██ ██   ██ ██   ██  ██  ██  \n"
    "  █████   ██████  ██ ██   ██ ███████   ████   \n"
    "  ██      ██   ██ ██ ██   ██ ██   ██    ██    \n"
    "  ██      ██   ██ ██ ██████  ██   ██    ██    \n"
)

ARC_REACTOR = (
    "      ___      \n"
    "    /     \\   \n"
    "   | () () |   \n"
    "   |  ___  |   \n"
    "    \\_____/   \n"
    "   [ARC CORE]  \n"
)

# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")

def _hex(n: int = 6) -> str:
    return "".join(random.choices("0123456789ABCDEF", k=n))

def _pct() -> int:
    return random.randint(60, 99)

def _log(role: str, text: str):
    chat_log.append({"role": role, "text": text, "ts": _ts()})


# ─────────────────────────────────────────────────────────────────────────────
#  HUD panel builders
# ─────────────────────────────────────────────────────────────────────────────
def _status_text(title: str, status: str, sc: str, detail: str) -> Text:
    t = Text(justify="center")
    t.append(title  + "\n", style=f"bold {C_CYAN}")
    t.append(status + "\n", style=f"bold {sc}")
    t.append(detail,        style=C_DIM)
    return t


def hud_top_bar(voice_on: bool = False) -> Panel:
    g = Table.grid(expand=True)
    g.add_column(ratio=1); g.add_column(ratio=1); g.add_column(ratio=1)
    mic_txt = Text("  MIC ACTIVE", style=f"bold {C_MAGENTA}") if voice_on else Text("", style="")
    g.add_row(
        Text(f" [{_ts()}]  SYSTEMS NOMINAL", style=C_GREEN),
        Text("F . R . I . D . A . Y", style=f"bold {C_CYAN}", justify="center"),
        Text(f"GROQ/{os.getenv('GROQ_MODEL','llama-3.3-70b-versatile')}  [LIVE] ",
             style=C_GOLD, justify="right"),
    )
    border = C_MAGENTA if voice_on else C_CYAN
    return Panel(g, box=HUD_BOX, border_style=border, padding=(0, 1))


def hud_status_row(voice_on: bool = False) -> Columns:
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    mic_status = "ACTIVE" if voice_on else "STANDBY"
    mic_colour = C_MAGENTA if voice_on else C_GOLD
    panels = [
        Panel(Align.center(_status_text("ARC REACTOR", "ONLINE",     C_GREEN,    f"{_pct()}% OUTPUT")),
              box=INNER_BOX, border_style=C_CYAN,    padding=(0, 1)),
        Panel(Align.center(_status_text("NEURAL NET",  "ACTIVE",     C_GREEN,    "RAG + MEMORY")),
              box=INNER_BOX, border_style=C_CYAN,    padding=(0, 1)),
        Panel(Align.center(_status_text("MICROPHONE",  mic_status,   mic_colour, "WHISPER VAD")),
              box=INNER_BOX, border_style=mic_colour, padding=(0, 1)),
        Panel(Align.center(_status_text("GROQ API",    "CONNECTED",  C_GREEN,    model[:18])),
              box=INNER_BOX, border_style=C_GREEN,   padding=(0, 1)),
    ]
    return Columns(panels, equal=True, expand=True)


def hud_command_bar() -> Panel:
    g = Table.grid(expand=True); g.add_column()
    row = Text()
    for key, label in [("[V]","VOICE"), ("[I]","INGEST"), ("[C]","CLEAR"),
                       ("[S]","STATUS"), ("[Q]","QUIT")]:
        row.append(f"  {key} ", style=f"bold {C_GOLD}")
        row.append(f"{label}  ", style=C_DIM)
    row.append(f"  //  [{_ts()}]", style=C_DIM)
    g.add_row(row)
    return Panel(g, box=HUD_BOX, border_style=C_CYAN, padding=(0, 0))


def _draw_hud(voice_on: bool = False):
    console.print(hud_top_bar(voice_on))
    console.print(hud_status_row(voice_on))
    console.print(hud_command_bar())
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
#  Boot sequence
# ─────────────────────────────────────────────────────────────────────────────
def boot_sequence():
    console.clear()
    for _ in range(2):
        console.print(Align.center(Text(ARC_REACTOR, style=f"bold {C_CYAN}")))
        time.sleep(0.15); console.clear(); time.sleep(0.08)

    console.print()
    console.print(Align.center(Text(LOGO, style=f"bold {C_CYAN}")))
    console.print(Align.center(Text(
        "  F.R.I.D.A.Y  ·  Female Replacement Intelligent Digital Assistant Youth\n",
        style=C_DIM)))
    console.print()

    checks = [
        ("INITIALISING ARC REACTOR",      C_CYAN,  0.08),
        ("LOADING NEURAL NETWORK WEIGHTS", C_CYAN,  0.10),
        ("CONNECTING TO GROQ API",         C_CYAN,  0.12),
        ("SPINNING UP RAG VECTORSTORE",    C_CYAN,  0.09),
        ("LOADING VAD ENGINE",             C_CYAN,  0.07),
        ("CALIBRATING WHISPER STT",        C_CYAN,  0.08),
        ("LOADING MEMORY INSIGHTS",        C_CYAN,  0.07),
        ("ENCRYPTING COMM CHANNEL",        C_GREEN, 0.06),
        ("ALL SYSTEMS NOMINAL",            C_GREEN, 0.05),
    ]
    with Live(console=console, refresh_per_second=20) as live:
        for label, colour, delay in checks:
            done = random.randint(20, 36)
            bar  = "[" + "=" * done + ">" + " " * (36 - done) + "]"
            t = Text()
            t.append(f"  [{_ts()}]  ", style=C_DIM)
            t.append(f"{label:<42}", style=f"bold {colour}")
            t.append(f"  {bar}  0x{_hex(4)}  ", style=colour)
            t.append("OK", style=f"bold {C_GREEN}")
            live.update(t); time.sleep(delay)

    console.print()
    key = os.getenv("GROQ_API_KEY", "")
    if not key or "your_" in key:
        console.print(Panel(
            Text("  FATAL: GROQ_API_KEY not set in .env", style=f"bold {C_RED}"),
            border_style=C_RED, box=HUD_BOX))
        sys.exit(1)

    console.print(Align.center(Text(
        "  AUTHENTICATION VERIFIED  //  OPERATOR: SIR  //  CLEARANCE: LEVEL-5\n",
        style=f"bold {C_GOLD}")))
    time.sleep(0.3)
    _draw_hud()
    console.print(Panel(
        Text(f"  [{_ts()}]  FRIDAY ONLINE.  Hey sir, I'm here whenever you need me!",
             style=f"bold {C_CYAN}"),
        box=HUD_BOX, border_style=C_GOLD, padding=(0, 1)))
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
#  Status dashboard
# ─────────────────────────────────────────────────────────────────────────────
def show_status():
    console.print()
    console.print(Rule(f"[bold {C_GOLD}]  SYSTEM STATUS REPORT  [{_ts()}]  [/]",
                       style=C_CYAN))
    tbl = Table(box=INNER_BOX, border_style=C_CYAN, expand=True,
                show_header=True, header_style=f"bold {C_GOLD}")
    tbl.add_column("SUBSYSTEM"); tbl.add_column("STATUS", justify="center")
    tbl.add_column("METRIC", justify="right"); tbl.add_column("ADDR", style=C_DIM)
    rows = [
        ("ARC REACTOR",     "ONLINE",    f"{_pct()}% OUTPUT",                  f"0x{_hex()}"),
        ("GROQ API",        "ACTIVE",    os.getenv("GROQ_MODEL", "?"),         f"0x{_hex()}"),
        ("VECTOR STORE",    "INDEXED",   "CHROMA-DB LOCAL",                    f"0x{_hex()}"),
        ("EMBED MODEL",     "LOADED",    "all-MiniLM-L6-v2",                   f"0x{_hex()}"),
        ("WHISPER STT",     "READY",     "BASE INT8 CPU",                      f"0x{_hex()}"),
        ("VAD ENGINE",      "WEBRTC",    f"MODE {2}  //  30ms frames",         f"0x{_hex()}"),
        ("EDGE-TTS",        "FALLBACK",  "en-GB-SoniaNeural",                  f"0x{_hex()}"),
        ("MEMORY",          "RUNNING",   f"{len(chat_log)} msgs",              f"0x{_hex()}"),
    ]
    for name, status, metric, addr in rows:
        tbl.add_row(
            Text(name, style=C_CYAN),
            Text(status, style=f"bold {C_GREEN}"),
            Text(metric, style=C_WHITE),
            Text(addr, style=C_DIM),
        )
    console.print(tbl); console.print()


# ─────────────────────────────────────────────────────────────────────────────
#  HUD panels for conversation
# ─────────────────────────────────────────────────────────────────────────────
def print_user_msg(text: str, source: str = "KEYBOARD"):
    icon = "MIC" if source == "VOICE" else "KBD"
    border = C_MAGENTA if source == "VOICE" else C_GOLD
    console.print(Panel(
        Text(f"  SIR [{icon}]  {_ts()}  >>  {escape(text)}", style=f"bold {border}"),
        box=HUD_BOX, border_style=border, padding=(0, 1)))
    console.print()


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
async def _tts_consumer(tts_q: asyncio.Queue):
    """Background task: synthesize and play each sentence in order."""
    try:
        from backend.tts import synthesize, play_interruptible
    except ImportError:
        return

    loop = asyncio.get_event_loop()
    while True:
        sentence = await tts_q.get()
        if sentence is None:        # sentinel — done
            break
        if interrupt_event.is_set():
            continue                # drain queue but skip playback
        try:
            audio, suffix = await synthesize(sentence)
            if audio and not interrupt_event.is_set():
                await loop.run_in_executor(
                    None, play_interruptible, audio, interrupt_event, suffix
                )
        except Exception as e:
            pass  # never let TTS crash the main loop


# ─────────────────────────────────────────────────────────────────────────────
#  Streaming response + sentence-streaming TTS (zero extra lag)
# ─────────────────────────────────────────────────────────────────────────────
async def stream_and_display(user_msg: str, voice_mode: bool = False) -> str:
    """
    Stream tokens from Groq while simultaneously:
      - Printing them to the terminal live
      - Splitting into sentences and queuing them for TTS playback
    First sentence starts speaking before the full response is generated.
    """
    full     = ""
    sent_buf = ""           # accumulates tokens until a sentence ends
    tts_q    = asyncio.Queue() if voice_mode else None
    tts_task = asyncio.create_task(_tts_consumer(tts_q)) if voice_mode else None

    # ── Thinking spinner ──────────────────────────────────────────────────────
    frames    = ["[>>]", "[> ]", "[  ]", "[ >]"]
    stop_spin = threading.Event()

    def _spin():
        i = 0
        while not stop_spin.is_set():
            sys.stdout.write(
                f"\r  \033[96m{frames[i%4]}  PROCESSING  //  "
                f"QUERY HASH: 0x{_hex(8)}\033[0m   "
            )
            sys.stdout.flush()
            time.sleep(0.12)
            i += 1
        sys.stdout.write("\r" + " " * 72 + "\r")
        sys.stdout.flush()

    spin_t = threading.Thread(target=_spin, daemon=True)
    spin_t.start()

    gen = brain.stream_response(user_msg, voice_mode=voice_mode)
    try:
        first = await gen.__anext__()
    except StopAsyncIteration:
        stop_spin.set()
        if tts_q: await tts_q.put(None)
        return ""
    finally:
        stop_spin.set(); spin_t.join(timeout=0.5)

    if interrupt_event.is_set():
        if tts_q: await tts_q.put(None)
        return ""

    # ── Print response header ─────────────────────────────────────────────────
    console.print(Rule(
        title=f"[bold {C_GOLD}]  F.R.I.D.A.Y  RESPONSE  [{_ts()}]  [/]",
        style=C_CYAN, characters="─"))
    console.print()
    console.print(f"  [bold {C_CYAN}]>>[/]  ", end="")

    # ── Stream + collect sentences ────────────────────────────────────────────
    for chunk in [first]:
        full += chunk
        sent_buf += chunk
        console.print(chunk, end="", style=C_WHITE, highlight=False)

    async for chunk in gen:
        if interrupt_event.is_set():
            console.print(
                f"\n\n  [bold {C_RED}][INTERRUPTED BY SIR][/]", highlight=False)
            break
        full     += chunk
        sent_buf += chunk
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

    # Signal TTS consumer to finish
    if tts_q:
        await tts_q.put(None)

    console.print()
    console.print()
    console.print(Rule(style=C_CYAN, characters="─"))
    console.print()

    # Wait for TTS to finish (or be interrupted)
    if tts_task:
        try:
            await asyncio.wait_for(tts_task, timeout=60.0)
        except asyncio.TimeoutError:
            tts_task.cancel()

    return full


# ─────────────────────────────────────────────────────────────────────────────
#  Wake word configuration
# ─────────────────────────────────────────────────────────────────────────────
# Microphone is always on — FRIDAY only acts when it hears the wake word.
# Supports variations: "friday", "hey friday", "ok friday", "yo friday"
WAKE_WORDS = ("friday", "hey friday", "ok friday", "yo friday", "hi friday")

def _strip_wake_word(text: str) -> str:
    """Remove the wake word prefix from the utterance and return the clean query."""
    lower = text.lower().strip()
    for w in sorted(WAKE_WORDS, key=len, reverse=True):  # longest first
        if lower.startswith(w):
            stripped = text[len(w):].strip().lstrip(",").strip()
            return stripped
    return text.strip()

def _has_wake_word(text: str) -> bool:
    """Return True if the utterance contains a wake-word trigger."""
    lower = text.lower()
    return any(w in lower for w in WAKE_WORDS)


# ─────────────────────────────────────────────────────────────────────────────
#  Voice bridge — moves utterances from thread queue → asyncio queue
#  Only forwards utterances that contain the wake word.
# ─────────────────────────────────────────────────────────────────────────────
async def voice_bridge(listener, voice_q: asyncio.Queue):
    """Runs as asyncio task; filters by wake word and feeds utterances into voice_q."""
    loop = asyncio.get_event_loop()
    while True:
        txt = await loop.run_in_executor(None, listener.get, 0.1)
        if txt:
            if _has_wake_word(txt):
                clean = _strip_wake_word(txt)
                if clean:  # ignore bare wake word with nothing after it
                    await voice_q.put(clean)
                else:
                    # Bare "Friday" — just acknowledge and stay ready
                    console.print(
                        f"  [bold {C_CYAN}]>> Yes, sir? I'm listening.[/]\n",
                        highlight=False)
            # If no wake word: silently discard — FRIDAY is not being addressed
        else:
            await asyncio.sleep(0.01)


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
    print_user_msg(text, source)
    interrupt_event.clear()

    try:
        # voice_mode=True → TTS streams sentence-by-sentence inside
        response = await stream_and_display(text, voice_mode=voice_mode)
    except Exception as e:
        console.print(Panel(
            Text(f"  ERROR: {escape(str(e))}", style=f"bold {C_RED}"),
            box=HUD_BOX, border_style=C_RED, padding=(0, 1)))
        return

    if response:
        _log("friday", response)


# ─────────────────────────────────────────────────────────────────────────────
#  Keyboard reader — runs in executor, feeds kbd_q
# ─────────────────────────────────────────────────────────────────────────────
async def keyboard_reader(kbd_q: asyncio.Queue):
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        await kbd_q.put(line.rstrip("\n"))


# ─────────────────────────────────────────────────────────────────────────────
#  Ingest
# ─────────────────────────────────────────────────────────────────────────────
def do_ingest():
    console.print(Rule(f"[bold {C_GOLD}]  DATA INGESTION SEQUENCE  [/]", style=C_CYAN))
    with console.status(f"[{C_CYAN}]SCANNING DATA DIRECTORY…[/]", spinner="arc"):
        rag.ingest_files()
    _log("system", "Documents ingested.")
    console.print(Panel(
        Text(f"  [{_ts()}]  INGESTION COMPLETE  //  VECTORSTORE UPDATED.",
             style=f"bold {C_GREEN}"),
        box=HUD_BOX, border_style=C_GREEN, padding=(0, 1)))
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────────────
async def main():
    boot_sequence()

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
        # ── Prompt ───────────────────────────────────────────────────────────
        if voice_mode:
            console.print(
                f"  [bold {C_MAGENTA}]MIC ON  —  say 'Friday ...' to wake me[/]  "
                f"[{C_DIM}]or type a command[/{C_DIM}]  "
                f"[bold {C_CYAN}]>[/]  ", end="")
        else:
            console.print(
                f"  [bold {C_GOLD}]SIR  //[/]  [bold {C_WHITE}]{_ts()}[/]  "
                f"[bold {C_CYAN}]>[/]  ", end="")

        # ── Wait for input (keyboard OR voice, whichever first) ───────────────
        kbd_task   = asyncio.create_task(kbd_q.get())
        voice_task = asyncio.create_task(voice_q.get())

        pending: set
        if voice_mode:
            done, pending = await asyncio.wait(
                [kbd_task, voice_task], return_when=asyncio.FIRST_COMPLETED)
        else:
            done, pending = await asyncio.wait(
                [kbd_task], return_when=asyncio.FIRST_COMPLETED)
            # cancel voice_task since we didn't really use it
            voice_task.cancel()

        # Cancel the task that didn't win
        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

        completed = list(done)[0]
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
                    if listener is None:
                        listener = ContinuousListener()
                    listener.start()
                    if bridge_task is None or bridge_task.done():
                        bridge_task = asyncio.create_task(voice_bridge(listener, voice_q))
                    # Start instant-interrupt watcher
                    stop_watcher.clear()
                    start_interrupt_watcher(listener, stop_watcher)
                    console.print(Panel(
                        Text(
                            f"  [{_ts()}]  MIC ACTIVE  //  WAKE WORD: 'FRIDAY'  //  "
                            f"I'll listen but only respond when you call my name, sir!",
                             style=f"bold {C_MAGENTA}"),
                        box=HUD_BOX, border_style=C_MAGENTA, padding=(0, 1)))
                except ImportError as e:
                    console.print(f"  [bold {C_RED}]VAD not available: {e}[/]")
                    voice_mode = False
            else:
                # Stop listener and watcher
                stop_watcher.set()
                if listener:
                    listener.stop()
                if bridge_task and not bridge_task.done():
                    bridge_task.cancel()
                console.print(Panel(
                    Text(f"  [{_ts()}]  MIC OFFLINE  //  KEYBOARD INPUT ACTIVE. Just type, sir.",
                         style=f"bold {C_DIM}"),
                    box=HUD_BOX, border_style=C_DIM, padding=(0, 1)))
            console.print()
            continue

        if cmd == "i":
            do_ingest(); continue

        if cmd == "c":
            brain.conversation_history.clear(); chat_log.clear()
            boot_sequence()
            if voice_mode:
                console.print(Panel(
                    Text(f"  [{_ts()}]  MIC ACTIVE", style=f"bold {C_MAGENTA}"),
                    box=INNER_BOX, border_style=C_MAGENTA, padding=(0, 1)))
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
