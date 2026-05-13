"""
Rich UI for the voice pipeline — live STT, stage LEDs, levels, and model info.
"""

from __future__ import annotations

from rich.align import Align
from rich.console import Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from backend.voice_state import PipelineStage, VoicePipelineModel

_STAGE_ORDER = [
    PipelineStage.IDLE,
    PipelineStage.CALIBRATING,
    PipelineStage.LISTENING,
    PipelineStage.SPEECH_ONSET,
    PipelineStage.STT_LIVE,
    PipelineStage.STT_FINAL,
    PipelineStage.LLM_STREAMING,
    PipelineStage.TTS_SYNTHESIZING,
    PipelineStage.TTS_PLAYING,
]

_STAGE_LABELS = {
    PipelineStage.IDLE: "Idle",
    PipelineStage.CALIBRATING: "Calibrate",
    PipelineStage.LISTENING: "Listen",
    PipelineStage.SPEECH_ONSET: "Speech",
    PipelineStage.STT_LIVE: "STT live",
    PipelineStage.STT_FINAL: "STT final",
    PipelineStage.LLM_STREAMING: "LLM",
    PipelineStage.TTS_SYNTHESIZING: "TTS synth",
    PipelineStage.TTS_PLAYING: "TTS play",
}


def _level_bar(level: float, width: int = 28) -> str:
    level = max(0.0, min(1.0, level))
    filled = int(round(level * width))
    return f"[{'█' * filled}{'░' * (width - filled)}]"


def _stage_row(current: PipelineStage) -> Text:
    parts: list[str | tuple[str, str]] = []
    hit = False
    for st in _STAGE_ORDER:
        if st == current:
            hit = True
        label = _STAGE_LABELS[st]
        if st == current:
            parts.append((f" ●{label} ", "bold bright_cyan"))
        elif not hit:
            parts.append((f" ○{label} ", "dim"))
        else:
            parts.append((f" ○{label} ", "grey50"))
    t = Text()
    for p in parts:
        if isinstance(p, tuple):
            t.append(p[0], style=p[1])
        else:
            t.append(p)
    return t


def render_voice_pipeline_panel(model: VoicePipelineModel) -> Panel:
    s = model.snapshot()

    live = s.live_stt.strip() or "…"
    live_display = Text(live, style="italic bright_white", overflow="ellipsis", no_wrap=False)

    meta = Table.grid(padding=(0, 2))
    meta.add_column(justify="left", style="cyan", ratio=1)
    meta.add_column(justify="left", style="white")
    meta.add_row("Mic", _level_bar(s.input_level))
    meta.add_row("Whisper", s.whisper_model or "—")
    meta.add_row("TTS", s.tts_backend or "—")
    meta.add_row("Utterances", str(s.utterance_count))
    meta.add_row("Partials", str(s.partial_count))
    if s.last_stt_ms > 0:
        meta.add_row("Last STT", f"{s.last_stt_ms:.0f} ms")
    if s.last_error:
        meta.add_row("Error", Text(s.last_error, style="bold red"))

    inner = Table.grid(expand=True)
    inner.add_column(ratio=1)
    inner.add_row(Align.left(_stage_row(s.stage), vertical="middle"))
    inner.add_row(Rule(style="grey37"))
    inner.add_row(Text("Live transcript", style="bold yellow"))
    inner.add_row(live_display)
    inner.add_row(Rule(style="grey37"))
    inner.add_row(Text("Last final", style="bold dim"))
    inner.add_row(
        Text(
            (s.last_final_stt[:400] + "…") if len(s.last_final_stt) > 400 else s.last_final_stt,
            style="dim",
            overflow="ellipsis",
        )
    )
    if s.llm_token_buf.strip():
        inner.add_row(Rule(style="grey37"))
        inner.add_row(Text("LLM (tail)", style="bold green"))
        inner.add_row(Text(s.llm_token_buf[-320:], style="green", overflow="ellipsis"))
    if s.tts_sentence.strip():
        inner.add_row(Rule(style="grey37"))
        inner.add_row(Text("TTS line", style="bold magenta"))
        inner.add_row(Text(s.tts_sentence, style="magenta", overflow="ellipsis"))

    inner.add_row(Rule(style="grey37"))
    inner.add_row(meta)

    return Panel(
        Group(inner),
        title="[bold bright_white]FRIDAY · Voice pipeline[/]",
        subtitle="[dim]Live STT updates while you speak · Final text commits on silence[/dim]",
        border_style="bright_blue",
        padding=(1, 2),
    )
