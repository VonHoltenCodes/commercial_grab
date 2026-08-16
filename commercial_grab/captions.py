"""Line 21 (EIA-608) closed-caption extraction.

Broadcast recordings that survived a DVD-recorder capture chain usually carry
the original closed captions as MPEG-2 user data (h264 re-encodes sometimes
preserve them as A53 side data). ffmpeg's lavfi `subcc` decoder turns them
into timed SRT cues — the broadcaster's verbatim text, which beats ASR for
brand names and product identification. Timing is caption-block granularity
(cues of a few seconds that can lead/lag the audio), so captions complement
rather than replace the word-level ASR transcript for boundary work.
"""

import re
import subprocess
from pathlib import Path

CUE_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)
TAG_RE = re.compile(r"</?font[^>]*>|\{\\an\d\}|</?i>|</?b>|</?u>")


def _ts(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def extract(video: Path) -> list[dict]:
    """Decode embedded EIA-608/708 captions to a list of timed cues."""
    # lavfi movie= filename needs its own escaping layer
    esc = str(video).replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"movie='{esc}'[out0+subcc]",
         "-map", "0:s:0", "-c:s", "srt", "-f", "srt", "-"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"caption extraction failed:\n{proc.stderr[-1500:]}")

    cues = []
    cur = None
    for line in proc.stdout.splitlines():
        m = CUE_RE.match(line.strip())
        if m:
            g = m.groups()
            cur = {"start": round(_ts(*g[:4]), 3), "end": round(_ts(*g[4:]), 3), "text": []}
            cues.append(cur)
            continue
        if cur is not None:
            text = TAG_RE.sub("", line).strip()
            if text and not text.isdigit():
                cur["text"].append(text)
    out = []
    for c in cues:
        text = re.sub(r"\s+", " ", " ".join(c["text"])).strip()
        if text:
            out.append({"start": c["start"], "end": c["end"], "text": text})
    return out


def text_between(cues: list[dict], start: float, end: float, max_chars: int = 0) -> str:
    parts = [c["text"] for c in cues if c["end"] > start and c["start"] < end]
    text = " ".join(parts).strip()
    if max_chars and len(text) > max_chars:
        text = text[: max_chars - 1].rsplit(" ", 1)[0] + "…"
    return text


def captions_markdown(cues: list[dict]) -> str:
    from .transcribe import fmt_ts
    lines = ["# Closed captions (EIA-608)", ""]
    for c in cues:
        lines.append(f"`[{fmt_ts(c['start'])} - {fmt_ts(c['end'])}]` {c['text']}")
    return "\n".join(lines) + "\n"
