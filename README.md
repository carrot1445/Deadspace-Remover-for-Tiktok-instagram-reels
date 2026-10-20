# tight-cut: a Claude Code skill for cutting dead space

Drop your raw talking-head videos into Claude Code and say "edit these". You get back the same
videos with the dead air between sentences removed.

- **Tight:** each clip starts the instant you start talking and ends the instant you stop, with
  zero gap between sentences.
- **Safe:** it never cuts inside a sentence and never clips a word. Soft word endings like the
  "-ting" in "marketing" are kept, while breaths, mouth clicks and room noise are cut.
- **Looks right:** it checks the frames so a clip doesn't end on you reaching to stop the
  recording.
- **Local and free:** ffmpeg plus [faster-whisper](https://github.com/SYSTRAN/faster-whisper). No
  API keys, and nothing is uploaded.
- **Organized:** output goes to `finished videos/<today's date>/`.

Made for phone selfie videos (TikTok, Reels, Shorts, UGC), where you record several takes back to
back and just want the pauses gone.

## Install

```bash
git clone https://github.com/carrot1445/Deadspace-Remover-for-Tiktok-instagram-reels
cp -r Deadspace-Remover-for-Tiktok-instagram-reels/tight-cut ~/.claude/skills/        # personal skill, every project
# or: cp -r Deadspace-Remover-for-Tiktok-instagram-reels/tight-cut <your-project>/.claude/skills/

pip install -r ~/.claude/skills/tight-cut/requirements.txt
```

You also need `ffmpeg` on your PATH (`brew install ffmpeg` / `apt install ffmpeg` /
`winget install ffmpeg`). The first run downloads the whisper `small` model (~460 MB, cached
after that).

## Use

In Claude Code:

```
edit these: ~/Downloads/clip1.MP4 ~/Downloads/clip2.MP4
```

or `/tight-cut ~/Downloads/clip1.MP4`. Claude runs the cutter, checks that no words were lost,
reads the frame sheet for start/stop-recording reaches, and tells you where the files are.

Or run the script yourself without Claude:

```bash
python ~/.claude/skills/tight-cut/scripts/tight_cut.py clip1.MP4 clip2.MP4 --verify
```

```
clip1.MP4: 76.06s -> 57.19s, removed 18.87s, 14 clips
   -> finished videos/2026-10-14/clip1_tight.mp4
   edge sheet -> finished videos/2026-10-14/.qa/clip1_edges.jpg
   verify: 286 -> 282 words, match 0.961
```

## How it decides where to cut

1. **Finding sentence breaks.** Whisper transcribes locally to find where sentences end (`.`,
   `?`, `!`, or any pause of 0.7 s or more). Whisper's word timestamps are often off by 100 ms to
   2 s, so they're used only to locate breaks, never to place a cut.
2. **Placing the cut.** Each cut edge comes from the audio itself, in 10 ms frames. Anything
   above -32 dB is speech. Brief dips inside a word are bridged so the word isn't split, and
   short isolated sounds are dropped as clicks. Speech edges then extend through soft endings
   (up to 200 ms) and soft starts (up to 50 ms) while louder than -41 dB, which keeps quiet word
   endings but not inhales.
3. **Cutting.** At each sentence break, every silent stretch of 0.12 s or more is removed. Pauses
   inside a sentence are never touched.
4. **Checking.** `--verify` re-transcribes the output and diffs the words against the source. An
   edge sheet (the first and last frames of every clip) lets you, or Claude, spot a clip that ends
   on a reach for the phone.

These defaults are the tightest setting that removed no audible speech in testing. Tighter
settings start clipping quiet word endings.

## Options

| Flag | Default | What it does |
|---|---|---|
| `--gap` | `0` | seconds of silence left between sentences |
| `--tail` / `--onset` | `0.2` / `0.05` | max soft-ending / soft-start kept around speech |
| `--edge-db` | `-41` | how quiet a soft edge can be and still count as speech |
| `--long-pause` | `0.7` | an unpunctuated pause this long counts as a sentence break |
| `--model` | `small` | faster-whisper model (`medium` for tougher audio) |
| `--out-dir` | `finished videos/<date>` | where the output goes |
| `--dry-run` | | print the plan without rendering |
| `--verify` | | re-transcribe the output and list any word differences |

## Limits

- Needs speech over a fairly quiet room. Constant background music leaves no silence to find.
- It re-encodes (x264 CRF 18, AAC 192k). Resolution and frame rate are preserved.
- It cuts dead space only: no filler-word removal, no retake selection, no captions.

## License

MIT
