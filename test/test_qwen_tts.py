import base64
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

FAY_ROOT = Path(__file__).resolve().parents[1]
if str(FAY_ROOT) not in sys.path:
    sys.path.insert(0, str(FAY_ROOT))


def _pcm_payload(sample_count=240):
    return struct.pack("<" + "h" * sample_count, *([0] * sample_count))


class FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = False
        self.received = iter([
            json.dumps({"type": "session.created"}),
            json.dumps({"type": "response.audio.delta", "delta": base64.b64encode(_pcm_payload()).decode("ascii")}),
            json.dumps({"type": "response.audio.done"}),
            json.dumps({"type": "session.finished"}),
        ])

    def send(self, message):
        self.sent.append(json.loads(message))

    def recv(self):
        return next(self.received)

    def close(self):
        self.closed = True


class QwenTtsTest(unittest.TestCase):
    def test_to_sample_uses_neil_and_returns_16khz_mono_wav(self):
        fake_socket = FakeWebSocket()
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {
                "QWEN_TTS_API_KEY": "test-key",
                "QWEN_TTS_MODEL": "qwen3-tts-flash-realtime",
                "QWEN_TTS_VOICE": "Neil",
                "QWEN_TTS_OUTPUT_DIR": temp_dir,
            },
            clear=False,
        ), patch("websocket.create_connection", return_value=fake_socket) as create_connection:
            from tts.qwen_tts import Speech

            result = Speech().to_sample("当前水位二十八点五米", None)
            self.assertIsNotNone(result)
            with open(result, "rb") as wav_file:
                self.assertEqual(wav_file.read(4), b"RIFF")
                self.assertEqual(wav_file.read(4), struct.pack("<I", os.path.getsize(result) - 8))
                self.assertEqual(wav_file.read(4), b"WAVE")
                self.assertEqual(wav_file.read(4), b"fmt ")
                self.assertEqual(struct.unpack("<I", wav_file.read(4))[0], 16)
                audio_format, channels, sample_rate = struct.unpack("<HHI", wav_file.read(8))
                self.assertEqual((audio_format, channels, sample_rate), (1, 1, 16000))

            self.assertEqual(fake_socket.sent[0]["type"], "session.update")
            self.assertEqual(fake_socket.sent[0]["session"]["voice"], "Neil")
            self.assertEqual(fake_socket.sent[0]["session"]["response_format"], "pcm")
            self.assertEqual(fake_socket.sent[0]["session"]["sample_rate"], 24000)
            self.assertIn("model=qwen3-tts-flash-realtime", create_connection.call_args.args[0])
            self.assertEqual(fake_socket.sent[1], {"type": "input_text_buffer.append", "text": "当前水位二十八点五米"})
            self.assertEqual(fake_socket.sent[2]["type"], "input_text_buffer.commit")
            self.assertEqual(fake_socket.sent[3]["type"], "session.finish")
            self.assertTrue(fake_socket.closed)

    def test_empty_text_returns_none_without_opening_socket(self):
        with patch("websocket.create_connection") as create_connection:
            from tts.qwen_tts import Speech
            self.assertIsNone(Speech().to_sample("  ", None))
        create_connection.assert_not_called()

    def test_connection_failure_returns_none(self):
        with patch("websocket.create_connection", side_effect=OSError("offline")):
            from tts.qwen_tts import Speech
            self.assertIsNone(Speech().to_sample("测试文本", None))


if __name__ == "__main__":
    unittest.main()
