"""MagnificUpscale — creative & precise image upscaling.

Creative (the classic "Magnific" look):  POST /v1/ai/image-upscaler
Precise  (faithful, no hallucination):    POST /v1/ai/image-upscaler-precision

Both are async (poll GET /v1/ai/<path>/{task_id}). No installed ComfyUI-Freepik /
ComfyUI-ClarityAI pack was present to extend, so this is a fresh node following
the same submit->poll->tensor pattern as ComfyUI-ClarityAI's upscaler.
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
from freepik_api import urls_to_image_batch

CREATIVE_PATH = "/v1/ai/image-upscaler"
PRECISE_PATH = "/v1/ai/image-upscaler-precision"

SCALE_FACTORS = ["2x", "4x", "8x", "16x"]
# Classic Magnific "optimized_for" presets.
OPTIMIZED_FOR = [
    "standard", "soft_portraits", "hard_portraits", "art_n_illustration",
    "videogame_assets", "nature_n_landscapes", "films_n_photography",
    "3d_renders", "science_fiction_n_horror",
]
ENGINES = ["automatic", "magnific_illusio", "magnific_sharpy", "magnific_sparkle"]


class MagnificUpscale:
    """Upscale an image 2x-16x with Magnific creative or precise engines."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                **connection_inputs(),
                "image": ("IMAGE",),
                "mode": (["creative", "precise"], {"default": "creative"}),
                "scale_factor": (SCALE_FACTORS, {"default": "2x"}),
                "optimized_for": (OPTIMIZED_FOR, {"default": "standard"}),
                "creativity": ("INT", {"default": 0, "min": -10, "max": 10}),
                "hdr": ("INT", {"default": 0, "min": -10, "max": 10}),
                "resemblance": ("INT", {"default": 0, "min": -10, "max": 10}),
                "fractality": ("INT", {"default": 0, "min": -10, "max": 10}),
                "engine": (ENGINES, {"default": "automatic"}),
            },
            "optional": {
                # Public URL overrides the IMAGE input (max quality, no re-encode).
                "image_url": ("STRING", {"default": ""}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "extra_params_json": ("STRING", {"default": "", "multiline": True}),
                **polling_inputs(),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "image_url")
    FUNCTION = "upscale"
    CATEGORY = CATEGORY

    def upscale(self, provider, api_key, image, mode, scale_factor, optimized_for,
                creativity, hdr, resemblance, fractality, engine,
                image_url="", prompt="", extra_params_json="",
                poll_interval=5.0, max_wait_seconds=900):
        import json

        payload = image_to_payload(image, image_url)
        if not payload:
            raise ValueError("MagnificUpscale: an 'image' (or 'image_url') is required.")

        path = CREATIVE_PATH if mode == "creative" else PRECISE_PATH
        body: dict = {
            "image": payload,
            "scale_factor": scale_factor,
            "optimized_for": optimized_for,
            "creativity": creativity,
            "hdr": hdr,
            "resemblance": resemblance,
            "fractality": fractality,
            "engine": engine,
        }
        if prompt.strip():
            body["prompt"] = prompt

        if extra_params_json.strip():
            try:
                extra = json.loads(extra_params_json)
            except json.JSONDecodeError as exc:
                raise ValueError(f"MagnificUpscale: extra_params_json is not valid JSON: {exc}")
            if not isinstance(extra, dict):
                raise ValueError("MagnificUpscale: extra_params_json must be a JSON object.")
            body.update(extra)

        client = build_client(provider, api_key, poll_interval, max_wait_seconds)
        urls = client.run(
            path, body,
            on_status=make_logger(f"Upscale/{mode}"),
            check_interrupt=comfy_interrupt_checker(),
        )
        images = urls_to_image_batch(client, urls)
        return (images, "\n".join(urls))


NODE_CLASS_MAPPINGS = {"MagnificUpscale": MagnificUpscale}
NODE_DISPLAY_NAME_MAPPINGS = {"MagnificUpscale": "Magnific Upscale"}
