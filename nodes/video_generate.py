"""MagnificVideoGenerate — text-to-video and image-to-video.

Each model is its own async endpoint under /v1/ai/{image,text}-to-video/<model>;
they share the submit->poll task contract. The finished video URL is downloaded
into ComfyUI's output folder and its path is returned (ComfyUI has no single
native video tensor — a file path is the portable hand-off, e.g. into
VideoHelperSuite's Load Video).

The model->endpoint map is the one brittle spot (Magnific occasionally renames
slugs); it lives in VIDEO_MODELS below and an `endpoint_override` widget lets you
paste an exact path without editing code.
"""
from __future__ import annotations

from ._common import (
    CATEGORY,
    build_client,
    comfy_interrupt_checker,
    connection_inputs,
    image_to_payload,
    make_logger,
    polling_inputs,
)
from freepik_api import save_url_to_output

# label -> (kind, endpoint path). kind: "i2v" needs an image, "t2v" does not.
VIDEO_MODELS: dict[str, tuple[str, str]] = {
    # image-to-video
    "kling-v2-6-pro":            ("i2v", "/v1/ai/image-to-video/kling-v2-6-pro"),
    "kling-v2-5-pro":            ("i2v", "/v1/ai/image-to-video/kling-v2-5-pro"),
    "kling-v2-1-pro":            ("i2v", "/v1/ai/image-to-video/kling-v2-1-pro"),
    "kling-o1-pro":              ("i2v", "/v1/ai/image-to-video/kling-o1-pro"),
    "minimax-hailuo-2-3-1080p":  ("i2v", "/v1/ai/image-to-video/minimax-hailuo-2-3-1080p"),
    "seedance-pro-1080p":        ("i2v", "/v1/ai/image-to-video/seedance-pro-1080p"),
    "pixverse-v5":               ("i2v", "/v1/ai/image-to-video/pixverse"),
    "wan-2-5-i2v-1080p":         ("i2v", "/v1/ai/image-to-video/wan-2-5-i2v-1080p"),
    "runway-gen4-turbo":         ("i2v", "/v1/ai/image-to-video/runway-gen4-turbo"),
    # text-to-video
    "wan-2-5-t2v-1080p":         ("t2v", "/v1/ai/text-to-video/wan-2-5-t2v-1080p"),
    "ltx-2-pro":                 ("t2v", "/v1/ai/text-to-video/ltx-2-pro"),
}

DURATIONS = ["5", "10"]
ASPECT_RATIOS = ["widescreen_16_9", "social_story_9_16", "square_1_1"]


class MagnificVideoGenerate:
    """Generate video from text or from an image + prompt, across model families."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                **connection_inputs(),
                "model": (list(VIDEO_MODELS.keys()), {"default": "kling-v2-6-pro"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "duration": (DURATIONS, {"default": "5"}),
                "aspect_ratio": (ASPECT_RATIOS, {"default": "widescreen_16_9"}),
                "cfg_scale": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05}),
                "generate_audio": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                # Required for image-to-video models; ignored for text-to-video.
                "image": ("IMAGE",),
                "image_url": ("STRING", {"default": ""}),
                "negative_prompt": ("STRING", {"default": "", "multiline": True}),
                "endpoint_override": ("STRING", {"default": ""}),
                "extra_params_json": ("STRING", {"default": "", "multiline": True}),
                **polling_inputs(),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("video_path", "video_url")
    FUNCTION = "generate"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def generate(self, provider, api_key, model, prompt, duration, aspect_ratio,
                 cfg_scale, generate_audio, image=None, image_url="", negative_prompt="",
                 endpoint_override="", extra_params_json="",
                 poll_interval=5.0, max_wait_seconds=1800):
        import json

        kind, path = VIDEO_MODELS[model]
        if endpoint_override.strip():
            path = endpoint_override.strip()

        img_payload = image_to_payload(image, image_url)
        if kind == "i2v" and not img_payload:
            raise ValueError(
                f"MagnificVideoGenerate: model '{model}' is image-to-video — "
                "connect an 'image' (or set 'image_url')."
            )
        if kind == "t2v" and img_payload:
            print(f"[ComfyUI-Magnific] '{model}' is text-to-video; ignoring the image input.")

        body: dict = {
            "prompt": prompt,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "cfg_scale": cfg_scale,
            "generate_audio": generate_audio,
        }
        if kind == "i2v":
            body["image"] = img_payload
        if negative_prompt.strip():
            body["negative_prompt"] = negative_prompt

        if extra_params_json.strip():
            try:
                extra = json.loads(extra_params_json)
            except json.JSONDecodeError as exc:
                raise ValueError(f"MagnificVideoGenerate: extra_params_json is not valid JSON: {exc}")
            if not isinstance(extra, dict):
                raise ValueError("MagnificVideoGenerate: extra_params_json must be a JSON object.")
            body.update(extra)

        client = build_client(provider, api_key, poll_interval, max_wait_seconds)
        urls = client.run(
            path, body,
            on_status=make_logger(f"Video/{model}"),
            check_interrupt=comfy_interrupt_checker(),
        )
        video_path = save_url_to_output(client, urls[0], prefix=f"magnific_{model}", ext_hint=".mp4")
        return (video_path, "\n".join(urls))


NODE_CLASS_MAPPINGS = {"MagnificVideoGenerate": MagnificVideoGenerate}
NODE_DISPLAY_NAME_MAPPINGS = {"MagnificVideoGenerate": "Magnific Video Generate"}
