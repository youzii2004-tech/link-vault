# Link Vault

[![CI](https://github.com/youzii2004-tech/link-vault/actions/workflows/ci.yml/badge.svg)](https://github.com/youzii2004-tech/link-vault/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

A small command-line tool for people who save lots of short-form videos and want them searchable.
Feed it a pile of links (CSV, text file, pasted clipboard); it cleans them, downloads the videos with
[yt-dlp](https://github.com/yt-dlp/yt-dlp), then extracts metadata, 5 keyframes and a
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) transcript from each one. A local HTML
dashboard lets you browse the results.

Most of the heavy lifting is done by yt-dlp, ffmpeg and faster-whisper. This project is the glue:
URL parsing/cleanup, download orchestration (threads, retries) and the analysis/dashboard layer.

## What it does

1. **Ingest** – extracts URLs from CSV (auto-detects the URL column), text files or raw pasted text.
2. **Sanitize** – strips tracking parameters (`utm_*`, `igsh`, `fbclid`, …), classifies the platform
   (Instagram, TikTok, YouTube, Facebook, X, Pinterest, Reddit, generic) and assigns a stable
   SHA-256-based ID so duplicates collapse.
3. **Download** – yt-dlp in a thread pool, with retries and exponential backoff. Raw `.mp4`/`.webm`
   URLs fall back to a plain HTTP download. Optional Netscape `cookies.txt` for logged-in content.
4. **Analyze** – `ffprobe` metadata (duration, codec, resolution, aspect ratio, audio track),
   5 JPEG keyframes at 10/30/50/70/90 % of the duration via `ffmpeg`, and a timestamped transcript via
   faster-whisper. Videos without an audio track skip transcription.
5. **Browse** – `serve` starts a local dashboard (`dashboard/index.html`) over the output folder.

## Requirements

- Python 3.10+
- `ffmpeg` and `ffprobe` on your `PATH`
- `pip install -r requirements.txt`

## Usage

```bash
python -m src.cli ingest sample_links.csv --out links.json
python -m src.cli download links.json --cookies cookies.txt --workers 4 --out-dir downloads/
python -m src.cli analyze downloads/ --out-dir analysis_output/
python -m src.cli serve --port 8080 --host 127.0.0.1
```

(On Windows you can use `py -m src.cli ...`.) Settings live in `config/link_vault.example.yaml`.

## Cookies and privacy

Some Instagram/Facebook content needs a logged-in session. Export your cookies in Netscape format to a
local `cookies.txt` (see `cookies.example.txt`). The file is read from disk and passed to the local
yt-dlp process; Link Vault itself makes no network calls other than the downloads you ask for.
`cookies.txt` is gitignored and its format is validated before use. Treat it like a password.

## Limitations

- Social platforms change constantly; downloads depend on yt-dlp keeping up. Instagram and Facebook in
  particular break often and may rate-limit or block accounts.
- Downloading content, especially with a logged-in session, may violate a platform's terms of service.
  Use it for content you have the right to save, and at your own risk.
- Download behaviour against real platforms is not covered by CI. The test suite uses real
  ffmpeg/ffprobe and a local HTTP server, plus one opt-in test against a public YouTube video.
- Transcription uses the `tiny` Whisper model on CPU by default (fast, not very accurate).
- Primarily developed on Windows; CI runs on Linux and Windows.

## Tests

```bash
python -m pytest -v
# also hit a real public URL (needs yt-dlp and network):
LINKVAULT_NETWORK_TESTS=1 python -m pytest -v -m network
```

## License

MIT, see [LICENSE](LICENSE).
