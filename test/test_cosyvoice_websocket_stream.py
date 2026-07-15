import base64
import json
import threading
import unittest
from unittest.mock import patch

from tts import cosyvoice_websocket_stream


class _FakeConnection:
    def __init__(self):
        self.sent = []
        self.responses = []

    def settimeout(self, value):
        return None

    def send(self, raw):
        message = json.loads(raw)
        self.sent.append(message)
        if message["type"] == "start":
            self.responses.append({"type": "started"})
        elif message["type"] == "append":
            self.responses.append({
                "type": "audio",
                "seq": 0,
                "pcm_base64": base64.b64encode(b"\x00\x00" * 160).decode("ascii"),
                "sample_rate": 22050,
                "channels": 1,
                "sample_width": 2,
            })
        elif message["type"] == "finish":
            self.responses.append({"type": "end", "seq": 1})

    def recv(self):
        if self.responses:
            return json.dumps(self.responses.pop(0))
        raise cosyvoice_websocket_stream.websocket.WebSocketTimeoutException()

    def close(self):
        return None


class CosyVoiceWebSocketStreamTest(unittest.TestCase):
    def test_sends_start_append_finish_and_emits_pcm_audio(self):
        audio = []
        ended = threading.Event()
        connection = _FakeConnection()
        manager = cosyvoice_websocket_stream.CosyVoiceWebSocketStreamManager()

        with patch.object(cosyvoice_websocket_stream, "build_stream_start_payload", return_value={
            "type": "start", "mode": "zero_shot", "speed": 1.0, "prompt_text": "参考台词", "prompt_wav_base64": "AA==",
        }), patch.object(cosyvoice_websocket_stream.websocket, "create_connection", return_value=connection):
            manager.submit(
                ("fay", "conv"), "第一句。", True, True,
                lambda pcm, sample_rate, text, first, end, seq: audio.append(
                    (pcm, sample_rate, text, first, end, seq)
                ),
                lambda first, seq, sample_rate: ended.set(),
                lambda key, message: self.fail(message),
            )
            self.assertTrue(ended.wait(1))

        self.assertEqual(["start", "append", "finish"], [item["type"] for item in connection.sent])
        self.assertEqual("第一句。", connection.sent[1]["text"])
        self.assertEqual(1, len(audio))
        self.assertEqual(b"\x00\x00" * 160, audio[0][0])
        self.assertEqual(22050, audio[0][1])
        self.assertEqual("第一句。", audio[0][2])
        self.assertTrue(audio[0][3])
        self.assertEqual(0, audio[0][5])

    def test_buffers_partial_text_until_sentence_completion(self):
        connection = _FakeConnection()
        ended = threading.Event()
        manager = cosyvoice_websocket_stream.CosyVoiceWebSocketStreamManager()

        with patch.object(cosyvoice_websocket_stream, "build_stream_start_payload", return_value={
            "type": "start", "mode": "zero_shot", "speed": 1.0, "prompt_text": "参考台词", "prompt_wav_base64": "AA==",
        }), patch.object(cosyvoice_websocket_stream.websocket, "create_connection", return_value=connection):
            manager.submit(("fay", "conv-buffer"), "第一", True, False, lambda *args: None, lambda *args: ended.set(), lambda *args: self.fail())
            self.assertTrue(_wait_until(lambda: len(connection.sent) >= 1))
            self.assertEqual(["start"], [item["type"] for item in connection.sent])

            manager.submit(("fay", "conv-buffer"), "句。", False, True, lambda *args: None, lambda *args: ended.set(), lambda *args: self.fail())
            self.assertTrue(ended.wait(1))

        self.assertEqual(["start", "append", "finish"], [item["type"] for item in connection.sent])


def _wait_until(predicate, timeout=1):
    done = threading.Event()
    timer = threading.Timer(timeout, done.set)
    timer.start()
    try:
        while not predicate() and not done.is_set():
            done.wait(0.01)
        return predicate()
    finally:
        timer.cancel()


if __name__ == "__main__":
    unittest.main()