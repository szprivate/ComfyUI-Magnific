"""MagnificTextToImage — text-to-image models other than Mystic.

All of these live under /v1/ai/text-to-image/<model> (confirmed via curl for
seedream and flux-pro-v1-1) and share the async task contract. Their optional
parameters differ per model, so this node sends the universally-accepted fields
(prompt, aspect_ratio, seed) and leaves model-specific knobs — e.g. flux-pro's
`safety_tolerance` / `output_format`, seedream's `guidance_scale` — to
`extra_params_json`. For Mystic (its own endpoint + rich params) use
MagnificImageGenerate.
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
from freepik_api import urls_to_image_batch

BASE = "/v1/ai/text-to-image"
# label -> path
T2I_MODELS: dict[str, str] = {
    "classic":         f"{BASE}",
    "flux-dev":        f"{BASE}/flux-dev",
    "flux-pro-v1-1":   f"{BASE}/flux-pro-v1-1",
    "flux-2-pro":      f"{BASE}/flux-2-pro",
    "flux-2-turbo":    f"{BASE}/flux-2-turbo",
    "flux-2-klein":    f"{BASE}/flux-2-klein",
    "hyperflux":       f"{BASE}/hyperflux",
    "seedream":        f"{BASE}/seedream",
    "seedream-4":      f"{BASE}/seedream-4",
    "seedream-v4-5":   f"{BASE}/seedream-v4-5",
    "z-image-turbo":   f"{BASE}/z-image-turbo",
    "runway":          f"{BASE}/runway",
}

ASPECT_RATIOS = [
    "unset", "square_1_1", "classic_4_3", "traditional_3_4", "widescreen_16_9",
    "social_story_9_16", "standard_3_2", "portrait_2_3", "horizontal_2_1",
    "vertical_1_2", "social_post_4_5",
]


class MagnificTextToImage:
    """Text-to-image across the Flux, Seedream, Z-Image, Hyperflux and Runway models."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                **connection_inputs(),
                "model": (list(T2I_MODELS.keys()), {"default": "flux-dev"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
            },
            "optional": {
                "aspect_ratio": (ASPECT_RATIOS, {"default": "unset"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
                "extra_params_json": ("STRING", {"default": "", "multiline": True,
                                      "tooltip": "Model-specific params as JSON, e.g. "
                                                 "{\"guidance_scale\": 3.5} or "
                                                 "{\"safety_tolerance\": 2, \"output_format\": \"png\"}."}),
                **polling_inputs(),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("images", "image_urls")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, provider, api_key, model, prompt, aspect_ratio="unset", seed=0,
                 extra_params_json="", poll_interval=5.0, max_wait_seconds=900):
        import json

        if not prompt.strip():
            raise ValueError("MagnificTextToImage: 'prompt' is required.")

        body: dict = {"prompt": prompt}
        if aspect_ratio != "unset":
            body["aspect_ratio"] = aspect_ratio
        if seed:
            body["seed"] = seed

        if extra_params_json.strip():
            try:
                extra = json.loads(extra_params_json)
            except json.JSONDecodeError as exc:
                raise ValueError(f"MagnificTextToImage: extra_params_json is not valid JSON: {exc}")
            if not isinstance(extra, dict):
                raise ValueError("MagnificTextToImage: extra_params_json must be a JSON object.")
            body.update(extra)

        client = build_client(provider, api_key, poll_interval, max_wait_seconds)
        urls = client.run(
            T2I_MODELS[model], body,
            on_status=make_logger(f"T2I/{model}"),
            check_interrupt=comfy_interrupt_checker(),
        )
        images = urls_to_image_batch(client, urls)
        return (images, "\n".join(urls))


NODE_CLASS_MAPPINGS = {"MagnificTextToImage": MagnificTextToImage}
NODE_DISPLAY_NAME_MAPPINGS = {"MagnificTextToImage": "Magnific Text-to-Image"}
