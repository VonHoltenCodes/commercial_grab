"""Cross-recording duplicate detection via transcript similarity.

Repeat airings of the same spot — within one broadcast or across tapes from
the same era — produce near-identical transcripts. This walks the commercial
segments of one or more .grab workdirs, pulls each segment's transcript text,
and groups segments whose normalized text is nearly identical. The first
(longest-text) member of each group is the keeper.

No-speech segments (bumpers, music-only ads) can't be compared this way and
are always kept.
"""

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

MIN_WORDS = 8          # too little speech to fingerprint
SIM_THRESHOLD = 0.80   # SequenceMatcher ratio on normalized text


def normalize(text: str) -> str:
    text = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def gather(workdirs: list[Path]) -> list[dict]:
    """Collect every commercial segment with its transcript text."""
    from .transcribe import text_between

    items = []
    for wd in workdirs:
        segs = json.loads((wd / "segments.json").read_text())
        transcript = json.loads((wd / "transcript.json").read_text())
        for s in segs:
            if s.get("label") != "commercial":
                continue
            text = normalize(text_between(transcript, s["start"], s["end"]))
            items.append({
                "workdir": str(wd),
                "recording": wd.stem.replace(".grab", ""),
                "break": s.get("break"),
                "spot": s.get("spot"),
                "start": s["start"],
                "end": s["end"],
                "duration": s.get("duration"),
                "text": text,
                "words": len(text.split()),
            })
    return items


def find_groups(items: list[dict], threshold: float = SIM_THRESHOLD) -> list[list[int]]:
    """Group indexes of near-identical transcripts (union-find over pairs)."""
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        parent[find(a)] = find(b)

    comparable = [i for i, it in enumerate(items) if it["words"] >= MIN_WORDS]
    for x, i in enumerate(comparable):
        for j in comparable[x + 1:]:
            a, b = items[i], items[j]
            # cheap length gate before the quadratic matcher
            if min(a["words"], b["words"]) / max(a["words"], b["words"]) < 0.5:
                continue
            if SequenceMatcher(None, a["text"], b["text"]).ratio() >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in comparable:
        groups.setdefault(find(i), []).append(i)
    return [sorted(g, key=lambda i: -items[i]["words"]) for g in groups.values() if len(g) > 1]


def report(items: list[dict], groups: list[list[int]]) -> str:
    lines = ["# Duplicate report", ""]
    if not groups:
        lines.append("No duplicates found.")
    for n, g in enumerate(groups, 1):
        keeper = items[g[0]]
        lines.append(f"## Group {n} — keep `{keeper['recording']}` b{keeper['break']:02d}s{keeper['spot']:02d}")
        for i in g:
            it = items[i]
            tag = "KEEP" if i == g[0] else "DUP "
            lines.append(
                f"- {tag} {it['recording']} break{it['break']:02d}/spot{it['spot']:02d} "
                f"({it['duration']:.0f}s): {it['text'][:110]}…"
            )
        lines.append("")
    return "\n".join(lines)
