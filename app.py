import os
import uuid
import glob
import json
import sys
import time
import re
import shutil
import subprocess
import threading
from flask import Flask, request, jsonify, send_file, render_template

app = Flask(__name__)
DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Optional shared cookies file for login-gated / age-restricted sites.
# Set COOKIES_FILE to a Netscape-format cookies.txt path.
COOKIES_FILE = os.environ.get("COOKIES_FILE") or None
if COOKIES_FILE and not os.path.isfile(COOKIES_FILE):
    COOKIES_FILE = None

# How long to keep downloaded files on disk before cleanup (seconds).
FILE_TTL = int(os.environ.get("PCLIP_FILE_TTL", "86400"))  # 24h default

jobs = {}
_jobs_lock = threading.Lock()

_tunnel = {"proc": None, "url": None, "log": None}
_tunnel_lock = threading.Lock()

CLOUDFLARED_PATHS = [
    os.path.join(os.path.dirname(__file__), "cloudflared.exe"),
    os.path.join(os.path.dirname(__file__), "cloudflared"),
]


def find_cloudflared():
    for p in CLOUDFLARED_PATHS:
        if os.path.isfile(p):
            return p
    return shutil.which("cloudflared")


def _cookies_arg():
    """Return ['--cookies', path] if a valid cookies file is configured."""
    if COOKIES_FILE and os.path.isfile(COOKIES_FILE):
        return ["--cookies", COOKIES_FILE]
    return []


def ytdlp_cmd(*extra):
    """Build a yt-dlp command with shared options (cookies, no playlist)."""
    return [sys.executable, "-m", "yt_dlp", "--no-playlist"] + _cookies_arg() + list(extra)


def parse_ytdlp_json(stdout):
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        return json.loads(line)
    raise ValueError("yt-dlp returned no data")


def last_err_line(stderr):
    lines = [l for l in (stderr or "").strip().splitlines() if l.strip()]
    return lines[-1] if lines else "Unknown error"


def fetch_info(url):
    cmd = ytdlp_cmd("-j", url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return None
        return parse_ytdlp_json(result.stdout)
    except Exception:
        return None


def _try_write_mp3_id3(mp3_path, info):
    try:
        from mutagen.mp3 import MP3
        from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, ID3NoHeaderError
        from urllib.request import urlopen
    except Exception:
        return
    try:
        try:
            audio = MP3(mp3_path)
            tags = audio.tags or ID3()
        except ID3NoHeaderError:
            tags = ID3()
            tags.save(mp3_path)
            audio = MP3(mp3_path)
            tags = audio.tags
        title = info.get("title") or ""
        artist = info.get("uploader") or info.get("channel") or info.get("creator") or ""
        album = info.get("playlist_title") or info.get("album") or ""
        if title:
            tags.delall("TIT2")
            tags.add(TIT2(encoding=3, text=title))
        if artist:
            tags.delall("TPE1")
            tags.add(TPE1(encoding=3, text=artist))
        if album:
            tags.delall("TALB")
            tags.add(TALB(encoding=3, text=album))
        thumb_url = info.get("thumbnail") or ""
        if thumb_url:
            try:
                req = urlopen(thumb_url, timeout=15)
                img_bytes = req.read()
                if img_bytes:
                    mime = "image/jpeg"
                    if thumb_url.lower().endswith(".png"):
                        mime = "image/png"
                    tags.delall("APIC")
                    tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=img_bytes))
            except Exception:
                pass
        tags.save(mp3_path, v2_version=3)
    except Exception:
        pass


def cleanup_old_files():
    """Remove downloaded files older than FILE_TTL seconds."""
    now = time.time()
    for f in glob.glob(os.path.join(DOWNLOAD_DIR, "*")):
        try:
            if now - os.path.getmtime(f) > FILE_TTL:
                os.remove(f)
        except OSError:
            pass


def cleanup_old_jobs():
    """Drop finished/errored jobs from memory after an hour."""
    now = time.time()
    with _jobs_lock:
        for jid in list(jobs.keys()):
            j = jobs[jid]
            if j.get("status") in ("done", "error") and now - j.get("_ts", now) > 3600:
                jobs.pop(jid, None)


