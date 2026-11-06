import os
import json
import csv
import tempfile
import unittest
from unittest.mock import patch, MagicMock, mock_open, call

import app


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        app.CONFIG_FILE = os.path.join(self.tmpdir, "config.json")

    def test_save_and_load_config(self):
        cfg = {"download_path": "/tmp/music"}
        app.save_config(cfg)
        loaded = app.load_config()
        self.assertEqual(loaded, cfg)

    def test_load_config_missing_file(self):
        app.CONFIG_FILE = os.path.join(self.tmpdir, "nonexistent.json")
        self.assertEqual(app.load_config(), {})

    def test_load_config_corrupt_file(self):
        with open(app.CONFIG_FILE, "w") as f:
            f.write("not valid json {{{")
        self.assertEqual(app.load_config(), {})


class TestPick(unittest.TestCase):
    def test_pick_exact_key(self):
        row = {"Artist": "Arijit Singh", "Title": "Tum Hi Ho"}
        self.assertEqual(app.pick(row, {"artist"}), "Arijit Singh")
        self.assertEqual(app.pick(row, {"title"}), "Tum Hi Ho")

    def test_pick_case_insensitive(self):
        row = {"ARTIST": "Shreya Ghoshal"}
        self.assertEqual(app.pick(row, {"artist"}), "Shreya Ghoshal")

    def test_pick_contains_key(self):
        row = {"Track Name": "Channa Mereya"}
        self.assertEqual(app.pick(row, {"track name"}), "Channa Mereya")

    def test_pick_empty(self):
        row = {}
        self.assertEqual(app.pick(row, {"artist"}), "")
        row2 = {"Artist": ""}
        self.assertEqual(app.pick(row2, {"artist"}), "")

    def test_pick_multiple_keys(self):
        row = {"Performer": "Arijit Singh"}
        self.assertEqual(app.pick(row, {"artist", "performer"}), "Arijit Singh")


