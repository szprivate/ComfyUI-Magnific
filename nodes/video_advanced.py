"""MagnificVideoAdvanced — the newer /v1/ai/video/ (+ /v1/ai/reference-to-video/)
model group: Kling 3 / Kling 3 Omni, OmniHuman 1.5, Runway Act-Two, VFX.

These differ from the /v1/ai/image-to-video/ models (MagnificVideoGenerate): media
inputs are **URLs** (`start_image_url`, `end_image_url`, `image_url`, `audio_url`,
`reference_video_url`), aspect ratio is `"16:9"` style, duration is 3-15s. Each
model declares which body fields it fills from which widget; params are filtered
per model. A connected ComfyUI IMAGE is base64-encoded into the primary image
field as a fallback, but these endpoints prefer public URLs — set the URL widget
if base64 is rejected.

Confirmed against the docs: kling-v3-pro, omni-human-1-5. Best-effort (path
confirmed, params partial): kling-v3-omni-pro/std, runway-act-two, vfx.
"""
from __future__ import annotations

from ._common import (
    CATEGORY,
    build_client,
    comfy_interrupt_checker,
    connection_inputs,
    make_logger,
    polling_inputs,
    image_to_payload,
)
from freepik_api import save_url_to_output

ASPECT_RATIOS = ["16:9", "9:16", "1:1"]
RESOLUTIONS = ["1080p", "720p"]

# model -> spec.
#   path          : API path
#   media         : list of (body_field, widget_key) URL/media inputs to fill
#   image_fill    : widget_key that a connected IMAGE tensor base64-fills if empty
#   required_media: widget_keys that must be provided
#   params        : optional param widget keys filtered into the body
ADV_MODELS: dict[str, dict] = {
    "kling-v3-pro": {
        "path": "/v1/ai/video/kling-v3-pro",
        "media": [("start_image_url", "start_image_url"), ("end_image_url", "end_image_url")],
        "image_fill": "start_image_url",
        "params": ("prompt", "duration", "aspect_ratio", "negative_prompt",
                   "cfg_scale", "generate_audio"),
        "confirmed": True,
    },
    "kling-v3-omni-pro": {
        "path": "/v1/ai/video/kling-v3-omni-pro",
        "media": [("start_image_url", "start_image_url"), ("end_image_url", "end_image_url")],
        "image_fill": "start_image_url",
        "params": ("prompt", "duration", "aspect_ratio", "negative_prompt",
                   "cfg_scale", "generate_audio"),
        "confirmed": False,
    },
    "kling-v3-omni-std": {
        "path": "/v1/ai/reference-to-video/kling-v3-omni-std",
        "media": [("reference_video_url", "reference_video_url"),
                  ("start_image_url", "start_image_url")],
        "image_fill": "start_image_url",
        "params": ("prompt", "duration", "aspect_ratio"),
        "confirmed": False,
    },
    "omni-human-1-5": {
        "path": "/v1/ai/video/omni-human-1-5",
        "media": [("image_url", "image_url"), ("audio_url", "audio_url")],
        "image_fill": "image_url",
        "required_media": ("image_url", "audio_url"),
        "params": ("prompt", "resolution", "turbo_mode"),
        "confirmed": True,
    },
    "runway-act-two": {
        "path": "/v1/ai/video/runway-act-two",
        "media": [("reference_video_url", "reference_video_url"), ("image_url", "image_url")],
        "image_fill": "image_url",
        "params": ("prompt",),
        "confirmed": False,
    },
    "vfx": {
        "path": "/v1/ai/video/vfx",
        "media": [("image_url", "image_url")],
        "image_fill": "image_url",
        "params": ("prompt",),
        "confirmed": False,
    },
}


