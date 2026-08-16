"""commercial_grab CLI — scan / transcribe / propose / cut, each stage resumable."""

import json
import sys
import time
from pathlib import Path

import click

from . import ffdetect, propose as propose_mod, transcribe as transcribe_mod
from .extract import extract as do_extract


def workdir_for(video: Path, workdir: str | None) -> Path:
    wd = Path(workdir) if workdir else video.parent / f"{video.stem}.grab"
    wd.mkdir(parents=True, exist_ok=True)
    return wd


@click.group()
def cli():
    """Pull vintage commercials out of off-air broadcast recordings."""


@cli.command()
@click.argument("video", type=click.Path(exists=True, path_type=Path))
def probe(video):
    """Show stream/format info for VIDEO."""
    click.echo(json.dumps(ffdetect.probe(video), indent=2))


@cli.command()
@click.argument("video", type=click.Path(exists=True, path_type=Path))
@click.option("--workdir", default=None, help="Working dir (default: <video>.grab/)")
@click.option("--black-dur", default=0.05, show_default=True, help="Min black duration (s)")
@click.option("--black-th", default=0.10, show_default=True, help="Black pixel threshold")
@click.option("--silence-db", default=-35.0, show_default=True, help="Silence threshold (dB)")
@click.option("--silence-dur", default=0.3, show_default=True, help="Min silence duration (s)")
@click.option("--hwaccel", default="auto", show_default=True)
def scan(video, workdir, black_dur, black_th, silence_db, silence_dur, hwaccel):
    """Scan VIDEO for black frames + silence (one ffmpeg pass)."""
    wd = workdir_for(video, workdir)
    t0 = time.time()
    click.echo(f"Scanning {video.name} …")
    data = ffdetect.scan(video, black_dur, black_th, silence_db, silence_dur, hwaccel)
    (wd / "scan.json").write_text(json.dumps(data, indent=2))
    cands = ffdetect.cut_candidates(data)
    (wd / "candidates.json").write_text(json.dumps(cands, indent=2))
    silent = sum(1 for c in cands if c["silent"])
    click.echo(
        f"Done in {time.time()-t0:.0f}s — {len(data['black'])} black events, "
        f"{len(data['silence'])} silences, {len(cands)} cut candidates "
        f"({silent} black+silent)."
    )


@cli.command()
@click.argument("video", type=click.Path(exists=True, path_type=Path))
@click.option("--workdir", default=None)
@click.option("--model", default="large-v3", show_default=True)
@click.option("--device", default="cuda", show_default=True)
@click.option("--compute-type", default="float16", show_default=True)
@click.option("--language", default="en", show_default=True)
def transcribe(video, workdir, model, device, compute_type, language):
    """Transcribe VIDEO with faster-whisper (word timestamps, local GPU)."""
    wd = workdir_for(video, workdir)
    t0 = time.time()
    click.echo(f"Transcribing {video.name} with {model} on {device} …")
    data = transcribe_mod.transcribe(video, model, device, compute_type, language)
    (wd / "transcript.json").write_text(json.dumps(data, indent=2))
    (wd / "transcript.md").write_text(transcribe_mod.transcript_markdown(data))
    click.echo(
        f"Done in {time.time()-t0:.0f}s — {len(data['segments'])} segments, "
        f"saved transcript.json + transcript.md"
    )


@cli.command()
@click.argument("video", type=click.Path(exists=True, path_type=Path))
@click.option("--workdir", default=None)
@click.option("--max-spot", default=130.0, show_default=True,
              help="Blocks at or below this length (s) are labeled commercial")
@click.option("--merge-gap", default=0.75, show_default=True,
              help="Collapse cut candidates closer than this (s)")
def propose(video, workdir, max_spot, merge_gap):
    """Fuse scan (+ transcript if present) into segments.json + breaks.md."""
    wd = workdir_for(video, workdir)
    cand_path = wd / "candidates.json"
    if not cand_path.exists():
        click.echo("No candidates.json — run `scan` first.", err=True)
        sys.exit(1)
    candidates = json.loads(cand_path.read_text())

    transcript = None
    tpath = wd / "transcript.json"
    if tpath.exists():
        transcript = transcribe_mod.load(tpath)

    duration = float(ffdetect.probe(video)["format"]["duration"])
    segments = propose_mod.build_segments(candidates, duration, max_spot=max_spot,
                                          merge_gap=merge_gap)
    propose_mod.save_segments(segments, wd / "segments.json")
    (wd / "breaks.md").write_text(
        propose_mod.review_markdown(segments, transcript, video.name)
    )
    n_comm = sum(1 for s in segments if s["label"] == "commercial")
    n_breaks = max((s.get("break", 0) for s in segments), default=0)
    click.echo(
        f"{len(segments)} blocks — {n_comm} commercial spots in {n_breaks} breaks. "
        f"Review {wd/'breaks.md'}, edit {wd/'segments.json'}, then run `cut`."
    )


@cli.command()
@click.argument("video", type=click.Path(exists=True, path_type=Path))
@click.option("--workdir", default=None)
@click.option("--only", default="commercial", show_default=True,
              help="Extract only this label ('all' for everything)")
@click.option("--precise", is_flag=True, help="Re-encode for frame-exact cuts")
@click.option("--pad", default=0.0, show_default=True, help="Pad each clip (s)")
def cut(video, workdir, only, precise, pad):
    """Extract clips per segments.json (stream copy by default)."""
    wd = workdir_for(video, workdir)
    seg_path = wd / "segments.json"
    if not seg_path.exists():
        click.echo("No segments.json — run `propose` first.", err=True)
        sys.exit(1)
    segments = propose_mod.load_segments(seg_path)
    out_dir = wd / "clips"
    only_label = None if only == "all" else only
    t0 = time.time()
    written = do_extract(video, segments, out_dir, only_label, precise, pad)
    click.echo(f"Wrote {len(written)} clips to {out_dir} in {time.time()-t0:.0f}s.")


@cli.command()
@click.argument("workdirs", nargs=-1, required=True,
                type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--threshold", default=0.80, show_default=True)
def dedupe(workdirs, threshold):
    """Find near-identical commercial transcripts across .grab WORKDIRS."""
    from . import dedupe as dd
    items = dd.gather(list(workdirs))
    groups = dd.find_groups(items, threshold)
    out = Path(workdirs[0]) / "dedupe_report.md"
    out.write_text(dd.report(items, groups))
    ndup = sum(len(g) - 1 for g in groups)
    click.echo(f"{len(items)} commercials compared — {len(groups)} duplicate groups, "
               f"{ndup} redundant clips. Report: {out}")


@cli.command()
@click.argument("video", type=click.Path(exists=True, path_type=Path))
def doctor(video):
    """Check VIDEO for recovered-source container pathologies before processing."""
    from .doctor import diagnose
    click.echo(f"Checking {video.name} …")
    problems = diagnose(video)
    if not problems:
        click.echo("OK — no container pathologies detected.")
    else:
        for p in problems:
            click.echo(f"⚠ {p}")
        sys.exit(1)


def main():
    cli()


if __name__ == "__main__":
    main()
