import unittest
from pathlib import Path


FLASK_SERVER_PATH = Path(__file__).resolve().parents[1] / "gui" / "flask_server.py"


class CosyVoicePcmRouteTest(unittest.TestCase):
    def test_cosyvoice_stream_route_uses_pcm_messages_instead_of_wav_messages(self):
        source = FLASK_SERVER_PATH.read_text(encoding="utf-8")
        route_start = source.index("def transparent_stream():")
        start = source.index("if config_util.tts_module == 'cosyvoice':", route_start)
        end = source.index("if config_util.tts_module == 'moss':", start)
        cosyvoice_block = source[start:end]

        self.assertIn("build_stream_pcm_message", cosyvoice_block)
        self.assertIn("def _emit_cosyvoice_pcm", cosyvoice_block)


if __name__ == "__main__":
    unittest.main()