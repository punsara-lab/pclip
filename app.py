import os
import uuid
import glob
import json
import sys
import subprocess
import threading
import tempfile
from urllib.parse import quote
from flask import Flask, Response, request, jsonify, send_file, render_template, stream_with_context

app = Flask(__name__)
VERCEL_MODE = os.environ.get("VERCEL") == "1"
DOWNLOAD_DIR = (
    os.path.join(tempfile.gettempdir(), "pclip-downloads")
    if VERCEL_MODE
    else os.path.join(os.path.dirname(__file__), "downloads")
)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

jobs = {}


def parse_ytdlp_json(stdout):
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        return json.loads(line)
    raise ValueError("yt-dlp returned no data")


def fetch_info(url):
    cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist", "-j", url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return None
        return parse_ytdlp_json(result.stdout)
    except Exception:
        return None


def _vercel_formats(info):
    best_by_height = {}
    for media_format in info.get("formats", []):
        height = media_format.get("height")
        if (
            not height
            or media_format.get("vcodec", "none") == "none"
            or media_format.get("acodec", "none") == "none"
            or media_format.get("ext") != "mp4"
        ):
            continue
        tbr = media_format.get("tbr") or 0
        if height not in best_by_height or tbr > (best_by_height[height].get("tbr") or 0):
            best_by_height[height] = media_format
    return [
        {"id": media_format["format_id"], "label": str(height) + "p", "height": height}
        for height, media_format in sorted(best_by_height.items(), reverse=True)
    ]


def _safe_filename(title, fallback, extension):
    safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()[:100].strip()
    return safe_title + extension if safe_title else fallback


