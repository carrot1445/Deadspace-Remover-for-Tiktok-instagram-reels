---
name: tight-cut
description: Dead-space-only cut for raw talking-head videos (phone selfie clips, TikToks, Reels, Shorts). Trims every clip tight to where speech starts and stops and collapses the gap BETWEEN sentences to zero, never cutting inside a sentence and never cutting a word. Also checks frames so no clip ends on the speaker reaching to stop the recording. Use when the user hands over video files and says "edit these", "cut the dead space", "deadspace cuts only", "remove the pauses", "tighten these", or sends videos to edit with no other instructions. Output goes to a dated folder, "finished videos/<YYYY-MM-DD>/". Not for captions, filler-word removal, retake selection or audio cleanup.
---

# tight-cut: dead space only, between sentences only

A local, free, deterministic cutter (ffmpeg + faster-whisper, no API keys). **Run it as-is; don't
re-derive the approach.** The reasoning behind every threshold is in the docstring of
`scripts/tight_cut.py`.

## Setup (once)

Needs `ffmpeg` on PATH and Python 3.10+:

```
pip install -r <this skill dir>/requirements.txt
```

The first run downloads the faster-whisper `small` model (~460 MB, cached after that).

## Run

From the folder where the user wants output:

```
python <this skill dir>/scripts/tight_cut.py <video1> <video2> ... --verify
```

→ `finished videos/<YYYY-MM-DD>/<name>_tight.mp4`. **Every batch goes in a folder named with
today's date inside `finished videos/`.** The tool creates it by default, and `--out-dir`
overrides it. Resolution and frame rate are preserved. QA sheets go in `.qa/` inside that folder.

## The rules (do not relax them)

- Cut ONLY between sentences. Pauses inside a sentence stay exactly as recorded.
- Each clip starts the instant speech starts and ends the instant it stops, with zero gap between
  sentences (`--gap 0`, the default). This is the tightest setting that cuts no words; tighter
  edges (`--tail` < 0.2, `--onset` < 0.05, `--edge-db` > -41) start eating soft word endings.
- Nothing else: no filler removal, no audio cleanup, no captions, no visuals.
- Never let a clip look like the speaker is about to press stop or has just pressed record.

## QA before reporting (both steps, every time)

1. **Words: `--verify`** re-transcribes each output and diffs it against the source. Ignore whisper
   noise ("want to"→"wanna", a compound word split or joined, a merged repeated phrase, a skipped
   final sentence). A genuinely missing or truncated word ("marketing"→"market", a dropped
   sentence-initial "Then") means the edges are too tight: re-run that file with
   `--tail 0.25 --onset 0.06 --edge-db -42`.
2. **Picture: read `.qa/<name>_edges.jpg`.** It has one row per kept clip: the left 3 frames are
   the clip's start, the right 5 are its end. Phone recordings are often several takes stitched
   together, and the reach toward the phone to stop or start a take is nearly silent, so the audio
   pass can't see it (frame-difference motion scores miss it too). Look for a hand moving toward
   the lens or lower edge, or eyes dropping to the phone.
   - Reach **after** the last word: shorten that clip so it ends before the reach.
   - Reach **during** the last word (common on a quick intro line): don't cut words. Tell the
     user and let them choose: drop the line, end on the previous word, or freeze the last clean
     frame.

## Knobs (only if the user asks)

| Want | Flag |
|---|---|
| a little breathing room between sentences | `--gap 0.05` |
| soft word endings clipped | `--tail 0.25 --edge-db -42` |
| soft word starts clipped | `--onset 0.06` |
| a long mid-sentence pause got shortened | `--long-pause 1.0` |
| better transcription on hard audio | `--model medium` |
| preview without rendering | `--dry-run` |

## Gotchas

- Whisper's word timings can be off by up to 2 s. The tool uses them only to find sentence breaks;
  cut edges come from 10 ms audio loudness. Don't "fix" it by trusting word times.
- Decoded samples are passed straight to faster-whisper, because its own decoder breaks on
  PyAV ≥ 19 (`metadata_errors` TypeError).
- Assumes a quiet room (noise floor around -50 dB). With constant music or noise under the voice
  there's no silence to find, so say so up front.
