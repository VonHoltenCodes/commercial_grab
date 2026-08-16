# commercial_grab

Pull vintage commercials out of off-air broadcast recordings — locally, losslessly, no cloud APIs.

Point it at a capture of an old broadcast (VHS rip, DVR recovery, DVD remux) and it
finds the commercial breaks, labels every spot with a transcript excerpt, and
stream-copies each commercial out as its own clip.

## How it works

The design borrows the transcript-first architecture of
[browser-use/video-use](https://github.com/browser-use/video-use), rebuilt for
archival work: no re-encoding by default, no cloud transcription.

1. **`scan`** — one ffmpeg pass runs `blackdetect` + `silencedetect`. Broadcasts
   cut to black between program and spots; black intervals that coincide with
   silence are high-confidence cut points.
2. **`transcribe`** — faster-whisper on the local GPU produces a word-timestamped
   transcript (`transcript.json` / `transcript.md`).
3. **`propose`** — cut points split the timeline into blocks. Blocks short enough
   to be a single spot (≤130 s by default) are labeled `commercial` and grouped
   into numbered breaks; longer blocks are `show`. Output: `segments.json` (the
   edit list) plus `breaks.md`, a review sheet with a transcript excerpt per
   block so a human — or an agent like Claude Code — can fix labels before cutting.
4. **`cut`** — extracts clips per `segments.json`. Default is `-c copy`
   (lossless, keyframe-snapped); `--precise` re-encodes for frame-exact bounds.

All stage outputs land in `<video>.grab/` next to the source, so every stage is
resumable and re-runnable independently.

## Install

```sh
pip install faster-whisper click   # plus ffmpeg on the system
git clone https://github.com/VonHoltenCodes/commercial_grab
cd commercial_grab
```

Requires an NVIDIA GPU + CUDA for transcription (`--device cpu` works, slowly).

## Use

```sh
python3 -m commercial_grab scan       recording.mkv
python3 -m commercial_grab transcribe recording.mkv
python3 -m commercial_grab propose    recording.mkv
# review recording.grab/breaks.md, edit recording.grab/segments.json if needed
python3 -m commercial_grab cut        recording.mkv            # commercials only
python3 -m commercial_grab cut       recording.mkv --only all  # everything
```

Clips land in `recording.grab/clips/` named `break03_spot02_1.02.45.mkv`.

### Tuning

- `scan --black-dur/--black-th/--silence-db` — detection thresholds. Noisy VHS
  sources may need `--black-th 0.15` and a hotter `--silence-db -30`.
- `propose --max-spot` — longest block still considered a single commercial
  (default 130 s covers 15/30/60/120 s spots with slop).
- `cut --pad 0.25` — pad clips if stream-copy keyframe snapping clips too tight.

Note on stream copy: `-c copy` cuts snap backward to the nearest keyframe, so a
clip can start a few seconds *early* (carrying the previous spot's tail) but
never late — no commercial content is ever lost. Use `--precise` when you need
frame-exact boundaries.

## Provenance

Built on devbase1 for the VonHolten fleet's broadcast archiving projects
(FX Batman '66 airings, HAVA captures, U-verse DVR recoveries).
