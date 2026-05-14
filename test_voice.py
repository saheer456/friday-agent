#!/usr/bin/env python3
"""Exercise STT + live partials using ContinuousListener (no temp helpers)."""

import time

from backend.voice_in import ContinuousListener
from backend.voice_state import VoicePipelineModel


def main():
    print("Voice test — speak a short phrase (30s max, Ctrl+C to abort).")
    viz = VoicePipelineModel()
    listener = ContinuousListener(viz=viz)
    listener.start()
    try:
        deadline = time.monotonic() + 30.0
        last_live = ""
        while time.monotonic() < deadline:
            txt = listener.get(timeout=0.15)
            if txt:
                print(f"\nFinal transcript: {txt}")
                return
            live = viz.snapshot().live_stt
            if live != last_live:
                last_live = live
                print(f"\r[live] {live[:100]:<100}", end="", flush=True)
        print("\nTimeout — no final transcript.")
    finally:
        listener.stop()


if __name__ == "__main__":
    main()
