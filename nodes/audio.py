"""Audio nodes: music / sound-effects generation and audio isolation.

All async (submit -> poll -> download). Results are saved into ComfyUI's output
folder and the file path is returned (ComfyUI has no single portable audio tensor
across versions).

  MagnificAudioGenerate  music   -> POST /v1/ai/music-generation  {prompt, music_length_seconds}
                         sfx     -> POST /v1/ai/sound-effects      {prompt, duration}  (best-effort)
  MagnificAudioIsolation         -> POST /v1/ai/audio-isolation    {audio, description}
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

MUSIC_PATH = "/v1/ai/music-generation"
SFX_PATH = "/v1/ai/sound-effects"
ISOLATION_PATH = "/v1/ai/audio-isolation"


class MagnificAudioGenerate:
    """Generate music or sound effects from a text prompt."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                **connection_inputs(),
                "task": (["music", "sound-effects"], {"default": "music"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "duration_seconds": ("INT", {"default": 30, "min": 1, "max": 240,
                                     "tooltip": "music: 10-240s (music_length_seconds); "
                                                "sound-effects: short clips."}),
            },
            "optional": {
                "extra_params_json": ("STRING", {"default": "", "multiline": True}),
                **polling_inputs(),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("audio_path", "audio_url")
    FUNCTION = "generate"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def generate(self, provider, api_key, task, prompt, duration_seconds,
                 extra_params_json="", poll_interval=5.0, max_wait_seconds=900):
        import json

        if not prompt.strip():
            raise ValueError("MagnificAudioGenerate: 'prompt' is required.")

        if task == "music":
            path = MUSIC_PATH
            body = {"prompt": prompt, "music_length_seconds": duration_seconds}
        else:  # sound-effects (best-effort body)
            path = SFX_PATH
            body = {"prompt": prompt, "duration": duration_seconds}
            print("[ComfyUI-Magnific] sound-effects params are best-effort; "
                  "adjust via extra_params_json if the API rejects a field.")

        if extra_params_json.strip():
            try:
                extra = json.loads(extra_params_json)
            except json.JSONDecodeError as exc:
                raise ValueError(f"MagnificAudioGenerate: extra_params_json is not valid JSON: {exc}")
            if not isinstance(extra, dict):
                raise ValueError("MagnificAudioGenerate: extra_params_json must be a JSON object.")
            body.update(extra)

        client = build_client(provider, api_key, poll_interval, max_wait_seconds)
        urls = client.run(
            path, body,
            on_status=make_logger(f"Audio/{task}"),
            check_interrupt=comfy_interrupt_checker(),
        )
        audio_path = save_url_to_output(client, urls[0], prefix=f"magnific_{task}", ext_hint=".mp3")
        return (audio_path, "\n".join(urls))


class MagnificAudioIsolation:
    """Isolate a described sound from an input audio/video URL."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                **connection_inputs(),
                "audio_url": ("STRING", {"default": "",
                              "tooltip": "Public https URL of the audio (or video) to process."}),
                "description": ("STRING", {"default": "", "multiline": True,
                                "tooltip": "Text description of the sound to isolate."}),
            },
            "optional": {
                "extra_params_json": ("STRING", {"default": "", "multiline": True}),
                **polling_inputs(),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("audio_path", "audio_url")
    FUNCTION = "isolate"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def isolate(self, provider, api_key, audio_url, description,
                extra_params_json="", poll_interval=5.0, max_wait_seconds=900):
        import json

        if not audio_url.strip():
            raise ValueError("MagnificAudioIsolation: 'audio_url' is required (a public https URL).")
        if not description.strip():
            raise ValueError("MagnificAudioIsolation: 'description' is required.")

        body = {"audio": audio_url.strip(), "description": description}
        if extra_params_json.strip():
            try:
                extra = json.loads(extra_params_json)
            except json.JSONDecodeError as exc:
                raise ValueError(f"MagnificAudioIsolation: extra_params_json is not valid JSON: {exc}")
            if not isinstance(extra, dict):
                raise ValueError("MagnificAudioIsolation: extra_params_json must be a JSON object.")
            body.update(extra)

        client = build_client(provider, api_key, poll_interval, max_wait_seconds)
        urls = client.run(
            ISOLATION_PATH, body,
            on_status=make_logger("Audio/isolation"),
            check_interrupt=comfy_interrupt_checker(),
        )
        audio_path = save_url_to_output(client, urls[0], prefix="magnific_isolation", ext_hint=".wav")
        return (audio_path, "\n".join(urls))


NODE_CLASS_MAPPINGS = {
    "MagnificAudioGenerate": MagnificAudioGenerate,
    "MagnificAudioIsolation": MagnificAudioIsolation,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "MagnificAudioGenerate": "Magnific Audio Generate (Music/SFX)",
    "MagnificAudioIsolation": "Magnific Audio Isolation",
}
