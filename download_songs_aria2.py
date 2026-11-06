import csv
import json
import os
import subprocess
import sys
import time
import uuid

import requests

ARIA2_RPC = "http://localhost:6800/jsonrpc"


class Aria2Client:
    def __init__(self, url=ARIA2_RPC, secret=""):
        self.url = url
        self.secret = "token:" + secret if secret else ""

    def call(self, method, params=None):
        if params is None:
            params = []
        if self.secret:
            params = [self.secret] + params
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        r = requests.post(self.url, json=payload, timeout=10)
        r.raise_for_status()
        resp = r.json()
        if "error" in resp:
            raise Exception(resp["error"])
        return resp["result"]

    def add_uri(self, uris, out, dir_path):
        options = {"out": out, "dir": dir_path, "continue": "true"}
        return self.call("aria2.addUri", [uris, options])

    def tell_status(self, gid):
        return self.call("aria2.tellStatus", [gid])


def load_songs(path):
    ext = os.path.splitext(path)[1].lower()
    songs = []
    with open(path, encoding="utf-8") as f:
        if ext == ".json":
            data = json.load(f)
            if isinstance(data, dict):
                data = data.get("songs", data)
            for item in data:
                songs.append(
                    {
                        "artist": item.get("artist", ""),
                        "title": item.get("title", ""),
                        "album": item.get("album", ""),
                    }
                )
        else:
            reader = csv.DictReader(f)
            for row in reader:
                songs.append(
                    {
                        "artist": row.get("artist", ""),
                        "title": row.get("title", ""),
                        "album": row.get("album", ""),
                    }
                )
    return songs


def resolve_audio_url(query):
    cmd = ["yt-dlp", "-g", "-f", "bestaudio/best", f"ytsearch1:{query}"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return r.stdout.strip().splitlines()[0]


def safe_name(song):
    base = f"{song['artist']} - {song['title']}"
    safe = "".join(c for c in base if c.isalnum() or c in " -_().[]")
    return safe


def main():
    if len(sys.argv) < 4:
        print("Usage: python download_songs_aria2.py <file.csv|file.json> <output_folder> <aria2_secret>")
        print("Start aria2 first: aria2c --enable-rpc --rpc-listen-all --rpc-secret=YOUR_SECRET")
        sys.exit(1)

    path, outdir, secret = sys.argv[1], sys.argv[2], sys.argv[3]
    os.makedirs(outdir, exist_ok=True)

    client = Aria2Client(secret=secret)
    songs = load_songs(path)
    print(f"Loaded {len(songs)} songs from {path}")

    ok = fail = 0
    for i, song in enumerate(songs, 1):
        q = f"{song['artist']} - {song['title']}"
        print(f"[{i}/{len(songs)}] {q}")
        url = resolve_audio_url(q)
        if not url:
            print("  Could not resolve URL")
            fail += 1
            continue
        name = safe_name(song)
        try:
            gid = client.add_uri([url], name + ".part", outdir)
            while True:
                st = client.tell_status(gid)
                status = st.get("status")
                if status == "complete":
                    break
                if status in ("error", "removed"):
                    raise Exception(status)
                time.sleep(2)
            src = os.path.join(outdir, name + ".part")
            dst = os.path.join(outdir, name + ".mp3")
            if os.path.exists(src):
                subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-i",
                        src,
                        "-vn",
                        "-codec:a",
                        "libmp3lame",
                        "-qscale:a",
                        "0",
                        dst,
                    ],
                    capture_output=True,
                )
                os.remove(src)
                print("  Downloaded and converted")
                ok += 1
            else:
                print("  File not found after download")
                fail += 1
        except Exception as e:
            print(f"  Error: {e}")
            fail += 1

    print(f"\nDone: {ok} succeeded, {fail} failed")


if __name__ == "__main__":
    main()
