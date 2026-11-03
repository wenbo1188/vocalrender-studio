# VocalRender Studio

A web editor for [VocalRender](https://github.com/pymaster17/VocalRender), a score-native singing voice synthesis model. It follows the track + piano-roll workflow of mainstream vocal synthesis tools. The editing model and the request format match VocalRender's real inputs.

It's a single static page (`index.html`) with no build step. Open it directly in a browser.

## Features

- **Piano roll**: drag a note vertically to change its pitch; drag the right edge to change its length (snaps to the 12 note values the model supports, and later notes shift automatically); double-click to enter lyrics (Tab jumps to the next note).
- **Lyric conventions**: one Chinese character per note; `-` continues the previous character (melisma); `SP` is a rest; `AP` is a breath.
- **Batch lyrics**: enter a line of lyrics and fill it into notes in order. On an empty roll, quarter notes are generated automatically.
- **Reference voices**: 6 GTSinger reference clips built in (Alto-1/2/3, Tenor-1/2/3). Custom 2–8 second uploads require confirming usage rights. Each voice's suggested range is marked on the keyboard and in the grid.
- **Phrase-by-phrase rendering**: the score is split into phrases at rests and each phrase is submitted separately (single-request limits: 64 lyric/rest units, 128 events). Status runs not rendered → queued → rendering → rendered / modified.
- **Takes**: generate multiple takes of the same phrase and pick one to compare. Changing the score, voice, model or generation parameters marks affected phrases for re-rendering.
- **Generation parameters**: `cfg_value`, `inference_timesteps`, `temperature`, `fsq_temperature`, `prompt_max_frames`, `max_len`, `lyrics_only`, and seed. Includes stable / balanced / vivid presets.
- **Validation**: non-Chinese lyrics, a melisma with no preceding character, over-limit phrases, and out-of-range notes are flagged in real time, with jump-to-location.
- **Other**: backing track import with synced playback, VocalRender label JSON import, undo/redo, keyboard shortcuts (press `?`), and autosave to browser local storage.

## Service API

By default the page runs in **demo mode** (rendering is simulated locally, and playback uses a formant synth as a stand-in for the voice). Switch to remote mode in Settings and enter a service URL, and the page calls the endpoints below:

| Method | Path | Description |
|---|---|---|
| GET | `/voices` | Built-in reference voices |
| POST | `/voices` | Upload reference audio (multipart), returns `upload_id` |
| POST | `/render` | Submit a phrase for rendering, returns `job_id` |
| GET | `/jobs/{job_id}` | `status`: queued / running / succeeded / failed, `progress` 0–1, `audio_url` |
| GET | `/jobs/{job_id}/audio` | 48 kHz WAV |
| POST | `/score/import` | Parse ABC / MusicXML into word·pitch·note·pitch2word |
| GET | `/health` | Connection test |

`POST /render` request body (the `score` field matches VocalRender's label JSON):

```json
{
  "checkpoint": "VocalRender-Pro",
  "score": {
    "item_name": "proj_p01",
    "word": ["晚", "风", "吹", "过", "旧", "街", "口", "SP"],
    "pitch": [64, 67, 69, 67, 64, 62, 60, 62, 0],
    "note": ["<NOTE_8>", "<NOTE_8>", "<NOTE_4>", "<NOTE_8>", "<NOTE_8>", "<NOTE_4>", "<NOTE_DOT_4>", "<NOTE_8>", "<NOTE_2>"],
    "pitch2word": [0, 1, 2, 3, 4, 5, 6, 6, 7],
    "bpm": 90
  },
  "prompt_audio": { "preset": "Alto-1" },
  "generation": {
    "cfg_value": 2.0, "inference_timesteps": 10, "temperature": 1.0,
    "fsq_temperature": 0, "max_len": 2000, "prompt_max_frames": 50,
    "lyrics_only": false, "seed": null
  },
  "output": { "sample_rate": 48000, "format": "wav" }
}
```

The server side can wrap the official repo's `demo/app.py` or `scripts/infer_vocalrender_svs_single.py`; the generation parameter names match that script's command-line arguments.
