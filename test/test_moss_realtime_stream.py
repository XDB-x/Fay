import threading
import time
import unittest
from unittest.mock import patch

import tts.moss_realtime_stream as realtime


class _Response:
    def __init__(self, event=None):
        self.event = event

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=4096):
        del chunk_size
        yield b"\x00" * 10000
        if self.event:
            self.event.wait(2)
        yield b"\x00" * 10000


class _Session:
    instances = []
    final_event = threading.Event()

    def __init__(self):
        self.posts = []
        self.audio = _Response(self.final_event)
        _Session.instances.append(self)

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json, timeout))
        if json and json.get("is_final"):
            _Session.final_event.set()
        return _Response()

    def get(self, url, stream=False, timeout=None):
        self.get_args = (url, stream, timeout)
        return self.audio

    def close(self):
        return None


class RealtimeStreamTest(unittest.TestCase):
    def setUp(self):
        _Session.instances = []
        _Session.final_event = threading.Event()
        self.audio_events = []
        self.errors = []

    def test_one_session_for_multiple_text_chunks(self):
        with patch.object(realtime.requests, "Session", _Session):
            manager = realtime.RealtimeStreamManager()
            manager.submit(
                ("user", "conv"), "第一句话。", True, False,
                lambda *args: self.audio_events.append(args),
                lambda *args: self.errors.append(args),
            )
            manager.submit(
                ("user", "conv"), "第二句话。", False, True,
                lambda *args: self.audio_events.append(args),
                lambda *args: self.errors.append(args),
            )
            deadline = time.time() + 3
            while time.time() < deadline and not self.audio_events:
                time.sleep(0.05)

        self.assertFalse(self.errors)
        self.assertEqual(len(_Session.instances), 1)
        posts = _Session.instances[0].posts
        push_posts = [item for item in posts if item[1] and "is_final" in item[1]]
        self.assertEqual([item[1]["text"] for item in push_posts], ["第一句话。", "第二句话。"])
        self.assertTrue(any(event[2] for event in self.audio_events))
        self.assertTrue(any(event[3] for event in self.audio_events))



    def test_keeps_short_contiguous_pcm_in_one_wav_message(self):
        with patch.object(realtime.requests, "Session", _Session):
            manager = realtime.RealtimeStreamManager()
            manager.submit(
                ("user", "conv"), "single response", True, True,
                lambda *args: self.audio_events.append(args),
                lambda *args: self.errors.append(args),
            )
            deadline = time.time() + 3
            while time.time() < deadline and not self.audio_events:
                time.sleep(0.05)

        self.assertFalse(self.errors)
        self.assertEqual(1, len(self.audio_events))
        self.assertTrue(self.audio_events[0][3])
        self.assertIsInstance(self.audio_events[0][0], bytes)
if __name__ == "__main__":
    unittest.main()
