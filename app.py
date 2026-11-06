import os
import csv
import json
import subprocess
import threading
import uuid
import tempfile
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
import requests

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = tempfile.gettempdir()
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

JOBS = {}
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".download_config.json")


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except Exception:
        pass


TITLE_KEYS = {"track name", "track_name", "song name", "song", "title", "name"}
ARTIST_KEYS = {"artist", "artists", "singer", "singers", "performer", "performers", "artist(s)", "artist name"}
ALBUM_KEYS = {"album", "album_name"}
URI_KEYS = {"track uri", "track_uri", "uri", "spotify uri", "spotify_track_uri"}


def pick(row, keys):
    lowered = {rk.lower(): rv for rk, rv in row.items() if rk}
    for k in keys:
        if k in lowered and lowered[k]:
            return lowered[k]
        for rk, rv in lowered.items():
            if k in rk and rv:
                return rv
    return ""


def get_spotify_token(client_id, client_secret):
    auth = requests.auth.HTTPBasicAuth(client_id, client_secret)
    data = {"grant_type": "client_credentials"}
    r = requests.post(
        "https://accounts.spotify.com/api/token", auth=auth, data=data, timeout=15
    )
    r.raise_for_status()
    return r.json()["access_token"]


def get_spotify_track(token, track_uri):
    track_id = track_uri.split(":")[-1] if ":" in track_uri else track_uri
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(
        f"https://api.spotify.com/v1/tracks/{track_id}", headers=headers, timeout=15
    )
    r.raise_for_status()
    data = r.json()
    artists = ", ".join(a.get("name", "") for a in data.get("artists", []))
    return {
        "title": data.get("name", ""),
        "artist": artists,
        "album": data.get("album", {}).get("name", ""),
        "source": "spotify",
    }


def load_songs(path, client_id="", client_secret=""):
    ext = os.path.splitext(path)[1].lower()
    songs = []
    token = None
    if client_id and client_secret:
        try:
            token = get_spotify_token(client_id, client_secret)
        except Exception as e:
            print(f"[WARN] Spotify token failed: {e}")

    with open(path, encoding="utf-8", errors="replace") as f:
        if ext == ".json":
            data = json.load(f)
            if isinstance(data, dict):
                data = data.get("songs", data)
            for item in data:
                uri = str(item.get("track uri", item.get("track_uri", item.get("uri", "")) or ""))
                if token and uri.startswith("spotify:track:"):
                    try:
                        meta = get_spotify_track(token, uri)
                        artist = meta["artist"]
                        title = meta["title"]
                        album = meta["album"]
                    except Exception as e:
                        print(f"[WARN] Spotify track fetch failed for {uri}: {e}")
                        artist = str(item.get("artist", "") or "")
                        title = str(item.get("title", "") or "")
                        album = str(item.get("album", "") or "")
                else:
                    artist = str(item.get("artist", "") or "")
                    title = str(item.get("title", "") or "")
                    album = str(item.get("album", "") or "")
                songs.append(
                    {
                        "artist": artist,
                        "title": title,
                        "album": album,
                        "uri": uri,
                        "raw": item,
                    }
                )
        else:
            reader = csv.DictReader(f)
            for row in reader:
                artist = pick(row, ARTIST_KEYS)
                title = pick(row, TITLE_KEYS)
                album = pick(row, ALBUM_KEYS)
                uri = pick(row, URI_KEYS)
                if token and uri and uri.startswith("spotify:track:"):
                    try:
                        meta = get_spotify_track(token, uri)
                        artist = meta["artist"] or artist
                        title = meta["title"] or title
                        album = meta["album"] or album
                    except Exception as e:
                        print(f"[WARN] Spotify track fetch failed for {uri}: {e}")
                if not title:
                    for v in row.values():
                        if v and len(v) > 1:
                            title = v
                            break
                songs.append(
                    {
                        "artist": artist,
                        "title": title,
                        "album": album,
                        "uri": uri,
                        "raw": row,
                    }
                )
    return songs


def safe_name(title):
    base = title or "track"
    return "".join(c for c in base if c.isalnum() or c in " -_().[]")


def log(job_id, msg, level="info"):
    entry = {"level": level, "msg": msg}
    if job_id in JOBS:
        JOBS[job_id]["logs"].append(entry)
    print(f"[{level.upper()}] {msg}")


