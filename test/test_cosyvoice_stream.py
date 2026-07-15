import threading
import unittest
from unittest.mock import patch

from tts import cosyvoice_stream


class _FakeSpeech:
    def stream_to_samples(self, text, style):
        del style
        yield text + ".wav"

    def close(self):
        return None


class CosyVoiceStreamManagerTest(unittest.TestCase):
    def test_emits_first_sentence_before_stream_end_and_closes_with_end_marker(self):
        audio = []
        ended = threading.Event()
        manager = cosyvoice_stream.CosyVoiceStreamManager()

        def emit_audio(path, text, first, end, seq):
            audio.append((path, text, first, end, seq))

        def emit_end(first, seq):
            audio.append((None, "", first, True, seq))
            ended.set()

        with patch.object(cosyvoice_stream, "Speech", _FakeSpeech):
            manager.submit(("fay", "conv"), "第一句。", True, False, emit_audio, emit_end, lambda key, message: None)
            self.assertTrue(_wait_until(lambda: len(audio) == 1))
            self.assertEqual(("第一句。.wav", "第一句。", True, False, 0), audio[0])

            manager.submit(("fay", "conv"), "", False, True, emit_audio, emit_end, lambda key, message: None)
            self.assertTrue(ended.wait(1))

        self.assertEqual((None, "", False, True, 1), audio[1])

    def test_buffers_partial_text_until_a_sentence_is_complete(self):
        audio = []
        ended = threading.Event()
        manager = cosyvoice_stream.CosyVoiceStreamManager()

        def emit_audio(path, text, first, end, seq):
            audio.append((path, text, first, end, seq))

        def emit_end(first, seq):
            audio.append((None, "", first, True, seq))
            ended.set()

        with patch.object(cosyvoice_stream, "Speech", _FakeSpeech):
            manager.submit(("fay", "conv-2"), "第一", True, False, emit_audio, emit_end, lambda key, message: None)
            self.assertFalse(_wait_until(lambda: bool(audio), timeout=0.05))

            manager.submit(("fay", "conv-2"), "句。", False, True, emit_audio, emit_end, lambda key, message: None)
            self.assertTrue(ended.wait(1))

        self.assertEqual(("第一句。.wav", "第一句。", True, False, 0), audio[0])
        self.assertEqual((None, "", False, True, 1), audio[1])

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