class MagnificVideoAdvanced:
    """Kling 3 / Omni, OmniHuman, Act-Two, VFX (the /v1/ai/video/ model group)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                **connection_inputs(),
                "model": (list(ADV_MODELS.keys()), {"default": "kling-v3-pro"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
            },
            "optional": {
                "image": ("IMAGE",),
                "start_image_url": ("STRING", {"default": ""}),
                "end_image_url": ("STRING", {"default": ""}),
                "image_url": ("STRING", {"default": ""}),
                "audio_url": ("STRING", {"default": "", "tooltip": "OmniHuman: driving audio URL."}),
                "reference_video_url": ("STRING", {"default": "",
                                        "tooltip": "Act-Two / Omni-std: reference/performance video URL."}),
                "duration": ("STRING", {"default": "5", "tooltip": "seconds (3-15 for Kling 3)."}),
                "aspect_ratio": (ASPECT_RATIOS, {"default": "16:9"}),
                "negative_prompt": ("STRING", {"default": "", "multiline": True}),
                "cfg_scale": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05}),
                "generate_audio": ("BOOLEAN", {"default": True}),
                "resolution": (RESOLUTIONS, {"default": "1080p"}),
                "turbo_mode": ("BOOLEAN", {"default": False}),
                "endpoint_override": ("STRING", {"default": ""}),
                "extra_params_json": ("STRING", {"default": "", "multiline": True}),
                **polling_inputs(),
            },
        }

    RETURN_TYPES = ("VIDEO", "STRING", "STRING")
    RETURN_NAMES = ("video", "video_path", "video_url")
    FUNCTION = "generate"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def generate(self, provider, api_key, model, prompt, image=None,
                 start_image_url="", end_image_url="", image_url="", audio_url="",
                 reference_video_url="", duration="5", aspect_ratio="16:9",
                 negative_prompt="", cfg_scale=0.5, generate_audio=True,
                 resolution="1080p", turbo_mode=False, endpoint_override="",
                 extra_params_json="", poll_interval=5.0, max_wait_seconds=1800):
        import json

        spec = ADV_MODELS[model]
        path = endpoint_override.strip() or spec["path"]

        media_vals = {
            "start_image_url": start_image_url.strip(),
            "end_image_url": end_image_url.strip(),
            "image_url": image_url.strip(),
            "audio_url": audio_url.strip(),
            "reference_video_url": reference_video_url.strip(),
        }
        # A connected IMAGE base64-fills the model's primary image slot if its URL is blank.
        fill = spec.get("image_fill")
        if image is not None and fill and not media_vals.get(fill):
            media_vals[fill] = image_to_payload(image, "")

        for key in spec.get("required_media", ()):
            if not media_vals.get(key):
                raise ValueError(
                    f"MagnificVideoAdvanced: '{model}' requires '{key}' "
                    "(a public https URL)."
                )

        body: dict = {}
        for body_field, widget_key in spec["media"]:
            val = media_vals.get(widget_key)
            if val:
                body[body_field] = val

        candidates = {
            "prompt": prompt,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "negative_prompt": negative_prompt,
            "cfg_scale": cfg_scale,
            "generate_audio": generate_audio,
            "resolution": resolution,
            "turbo_mode": turbo_mode,
        }
        for key in spec["params"]:
            val = candidates.get(key)
            if val is None:
                continue
            if isinstance(val, str) and not val.strip():
                continue
            body[key] = val

        if extra_params_json.strip():
            try:
                extra = json.loads(extra_params_json)
            except json.JSONDecodeError as exc:
                raise ValueError(f"MagnificVideoAdvanced: extra_params_json is not valid JSON: {exc}")
            if not isinstance(extra, dict):
                raise ValueError("MagnificVideoAdvanced: extra_params_json must be a JSON object.")
            body.update(extra)

        if not spec.get("confirmed"):
            print(f"[ComfyUI-Magnific] '{model}' params are best-effort (path confirmed); "
                  "adjust via extra_params_json / endpoint_override if the API rejects a field.")

        client = build_client(provider, api_key, poll_interval, max_wait_seconds)
        urls = client.run(
            path, body,
            on_status=make_logger(f"VideoAdv/{model}"),
            check_interrupt=comfy_interrupt_checker(),
        )
        video_path = save_url_to_output(client, urls[0], prefix=f"magnific_{model}", ext_hint=".mp4")
        from comfy_api.input_impl import VideoFromFile  # lazy: only when a video is produced
        from freepik_api import output_media_preview
        return {"ui": output_media_preview(video_path),
                "result": (VideoFromFile(video_path), video_path, "\n".join(urls))}


NODE_CLASS_MAPPINGS = {"MagnificVideoAdvanced": MagnificVideoAdvanced}
NODE_DISPLAY_NAME_MAPPINGS = {"MagnificVideoAdvanced": "Magnific Video Advanced (Kling 3 / Omni / OmniHuman)"}
