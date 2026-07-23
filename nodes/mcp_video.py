"""MagnificMCPVideo — reach the newer video models via the Magnific MCP.

The REST API (the other nodes) only exposes a curated subset of models. This node
talks to the Magnific **MCP** (`mcp.magnific.com`, OAuth), whose generic
`video_generate` takes a model **slug** from a much larger, more current catalog —
Seedance 2.0, Sora 2, Veo 3.1, Kling 3, etc.

One-time setup: run `python authorize_magnific.py` in the pack folder to sign in
(browser). See mcp_client.py. `mcp` must be installed in ComfyUI's Python
(`pip install mcp`).

Image-to-video: connect a ComfyUI IMAGE (uploaded to the MCP via
request_upload -> PUT -> finalize) or give a public URL (a URL wins for that slot).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Import the pack-root mcp_client whether loaded as a package or standalone.
_PACK_DIR = Path(__file__).resolve().parent.parent
if str(_PACK_DIR) not in sys.path:
    sys.path.insert(0, str(_PACK_DIR))

import mcp_client  # noqa: E402
from freepik_api import tensor_to_base64_png  # noqa: E402

CATEGORY = "Magnific"


def _png_bytes(image):
    """A ComfyUI IMAGE tensor -> raw PNG bytes (reuses the base64 encoder)."""
    import base64
    return base64.b64decode(tensor_to_base64_png(image))

# Model slugs from the MCP video_models_list catalog (newer / REST-missing ones).
# "custom" -> use the slug_override widget for anything not listed here.
MODEL_SLUGS = [
    "bytedance-seedance-pro-2.0",
    "bytedance-seedance-fast-2.0",
    "bytedance-seedance-mini-2.0",
    "bytedance-seedance-pro-1.5",
    "kling-30",
    "kling-omni3",
    "kling-30-turbo",
    "openai-sora2-standard",
    "openai-sora2-pro",
    "google-veo3_1",
    "google-veo3_1-fast",
    "custom",
]
ASPECT_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "9:21"]
RESOLUTIONS = ["1080p", "720p", "580p", "480p"]


class MagnificMCPVideo:
    """Generate video through the Magnific MCP (Seedance 2.0, Sora 2, Kling 3, ...)."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": (MODEL_SLUGS, {"default": "bytedance-seedance-pro-2.0"}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "duration": ("INT", {"default": 5, "min": 1, "max": 30,
                             "tooltip": "Seconds (allowed range per model)."}),
                "aspect_ratio": (ASPECT_RATIOS, {"default": "16:9"}),
                "resolution": (RESOLUTIONS, {"default": "1080p"}),
            },
            "optional": {
                "slug_override": ("STRING", {"default": "",
                                  "tooltip": "Exact slug from video_models_list; used when model=custom."}),
                # Image-to-video: connect a ComfyUI IMAGE (uploaded to the MCP), or
                # give a public URL. A URL wins over the tensor for the same slot.
                "start_image": ("IMAGE",),
                "end_image": ("IMAGE",),
                "start_image_url": ("STRING", {"default": "",
                                    "tooltip": "Public image URL (keyframe start); overrides start_image."}),
                "end_image_url": ("STRING", {"default": ""}),
                "extra_params_json": ("STRING", {"default": "", "multiline": True,
                                      "tooltip": "Merged into the clip, e.g. {\"soundEffects\": true}."}),
                "poll_interval": ("FLOAT", {"default": 6.0, "min": 2.0, "max": 60.0, "step": 1.0}),
                "max_wait_seconds": ("INT", {"default": 1800, "min": 60, "max": 3600, "step": 30}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("video_path", "video_url")
    FUNCTION = "generate"
    CATEGORY = CATEGORY
    OUTPUT_NODE = True

    def generate(self, model, prompt, duration, aspect_ratio, resolution,
                 slug_override="", start_image=None, end_image=None,
                 start_image_url="", end_image_url="",
                 extra_params_json="", poll_interval=6.0, max_wait_seconds=1800):
        import json

        slug = slug_override.strip() if model == "custom" else model
        if not slug:
            raise ValueError("MagnificMCPVideo: model=custom needs a 'slug_override'.")
        has_start = bool(start_image_url.strip()) or start_image is not None
        if not prompt.strip() and not has_start:
            raise ValueError("MagnificMCPVideo: provide a 'prompt' and/or a start image "
                             "(connect 'start_image' or set 'start_image_url').")

        clip: dict = {
            "slug": slug,
            "duration": duration,
            "aspectRatio": aspect_ratio,
            "resolution": resolution,
        }
        if prompt.strip():
            clip["prompt"] = prompt

        if extra_params_json.strip():
            try:
                extra = json.loads(extra_params_json)
            except json.JSONDecodeError as exc:
                raise ValueError(f"MagnificMCPVideo: extra_params_json is not valid JSON: {exc}")
            if not isinstance(extra, dict):
                raise ValueError("MagnificMCPVideo: extra_params_json must be a JSON object.")
            clip.update(extra)

        # A ComfyUI IMAGE is uploaded to the MCP; a URL (if given) wins for that slot.
        start_bytes = _png_bytes(start_image) if (start_image is not None and not start_image_url.strip()) else None
        end_bytes = _png_bytes(end_image) if (end_image is not None and not end_image_url.strip()) else None

        def _status(msg):
            print(f"[ComfyUI-Magnific] MCP/{slug}: {msg}")

        urls = mcp_client.generate_video(
            slug, clip,
            start_url=start_image_url, end_url=end_image_url,
            start_bytes=start_bytes, end_bytes=end_bytes,
            poll_interval=poll_interval, max_wait=max_wait_seconds, status_cb=_status,
        )
        video_path = mcp_client.download_to_output(urls[0], prefix=f"magnific_mcp_{slug}", ext_hint=".mp4")
        return (video_path, "\n".join(urls))


NODE_CLASS_MAPPINGS = {"MagnificMCPVideo": MagnificMCPVideo}
NODE_DISPLAY_NAME_MAPPINGS = {"MagnificMCPVideo": "Magnific MCP Video (Seedance 2.0 / Sora 2 / Kling 3)"}