def find_new_mp3(output_dir, before_files):
    try:
        after = set(os.listdir(output_dir))
    except FileNotFoundError:
        return None
    new = after - before_files
    mp3s = sorted(
        [f for f in new if f.lower().endswith(".mp3")],
        key=lambda f: os.path.getmtime(os.path.join(output_dir, f)),
        reverse=True,
    )
    return mp3s[0] if mp3s else None


def mp3_exists(output_dir, name):
    """Check if an mp3 file already exists for this song (by safe title prefix)."""
    try:
        for f in os.listdir(output_dir):
            if f.lower().endswith(".mp3") and f.startswith(name):
                return True
    except FileNotFoundError:
        return False
    return False


def download_song(job_id, song, idx, total, output_dir, client_id="", client_secret="", cookies=""):
    artist = song["artist"]
    title = song["title"]
    album = song["album"]
    uri = song.get("uri", "")
    name = safe_name(title)

    # Skip if already downloaded (no duplicates)
    if mp3_exists(output_dir, name):
        JOBS[job_id]["done"] += 1
        JOBS[job_id]["songs"].append(
            {
                "idx": idx,
                "artist": artist,
                "title": title,
                "album": album,
                "uri": uri,
                "status": "ok",
                "file": name + ".mp3 (already exists)",
                "debug": "skipped: file already exists",
            }
        )
        log(job_id, f"[{idx}/{total}] SKIP (already exists): {title}")
        return True

    # Build search queries: artist + title, then title alone, then title + album
    queries = []
    if artist and title:
        queries.append(f"{artist} - {title}")
    if title:
        queries.append(title)
    if artist and title and album:
        queries.append(f"{title} {album}")

    downloaded_file = None
    last_error = ""

    for q in queries:
        outtmpl = os.path.join(output_dir, name + ".%(ext)s")
        cmd = [
            "yt-dlp",
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "0",
            "--no-playlist",
            "-o",
            outtmpl,
        ]
        if cookies:
            if cookies.lower() in ("chrome", "firefox", "edge", "opera", "brave", "safari", "chromium"):
                cmd += ["--cookies-from-browser", cookies]
            else:
                cmd += ["--cookies", cookies]
        cmd.append(f"ytsearch1:{q}")
        log(job_id, f"[{idx}/{total}] Searching: {q}")
        try:
            before = set(os.listdir(output_dir))
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=180
            )
            stdout_tail = (r.stdout or "")[-500:]
            stderr_tail = (r.stderr or "")[-800:]
            debug = (
                f"CMD: {' '.join(cmd)}\n"
                f"STDOUT: {stdout_tail}\n"
                f"STDERR: {stderr_tail}"
            )

            if r.returncode == 0:
                found = find_new_mp3(output_dir, before)
                if found:
                    downloaded_file = found
                    JOBS[job_id]["done"] += 1
                    JOBS[job_id]["songs"].append(
                        {
                            "idx": idx,
                            "artist": artist,
                            "title": title,
                            "album": album,
                            "uri": uri,
                            "status": "ok",
                            "file": found,
                            "debug": debug,
                        }
                    )
                    log(job_id, f"  OK -> {found}")
                    return True
                else:
                    last_error = "Returned 0 but no new mp3 found"
            else:
                last_error = stderr_tail[-300:]
        except subprocess.TimeoutExpired:
            last_error = "timeout"
            log(job_id, "  FAILED: timeout", "error")
            continue

    if not downloaded_file:
        JOBS[job_id]["failed"] += 1
        JOBS[job_id]["songs"].append(
            {
                "idx": idx,
                "artist": artist,
                "title": title,
                "album": album,
                "uri": uri,
                "status": "fail",
                "file": "",
                "error": last_error or "unknown error",
                "debug": last_error or "",
            }
        )
        log(job_id, f"  FAILED: {last_error or 'unknown'}", "error")
        return False


def run_download(job_id, file_path, output_dir, client_id="", client_secret="", songs=None, start_idx=1, cookies=""):
    try:
        os.makedirs(output_dir, exist_ok=True)
        if songs is None:
            songs = load_songs(file_path, client_id, client_secret)
        total = len(songs)
        if job_id not in JOBS:
            JOBS[job_id] = {
                "status": "running",
                "total": total,
                "done": 0,
                "failed": 0,
                "logs": [],
                "songs": [],
            }
        log(job_id, f"Output directory: {os.path.abspath(output_dir)}")
        if client_id and client_secret:
            log(job_id, "Spotify metadata enrichment enabled")
        else:
            log(job_id, "Spotify credentials not provided; using CSV columns only")

        for i, song in enumerate(songs, start_idx):
            download_song(job_id, song, i, total, output_dir, client_id, client_secret, cookies)

        JOBS[job_id]["status"] = "completed"
        log(
            job_id,
            f"Done: {JOBS[job_id]['done']} succeeded, {JOBS[job_id]['failed']} failed -> {output_dir}",
        )
    except Exception as e:
        JOBS[job_id]["status"] = "error"
        log(job_id, f"Fatal error: {e}", "error")


