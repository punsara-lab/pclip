# PClip

> A sleek, self-hosted video & audio downloader with a premium dark UI. Paste links from YouTube, TikTok, Instagram, X/Twitter, and **1000+ sites** — download as MP4 or MP3 with full metadata and cover art.

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![yt-dlp](https://img.shields.io/badge/powered--by-yt--dlp-ff6b6b)
![UI](https://img.shields.io/badge/UI-Dark%20Mode%20%E2%9C%A8-7c5cff)

Built by [**punsara-lab**](https://github.com/punsara-lab) — minimal, fast, no frameworks.

---

## ✨ Features

- **1000+ sites** — anything yt-dlp supports (YouTube, TikTok, IG, X, Reddit, SoundCloud, Twitch, Vimeo, etc.)
- **MP4 video** or **MP3 audio** with embedded cover art + title/artist metadata
- **Quality picker** — per-video resolution selection, bitrate selector (128/192/256/320 kbps)
- **Bulk downloads** — paste 50 URLs at once, click *Download All*
- **Auto playlist expansion** — paste a playlist URL, get all entries
- **URL dedup** — no duplicate downloads
- **Zero frontend build step** — vanilla HTML/CSS/JS, single template file
- **Tiny backend** — one Flask file (~280 lines)
- **Dark UI** — glassmorphism, soft gradients, tasteful minimalism
- **Cross-platform** — Windows `.bat`, macOS/Linux `.sh`, Docker

---

## 🚀 Quick Start

### Windows (one-click)

Ensure **Python 3.8+** and **FFmpeg** are on your `PATH`, then:

```bat
pclip.bat
```

The script auto-creates a venv, installs deps, updates yt-dlp, and opens your browser.

### macOS / Linux

```bash
# Install ffmpeg first: brew install ffmpeg  # or: sudo apt install ffmpeg
git clone https://github.com/punsara-lab/pclip.git
cd pclip
./pclip.sh
```

Open **http://localhost:8899**

### Docker

```bash
docker build -t pclip . && docker run -p 8899:8899 -v pclip-downloads:/app/downloads pclip
```

Or with docker-compose:

```bash
docker compose up -d
```

---

## 🧠 Usage

1. **Paste URLs** in the input (one per line, or separated by spaces/commas)
2. Pick **MP4** (video) or **MP3** (audio)
   - For MP3: choose bitrate 128 / 192 / 256 / 320
3. Click **Fetch** (or `Ctrl+Enter`) to load thumbs, titles, durations
4. Optional — per-card override: pick a specific resolution or bitrate
5. Click **Download** on a card, or **Download All** for the batch

Files land in `/downloads` with human-readable names, proper MP3 ID3v2.3 tags, and embedded cover art.

---

## 🧱 Stack

| Layer         | Tech                                                              |
|---------------|-------------------------------------------------------------------|
| Backend       | Python 3 · Flask (single ~280-line file)                          |
| Frontend      | Vanilla HTML/CSS/JS — no build, no npm, zero frameworks           |
| Downloader    | [yt-dlp](https://github.com/yt-dlp/yt-dlp)                        |
| Media toolkit | [FFmpeg](https://ffmpeg.org/)                                     |
| Metadata      | [mutagen](https://github.com/quodlibet/mutagen) (ID3 + cover art) |
| Hosting       | Local Flask, Docker-ready, no DB                                  |

**Direct pip deps**: `flask`, `yt-dlp`, `mutagen` — that's it.

---

## ⚙️ Environment Variables

| Variable           | Default       | Purpose                                       |
|--------------------|---------------|-----------------------------------------------|
| `PORT`             | `8899`        | Listen port                                   |
| `HOST`             | `127.0.0.1`   | Bind host — set `0.0.0.0` to expose on LAN    |
| `PCLIP_AUTO_OPEN`  | `1`           | Set to `0` to skip auto-opening the browser   |
| `PCLIP_NO_UPDATE`  | *(unset)*     | Define to skip the yt-dlp auto-update on boot |

---

## 📁 Project Layout

```
pclip/
├── app.py                  # Flask backend — all API routes + download logic
├── templates/
│   └── index.html          # Entire UI (HTML/CSS/JS in one file)
├── static/
│   └── favicon.svg         # Brand mark
├── downloads/              # Saved media (created automatically)
├── pclip.bat               # Windows launcher (venv + deps + auto-open)
├── pclip.sh                # macOS/Linux launcher
├── Dockerfile
├── docker-compose.yml
├── requirements.txt        # flask, yt-dlp, mutagen
└── README.md
```

---

## ⚠️ Disclaimer

Personal use only. Respect copyright and each platform's TOS. The authors are not liable for misuse.

---

## 📜 License

[MIT](LICENSE) · © 2026 [punsara-lab](https://github.com/punsara-lab)
