import json
import tempfile
import unittest
from pathlib import Path

from tts import cosyvoice_tts
from utils import config_util


class CosyVoiceVoiceConfigTest(unittest.TestCase):
    def test_backend_voice_selection_updates_runtime_voice(self):
        existing = {
            "attribute": {"voice": "cosy-news-female"},
            "interact": {"voice": "\u4e91\u590f"},
        }
        submitted = {"attribute": {"voice": "cosy-news-male"}}

        config_util.sync_selected_voice(existing, submitted)

        self.assertEqual("cosy-news-male", existing["interact"]["voice"])

    def test_missing_voice_does_not_override_runtime_voice(self):
        existing = {
            "attribute": {"voice": "cosy-news-female"},
            "interact": {"voice": "cosy-news-male"},
        }

        config_util.sync_selected_voice(existing, {"attribute": {}})

        self.assertEqual("cosy-news-male", existing["interact"]["voice"])

    def test_selected_male_voice_wins_over_earlier_default_female_voice(self):
        original_map = config_util.cosyvoice_voice_map
        original_default = config_util.cosyvoice_default_voice
        original_config = config_util.config
        try:
            with tempfile.TemporaryDirectory() as directory:
                voice_map = Path(directory) / "voices.json"
                voice_map.write_text(
                    json.dumps({"voices": [
                        {
                            "id": "cosy-news-female",
                            "name": "female",
                            "prompt_audio": "female.wav",
                            "prompt_text": "female prompt",
                        },
                        {
                            "id": "cosy-news-male",
                            "name": "male",
                            "prompt_audio": "male.wav",
                            "prompt_text": "male prompt",
                        },
                    ]}),
                    encoding="utf-8",
                )
                config_util.cosyvoice_voice_map = str(voice_map)
                config_util.cosyvoice_default_voice = "cosy-news-female"
                config_util.config = {"interact": {"voice": "cosy-news-male"}}

                prompt_audio, prompt_text = cosyvoice_tts._get_prompt_config()

                self.assertEqual("male.wav", prompt_audio)
                self.assertEqual("male prompt", prompt_text)
        finally:
            config_util.cosyvoice_voice_map = original_map
            config_util.cosyvoice_default_voice = original_default
            config_util.config = original_config


if __name__ == "__main__":
    unittest.main()