class TestLoadSongs(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write_csv(self, rows, filename="songs.csv"):
        path = os.path.join(self.tmpdir, filename)
        fieldnames = set()
        for row in rows:
            fieldnames.update(row.keys())
        fieldnames = sorted(fieldnames)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return path

    def _write_json(self, data, filename="songs.json"):
        path = os.path.join(self.tmpdir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return path

    def test_load_csv(self):
        path = self._write_csv([
            {"artist": "Arijit Singh", "title": "Tum Hi Ho", "album": "Aashiqui 2"},
            {"artist": "Shreya Ghoshal", "title": "Agar Tum Saath Ho", "album": "Tamasha"},
        ])
        songs = app.load_songs(path)
        self.assertEqual(len(songs), 2)
        self.assertEqual(songs[0]["artist"], "Arijit Singh")
        self.assertEqual(songs[0]["title"], "Tum Hi Ho")
        self.assertEqual(songs[0]["album"], "Aashiqui 2")

    def test_load_json(self):
        path = self._write_json([
            {"artist": "Arijit Singh", "title": "Tum Hi Ho", "album": "Aashiqui 2"}
        ])
        songs = app.load_songs(path)
        self.assertEqual(len(songs), 1)
        self.assertEqual(songs[0]["title"], "Tum Hi Ho")

    def test_load_json_dict_with_songs_key(self):
        path = self._write_json({"songs": [{"artist": "A", "title": "B"}]})
        songs = app.load_songs(path)
        self.assertEqual(len(songs), 1)

    def test_load_csv_fallback_title(self):
        path = self._write_csv([
            {"artist": "A", "track_name": "Fallback Title", "album": "Album"}
        ])
        songs = app.load_songs(path)
        self.assertEqual(songs[0]["title"], "Fallback Title")

    @patch("app.get_spotify_token")
    @patch("app.get_spotify_track")
    def test_load_csv_spotify_uri(self, mock_track, mock_token):
        mock_token.return_value = "fake_token"
        mock_track.return_value = {
            "title": "Spotify Title",
            "artist": "Spotify Artist",
            "album": "Spotify Album",
        }
        path = self._write_csv([
            {"artist": "CSV Artist", "title": "CSV Title", "track uri": "spotify:track:12345"}
        ])
        songs = app.load_songs(path, client_id="cid", client_secret="csecret")
        self.assertEqual(songs[0]["title"], "Spotify Title")
        self.assertEqual(songs[0]["artist"], "Spotify Artist")
        self.assertEqual(songs[0]["album"], "Spotify Album")

    @patch("app.get_spotify_token", side_effect=Exception("auth failed"))
    def test_load_csv_spotify_token_failure(self, mock_token):
        path = self._write_csv([
            {"artist": "A", "title": "B", "track uri": "spotify:track:12345"}
        ])
        songs = app.load_songs(path, client_id="cid", client_secret="csecret")
        self.assertEqual(songs[0]["title"], "B")


class TestSafeName(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(app.safe_name("Tum Hi Ho"), "Tum Hi Ho")

    def test_special_chars_removed(self):
        self.assertEqual(app.safe_name('Chahun Main Ya Naa (From "Aashiqui 2")'),
                         'Chahun Main Ya Naa (From Aashiqui 2)')

    def test_empty(self):
        self.assertEqual(app.safe_name(""), "track")

    def test_none(self):
        self.assertEqual(app.safe_name(None), "track")


class TestLog(unittest.TestCase):
    def setUp(self):
        app.JOBS = {}

    def test_log_existing_job(self):
        app.JOBS["job1"] = {"logs": []}
        app.log("job1", "test message")
        self.assertEqual(app.JOBS["job1"]["logs"][0]["msg"], "test message")
        self.assertEqual(app.JOBS["job1"]["logs"][0]["level"], "info")

    def test_log_nonexisting_job(self):
        # Should not raise
        app.log("nonexistent", "test message")


class TestFindNewMp3(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    @patch("os.listdir")
    def test_find_new_mp3(self, mock_listdir):
        mock_listdir.return_value = {"song1.mp3", "song2.webm", "new_song.mp3"}
        with patch("os.path.getmtime", return_value=1000):
            result = app.find_new_mp3("/tmp/dir", {"song1.mp3", "song2.webm"})
        self.assertEqual(result, "new_song.mp3")

    @patch("os.listdir")
    def test_find_new_mp3_none(self, mock_listdir):
        mock_listdir.side_effect = [
            {"song1.mp3"},
            {"song1.mp3"},
        ]
        result = app.find_new_mp3("/tmp/dir", {"song1.mp3"})
        self.assertIsNone(result)

    @patch("os.listdir", side_effect=FileNotFoundError)
    def test_find_new_mp3_dir_missing(self, mock_listdir):
        result = app.find_new_mp3("/tmp/dir", set())
        self.assertIsNone(result)


class TestMp3Exists(unittest.TestCase):
    @patch("os.listdir")
    def test_mp3_exists_true(self, mock_listdir):
        mock_listdir.return_value = ["Tum Hi Ho.mp3", "other.mp3"]
        self.assertTrue(app.mp3_exists("/tmp/dir", "Tum Hi Ho"))

    @patch("os.listdir")
    def test_mp3_exists_false(self, mock_listdir):
        mock_listdir.return_value = ["other.mp3"]
        self.assertFalse(app.mp3_exists("/tmp/dir", "Tum Hi Ho"))

    @patch("os.listdir", side_effect=FileNotFoundError)
    def test_mp3_exists_dir_missing(self, mock_listdir):
        self.assertFalse(app.mp3_exists("/tmp/dir", "Tum Hi Ho"))


class TestDownloadSong(unittest.TestCase):
    def setUp(self):
        app.JOBS = {}
        self.job_id = "test_job"
        app.JOBS[self.job_id] = {"logs": [], "done": 0, "failed": 0, "songs": []}
        self.song = {
            "artist": "Arijit Singh",
            "title": "Tum Hi Ho",
            "album": "Aashiqui 2",
            "uri": "",
        }

    @patch("app.mp3_exists", return_value=True)
    def test_download_song_skip_existing(self, mock_exists):
        result = app.download_song(self.job_id, self.song, 1, 1, "/tmp/dir")
        self.assertTrue(result)
        self.assertEqual(app.JOBS[self.job_id]["done"], 1)
        self.assertEqual(app.JOBS[self.job_id]["failed"], 0)
        self.assertEqual(len(app.JOBS[self.job_id]["songs"]), 1)
        self.assertEqual(app.JOBS[self.job_id]["songs"][0]["status"], "ok")

    @patch("app.mp3_exists", return_value=False)
    @patch("app.find_new_mp3", return_value="Tum Hi Ho.mp3")
    @patch("subprocess.run")
    @patch("os.listdir", return_value=set())
    def test_download_song_success(self, mock_listdir, mock_run, mock_find, mock_exists):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = app.download_song(self.job_id, self.song, 1, 1, "/tmp/dir")
        self.assertTrue(result)
        self.assertEqual(app.JOBS[self.job_id]["done"], 1)
        mock_run.assert_called_once()

    @patch("app.mp3_exists", return_value=False)
    @patch("app.find_new_mp3", return_value=None)
    @patch("subprocess.run")
    @patch("os.listdir", return_value=set())
    def test_download_song_failure(self, mock_listdir, mock_run, mock_find, mock_exists):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error msg")
        result = app.download_song(self.job_id, self.song, 1, 1, "/tmp/dir")
        self.assertFalse(result)
        self.assertEqual(app.JOBS[self.job_id]["failed"], 1)


class TestRunDownload(unittest.TestCase):
    def setUp(self):
        app.JOBS = {}

    @patch("app.load_songs", return_value=[
        {"artist": "A", "title": "B", "album": "C", "uri": ""},
    ])
    @patch("app.download_song", return_value=True)
    def test_run_download_completed(self, mock_dl, mock_load):
        job_id = "job1"
        app.run_download(job_id, "/tmp/songs.csv", "/tmp/out")
        self.assertEqual(app.JOBS[job_id]["status"], "completed")
        mock_dl.assert_called_once()

    @patch("app.load_songs", return_value=[])
    def test_run_download_empty(self, mock_load):
        job_id = "job2"
        app.run_download(job_id, "/tmp/songs.csv", "/tmp/out")
        self.assertEqual(app.JOBS[job_id]["total"], 0)
        self.assertEqual(app.JOBS[job_id]["status"], "completed")


class TestFlaskRoutes(unittest.TestCase):
    def setUp(self):
        app.app.testing = True
        self.client = app.app.test_client()
        app.JOBS = {}

    def test_index(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)

    @patch("app.load_songs", return_value=[{"artist": "A", "title": "B", "album": "C", "uri": ""}])
    def test_upload_csv(self, mock_load):
        data = {"file": (tempfile.NamedTemporaryFile(suffix=".csv"), "songs.csv")}
        with patch("builtins.open", mock_open()):
            resp = self.client.post("/upload", data=data, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 200)
        json_data = resp.get_json()
        self.assertIn("file_path", json_data)

    @patch("app.run_download")
    def test_download(self, mock_run_download):
        with patch("os.path.exists", return_value=True):
            resp = self.client.post("/download", json={
                "file_path": "/tmp/songs.csv",
                "output_dir": "/tmp/downloads",
            })
        self.assertEqual(resp.status_code, 200)
        json_data = resp.get_json()
        self.assertIn("job_id", json_data)

    def test_download_invalid_path(self):
        resp = self.client.post("/download", json={"file_path": "/nonexistent.csv"})
        self.assertEqual(resp.status_code, 400)

    def test_status_not_found(self):
        resp = self.client.get("/status/nonexistent")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "not_found")

    @patch("app.JOBS", {
        "job1": {
            "status": "completed",
            "total": 2,
            "done": 1,
            "failed": 1,
            "songs": [
                {"idx": 1, "artist": "A", "title": "B", "album": "C", "uri": "", "status": "ok", "file": "B.mp3"},
                {"idx": 2, "artist": "X", "title": "Y", "album": "Z", "uri": "", "status": "fail", "file": "", "error": "err"},
            ],
            "logs": [],
        }
    })
    def test_status_found(self):
        resp = self.client.get("/status/job1")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["failed"], 1)

    @patch("app.run_download")
    def test_retry(self, mock_run_download):
        app.JOBS["parent"] = {
            "status": "completed",
            "total": 2,
            "done": 1,
            "failed": 1,
            "songs": [
                {"idx": 1, "artist": "A", "title": "B", "album": "C", "uri": "", "status": "ok"},
                {"idx": 2, "artist": "X", "title": "Y", "album": "Z", "uri": "", "status": "fail"},
            ],
            "output_dir": "/tmp/out",
            "client_id": "",
            "client_secret": "",
            "cookies": "",
        }
        resp = self.client.post("/retry", json={"job_id": "parent"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("job_id", data)

    def test_retry_invalid_job(self):
        resp = self.client.post("/retry", json={"job_id": "nonexistent"})
        self.assertEqual(resp.status_code, 400)

    def test_retry_no_failed(self):
        app.JOBS["parent"] = {
            "status": "completed",
            "total": 1,
            "done": 1,
            "failed": 0,
            "songs": [{"status": "ok"}],
            "output_dir": "/tmp/out",
            "client_id": "",
            "client_secret": "",
            "cookies": "",
        }
        resp = self.client.post("/retry", json={"job_id": "parent"})
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
