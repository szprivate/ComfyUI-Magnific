"""MagnificImageGenerate — text-to-image via the Mystic endpoint.

POST /v1/ai/mystic  (async, poll GET /v1/ai/mystic/{task_id}).
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

MYSTIC_PATH = "/v1/ai/mystic"

# Confirmed Mystic enums (docs.magnific.com / docs.freepik.com Mystic reference).
RESOLUTIONS = ["1k", "2k", "4k"]
MODELS = ["realism", "fluid", "zen"]
ENGINES = ["automatic", "magnific_illusio", "magnific_sharpy", "magnific_sparkle"]
ASPECT_RATIOS = [
    "square_1_1", "classic_4_3", "traditional_3_4", "widescreen_16_9",
    "social_story_9_16", "smartphone_horizontal_20_9", "smartphone_vertical_9_20",
    "standard_3_2", "portrait_2_3", "horizontal_2_1", "vertical_1_2",
    "social_5_4", "social_post_4_5",
]


class MagnificImageGenerate:
    """Generate images from a text prompt with optional structure/style references."""

    @classmethod
    def INPUT_TYPES(cls):
        conn = connection_inputs()
        poll = polling_inputs()
        return {
            "required": {
                **conn,
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "model": (MODELS, {"default": "realism"}),
                "resolution": (RESOLUTIONS, {"default": "2k"}),
                "aspect_ratio": (ASPECT_RATIOS, {"default": "square_1_1"}),
                "engine": (ENGINES, {"default": "automatic"}),
                "creative_detailing": ("INT", {"default": 33, "min": 0, "max": 100}),
                "hdr": ("INT", {"default": 50, "min": 0, "max": 100}),
                "filter_nsfw": ("BOOLEAN", {"default": True}),
                "fixed_generation": ("BOOLEAN", {"default": False}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
            },
            "optional": {
                # Reference images: either a ComfyUI IMAGE or a public URL.
                "structure_reference": ("IMAGE",),
                "structure_reference_url": ("STRING", {"default": ""}),
                "structure_strength": ("INT", {"default": 50, "min": 0, "max": 100}),
                "style_reference": ("IMAGE",),
                "style_reference_url": ("STRING", {"default": ""}),
                "adherence": ("INT", {"default": 50, "min": 0, "max": 100}),
                # A MAGNIFIC_REFERENCE from MagnificReferenceCreate (fills the slot
                # matching its role); overrides the plain image inputs above.
                "reference": ("MAGNIFIC_REFERENCE",),
                # Any additional documented Mystic param, e.g. {"styling": {...}}.
                "extra_params_json": ("STRING", {"default": "", "multiline": True}),
                **poll,
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("images", "image_urls")
    FUNCTION = "generate"
    CATEGORY = CATEGORY

    def generate(self, provider, api_key, prompt, model, resolution, aspect_ratio,
                 engine, creative_detailing, hdr, filter_nsfw, fixed_generation, seed,
                 structure_reference=None, structure_reference_url="", structure_strength=50,
                 style_reference=None, style_reference_url="", adherence=50,
                 reference=None, extra_params_json="",
                 poll_interval=5.0, max_wait_seconds=900):
        import json

        if not prompt.strip():
            raise ValueError("MagnificImageGenerate: 'prompt' is required.")

        body: dict = {
            "prompt": prompt,
            "model": model,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "engine": engine,
            "creative_detailing": creative_detailing,
            "hdr": hdr,
            "filter_nsfw": filter_nsfw,
            "fixed_generation": fixed_generation,
        }
        if seed:
            body["seed"] = seed

        struct = image_to_payload(structure_reference, structure_reference_url)
        if struct:
            body["structure_reference"] = struct
            body["structure_strength"] = structure_strength
        style = image_to_payload(style_reference, style_reference_url)
        if style:
            body["style_reference"] = style
            body["adherence"] = adherence

        # A MAGNIFIC_REFERENCE object routes into the correct slot by its role.
        if reference:
            role = reference.get("role", "style")
            b64 = reference.get("b64", "")
            if role == "structure":
                body["structure_reference"] = b64
                body["structure_strength"] = reference.get("strength", structure_strength)
            elif role == "character":
                styling = body.setdefault("styling", {})
                chars = styling.setdefault("characters", [])
                chars.append({"id": reference.get("name", "character"),
                              "strength": reference.get("strength", 100)})
            else:  # style
                body["style_reference"] = b64
                body["adherence"] = reference.get("strength", adherence)

        if extra_params_json.strip():
            try:
                extra = json.loads(extra_params_json)
            except json.JSONDecodeError as exc:
                raise ValueError(f"MagnificImageGenerate: extra_params_json is not valid JSON: {exc}")
            if not isinstance(extra, dict):
                raise ValueError("MagnificImageGenerate: extra_params_json must be a JSON object.")
            body.update(extra)

        client = build_client(provider, api_key, poll_interval, max_wait_seconds)
        urls = client.run(
            MYSTIC_PATH, body,
            on_status=make_logger("Mystic"),
            check_interrupt=comfy_interrupt_checker(),
        )
        images = urls_to_image_batch(client, urls)
        return (images, "\n".join(urls))


NODE_CLASS_MAPPINGS = {"MagnificImageGenerate": MagnificImageGenerate}
NODE_DISPLAY_NAME_MAPPINGS = {"MagnificImageGenerate": "Magnific Image Generate (Mystic)"}
