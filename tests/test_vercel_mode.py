import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app as pclip


class VercelModeTests(unittest.TestCase):
    def setUp(self):
        self.client = pclip.app.test_client()
        self.vercel_mode = pclip.VERCEL_MODE
        pclip.VERCEL_MODE = True

    def tearDown(self):
        pclip.VERCEL_MODE = self.vercel_mode

    @staticmethod
    def _media_info():
        return {
            "title": "Sample video",
            "formats": [
                {"format_id": "small", "height": 360, "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a", "filesize": 100, "tbr": 100},
                {"format_id": "large", "height": 720, "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a", "filesize": 5 * 1024 * 1024, "tbr": 500},
                {"format_id": "video-only", "height": 1080, "ext": "mp4", "vcodec": "avc1", "acodec": "none", "filesize": 100, "tbr": 1000},
            ],
        }

    def test_info_only_offers_small_progressive_mp4_formats(self):
        result = SimpleNamespace(returncode=0, stdout=json.dumps(self._media_info()), stderr="")
        with patch.object(pclip.subprocess, "run", return_value=result):
            response = self.client.post("/api/info", json={"url": "https://example.com/video"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["formats"], [{"id": "small", "label": "360p", "height": 360}])

    def test_small_download_is_returned_as_browser_attachment(self):
        info_result = SimpleNamespace(returncode=0, stdout=json.dumps(self._media_info()), stderr="")

        def fake_run(command, **kwargs):
            if "-j" in command:
                return info_result
            output_template = command[command.index("-o") + 1]
            output_path = output_template.replace("%(ext)s", "mp4")
            with open(output_path, "wb") as media_file:
                media_file.write(b"small video")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(pclip.subprocess, "run", side_effect=fake_run):
            response = self.client.post(
                "/api/download",
                json={"url": "https://example.com/video", "format": "video", "format_id": "small"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"small video")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertIn("Sample video.mp4", response.headers["Content-Disposition"])

    def test_vercel_mode_rejects_audio_without_running_a_download(self):
        with patch.object(pclip.subprocess, "run") as run:
            response = self.client.post(
                "/api/download",
                json={"url": "https://example.com/video", "format": "audio"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("MP3 conversion is unavailable", response.get_json()["error"])
        run.assert_not_called()

    def test_download_larger_than_limit_is_rejected(self):
        info_result = SimpleNamespace(returncode=0, stdout=json.dumps(self._media_info()), stderr="")

        def fake_run(command, **kwargs):
            if "-j" in command:
                return info_result
            output_template = command[command.index("-o") + 1]
            output_path = output_template.replace("%(ext)s", "mp4")
            with open(output_path, "wb") as media_file:
                media_file.write(b"x" * (pclip.MAX_VERCEL_DOWNLOAD_BYTES + 1))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(pclip.subprocess, "run", side_effect=fake_run):
            response = self.client.post(
                "/api/download",
                json={"url": "https://example.com/video", "format": "video", "format_id": "small"},
            )

        self.assertEqual(response.status_code, 413)


if __name__ == "__main__":
    unittest.main()
