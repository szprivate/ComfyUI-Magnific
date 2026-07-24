"""MagnificVideoGenerate — text-to-video and image-to-video.

Each model is its own async endpoint under /v1/ai/{image,text}-to-video/<model>;
they share the submit->poll task contract. The finished video URL is downloaded
into ComfyUI's output folder and its path is returned (ComfyUI has no single
native video tensor — a file path is the portable hand-off, e.g. into
VideoHelperSuite's Load Video).

Video models do NOT share one request schema, so the body is assembled per model
*family* and filtered to that family's known parameters — a Kling-only field like
``cfg_scale`` is never sent to Seedance (which would 422 on a strict validator),
and Seedance's ``camera_fixed`` / ``frames_per_second`` / ``seed`` are only sent
to Seedance. Confirmed against the docs for Kling and Seedance; other families
send just the common fields and rely on ``extra_params_json`` for specifics.

The model->endpoint map is the one brittle spot (Magnific occasionally renames
slugs); it lives in VIDEO_MODELS below and an ``endpoint_override`` widget lets
you paste an exact path without editing code.
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
    "kling-motion":              ("i2v", "/v1/ai/image-to-video/kling-motion"),
    "minimax-hailuo-2-3-1080p":  ("i2v", "/v1/ai/image-to-video/minimax-hailuo-2-3-1080p"),
    "minimax-hailuo-02-1080p":   ("i2v", "/v1/ai/image-to-video/minimax-hailuo-02-1080p"),
    "minimax-video-01-live":     ("i2v", "/v1/ai/image-to-video/minimax-video-01-live"),
    "seedance-pro-1080p":        ("i2v", "/v1/ai/image-to-video/seedance-pro-1080p"),
    "pixverse-v5":               ("i2v", "/v1/ai/image-to-video/pixverse"),
    "wan-2-5-i2v-1080p":         ("i2v", "/v1/ai/image-to-video/wan-2-5-i2v-1080p"),
    "wan-v2-6-1080p":            ("i2v", "/v1/ai/image-to-video/wan-v2-6-1080p"),
    "runway-gen4-turbo":         ("i2v", "/v1/ai/image-to-video/runway-gen4-turbo"),
    # text-to-video
    "wan-2-5-t2v-1080p":         ("t2v", "/v1/ai/text-to-video/wan-2-5-t2v-1080p"),
    "ltx-2-pro":                 ("t2v", "/v1/ai/text-to-video/ltx-2-pro"),
}

DURATIONS = ["5", "10"]
ASPECT_RATIOS = ["widescreen_16_9", "social_story_9_16", "square_1_1"]

# Fields every video family accepts.
COMMON_KEYS = ("prompt", "duration", "aspect_ratio")
# Fields specific to a model family (confirmed from the Kling / Seedance docs).
FAMILY_EXTRA_KEYS: dict[str, set[str]] = {
    "kling": {"negative_prompt", "cfg_scale", "generate_audio"},
    "seedance": {"camera_fixed", "frames_per_second", "seed"},
    # minimax / pixverse / wan / runway / ltx: send common fields only; use
    # extra_params_json for their model-specific parameters.
}


def model_family(model: str) -> str:
    for fam in ("kling", "seedance", "minimax", "pixverse", "wan", "runway", "ltx"):
        if model.startswith(fam):
            return fam
    if "hailuo" in model:
        return "minimax"
    return "generic"


def build_video_body(model: str, kind: str, img_payload: str, values: dict) -> tuple[dict, str]:
    """Assemble the request body with only the fields this model's family accepts.

    Empty strings / None are dropped so we never send blank params. Returns
    ``(body, family)``.
    """
    fam = model_family(model)
    allowed = set(COMMON_KEYS) | FAMILY_EXTRA_KEYS.get(fam, set())
    body: dict = {}
    for key in allowed:
        val = values.get(key)
        if val is None:
            continue
        if isinstance(val, str) and not val.strip():
            continue
        body[key] = val
    if kind == "i2v":
        body["image"] = img_payload
    return body, fam


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
            },
            "optional": {
                # Required for image-to-video models; ignored for text-to-video.
                "image": ("IMAGE",),
                "image_url": ("STRING", {"default": ""}),
                # Kling family
                "negative_prompt": ("STRING", {"default": "", "multiline": True}),
                "cfg_scale": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05,
                                        "tooltip": "Kling family."}),
                "generate_audio": ("BOOLEAN", {"default": False, "tooltip": "Kling family."}),
                # Seedance family
                "camera_fixed": ("BOOLEAN", {"default": False, "tooltip": "Seedance family."}),
                "frames_per_second": ("INT", {"default": 24, "min": 1, "max": 60,
                                              "tooltip": "Seedance family."}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF,
                                 "tooltip": "Seedance family (0 = omit)."}),
                # Escape hatches for doc drift / other families.
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

    def generate(self, provider, api_key, model, prompt, duration, aspect_ratio,
                 image=None, image_url="", negative_prompt="", cfg_scale=0.5,
                 generate_audio=False, camera_fixed=False, frames_per_second=24, seed=0,
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

        values = {
            "prompt": prompt,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "negative_prompt": negative_prompt,
            "cfg_scale": cfg_scale,
            "generate_audio": generate_audio,
            "camera_fixed": camera_fixed,
            "frames_per_second": frames_per_second,
            "seed": seed or None,  # 0 -> omit
        }
        body, fam = build_video_body(model, kind, img_payload, values)

        if extra_params_json.strip():
            try:
                extra = json.loads(extra_params_json)
            except json.JSONDecodeError as exc:
                raise ValueError(f"MagnificVideoGenerate: extra_params_json is not valid JSON: {exc}")
            if not isinstance(extra, dict):
                raise ValueError("MagnificVideoGenerate: extra_params_json must be a JSON object.")
            body.update(extra)

        if fam == "generic":
            print(f"[ComfyUI-Magnific] '{model}' has no built-in parameter profile; "
                  "sending common fields only — add model-specific params via extra_params_json.")

        client = build_client(provider, api_key, poll_interval, max_wait_seconds)
        urls = client.run(
            path, body,
            on_status=make_logger(f"Video/{model}"),
            check_interrupt=comfy_interrupt_checker(),
        )
        video_path = save_url_to_output(client, urls[0], prefix=f"magnific_{model}", ext_hint=".mp4")
        from comfy_api.input_impl import VideoFromFile  # lazy: only when a video is produced
        return (VideoFromFile(video_path), video_path, "\n".join(urls))


NODE_CLASS_MAPPINGS = {"MagnificVideoGenerate": MagnificVideoGenerate}
NODE_DISPLAY_NAME_MAPPINGS = {"MagnificVideoGenerate": "Magnific Video Generate"}
