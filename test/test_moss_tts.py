import base64
import io
import os
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

FAY_ROOT = Path(__file__).resolve().parents[1]
if str(FAY_ROOT) not in sys.path:
    sys.path.insert(0, str(FAY_ROOT))


def wav_bytes(sample_rate=24000, channels=2, frames=480):
    raw = struct.pack("<" + "h" * (frames * channels), *([0] * frames * channels))
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(raw)
    return output.getvalue()


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP {}".format(self.status_code))

    def json(self):
        return self.payload


class FakeAudioSegment:
    def set_channels(self, channels):
        self.channels = channels
        return self

    def set_frame_rate(self, sample_rate):
        self.sample_rate = sample_rate
        return self

    def export(self, path, format):
        del format
        Path(path).write_bytes(wav_bytes(self.sample_rate, self.channels))


class MossTtsTest(unittest.TestCase):
    def setUp(self):
        from utils import config_util as cfg
        self.cfg = cfg
        self.tmp = tempfile.TemporaryDirectory()
        self.prompt = Path(self.tmp.name) / "prompt.wav"
        self.prompt.write_bytes(wav_bytes())
        self.old = {name: getattr(cfg, name, None) for name in (
            "moss_tts_base_url", "moss_tts_prompt_audio", "moss_tts_timeout_seconds", "moss_tts_cpu_threads")}
        cfg.moss_tts_base_url = "http://127.0.0.1:18083"
        cfg.moss_tts_prompt_audio = str(self.prompt)
        cfg.moss_tts_timeout_seconds = 120
        cfg.moss_tts_cpu_threads = 4

    def tearDown(self):
        for name, value in self.old.items():
            setattr(self.cfg, name, value)
        self.tmp.cleanup()

    def test_to_sample_posts_prompt_and_returns_16khz_mono_wav(self):
        payload = {"audio_base64": base64.b64encode(wav_bytes()).decode("ascii")}
        with tempfile.TemporaryDirectory() as sample_dir, patch("requests.Session.post", return_value=FakeResponse(payload)) as post:
            from tts import moss_tts
            def resolve(path):
                if path.startswith("./samples"):
                    return str(Path(sample_dir) / Path(path).name)
                return str(self.prompt)
            with patch.object(moss_tts.os.path, "abspath", side_effect=resolve), patch.object(
                moss_tts.AudioSegment, "from_file", return_value=FakeAudioSegment()):
                result = moss_tts.Speech().to_sample("当前水位二十八点五米", None)
            self.assertTrue(result.endswith(".wav"))
            with wave.open(result, "rb") as output:
                self.assertEqual((output.getnchannels(), output.getframerate()), (1, 16000))
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs["data"]["text"], "当前水位二十八点五米")
        self.assertIn("prompt_audio", post.call_args.kwargs["files"])

    def test_empty_text_returns_none_without_http_call(self):
        with patch("requests.Session.post") as post:
            from tts.moss_tts import Speech
            self.assertIsNone(Speech().to_sample("  ", None))
        post.assert_not_called()

    def test_http_failure_returns_none(self):
        with patch("requests.Session.post", return_value=FakeResponse({}, 500)):
            from tts.moss_tts import Speech
            self.assertIsNone(Speech().to_sample("测试文本", None))

    def test_invalid_base64_returns_none(self):
        with patch("requests.Session.post", return_value=FakeResponse({"audio_base64": "%%%"})):
            from tts.moss_tts import Speech
            self.assertIsNone(Speech().to_sample("测试文本", None))

    def test_missing_prompt_returns_none_without_http_call(self):
        self.cfg.moss_tts_prompt_audio = str(Path(self.tmp.name) / "missing.wav")
        with patch("requests.Session.post") as post:
            from tts.moss_tts import Speech
            self.assertIsNone(Speech().to_sample("测试文本", None))
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