@app.route("/")
def index():
    cfg = load_config()
    return render_template(
        "index.html",
        saved_path=cfg.get("download_path", ""),
        spotify_client_id=os.environ.get("SPOTIFY_CLIENT_ID", ""),
        spotify_client_secret=os.environ.get("SPOTIFY_CLIENT_SECRET", ""),
    )


@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error": "no filename"}), 400
    fname = secure_filename(f.filename)
    path = os.path.join(app.config["UPLOAD_FOLDER"], fname)
    f.save(path)
    try:
        preview = load_songs(path)[:5]
    except Exception as e:
        preview = []
        log_dbg = str(e)
    else:
        log_dbg = None
    return jsonify(
        {
            "file_path": path,
            "name": fname,
            "preview": preview,
            "preview_error": log_dbg,
        }
    )


@app.route("/upload-cookies", methods=["POST"])
def upload_cookies():
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400
    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error": "no filename"}), 400
    fname = secure_filename(f.filename)
    path = os.path.join(app.config["UPLOAD_FOLDER"], fname)
    f.save(path)
    return jsonify({"cookies_path": path, "name": fname})


@app.route("/download", methods=["POST"])
def download():
    data = request.get_json(force=True)
    file_path = data.get("file_path")
    output_dir = data.get("output_dir", "./downloads")
    remember = data.get("remember_path", False)
    client_id = data.get("spotify_client_id", "") or os.environ.get("SPOTIFY_CLIENT_ID", "")
    client_secret = data.get("spotify_client_secret", "") or os.environ.get("SPOTIFY_CLIENT_SECRET", "")
    cookies = data.get("cookies", "")
    if remember:
        cfg = load_config()
        cfg["download_path"] = output_dir
        save_config(cfg)
        print(f"[system] Saved download path to config: {output_dir}")
    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "invalid file_path"}), 400
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "status": "starting",
        "total": 0,
        "done": 0,
        "failed": 0,
        "logs": [],
        "songs": [],
        "file_path": file_path,
        "output_dir": output_dir,
        "client_id": client_id,
        "client_secret": client_secret,
        "cookies": cookies,
    }
    thread = threading.Thread(
        target=run_download,
        args=(job_id, file_path, output_dir, client_id, client_secret, None, 1, cookies),
        daemon=True,
    )
    thread.start()
    return jsonify({"job_id": job_id})


@app.route("/retry", methods=["POST"])
def retry():
    data = request.get_json(force=True)
    job_id = data.get("job_id")
    if not job_id or job_id not in JOBS:
        return jsonify({"error": "invalid job_id"}), 400
    job = JOBS[job_id]
    failed_songs = [s for s in job.get("songs", []) if s.get("status") == "fail"]
    if not failed_songs:
        return jsonify({"error": "no failed songs to retry"}), 400

    output_dir = job.get("output_dir", "./downloads")
    client_id = job.get("client_id", "")
    client_secret = job.get("client_secret", "")
    cookies = data.get("cookies", "") or job.get("cookies", "")

    new_job_id = str(uuid.uuid4())
    JOBS[new_job_id] = {
        "status": "starting",
        "total": len(failed_songs),
        "done": 0,
        "failed": 0,
        "logs": [],
        "songs": [],
        "file_path": job.get("file_path", ""),
        "output_dir": output_dir,
        "client_id": client_id,
        "client_secret": client_secret,
        "is_retry": True,
        "parent_job_id": job_id,
    }
    log(new_job_id, f"Retrying {len(failed_songs)} failed songs from job {job_id}")
    log(new_job_id, f"Output directory: {os.path.abspath(output_dir)}")

    thread = threading.Thread(
        target=run_download,
        args=(new_job_id, None, output_dir, client_id, client_secret, failed_songs, 1, cookies),
        daemon=True,
    )
    thread.start()
    return jsonify({"job_id": new_job_id})


@app.route("/status/<job_id>")
def status(job_id):
    return jsonify(JOBS.get(job_id, {"status": "not_found"}))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
