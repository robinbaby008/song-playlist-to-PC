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
**CSV** (header row required; Spotify export format supported):
```csv
Track URI,ISRC,Track Name,Album Name,Artist Name(s),Release Date,Duration (ms),Popularity,Explicit,Added By,Added At,Genres,Record Label,Danceability,Energy,Key,Loudness,Mode,Speechiness,Acousticness,Instrumentalness,Liveness,Valence,Tempo,Time Signature
spotify:track:xxxxx,INS181303xxx,xxx(From "xxx"),Best Of Palak Muchhal,Palak Muchhal;Arijit Singh,2020-06-09,304899,76,false,31yc6sv47oty65ur3k6ytov2p6ui,2026-10-27T13:12:18Z,bollywood,hindi pop,gujarati garba,desi,bangla pop,T-Series,0.644,0.517,9,-6.707,0,0.0273,0.521,0.00000327,0.0905,0.259,106.906,4
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