def run_download(job_id, url, format_choice, format_id, audio_quality=None):
    with _jobs_lock:
        jobs[job_id]["_ts"] = time.time()
    out_template = os.path.join(DOWNLOAD_DIR, job_id + ".%(ext)s")
    info = fetch_info(url) or {}
    title = jobs[job_id].get("title") or info.get("title") or ""
    uploader = info.get("uploader") or info.get("channel") or ""
    if title:
        jobs[job_id]["title"] = title
    if uploader:
        jobs[job_id]["uploader"] = uploader

    cmd = ytdlp_cmd("-o", out_template)
    if format_choice == "audio":
        cmd += ["-x", "--audio-format", "mp3", "--embed-metadata",
                "--embed-thumbnail", "--convert-thumbnails", "jpg"]
        if audio_quality:
            cmd += ["--audio-quality", audio_quality,
                    "--postprocessor-args", "ExtractAudio+ffmpeg:-b:a " + audio_quality]
    elif format_id:
        cmd += ["-f", format_id + "+bestaudio/best", "--merge-output-format", "mp4"]
    else:
        cmd += ["-f", "bestvideo+bestaudio/best", "--merge-output-format", "mp4"]
    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = last_err_line(result.stderr)
            return
        files = glob.glob(os.path.join(DOWNLOAD_DIR, job_id + ".*"))
        if not files:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = "Download completed but no file was found"
            return
        if format_choice == "audio":
            target = [f for f in files if f.endswith(".mp3")]
            chosen = target[0] if target else files[0]
            if chosen.endswith(".mp3"):
                merged_info = {"title": title, "uploader": uploader,
                               "thumbnail": info.get("thumbnail") or ""}
                _try_write_mp3_id3(chosen, merged_info)
        else:
            target = [f for f in files if f.endswith(".mp4")]
            chosen = target[0] if target else files[0]
        for ff in files:
            if ff != chosen:
                try:
                    os.remove(ff)
                except OSError:
                    pass
        jobs[job_id]["status"] = "done"
        jobs[job_id]["file"] = chosen
        ext = os.path.splitext(chosen)[1]
        final_title = (jobs[job_id].get("title") or "").strip()
        if final_title:
            safe_title = "".join(c for c in final_title if c not in r'\/:*?"<>|').strip()[:100].strip()
            jobs[job_id]["filename"] = safe_title + ext if safe_title else os.path.basename(chosen)
        else:
            jobs[job_id]["filename"] = os.path.basename(chosen)
    except subprocess.TimeoutExpired:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = "Download timed out (5 min limit)"
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.json or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    cmd = ytdlp_cmd("-j", url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return jsonify({"error": last_err_line(result.stderr)}), 400
        info = parse_ytdlp_json(result.stdout)
        best_by_height = {}
        for f in info.get("formats", []):
            height = f.get("height")
            if height and f.get("vcodec", "none") != "none":
                tbr = f.get("tbr") or 0
                if height not in best_by_height or tbr > (best_by_height[height].get("tbr") or 0):
                    best_by_height[height] = f
        formats = [
            {"id": f["format_id"], "label": str(height) + "p", "height": height}
            for height, f in best_by_height.items()
        ]
        formats.sort(key=lambda item: item["height"], reverse=True)
        return jsonify({
            "title": info.get("title", ""),
            "thumbnail": info.get("thumbnail", ""),
            "duration": info.get("duration"),
            "uploader": info.get("uploader") or info.get("channel") or "",
            "formats": formats,
        })
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out fetching video info"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/playlist", methods=["POST"])
def get_playlist_info():
    data = request.json or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    cmd = ytdlp_cmd("--flat-playlist", "-J", url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return jsonify({"error": last_err_line(result.stderr)}), 400
        info = json.loads(result.stdout)
        entries = info.get("entries", [])
        urls = [entry.get("url") for entry in entries if entry.get("url")]
        return jsonify({"urls": urls})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out fetching playlist info"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.get_json(silent=True) or request.form or {}
    url = data.get("url", "")
    if not isinstance(url, str):
        return jsonify({"error": "Invalid URL"}), 400
    url = url.strip()
    format_choice = data.get("format", "video")
    format_id = data.get("format_id")
    title = data.get("title", "")
    if not isinstance(title, str):
        title = ""
    audio_quality = data.get("audio_quality")
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    job_id = uuid.uuid4().hex[:10]
    with _jobs_lock:
        jobs[job_id] = {"status": "downloading", "url": url, "title": title, "_ts": time.time()}
    thread = threading.Thread(target=run_download, args=(job_id, url, format_choice, format_id, audio_quality))
    thread.daemon = True
    thread.start()
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def check_status(job_id):
    with _jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job["status"],
        "error": job.get("error"),
        "filename": job.get("filename"),
    })


