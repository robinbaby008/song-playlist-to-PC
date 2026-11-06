# Web Song Downloader

Local Flask web UI that accepts a CSV/JSON of song details and downloads them as MP3 to a folder on your PC.

## Requirements
- Python 3
- `ffmpeg` installed (for MP3 conversion)
- `pip install -r requirements.txt`

## Run
```bash
pip install -r requirements.txt
python app.py
```
Open `http://127.0.0.1:5000`

## File formats
**CSV** (header row required):
```csv
artist,title,album
Artist One,Song Title,Album Name
```

**JSON**:
```json
[
  { "artist": "Artist One", "title": "Song Title", "album": "Album Name" }
]
```

## Workflow
1. Upload your CSV/JSON.
2. Enter the local download folder path (e.g. `./downloads` or `/home/robin/Music`).
3. Click **Start Download**.
4. Watch progress; MP3s are saved directly to that folder.

Only download content you have the right to.
