"""GPU transcription with faster-whisper — word-level timestamps, no cloud APIs."""

import json
from pathlib import Path


def transcribe(
    video: Path,
    model_name: str = "large-v3",
    device: str = "cuda",
    compute_type: str = "float16",
    language: str = "en",
) -> dict:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    segments, info = model.transcribe(
        str(video),
        language=language,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )

    out_segments = []
    for seg in segments:
        out_segments.append({
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text.strip(),
            "words": [
                {"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word}
                for w in (seg.words or [])
            ],
        })

    return {
        "model": model_name,
        "language": info.language,
        "duration": round(info.duration, 3),
        "segments": out_segments,
    }


def fmt_ts(t: float) -> str:
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def transcript_markdown(transcript: dict) -> str:
    lines = [f"# Transcript ({transcript['model']}, {fmt_ts(transcript['duration'])})", ""]
    for seg in transcript["segments"]:
        lines.append(f"`[{fmt_ts(seg['start'])} - {fmt_ts(seg['end'])}]` {seg['text']}")
    return "\n".join(lines) + "\n"


def text_between(transcript: dict, start: float, end: float, max_chars: int = 0) -> str:
    parts = [
        seg["text"] for seg in transcript["segments"]
        if seg["end"] > start and seg["start"] < end
    ]
    text = " ".join(parts).strip()
    if max_chars and len(text) > max_chars:
        text = text[: max_chars - 1].rsplit(" ", 1)[0] + "…"
    return text


def load(path: Path) -> dict:
    return json.loads(path.read_text())