@app.route("/api/file/<job_id>")
def download_file(job_id):
    with _jobs_lock:
        job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "File not ready"}), 404
    return send_file(job["file"], as_attachment=True, download_name=job["filename"])


@app.route("/api/access")
def access_info():
    port = int(os.environ.get("PORT", 8899))
    lan = get_lan_ip()
    with _tunnel_lock:
        tunnel_url = _tunnel["url"]
    return jsonify({
        "local": "http://localhost:" + str(port),
        "wifi": ("http://" + lan + ":" + str(port)) if lan else None,
        "lan_ip": lan,
        "port": port,
        "tunnel": tunnel_url,
        "tunnel_available": find_cloudflared() is not None,
    })


@app.route("/api/tunnel/start", methods=["POST"])
def tunnel_start():
    with _tunnel_lock:
        if _tunnel["proc"] and _tunnel["proc"].poll() is None:
            return jsonify({"url": _tunnel["url"], "status": "running"})
    cf = find_cloudflared()
    if not cf:
        return jsonify({"error": "cloudflared not found. Run pclip-tunnel.bat once to download it."}), 404
    port = int(os.environ.get("PORT", 8899))
    log_path = os.path.join(os.environ.get("TEMP", os.path.dirname(__file__)), "pclip-cloudflared.log")
    try:
        log_f = open(log_path, "w")
    except Exception:
        log_f = subprocess.DEVNULL
    proc = subprocess.Popen(
        [cf, "tunnel", "--url", "http://127.0.0.1:" + str(port), "--no-autoupdate"],
        stdout=log_f, stderr=subprocess.STDOUT,
    )
    with _tunnel_lock:
        _tunnel["proc"] = proc
        _tunnel["log"] = log_path
        _tunnel["url"] = None

    # Poll the log file for the public URL
    url = None
    for _ in range(80):  # up to ~16 seconds
        time.sleep(0.2)
        try:
            with open(log_path, "r", errors="ignore") as f:
                content = f.read()
            m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", content)
            if m:
                url = m.group(0)
                break
        except Exception:
            pass
    with _tunnel_lock:
        _tunnel["url"] = url
    if url:
        return jsonify({"url": url, "status": "running"})
    return jsonify({"error": "Timed out waiting for tunnel URL", "log": log_path}), 500


@app.route("/api/tunnel/stop", methods=["POST"])
def tunnel_stop():
    with _tunnel_lock:
        proc = _tunnel.pop("proc", None)
        _tunnel["url"] = None
    if proc:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    return jsonify({"status": "stopped"})


def _open_browser_later(port):
    import webbrowser
    import socket
    url = "http://127.0.0.1:" + str(port)
    try:
        for _ in range(25):
            time.sleep(0.15)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.2)
            try:
                result = sock.connect_ex(("127.0.0.1", port))
                if result == 0:
                    webbrowser.open(url, new=2)
                    break
            except Exception:
                pass
            finally:
                try:
                    sock.close()
                except Exception:
                    pass
    except Exception:
        pass


def get_lan_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


if __name__ == "__main__":
    cleanup_old_files()
    cleanup_old_jobs()

    port = int(os.environ.get("PORT", 8899))
    host = os.environ.get("HOST", "0.0.0.0")
    if os.environ.get("PCLIP_AUTO_OPEN", "1") != "0":
        threading.Thread(target=_open_browser_later, args=(port,), daemon=True).start()
    lan = get_lan_ip()
    print("")
    print("  PClip running")
    print("    this PC :  http://localhost:" + str(port))
    if lan and host != "127.0.0.1":
        print("    same WiFi: http://" + lan + ":" + str(port) + "   <- use this on your phone")
    if COOKIES_FILE:
        print("    cookies :  " + COOKIES_FILE)
    print("")
    app.run(host=host, port=port, use_reloader=False)
