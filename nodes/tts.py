"""MagnificTTS — text-to-speech via the ElevenLabs-powered Voiceover endpoint.

POST /v1/ai/voiceover  (async, poll GET /v1/ai/voiceover/{task_id}).
The finished audio is downloaded into ComfyUI's output folder; its path is
returned (ComfyUI has no single portable audio tensor across versions).
"""
from __future__ import annotations

from ._common import (
    CATEGORY,
    build_client,
    comfy_interrupt_checker,
    connection_inputs,
    make_logger,
    polling_inputs,
)
from freepik_api import save_url_to_output

VOICEOVER_PATH = "/v1/ai/voiceover"
TTS_MODELS = ["eleven_turbo_v2_5", "eleven_multilingual_v2", "eleven_flash_v2_5"]


class MagnificTTS:
    """Synthesize speech from text with a chosen ElevenLabs voice."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                **connection_inputs(),
                "text": ("STRING", {"default": "", "multiline": True}),
                "voice_id": ("STRING", {
                    "default": "",
                    "tooltip": "ElevenLabs voice id (from your Magnific/Freepik voice library).",
                }),
                "model": (TTS_MODELS, {"default": "eleven_turbo_v2_5"}),
                "stability": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05}),
                "similarity_boost": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05}),
                "speed": ("FLOAT", {"default": 1.0, "min": 0.7, "max": 1.2, "step": 0.05}),
                "use_speaker_boost": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "extra_params_json": ("STRING", {"default": "", "multiline": True}),
                **polling_inputs(),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("audio_path", "audio_url")
    FUNCTION = "synthesize"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def synthesize(self, provider, api_key, text, voice_id, model, stability,
                   similarity_boost, speed, use_speaker_boost, extra_params_json="",
                   poll_interval=5.0, max_wait_seconds=900):
        import json

        if not text.strip():
            raise ValueError("MagnificTTS: 'text' is required.")
        if not voice_id.strip():
            raise ValueError("MagnificTTS: 'voice_id' is required (an ElevenLabs voice id).")

        body: dict = {
            "text": text,
            "voice_id": voice_id.strip(),
            "model": model,
            "stability": stability,
            "similarity_boost": similarity_boost,
            "speed": speed,
            "use_speaker_boost": use_speaker_boost,
        }
        if extra_params_json.strip():
            try:
                extra = json.loads(extra_params_json)
            except json.JSONDecodeError as exc:
                raise ValueError(f"MagnificTTS: extra_params_json is not valid JSON: {exc}")
            if not isinstance(extra, dict):
                raise ValueError("MagnificTTS: extra_params_json must be a JSON object.")
            body.update(extra)

        client = build_client(provider, api_key, poll_interval, max_wait_seconds)
        urls = client.run(
            VOICEOVER_PATH, body,
            on_status=make_logger("Voiceover"),
            check_interrupt=comfy_interrupt_checker(),
        )
        audio_path = save_url_to_output(client, urls[0], prefix="magnific_tts", ext_hint=".mp3")
        return (audio_path, "\n".join(urls))


NODE_CLASS_MAPPINGS = {"MagnificTTS": MagnificTTS}
NODE_DISPLAY_NAME_MAPPINGS = {"MagnificTTS": "Magnific Text-to-Speech"}
