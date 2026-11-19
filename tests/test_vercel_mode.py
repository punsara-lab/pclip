import io
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
                {"format_id": "progressive", "height": 360, "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a", "filesize": 5 * 1024 * 1024, "tbr": 100},
                {"format_id": "video-only", "height": 1080, "ext": "mp4", "vcodec": "avc1", "acodec": "none", "filesize": 100, "tbr": 1000},
            ],
        }

    def test_info_returns_progressive_mp4_formats_without_a_size_cap(self):
        result = SimpleNamespace(returncode=0, stdout=json.dumps(self._media_info()), stderr="")
        with patch.object(pclip.subprocess, "run", return_value=result):
            response = self.client.post("/api/info", json={"url": "https://example.com/video"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["formats"],
            [{"id": "progressive", "label": "360p", "height": 360}],
        )

    def test_vercel_landing_page_explains_browser_storage_mode(self):
        response = self.client.get("/")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("streams progressive MP4 files directly to your browser", html)
        self.assertIn('data-format="audio"', html)
        self.assertIn("disabled", html)

    def test_browser_form_download_streams_mp4_attachment(self):
        info_result = SimpleNamespace(returncode=0, stdout=json.dumps(self._media_info()), stderr="")
        process = SimpleNamespace(
            stdout=io.BytesIO(b"streamed video"),
            poll=lambda: 0,
            wait=lambda **kwargs: 0,
        )
        with patch.object(pclip.subprocess, "run", return_value=info_result), patch.object(
            pclip.subprocess, "Popen", return_value=process
        ) as popen:
            response = self.client.post(
                "/api/download",
                data={"url": "https://example.com/video", "format": "video", "format_id": "progressive"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"streamed video")
        self.assertEqual(response.mimetype, "video/mp4")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertIn("Sample%20video.mp4", response.headers["Content-Disposition"])
        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("-o") + 1], "-")

    def test_audio_is_rejected_without_starting_a_stream(self):
        with patch.object(pclip.subprocess, "run") as run, patch.object(pclip.subprocess, "Popen") as popen:
            response = self.client.post(
                "/api/download",
                json={"url": "https://example.com/video", "format": "audio"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("MP3 conversion is unavailable", response.get_json()["error"])
        run.assert_not_called()
        popen.assert_not_called()

    def test_video_only_format_is_rejected(self):
        info_result = SimpleNamespace(returncode=0, stdout=json.dumps(self._media_info()), stderr="")
        with patch.object(pclip.subprocess, "run", return_value=info_result), patch.object(
            pclip.subprocess, "Popen"
        ) as popen:
            response = self.client.post(
                "/api/download",
                json={"url": "https://example.com/video", "format": "video", "format_id": "video-only"},
            )

        self.assertEqual(response.status_code, 400)
        popen.assert_not_called()

    def test_local_downloads_keep_the_background_job_flow(self):
        with patch.object(pclip, "VERCEL_MODE", False), patch.object(pclip.threading, "Thread") as thread:
            response = self.client.post(
                "/api/download",
                json={"url": "https://example.com/video", "format": "video"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("job_id", response.get_json())
        thread.return_value.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