def _vercel_download(url, format_id, format_choice, title):
    if format_choice == "audio":
        return jsonify({"error": "MP3 conversion is unavailable on Vercel. Run PClip locally for audio downloads."}), 400
    if not isinstance(format_id, str) or not format_id:
        return jsonify({"error": "No progressive MP4 format is available. Try PClip locally for merged formats or audio."}), 400

    try:
        info_result = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--no-playlist", "-j", url],
            capture_output=True,
            text=True,
            timeout=25,
        )
        if info_result.returncode != 0:
            message = info_result.stderr.strip().split("\n")[-1]
            return jsonify({"error": message or "Could not fetch media information"}), 400
        info = parse_ytdlp_json(info_result.stdout)
        allowed_formats = {item["id"] for item in _vercel_formats(info)}
        if format_id not in allowed_formats:
            return jsonify({"error": "That format cannot stream directly on Vercel. Try PClip locally for merged formats."}), 400

        filename = _safe_filename(info.get("title") or title or "", "pclip", ".mp4")
        stderr_file = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")
        command = [
            sys.executable, "-m", "yt_dlp", "--no-playlist", "--quiet",
            "--no-progress", "--no-warnings", "-f", format_id, "-o", "-", url,
        ]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=stderr_file)

        def stream_media():
            try:
                if process.stdout is None:
                    raise RuntimeError("yt-dlp did not open a media stream")
                for chunk in iter(lambda: process.stdout.read(64 * 1024), b""):
                    yield chunk
                return_code = process.wait()
                if return_code:
                    stderr_file.seek(0)
                    app.logger.error("Vercel yt-dlp stream failed: %s", stderr_file.read()[-2000:])
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                if process.stdout:
                    process.stdout.close()
                stderr_file.close()

        encoded_filename = quote(filename)
        return Response(
            stream_with_context(stream_media()),
            mimetype="video/mp4",
            headers={
                "Content-Disposition": "attachment; filename=\"pclip.mp4\"; filename*=UTF-8''" + encoded_filename,
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Vercel download timed out. Try a shorter media file or run PClip locally."}), 504
    except (OSError, ValueError) as error:
        app.logger.exception("Vercel download failed")
        return jsonify({"error": "Could not prepare this download: " + str(error)}), 500


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


def run_download(job_id, url, format_choice, format_id, audio_quality=None):
    job = jobs[job_id]
    out_template = os.path.join(DOWNLOAD_DIR, job_id + ".%(ext)s")
    info = fetch_info(url) or {}
    title = job.get("title") or info.get("title") or ""
    uploader = info.get("uploader") or info.get("channel") or ""
    if title:
        job["title"] = title
    if uploader:
        job["uploader"] = uploader
    cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist", "-o", out_template]
    if format_choice == "audio":
        cmd += ["-x", "--audio-format", "mp3", "--embed-metadata", "--embed-thumbnail", "--convert-thumbnails", "jpg"]
        if audio_quality:
            cmd += ["--audio-quality", audio_quality, "--postprocessor-args", "ExtractAudio+ffmpeg:-b:a " + audio_quality]
    elif format_id:
        cmd += ["-f", format_id + "+bestaudio/best", "--merge-output-format", "mp4"]
    else:
        cmd += ["-f", "bestvideo+bestaudio/best", "--merge-output-format", "mp4"]
    cmd.append(url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            job["status"] = "error"
            job["error"] = result.stderr.strip().split("\n")[-1]
            return
        files = glob.glob(os.path.join(DOWNLOAD_DIR, job_id + ".*"))
        if not files:
            job["status"] = "error"
            job["error"] = "Download completed but no file was found"
            return
        if format_choice == "audio":
            target = [f for f in files if f.endswith(".mp3")]
            chosen = target[0] if target else files[0]
            if chosen.endswith(".mp3"):
                merged_info = {"title": title, "uploader": uploader, "thumbnail": info.get("thumbnail") or ""}
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
        job["status"] = "done"
        job["file"] = chosen
        ext = os.path.splitext(chosen)[1]
        final_title = (job.get("title") or "").strip()
        if final_title:
            safe_title = "".join(c for c in final_title if c not in r'\/:*?"<>|').strip()[:100].strip()
            job["filename"] = safe_title + ext if safe_title else os.path.basename(chosen)
        else:
            job["filename"] = os.path.basename(chosen)
    except subprocess.TimeoutExpired:
        job["status"] = "error"
        job["error"] = "Download timed out (5 min limit)"
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


@app.route("/")
def index():
    return render_template(
        "index.html",
        vercel_limited=VERCEL_MODE,
    )


@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    cmd = [sys.executable, "-m", "yt_dlp", "--no-playlist", "-j", url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=25 if VERCEL_MODE else 60)
        if result.returncode != 0:
            return jsonify({"error": result.stderr.strip().split("\n")[-1]}), 400
        info = parse_ytdlp_json(result.stdout)
        if VERCEL_MODE:
            formats = _vercel_formats(info)
        else:
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
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    cmd = [sys.executable, "-m", "yt_dlp", "--flat-playlist", "-J", url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=25 if VERCEL_MODE else 60)
        if result.returncode != 0:
            return jsonify({"error": result.stderr.strip().split("\n")[-1]}), 400
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
    if VERCEL_MODE:
        return _vercel_download(url, format_id, format_choice, title)
    job_id = uuid.uuid4().hex[:10]
    jobs[job_id] = {"status": "downloading", "url": url, "title": title}
    thread = threading.Thread(target=run_download, args=(job_id, url, format_choice, format_id, audio_quality))
    thread.daemon = True
    thread.start()
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>")
def check_status(job_id):
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
    job = jobs.get(job_id)
    if not job or job["status"] != "done":
        return jsonify({"error": "File not ready"}), 404
    return send_file(job["file"], as_attachment=True, download_name=job["filename"])


def _open_browser_later(port, host):
    import webbrowser
    import time
    import socket
    url = "http://" + host + ":" + str(port) if host != "0.0.0.0" else "http://127.0.0.1:" + str(port)
    try:
        for _ in range(25):
            time.sleep(0.15)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.2)
            try:
                result = sock.connect_ex(("127.0.0.1" if host == "0.0.0.0" else host, port))
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8899))
    host = os.environ.get("HOST", "127.0.0.1")
    if os.environ.get("PCLIP_AUTO_OPEN", "1") != "0":
        threading.Thread(target=_open_browser_later, args=(port, host), daemon=True).start()
    app.run(host=host, port=port, use_reloader=False)

