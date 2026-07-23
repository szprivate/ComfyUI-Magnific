"""MagnificImageEdit — image editing / transformation models.

These endpoints are heterogeneous: different paths, different image field names
(`image`, `input_image`, `image_url`), some async, one synchronous. Each model
carries its own spec below; the request body is filtered to that model's known
fields, and `extra_params_json` covers anything model-specific.

Confirmed against the docs: style-transfer, flux-kontext-pro, remove-background.
Best-effort (path confirmed, params partial — tune via extra_params_json):
relight, reimagine-flux, seedream-v4-5-edit, image-expand.
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

# Aspect ratios shared by the models that accept one.
ASPECT_RATIOS = [
    "unset", "square_1_1", "classic_4_3", "traditional_3_4", "widescreen_16_9",
    "social_story_9_16", "standard_3_2", "portrait_2_3", "horizontal_2_1",
    "vertical_1_2", "social_post_4_5",
]

# model -> spec.
#   path         : API path
#   image_field  : body key for the source image
#   ref_field    : (optional) body key for a second/style/reference image
#   url_only     : source must be a public URL (base64/tensor not accepted)
#   sync_form    : synchronous, application/x-www-form-urlencoded (no polling)
#   needs_prompt : prompt is required
#   keys         : optional widget keys this model accepts (filtered into body)
EDIT_MODELS: dict[str, dict] = {
    "style-transfer": {
        "path": "/v1/ai/image-style-transfer",
        "image_field": "image", "ref_field": "reference_image",
        "keys": ("prompt", "style_strength", "structure_strength"),
        "confirmed": True,
    },
    "flux-kontext-pro": {
        "path": "/v1/ai/text-to-image/flux-kontext-pro",
        "image_field": "input_image", "url_only": True, "needs_prompt": True,
        "keys": ("prompt", "aspect_ratio", "seed", "guidance", "steps"),
        "confirmed": True,
    },
    "remove-background": {
        "path": "/v1/ai/beta/remove-background",
        "image_field": "image_url", "url_only": True, "sync_form": True,
        "keys": (),
        "confirmed": True,
    },
    "relight": {
        "path": "/v1/ai/image-relight",
        "image_field": "image", "ref_field": "reference_image",
        "keys": ("prompt",),
        "confirmed": False,
    },
    "reimagine-flux": {
        "path": "/v1/ai/text-to-image/reimagine-flux",
        "image_field": "image",
        "keys": ("prompt", "aspect_ratio"),
        "confirmed": False,
    },
    "seedream-v4-5-edit": {
        "path": "/v1/ai/text-to-image/seedream-v4-5-edit",
        "image_field": "image", "needs_prompt": True,
        "keys": ("prompt", "aspect_ratio", "seed"),
        "confirmed": False,
    },
    "image-expand": {
        "path": "/v1/ai/image-expand/flux-pro",
        "image_field": "image",
        "keys": ("prompt",),
        "confirmed": False,
    },
}


class MagnificImageEdit:
    """Edit/transform an image: style transfer, Kontext edit, relight, remove bg, expand, ..."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                **connection_inputs(),
                "model": (list(EDIT_MODELS.keys()), {"default": "style-transfer"}),
                "image": ("IMAGE",),
            },
            "optional": {
                "image_url": ("STRING", {"default": "",
                              "tooltip": "Public https URL; required for flux-kontext-pro "
                                         "and remove-background (they don't accept base64)."}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                # style-transfer / relight second image
                "reference_image": ("IMAGE",),
                "reference_image_url": ("STRING", {"default": ""}),
                "aspect_ratio": (ASPECT_RATIOS, {"default": "unset"}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF}),
                # style-transfer
                "style_strength": ("INT", {"default": 100, "min": 0, "max": 100}),
                "structure_strength": ("INT", {"default": 50, "min": 0, "max": 100}),
                # flux-kontext
                "guidance": ("FLOAT", {"default": 3.0, "min": 1.0, "max": 10.0, "step": 0.5}),
                "steps": ("INT", {"default": 50, "min": 1, "max": 100}),
                "extra_params_json": ("STRING", {"default": "", "multiline": True}),
                **polling_inputs(),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "image_urls")
    FUNCTION = "edit"
    CATEGORY = CATEGORY

    def edit(self, provider, api_key, model, image, image_url="", prompt="",
             reference_image=None, reference_image_url="", aspect_ratio="unset", seed=0,
             style_strength=100, structure_strength=50, guidance=3.0, steps=50,
             extra_params_json="", poll_interval=5.0, max_wait_seconds=900):
        import json

        spec = EDIT_MODELS[model]
        payload = image_to_payload(image, image_url)
        if not payload:
            raise ValueError("MagnificImageEdit: an 'image' (or 'image_url') is required.")
        if spec.get("url_only") and not payload.startswith("http"):
            raise ValueError(
                f"MagnificImageEdit: '{model}' accepts only an image URL — set 'image_url' "
                "to a public https URL (this endpoint does not accept base64/tensor input)."
            )
        if spec.get("needs_prompt") and not prompt.strip():
            raise ValueError(f"MagnificImageEdit: '{model}' requires a 'prompt'.")

        candidates = {
            "prompt": prompt,
            "aspect_ratio": None if aspect_ratio == "unset" else aspect_ratio,
            "seed": seed or None,
            "style_strength": style_strength,
            "structure_strength": structure_strength,
            "guidance": guidance,
            "steps": steps,
        }
        allowed = set(spec["keys"])
        body: dict = {}
        for key in allowed:
            val = candidates.get(key)
            if val is None:
                continue
            if isinstance(val, str) and not val.strip():
                continue
            body[key] = val
        body[spec["image_field"]] = payload

        if spec.get("ref_field"):
            ref = image_to_payload(reference_image, reference_image_url)
            if ref:
                body[spec["ref_field"]] = ref

        if extra_params_json.strip():
            try:
                extra = json.loads(extra_params_json)
            except json.JSONDecodeError as exc:
                raise ValueError(f"MagnificImageEdit: extra_params_json is not valid JSON: {exc}")
            if not isinstance(extra, dict):
                raise ValueError("MagnificImageEdit: extra_params_json must be a JSON object.")
            body.update(extra)

        if not spec.get("confirmed"):
            print(f"[ComfyUI-Magnific] '{model}' params are best-effort (path confirmed); "
                  "if the API rejects a field, adjust it via extra_params_json.")

        client = build_client(provider, api_key, poll_interval, max_wait_seconds)
        if spec.get("sync_form"):
            urls = client.post_form_sync(spec["path"], body)
        else:
            urls = client.run(
                spec["path"], body,
                on_status=make_logger(f"Edit/{model}"),
                check_interrupt=comfy_interrupt_checker(),
            )
        images = urls_to_image_batch(client, urls)
        return (images, "\n".join(urls))


NODE_CLASS_MAPPINGS = {"MagnificImageEdit": MagnificImageEdit}
NODE_DISPLAY_NAME_MAPPINGS = {"MagnificImageEdit": "Magnific Image Edit"}
